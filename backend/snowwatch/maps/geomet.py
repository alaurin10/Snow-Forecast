"""Fetching for the map: a polite GET, and Environment Canada's MSC GeoMet.

GeoMet (geo.weather.gc.ca/geomet) styles WMS pictures in our colours from an SLD we
send, and answers WCS with the raw numbers. Free, no key, Open Government Licence – Canada.
"""

from __future__ import annotations

import io
import logging
import math
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
from PIL import Image, TiffImagePlugin

from snowwatch.maps.region import WORLD, Region

log = logging.getLogger("snowwatch.precip")

GEOMET = "https://geo.weather.gc.ca/geomet"


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

    def range(self, url: str, start: int, end: int | None, tries: int = 3) -> bytes | None:
        """Bytes `start`..`end` (inclusive; None for the rest) of a file, or None.

        Only a 206 answer counts: a server that ignores Range would send the whole
        file, which for a GRIB2 forecast is hundreds of MB."""
        want = f"bytes={start}-{'' if end is None else end}"
        for attempt in range(tries):
            if attempt:
                self.sleep(2 + 3 * attempt)
            try:
                with self.client.stream("GET", url, headers={"Range": want}, timeout=30) as r:
                    if r.status_code == 206:
                        return r.read()
                    status = r.status_code
            except httpx.HTTPError as e:
                log.debug("range GET %s failed: %s", url, e)
                continue
            if status != 429 and status < 500:
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
        try:
            return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))
        except (OSError, ValueError, Image.DecompressionBombError) as e:
            log.warning("unreadable image from %s: %s", url.split("?")[0], e)
            return None


def sld(layer: str, ramp: list[tuple[float, str]], scale: float = 1) -> str:
    """A GeoMet style: each entry is the lower bound of a band; below the first is clear.

    `scale` multiplies the bounds (a 3-hour total drawn on an hourly-rate ramp: × 3)."""
    entries = [*((q * scale, c) for q, c in ramp), (9999 * scale, ramp[-1][1])]
    cmap = "".join(f'<ColorMapEntry color="{c}" quantity="{q:g}"/>' for q, c in entries)
    return (
        '<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">'
        f"<NamedLayer><Name>{layer}</Name><UserStyle><FeatureTypeStyle><Rule>"
        f'<RasterSymbolizer><ColorMap type="intervals">{cmap}</ColorMap></RasterSymbolizer>'
        "</Rule></FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>"
    )


def geomet_map(
    net: Net,
    layer: str,
    style: str | None,
    region: Region,
    time_: str | None,
    extra: dict[str, str] | None = None,
) -> np.ndarray | None:
    """One GetMap over the region. `style` is an SLD, or None for the layer's own style;
    `extra` adds parameters (such as `dim_reference_time`)."""
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
    }
    if style is not None:
        params["sld_body"] = style
    if time_:
        params["time"] = time_
    params.update(extra or {})
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


# ---- Raw grids (WCS) -------------------------------------------------------------


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
