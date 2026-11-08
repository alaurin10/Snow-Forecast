"""Precipitation frames for the Map page, drawn here rather than on the phone.

One timeline, past radar to ~48 h of forecast, rendered as one picture per frame over
the region around the active locations (Web Mercator, so it lines up with the map).
The browser downloads these few dozen small PNGs once and swaps between them, which
makes scrubbing instant and keeps a phone's memory low. Phones crashed, and were slow,
when they stitched and repainted the tiles themselves.

Sources, all free and keyless (see docs/SOURCES.md):
  past      RainViewer radar mosaic. Its published "Universal Blue" table gives each
            colour's dBZ and whether it's rain or snow; we turn that into a rate.
  forecast  Environment Canada HRDPS (GeoMet WMS): rain, freezing rain, snow per hour,
            styled by GeoMet in our colours. Covers Canada and the northern US.
  rest of US NOAA HRRR simulated radar by type (Iowa State IEM tiles), repainted; where
            HRRR has nothing, NWS WPC 6-hour totals in tan. Cut out where HRDPS covers.

Each frame's file name includes a hash of its pixels, so the browser can cache it for
good. A frame is only redrawn when its inputs change (a new radar scan, a new model run).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
import time
import urllib.parse
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageDraw, TiffImagePlugin

log = logging.getLogger("snowwatch.precip")

GEOMET = "https://geo.weather.gc.ca/geomet"
IEM = "https://mesonet.agron.iastate.edu"
RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json"
WPC = "https://mapservices.weather.noaa.gov/vector/rest/services/precip/wpc_qpf/MapServer"

HOUR = 3600
WORLD = 20037508.342789244  # half the Web Mercator world, metres
TILE_ZOOM = 7  # RainViewer's free tiles stop at 7; IEM's HRRR is ~3 km, so 7 is plenty
WIDTH = 1400  # frame width in pixels

# ---- Colours (keep in step with frontend/src/lib/radar.ts) ---------------------------

# Lower bound in mm of water per hour (≈ cm of snow per hour for snow), colour.
SNOW = [(0.1, "#c6dbef"), (0.5, "#8fbfe6"), (1, "#4a90d9"), (2, "#2c5fb8"), (3, "#6a3fb0")]
MIX = [(0.1, "#f4a6c6"), (1, "#e0457b")]
RAIN = [
    (0.1, "#a6dba0"),
    (0.5, "#5aae61"),
    (1, "#1b7837"),
    (2.5, "#f4d03f"),
    (5, "#ee8a2a"),
    (10, "#d7301f"),
]
# NWS 6-hour totals carry no type; lower bound in inches per 6 hours.
UNTYPED = [(0.1, "#e6d3b3"), (0.25, "#d4b083"), (0.5, "#b88a50"), (1, "#8f612c")]

HRDPS_LAYERS = [
    ("HRDPS.CONTINENTAL.DIAG_RN_PT1H", RAIN),
    ("HRDPS.CONTINENTAL.DIAG_FR_PT1H", MIX),
    ("HRDPS.CONTINENTAL.DIAG_SN_PT1H", SNOW),
]
DOMAIN_LAYER = "HRDPS.CONTINENTAL.DIAG_PR_PT1H"

RGB = tuple[int, int, int]


def hex_rgb(h: str) -> RGB:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ramp_color(ramp: list[tuple[float, str]], value: float) -> RGB | None:
    out = None
    for low, color in ramp:
        if value >= low:
            out = hex_rgb(color)
    return out


# Snowfall totals: lower bound in cm of snow (the model's water equivalent at 10:1).
# Steps sit on whole inches (1, 3, 6, 9, 12, 18, 24, 36, 48) so both units read cleanly.
TOTAL = [
    (2.54, "#cfe8f8"),
    (7.62, "#8cc8ef"),
    (15.24, "#4a98e0"),
    (22.86, "#2b5cc2"),
    (30.48, "#6a3fb0"),
    (45.72, "#a535a3"),
    (60.96, "#e0457b"),
    (91.44, "#f08a24"),
    (121.92, "#f4d03f"),
]
TOTAL_HOURS = (12, 24, 48)
SN_TOTAL_LAYER = "HRDPS.CONTINENTAL_SN"  # water equivalent (mm) since the run began

# Every colour a frame can hold: index 0 is transparent.
PALETTE: list[RGB] = [(0, 0, 0)] + [
    hex_rgb(c) for ramp in (SNOW, MIX, RAIN, UNTYPED, TOTAL) for _, c in ramp
]

# ---- Region ------------------------------------------------------------------


def merc_x(lon: float) -> float:
    return lon * WORLD / 180


def merc_y(lat: float) -> float:
    lat = max(min(lat, 85.0), -85.0)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * WORLD / math.pi


def merc_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y * math.pi / WORLD)) - math.pi / 2)


@dataclass(frozen=True)
class Region:
    """A box in Web Mercator metres and its size in pixels."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: int
    height: int

    @property
    def bounds(self) -> list[list[float]]:
        """[[south, west], [north, east]] in degrees, as Leaflet wants."""
        w, e = self.x0 * 180 / WORLD, self.x1 * 180 / WORLD
        return [
            [round(merc_lat(self.y0), 5), round(w, 5)],
            [round(merc_lat(self.y1), 5), round(e, 5)],
        ]

    @property
    def key(self) -> str:
        return f"{self.x0:.0f},{self.y0:.0f},{self.x1:.0f},{self.y1:.0f},{self.width}x{self.height}"


def region_for(points: Iterable[tuple[float, float]], width: int = WIDTH) -> Region:
    """The locations (lat, lon) with a margin: weather arrives from well upwind."""
    pts = list(points) or [(47.4, -121.4)]
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    south, north = min(lats) - 5, max(lats) + 6
    west, east = min(lons) - 10, max(lons) + 8
    # At least ~12 x 18 degrees, so a single location still gets context.
    if north - south < 12:
        mid = (north + south) / 2
        south, north = mid - 6, mid + 6
    if east - west < 18:
        mid = (east + west) / 2
        west, east = mid - 9, mid + 9
    x0, x1 = merc_x(west), merc_x(east)
    y0, y1 = merc_y(south), merc_y(north)
    height = min(1800, round(width * (y1 - y0) / (x1 - x0)))
    return Region(x0, y0, x1, y1, width, height)


# ---- Fetching ------------------------------------------------------------------


class Net:
    """GETs with a retry for busy servers (GeoMet answers 429 when pressed)."""

    def __init__(self, client: httpx.Client, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.sleep = sleep

    def get(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> httpx.Response | None:
        for attempt in range(tries):
            if attempt:
                self.sleep(2 + 3 * attempt)
            try:
                r = self.client.get(url, params=params, timeout=20)
            except httpx.HTTPError as e:
                log.debug("GET %s failed: %s", url, e)
                r = None
            if r is not None and r.status_code == 200:
                return r
            if r is not None and r.status_code != 429 and r.status_code < 500:
                return None
        return None

    def json(self, url: str, params: dict[str, str] | None = None) -> Any:
        r = self.get(url, params)
        try:
            return r.json() if r is not None else None
        except ValueError:
            return None

    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None:
        """RGBA pixels, or None."""
        r = self.get(url, params, tries)
        if r is None or not r.headers.get("content-type", "").startswith("image/"):
            return None
        return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))


def sld(layer: str, ramp: list[tuple[float, str]]) -> str:
    """A GeoMet style: each entry is the lower bound of a band; below the first is clear."""
    entries = [*ramp, (9999, ramp[-1][1])]
    cmap = "".join(f'<ColorMapEntry color="{c}" quantity="{q}"/>' for q, c in entries)
    return (
        '<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">'
        f"<NamedLayer><Name>{layer}</Name><UserStyle><FeatureTypeStyle><Rule>"
        f'<RasterSymbolizer><ColorMap type="intervals">{cmap}</ColorMap></RasterSymbolizer>'
        "</Rule></FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>"
    )


def geomet_map(
    net: Net, layer: str, style: str, region: Region, time_: str | None
) -> np.ndarray | None:
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "crs": "EPSG:3857",
        "bbox": f"{region.x0},{region.y0},{region.x1},{region.y1}",
        "width": str(region.width),
        "height": str(region.height),
        "format": "image/png",
        "transparent": "true",
        "layers": layer,
        "styles": "",
        "sld_body": style,
    }
    if time_:
        params["time"] = time_
    return net.image(GEOMET, params)


def capabilities_dims(net: Net, layer: str) -> dict[str, str]:
    r = net.get(
        GEOMET,
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities", "layer": layer},
    )
    if r is None:
        return {}
    out = {}
    for m in re.finditer(r'<Dimension[^>]*name="(\w+)"([^>]*)>([^<]*)<', r.text):
        default = re.search(r'default="([^"]*)"', m.group(2))
        out[m.group(1)] = m.group(3)
        out[m.group(1) + ".default"] = default.group(1) if default else ""
    return out


def parse_times(dim: str) -> list[int]:
    """WMS time dimension ("start/end/PT1H" ranges, comma lists) to Unix seconds."""
    out: set[int] = set()
    for part in (p.strip() for p in dim.split(",")):
        if not part:
            continue
        bits = part.split("/")
        try:
            start = iso_ts(bits[0])
        except ValueError:
            continue
        if len(bits) == 1:
            out.add(start)
            continue
        m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", bits[2] if len(bits) > 2 else "")
        step = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60) if m else 0
        if step <= 0:
            continue
        end = iso_ts(bits[1])
        out.update(range(start, end + 1, step))
    return sorted(out)


def iso_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def ts_iso(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- Tiles ---------------------------------------------------------------------


def stitch(net: Net, template: str, region: Region, z: int = TILE_ZOOM) -> np.ndarray | None:
    """XYZ tiles covering the region, resampled onto its pixel grid. None if none came."""
    world_px = 256 * 2**z

    def px(x: float) -> float:
        return float((x + WORLD) / (2 * WORLD) * world_px)

    def py(y: float) -> float:
        return float((WORLD - y) / (2 * WORLD) * world_px)

    gx0, gx1 = px(region.x0), px(region.x1)
    gy0, gy1 = py(region.y1), py(region.y0)
    tx0, tx1 = int(gx0 // 256), int((gx1 - 1) // 256)
    ty0, ty1 = int(gy0 // 256), int((gy1 - 1) // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 4), np.uint8)
    coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]

    def one(c: tuple[int, int]) -> tuple[tuple[int, int], np.ndarray | None]:
        x, y = c
        # Tile caches serve or they don't: no retries (a missing hour can take 20 s to fail).
        return c, net.image(template.format(z=z, x=x, y=y), tries=1)

    # One tile from the middle first: if the source has nothing, don't ask for the rest.
    probe = coords[len(coords) // 2]
    if one(probe)[1] is None and one(coords[0])[1] is None:
        return None
    got = 0
    with ThreadPoolExecutor(6) as pool:
        for (x, y), img in pool.map(one, coords):
            if img is None or img.shape[:2] != (256, 256):
                continue
            got += 1
            mosaic[(y - ty0) * 256 : (y - ty0 + 1) * 256, (x - tx0) * 256 : (x - tx0 + 1) * 256] = (
                img
            )
    if not got:
        return None
    # Nearest-neighbour sample: both grids are Web Mercator, so the mapping is linear.
    cols = (gx0 + (np.arange(region.width) + 0.5) * (gx1 - gx0) / region.width - tx0 * 256).astype(
        int
    )
    rows = (
        gy0 + (np.arange(region.height) + 0.5) * (gy1 - gy0) / region.height - ty0 * 256
    ).astype(int)
    cols = np.clip(cols, 0, mosaic.shape[1] - 1)
    rows = np.clip(rows, 0, mosaic.shape[0] - 1)
    out: np.ndarray = mosaic[rows][:, cols]
    return out


def repaint(
    img: np.ndarray, fn: Callable[[int, int, int], RGB | None], min_alpha: int = 24
) -> np.ndarray:
    """Map each distinct colour through `fn`; drop faint and unmapped pixels."""
    out = np.zeros_like(img)
    solid = img[..., 3] >= min_alpha
    if not solid.any():
        return out
    packed = (
        (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2]
    )
    keys, inverse = np.unique(packed[solid], return_inverse=True)
    lut = np.zeros((len(keys), 4), np.uint8)
    for i, k in enumerate(keys.tolist()):
        c = fn((k >> 16) & 255, (k >> 8) & 255, k & 255)
        if c:
            lut[i] = (*c, 255)
    out[solid] = lut[inverse]
    return out


# ---- Radar colours (RainViewer "Universal Blue") --------------------------------------
# rainviewer.com/api/color-schemes.html: one colour per dBZ, for rain and for snow.

RV_RAIN_FROM = 15
RV_RAIN = [
    "88ddee",
    "6cd1eb",
    "51c5e8",
    "36bae5",
    "1baee2",
    "00a3e0",
    "009ad5",
    "0091ca",
    "0088bf",
    "007fb4",
    "0077aa",
    "0070a3",
    "00699c",
    "006295",
    "005b8e",
    "005588",
    "005180",
    "004e78",
    "004a70",
    "004768",
    "ffee00",
    "ffe000",
    "ffd200",
    "ffc500",
    "ffb700",
    "ffaa00",
    "ff9f00",
    "ff9500",
    "ff8b00",
    "ff8100",
    "ff4400",
    "f23600",
    "e62800",
    "d91b00",
    "cd0d00",
    "c10000",
    "a80000",
    "8f0000",
    "760000",
    "5d0000",
    "ffaaff",
    "ff9fff",
    "ff95ff",
    "ff8bff",
    "ff81ff",
    "ff77ff",
    "ff6cff",
    "ff62ff",
    "ff58ff",
    "ff4eff",
]
RV_SNOW_FROM = 0
RV_SNOW = [
    "c7ffff",
    "c6ffff",
    "c5ffff",
    "c4ffff",
    "c3ffff",
    "c3ffff",
    "c2ffff",
    "c1ffff",
    "c0ffff",
    "bfffff",
    "bfffff",
    "b8f8ff",
    "b2f2ff",
    "abebff",
    "a5e5ff",
    "9fdfff",
    "98d8ff",
    "92d2ff",
    "8bcbff",
    "85c5ff",
    "7fbfff",
    "78b8ff",
    "72b2ff",
    "6babff",
    "65a5ff",
    "5f9fff",
    "5b9bff",
    "5898ff",
    "5595ff",
    "5292ff",
    "4f8fff",
    "4b8bff",
    "4888ff",
    "4585ff",
    "4282ff",
    "3f7fff",
    "3b7bff",
    "3878ff",
    "3575ff",
    "3272ff",
    "2f6fff",
    "2b6bff",
    "2868ff",
    "2565ff",
    "2262ff",
    "1f5fff",
    "1b5bff",
    "1858ff",
    "1555ff",
    "1252ff",
    "0f4fff",
    "0c4bff",
    "0948ff",
    "0645ff",
    "0242ff",
    "003fff",
    "003bff",
    "0038ff",
    "0035ff",
    "0032ff",
]
_RV = [(hex_rgb("#" + h), False, RV_RAIN_FROM + i) for i, h in enumerate(RV_RAIN)] + [
    (hex_rgb("#" + h), True, RV_SNOW_FROM + i) for i, h in enumerate(RV_SNOW)
]


def rain_rate(dbz: float) -> float:
    """Marshall–Palmer, Z = 200 R^1.6, mm/h."""
    return float((10 ** (dbz / 10) / 200) ** (1 / 1.6))


def snow_rate(dbz: float) -> float:
    """Z = 180 S^2 (NEXRAD's cautious snow setting), mm of water/h ≈ cm of snow/h."""
    return math.sqrt(10 ** (dbz / 10) / 180)


def radar_recolor(r: int, g: int, b: int) -> RGB | None:
    best, dist = _RV[0], math.inf
    for e in _RV:
        d = (e[0][0] - r) ** 2 + (e[0][1] - g) ** 2 + (e[0][2] - b) ** 2
        if d < dist:
            best, dist = e, d
    if dist > 40 * 40 * 3:
        return None
    _, is_snow, dbz = best
    return ramp_color(SNOW, snow_rate(dbz)) if is_snow else ramp_color(RAIN, rain_rate(dbz))


def hrrr_recolor(r: int, g: int, b: int) -> RGB | None:
    """IEM paints HRRR by type: greens/yellows rain, blues snow, purples/reds ice."""
    mx, mn = max(r, g, b) / 255, min(r, g, b) / 255
    light = (mx + mn) / 2
    d = mx - mn
    if d < 0.04:
        return None
    sat = d / (1 - abs(2 * light - 1)) if light not in (0, 1) else 0
    R, G, B = r / 255, g / 255, b / 255
    if mx == R:
        h = 60 * (((G - B) / d) % 6)
    elif mx == G:
        h = 60 * ((B - R) / d + 2)
    else:
        h = 60 * ((R - G) / d + 4)
    rain = [hex_rgb(c) for _, c in RAIN]
    snow = [hex_rgb(c) for _, c in SNOW]
    mix = [hex_rgb(c) for _, c in MIX]
    if 30 <= h < 65 and sat > 0.8:
        return rain[3] if h >= 48 else rain[4] if h >= 42 else rain[5]
    if 80 <= h < 170:
        return rain[0] if light > 0.75 else rain[1] if light > 0.45 else rain[2]
    if 170 <= h < 225:
        if light > 0.62:
            return snow[0]
        if light > 0.5:
            return snow[1]
        if light > 0.42:
            return snow[2]
        return snow[3] if light > 0.31 else snow[4]
    return mix[0] if light > 0.78 else mix[1]


# ---- Sources -----------------------------------------------------------------------


@dataclass
class RadarFrame:
    t: int
    path: str
    template: str


def radar_frames(net: Net) -> list[RadarFrame]:
    ix = net.json(RAINVIEWER_INDEX)
    if not ix or not ix.get("host"):
        return []
    out = []
    for f in (ix.get("radar") or {}).get("past") or []:
        if isinstance(f.get("time"), int) and isinstance(f.get("path"), str):
            out.append(
                RadarFrame(
                    f["time"], f["path"], f"{ix['host']}{f['path']}/256/{{z}}/{{x}}/{{y}}/2/1_1.png"
                )
            )
    return sorted(out, key=lambda f: f.t)


def hrrr_slots(net: Net) -> dict[int, tuple[int, str]]:
    """Valid time → (IEM forecast minute, model run). Each slot comes from the newest run
    reaching it (hourly runs to 18 h, 6-hourly runs to 48 h), so read each slot's own JSON."""
    out: dict[int, tuple[int, str]] = {}

    def one(minute: int) -> tuple[int, int | None, str]:
        j = net.json(f"{IEM}/data/gis/images/4326/hrrr/refp_{minute:04d}.json")
        if not isinstance(j, dict) or not isinstance(j.get("model_forecast_utc"), str):
            return minute, None, ""
        return minute, iso_ts(j["model_forecast_utc"]), str(j.get("model_init_utc", ""))

    with ThreadPoolExecutor(4) as pool:
        for minute, valid, init in pool.map(one, range(0, 48 * 60 + 1, 60)):
            if valid is not None and valid not in out:
                out[valid] = (minute, init)
    return out


@dataclass
class Wpc:
    base: int
    issued: str


def wpc_info(net: Net) -> Wpc | None:
    j = net.json(
        f"{WPC}/13/query",
        {
            "where": "1=1",
            "outFields": "start_time,issue_time",
            "returnGeometry": "false",
            "resultRecordCount": "1",
            "f": "json",
        },
    )
    try:
        a = j["features"][0]["attributes"]
        return Wpc(wpc_ts(a["start_time"]), str(a.get("issue_time", "")))
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def wpc_ts(s: str) -> int:
    """'2026-11-07 12:00:00' (UTC) → Unix seconds."""
    return iso_ts(s.replace(" ", "T") + "Z")


def wpc_layer(t: int, base: int) -> int | None:
    """Layer 13 holds hours 0–6 from `base`, 14 holds 6–12, … 25 holds 72–78."""
    i = (t - HOUR - base) // (6 * HOUR)
    return 13 + i if 0 <= i <= 12 else None


def wpc_draw(net: Net, layer: int, region: Region) -> np.ndarray | None:
    fc = net.json(
        f"{WPC}/{layer}/query",
        {
            "where": "qpf>=0.1",
            "outFields": "qpf",
            "returnGeometry": "true",
            "maxAllowableOffset": "0.02",
            "geometryPrecision": "3",
            "outSR": "4326",
            "f": "geojson",
        },
    )
    if not isinstance(fc, dict) or not isinstance(fc.get("features"), list):
        return None
    sx = region.width / (region.x1 - region.x0)
    sy = region.height / (region.y1 - region.y0)

    def pix(lon: float, lat: float) -> tuple[float, float]:
        return (merc_x(lon) - region.x0) * sx, (region.y1 - merc_y(lat)) * sy

    out = Image.new("RGBA", (region.width, region.height), (0, 0, 0, 0))
    feats = sorted(fc["features"], key=lambda f: (f.get("properties") or {}).get("qpf", 0))
    for f in feats:
        color = ramp_color(UNTYPED, float((f.get("properties") or {}).get("qpf", 0)))
        geom = f.get("geometry") or {}
        if not color or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        mask = Image.new("L", out.size, 0)
        draw = ImageDraw.Draw(mask)
        for poly in polys:
            for i, ring in enumerate(poly):
                if len(ring) >= 3:
                    draw.polygon([pix(x, y) for x, y in ring], fill=0 if i else 1)
        out.paste((*color, 255), (0, 0), mask.point(lambda v: 255 if v else 0))
    return np.asarray(out)


# ---- Snowfall totals ------------------------------------------------------------------


@dataclass
class Grid:
    """Raw values on a lat/lon grid: row 0 is the north edge, column 0 the west."""

    data: np.ndarray
    lon0: float
    lat0: float
    dlon: float
    dlat: float


def wcs_grid(net: Net, layer: str, time_: str, region: Region, margin: float = 0.5) -> Grid | None:
    """GeoMet WCS: the raw numbers (not a picture) over the region, as a float grid."""
    (south, west), (north, east) = region.bounds
    q = urllib.parse.urlencode(
        [
            ("service", "WCS"),
            ("version", "2.0.1"),
            ("request", "GetCoverage"),
            ("coverageId", layer),
            ("format", "image/tiff"),
            ("subsettingCrs", "EPSG:4326"),
            ("subset", f"lat({south - margin},{north + margin})"),
            ("subset", f"long({west - margin},{east + margin})"),
            ("TIME", time_),
        ]
    )
    r = net.get(f"{GEOMET}?{q}")
    if r is None or "tiff" not in r.headers.get("content-type", ""):
        return None
    try:
        im = Image.open(io.BytesIO(r.content))
        if not isinstance(im, TiffImagePlugin.TiffImageFile):
            return None
        data = np.asarray(im, dtype=np.float32)
        tie = im.tag_v2[33922]
        scale = im.tag_v2[33550]
    except (OSError, KeyError, ValueError):
        return None
    return Grid(data, float(tie[3]), float(tie[4]), float(scale[0]), float(scale[1]))


def on_region(grid: Grid, region: Region) -> np.ndarray:
    """Sample a lat/lon grid onto the region's Web Mercator pixels (NaN where it has none)."""
    xs = region.x0 + (np.arange(region.width) + 0.5) * (region.x1 - region.x0) / region.width
    ys = region.y1 - (np.arange(region.height) + 0.5) * (region.y1 - region.y0) / region.height
    lons = xs * 180 / WORLD
    lats = np.degrees(2 * np.arctan(np.exp(ys * math.pi / WORLD)) - math.pi / 2)
    ci = np.floor((lons - grid.lon0) / grid.dlon).astype(int)
    ri = np.floor((grid.lat0 - lats) / grid.dlat).astype(int)
    h, w = grid.data.shape
    out = np.full((region.height, region.width), np.nan, np.float32)
    cv = (ci >= 0) & (ci < w)
    rv = (ri >= 0) & (ri < h)
    sub = grid.data[np.ix_(ri[rv], ci[cv])]
    out[np.ix_(rv, cv)] = sub
    # Values far out of range are the model's "no data" outside its domain.
    out[(out < 0) | (out > 5000)] = np.nan
    return out


def paint_total(cm: np.ndarray) -> np.ndarray:
    """Snow totals (cm) to RGBA on the TOTAL ramp; below the first step is clear."""
    out = np.zeros((*cm.shape, 4), np.uint8)
    lows = np.array([low for low, _ in TOTAL])
    idx = np.digitize(np.nan_to_num(cm, nan=-1.0), lows)  # 0 = below the first step
    for i, (_, color) in enumerate(TOTAL, start=1):
        out[idx == i] = (*hex_rgb(color), 255)
    return out


# ---- Composing and saving -------------------------------------------------------------


def over(top: np.ndarray | None, bottom: np.ndarray) -> np.ndarray:
    """Opaque-or-clear layering: top's solid pixels replace bottom's."""
    if top is None:
        return bottom
    out = bottom.copy()
    solid = top[..., 3] > 0
    out[solid] = top[solid]
    return out


def snap(img: np.ndarray, region: Region) -> np.ndarray:
    """Each pixel to the nearest palette colour (index 0 = clear)."""
    out = np.zeros(img.shape[:2], np.uint8)
    solid = img[..., 3] > 0
    if not solid.any():
        return out
    pal = np.array(PALETTE[1:], np.int32)
    px = img[solid][:, :3].astype(np.int32)
    keys, inverse = np.unique(px, axis=0, return_inverse=True)
    d = ((keys[:, None, :] - pal[None, :, :]) ** 2).sum(-1)
    out[solid] = (d.argmin(1) + 1).astype(np.uint8)[inverse.reshape(-1)]
    return out


def encode(indexed: np.ndarray) -> bytes:
    """A small palette PNG with index 0 transparent."""
    im = Image.fromarray(indexed, "P")
    im.putpalette([v for c in PALETTE for v in c])
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True, transparency=0)
    return buf.getvalue()


@dataclass
class FrameOut:
    t: int
    past: bool
    file: str
    key: str
    # Where the US forecast came from: "hrrr", "wpc" (no type) or "" (none / radar).
    south: str


@dataclass
class TotalOut:
    hours: int
    start: int
    end: int
    file: str
    key: str


class Renderer:
    """Draws frames into `out_dir` and writes `index.json` for the map."""

    def __init__(self, out_dir: Path, net: Net, now: Callable[[], float] = time.time) -> None:
        self.dir = out_dir
        self.net = net
        self.now = now
        self.totals: list[TotalOut] = []
        self._prev_totals: dict[str, TotalOut] = {}
        self.dir.mkdir(parents=True, exist_ok=True)

    def _previous(self) -> dict[str, FrameOut]:
        try:
            data = json.loads((self.dir / "index.json").read_text())
            self._prev_totals = {t["key"]: TotalOut(**t) for t in data.get("totals", [])}
            return {f["key"]: FrameOut(**f) for f in data.get("frames", [])}
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def _save(self, img: np.ndarray, region: Region, prefix: str) -> str:
        data = encode(snap(img, region))
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        path = self.dir / name
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return name

    def run(self, region: Region) -> dict[str, Any]:
        prev = self._previous()
        frames: list[FrameOut] = []
        now = int(self.now())
        blank = np.zeros((region.height, region.width, 4), np.uint8)

        # Past: radar, every 10 minutes for two hours.
        for rf in radar_frames(self.net):
            key = f"radar|{rf.path}|{region.key}"
            if key in prev and (self.dir / prev[key].file).exists():
                frames.append(prev[key])
                continue
            img = stitch(self.net, rf.template, region)
            if img is None:
                continue
            painted = repaint(img, radar_recolor)
            frames.append(FrameOut(rf.t, True, self._save(painted, region, f"r{rf.t}"), key, ""))

        self._write(region, now, frames)

        # Future: HRDPS hourly, with HRRR or WPC outside its domain.
        dims = capabilities_dims(self.net, HRDPS_LAYERS[2][0])
        times = [t for t in parse_times(dims.get("time", "")) if t > now]
        run_ref = dims.get("reference_time.default", "")
        slots = hrrr_slots(self.net) if times else {}
        wpc = wpc_info(self.net) if times else None
        todo: list[tuple[int, str, int | None, int | None]] = []
        for t in times:
            minute, init = slots.get(t, (None, ""))
            layer = wpc_layer(t, wpc.base) if wpc else None
            if minute is not None:
                south_key = f"hrrr:{minute}:{init}"
            elif wpc and layer is not None:
                south_key = f"wpc:{layer}:{wpc.issued}"
            else:
                south_key = "none"
            key = f"fc|{t}|{run_ref}|{south_key}|{region.key}"
            if key in prev and (self.dir / prev[key].file).exists():
                frames.append(prev[key])
            else:
                todo.append((t, key, minute, layer))

        if todo:
            d = geomet_map(
                self.net, DOMAIN_LAYER, sld(DOMAIN_LAYER, [(-1, "#000000")]), region, None
            )
            domain = (d[..., 3] > 0) if d is not None else np.zeros(blank.shape[:2], bool)

            def draw(job: tuple[int, str, int | None, int | None]) -> FrameOut:
                t, key, minute, layer = job
                south, kind = blank, ""
                if minute is not None:
                    tiles = stitch(
                        self.net,
                        f"{IEM}/cache/tile.py/1.0.0/hrrr::REFP-F{minute:04d}-0/{{z}}/{{x}}/{{y}}.png",
                        region,
                    )
                    if tiles is not None:
                        south, kind = repaint(tiles, hrrr_recolor), "hrrr"
                if not kind and layer is not None:
                    drawn = wpc_draw(self.net, layer, region)
                    if drawn is not None:
                        south, kind = drawn, "wpc"
                img = south.copy()
                img[domain] = 0
                for name, ramp in HRDPS_LAYERS:
                    img = over(geomet_map(self.net, name, sld(name, ramp), region, ts_iso(t)), img)
                return FrameOut(t, False, self._save(img, region, f"f{t}"), key, kind)

            # Two frames at a time (the sources are the slow part; more costs worker
            # memory), soonest first, with the index rewritten as they land so a first
            # build is usable early.
            with ThreadPoolExecutor(2) as pool:
                for i, frame in enumerate(pool.map(draw, todo), 1):
                    frames.append(frame)
                    if i % 6 == 0:
                        self._write(region, now, frames)

        self.totals = self._snow_totals(region, now)
        index = self._write(region, now, frames)
        self._prune(
            {f.file for f in frames}
            | {f.file for f in prev.values()}
            | {t.file for t in self.totals}
            | {t.file for t in self._prev_totals.values()}
        )
        return index

    def _snow_totals(self, region: Region, now: int) -> list[TotalOut]:
        """Snow over the next 12, 24 and 48 hours (or to the run's end), Canadian model."""
        dims = capabilities_dims(self.net, SN_TOTAL_LAYER)
        times = parse_times(dims.get("time", ""))
        if not times:
            return []
        run_ref = dims.get("reference_time.default", "")
        past = [t for t in times if t <= now]
        t0 = past[-1] if past else times[0]
        start: np.ndarray | None = None
        out: list[TotalOut] = []
        seen_ends: set[int] = set()
        for hours in TOTAL_HOURS:
            end = t0 + hours * HOUR
            if end not in times:
                end = times[-1]
            if end <= t0 or end in seen_ends:
                continue
            seen_ends.add(end)
            span = round((end - t0) / HOUR)
            key = f"tot|{run_ref}|{t0}|{end}|{region.key}"
            had = self._prev_totals.get(key)
            if had and (self.dir / had.file).exists():
                out.append(had)
                continue
            if start is None:
                g0 = wcs_grid(self.net, SN_TOTAL_LAYER, ts_iso(t0), region)
                if g0 is None:
                    return out
                start = on_region(g0, region)
            g1 = wcs_grid(self.net, SN_TOTAL_LAYER, ts_iso(end), region)
            if g1 is None:
                continue
            # mm of water over the window; at 10:1 that's cm of snow.
            cm = np.clip(on_region(g1, region) - start, 0, None)
            name = self._save(paint_total(cm), region, f"t{span}")
            out.append(TotalOut(span, t0, end, name, key))
        return out

    def _write(self, region: Region, now: int, frames: list[FrameOut]) -> dict[str, Any]:
        frames.sort(key=lambda f: (f.t, not f.past))
        index = {
            "generated": ts_iso(now),
            "bounds": region.bounds,
            "width": region.width,
            "height": region.height,
            "now": max((f.t for f in frames if f.past), default=None),
            "frames": [asdict(f) for f in frames],
            "totals": [asdict(t) for t in self.totals],
        }
        tmp = self.dir / "index.json.tmp"
        tmp.write_text(json.dumps(index))
        tmp.replace(self.dir / "index.json")
        return index

    def _prune(self, keep: set[str]) -> None:
        """Drop frames neither this index nor the last one uses (a page may still load those)."""
        for p in self.dir.glob("*.png"):
            if p.name not in keep:
                p.unlink(missing_ok=True)
