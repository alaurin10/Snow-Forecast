"""Recent satellite imagery for the map (docs/MAP-PLAN.md, B6).

Every six hours the worker looks, for each location, for the newest Sentinel-2 views
(Microsoft Planetary Computer) that actually see the ground there. A scene's own cloud
percentage covers a 110 km tile and says little about one valley (a "0 % cloud" scene
had no data at all at a test location), so each candidate is judged by its scene
classification layer (SCL) over a small square round the location: at least
`min_clear` of the pixels with data must be free of cloud and cloud shadow, and at most
`max_nodata` may have no data. The newest `keep` that pass go into
`data/sat/index.json`, which the API serves at /api/sat and which also lists the only
Sentinel-2 items the tile proxy will fetch (see snowwatch/tiles.py).

A Sentinel-2 pass is cut into 110 km MGRS tiles, each its own STAC item; a "scene" here
is one pass (a datatake): every item of it that covers the square. Its SCL crops are
merged, so a location on a tile edge still counts as covered.

The index also names the newest day of NASA GIBS's daily VIIRS mosaic that has imagery
over the map (today's is black until the afternoon pass is processed) and the newest
day of HLS (30 m Sentinel-2, about six days behind). Judged scenes are remembered in
`data/sat/checked.json`, so each refresh only reads the SCL of new passes.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from snowwatch.models import Location

log = logging.getLogger("snowwatch.sat")

PC = "https://planetarycomputer.microsoft.com/api"
STAC_SEARCH = f"{PC}/stac/v1/search"
PC_DATA = f"{PC}/data/v1"
COLLECTION = "sentinel-2-l2a"
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
VIIRS = "VIIRS_NOAA20_CorrectedReflectance_TrueColor"
VIIRS_SNOW = "VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1"
HLS = "HLS_S30_Nadir_BRDF_Adjusted_Reflectance"

# The square judged round each location for whole scenes: 8 x 8 km.
CROP_KM = 4.0
# The area stitched round each location from the newest clear pixels: 24 x 24 km at
# 96 x 96 cells (250 m each). One SCL crop per tile serves both: the 8 km square is
# its middle 32 x 32 cells.
AREA_KM = 12.0
AREA_PX = 96
INNER = slice(AREA_PX // 2 - 16, AREA_PX // 2 + 16)
# Cells of a pass's grid: no data, clear ground, cloud or cloud shadow, clear snow.
G_NODATA, G_CLEAR, G_CLOUD, G_SNOW = 0, 1, 2, 3
# Stitching. A pass's clear cells lose a cell's margin next to its cloud (SCL misses
# thin cloud edges), and specks under MIN_PIECE cells are dropped (cloud-edge errors
# more often than ground). A pass is a layer only if what it adds is at least MIN_SHARE
# of the area or MIN_INNER of the 8 km square round the location, so a small strip of
# new ground at the location still counts while scraps elsewhere don't. Stop once
# FULL_SHARE is filled or at MAX_LAYERS.
MIN_PIECE = 12
MIN_SHARE = 0.02
MIN_INNER = 0.05
FULL_SHARE = 0.98
MAX_LAYERS = 8
# A date label for a part at least this share of the area (at most two per pass).
LABEL_SHARE = 0.02
# SCL classes: 0 no data, 3 cloud shadow, 8 and 9 cloud, 10 thin cirrus, 11 snow.
NO_DATA = 0
CLOUDY = (3, 8, 9, 10)
SNOW = 11
# New passes judged per location per refresh (each is one to four small requests);
# the rest wait for the next refresh.
MAX_CHECKS = 24
# How long a judged pass is remembered (longer than the search window).
CHECKED_DAYS = 45

ITEM_ID = re.compile(r"S2[A-D]_MSIL2A_\d{8}T\d{6}_R\d{3}_T\d{2}[A-Z]{3}_\d{8}T\d{6}")
ATTRIBUTION = [
    "Contains modified Copernicus Sentinel data",
    "Microsoft Planetary Computer",
    "NASA GIBS (VIIRS, HLS)",
]

Quad = Annotated[list[float], Field(min_length=4, max_length=4)]


class SatItem(BaseModel):
    """One Sentinel-2 tile of a pass: its id for the tile proxy and its outline."""

    id: str
    bbox: Quad  # west, south, east, north


class SatScene(BaseModel):
    """One Sentinel-2 pass that sees the ground at a location."""

    id: str  # the pass (datatake), e.g. S2C_MSIL2A_20261110T182601_R127
    time: datetime
    platform: str  # Sentinel-2A, -2B or -2C
    clear_pct: int  # of the square round the location with data: no cloud or shadow
    snow_pct: int  # of the same: snow
    nodata_pct: int  # of the whole square
    items: list[SatItem]
    # GIBS has HLS (30 m, from this same pass) for its date: wider than the items.
    hls: bool = False


Pair = Annotated[list[float], Field(min_length=2, max_length=2)]


class SatLayer(BaseModel):
    """One pass in a stitched view: its clear pixels, over every older layer."""

    id: str
    time: datetime
    platform: str
    share_pct: int  # of the stitched area this pass supplies
    items: list[SatItem]
    bbox: Quad  # west, south, east, north of the part it supplies (with a margin)


class SatLabel(BaseModel):
    lon: float
    lat: float
    time: datetime


class SatComposite(BaseModel):
    """The newest clear view round a location, stitched from passes: each cell from the
    newest pass that saw the ground there, cloud cut out (see `stitch`)."""

    layers: list[SatLayer]  # newest first; the map draws them oldest at the bottom
    filled_pct: int  # of the area some pass saw clearly
    at_location: datetime | None  # when the cell under the location was seen
    latest_pass: datetime | None  # the newest pass looked at, clear or not
    box: Quad  # the area worked out: west, south, east, north
    boundaries: list[list[Pair]]  # where one pass's part meets another's, lon/lat lines
    labels: list[SatLabel]  # where to write each part's date


class SatLocation(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    scenes: list[SatScene]  # newest first
    composite: SatComposite | None = None
    checked_at: datetime | None = None
    error: str | None = None


class SatOut(BaseModel):
    """The map's recent satellite imagery: daily VIIRS, and clear Sentinel-2 scenes per
    location (newest first)."""

    generated_at: datetime | None = None
    viirs_date: str | None = None  # the newest day of daily VIIRS with imagery here
    hls_date: str | None = None  # the newest day of HLS on GIBS
    days: int = 30  # how far back scenes are looked for
    min_clear_pct: int = 70
    locations: list[SatLocation] = []
    attribution: list[str] = ATTRIBUTION


# --- judging a pass ---------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    clear: float  # share of pixels with data that are free of cloud and shadow
    nodata: float  # share of all pixels without data
    snow: float  # share of pixels with data that are snow


def merge_crops(crops: Iterable[np.ndarray]) -> np.ndarray:
    """One SCL square from several tiles' crops: each pixel from the first that has data.

    A crop is Planetary Computer's `.npy` answer: (2, h, w), the SCL class then a mask
    (0 where the tile has no data)."""
    out: np.ndarray | None = None
    for a in crops:
        scl = np.where(a[1] > 0, a[0], NO_DATA).astype(np.uint8)
        out = scl if out is None else np.where(out == NO_DATA, scl, out)
    if out is None:
        raise ValueError("no crops")
    return out


def classify(scl: np.ndarray) -> np.ndarray:
    """SCL classes to grid cells: no data, clear, cloud (or its shadow), snow."""
    g = np.full(scl.shape, G_CLEAR, np.uint8)
    g[np.isin(scl, CLOUDY)] = G_CLOUD
    g[scl == SNOW] = G_SNOW
    g[scl == NO_DATA] = G_NODATA
    return g


def judge_grid(g: np.ndarray) -> Look:
    """A Look from grid cells (the same rule as `judge`)."""
    valid = g != G_NODATA
    n = int(valid.sum())
    if n == 0:
        return Look(clear=0.0, nodata=1.0, snow=0.0)
    return Look(
        clear=1 - int((g == G_CLOUD).sum()) / n,
        nodata=1 - n / g.size,
        snow=int((g == G_SNOW).sum()) / n,
    )


def judge(scl: np.ndarray) -> Look:
    valid = scl != NO_DATA
    n = int(valid.sum())
    if n == 0:
        return Look(clear=0.0, nodata=1.0, snow=0.0)
    cloudy = int(np.isin(scl, CLOUDY).sum())
    return Look(
        clear=1 - cloudy / n,
        nodata=1 - n / scl.size,
        snow=int((scl == SNOW).sum()) / n,
    )


def crop_box(lat: float, lon: float, km: float = CROP_KM) -> tuple[float, float, float, float]:
    """West, south, east, north of the square round a point."""
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.1, math.cos(math.radians(lat))))
    return (round(lon - dlon, 5), round(lat - dlat, 5), round(lon + dlon, 5), round(lat + dlat, 5))


# --- passes -----------------------------------------------------------------------


@dataclass
class Pass:
    id: str
    time: datetime
    platform: str
    items: list[SatItem] = field(default_factory=list)


def pass_id(item_id: str) -> str:
    """The datatake an item belongs to: satellite, product, sensing time, orbit."""
    return "_".join(item_id.split("_")[:4])


def group_passes(features: Sequence[dict[str, Any]]) -> list[Pass]:
    """STAC items grouped by pass, newest first. An MGRS tile processed twice keeps its
    newest processing."""
    by_pass: dict[str, Pass] = {}
    tiles: dict[tuple[str, str], str] = {}
    for f in features:
        fid = str(f.get("id", ""))
        if not ITEM_ID.fullmatch(fid):
            continue
        props = f.get("properties") or {}
        try:
            t = datetime.fromisoformat(str(props["datetime"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        bbox = f.get("bbox") or []
        if len(bbox) != 4:
            continue
        pid = pass_id(fid)
        tile = fid.split("_")[4]
        prev = tiles.get((pid, tile))
        if prev is not None and prev >= fid:
            continue
        p = by_pass.setdefault(pid, Pass(pid, t, str(props.get("platform") or _platform(fid)), []))
        if prev is not None:
            p.items = [i for i in p.items if i.id != prev]
        tiles[(pid, tile)] = fid
        p.items.append(SatItem(id=fid, bbox=[round(float(v), 5) for v in bbox]))
    return sorted(by_pass.values(), key=lambda p: p.time, reverse=True)


def _platform(item_id: str) -> str:
    return f"Sentinel-2{item_id[2]}"


def search(
    client: httpx.Client, lat: float, lon: float, start: datetime, end: datetime
) -> list[Pass]:
    w, s, e, n = crop_box(lat, lon)
    body = {
        "collections": [COLLECTION],
        "bbox": [w, s, e, n],
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": 200,
        "sortby": [{"field": "datetime", "direction": "desc"}],
        "fields": {
            "include": ["id", "bbox", "properties.datetime", "properties.platform"],
            "exclude": ["assets", "links", "geometry"],
        },
    }
    r = client.post(STAC_SEARCH, json=body, timeout=40)
    r.raise_for_status()
    return group_passes(r.json().get("features") or [])


def scl_crop(client: httpx.Client, item: str, lat: float, lon: float) -> np.ndarray | None:
    """The SCL of the area round a point from one item (row 0 north, equal steps of
    longitude and latitude), or None where the item doesn't reach."""
    w, s, e, n = crop_box(lat, lon, AREA_KM)
    url = f"{PC_DATA}/item/bbox/{w},{s},{e},{n}/{AREA_PX}x{AREA_PX}.npy"
    r = client.get(
        url, params={"collection": COLLECTION, "item": item, "assets": "SCL"}, timeout=40
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    a: np.ndarray = np.load(io.BytesIO(r.content), allow_pickle=False)
    if a.ndim != 3 or a.shape[0] != 2:
        raise ValueError(f"unexpected SCL crop shape {a.shape}")
    return a


def read_pass(client: httpx.Client, p: Pass, lat: float, lon: float) -> np.ndarray:
    """A pass's grid over the area round a point, reading as few of its tiles as it
    takes to cover it."""
    crops: list[np.ndarray] = []
    for it in p.items:
        a = scl_crop(client, it.id, lat, lon)
        if a is None:
            continue
        crops.append(a)
        if not (merge_crops(crops) == NO_DATA).any():
            break
    if not crops:
        return np.zeros((AREA_PX, AREA_PX), np.uint8)
    return classify(merge_crops(crops))


# --- stitching --------------------------------------------------------------------


def stitch(
    grids: Sequence[tuple[Pass, np.ndarray]],
    box: tuple[float, float, float, float],
    latest: datetime | None = None,
) -> SatComposite:
    """The newest clear view of an area from passes' grids (given newest first).

    Newest first, each pass takes the cells it saw clearly (ground or snow) that no
    newer pass did. A pass adding less than MIN_SHARE of the area is left out; it stops
    once FULL_SHARE is filled or at MAX_LAYERS. So a sliver of new clear ground (a pass
    whose swath ends a few km away, or a gap in today's cloud) is shown, with older
    clear passes around it, rather than the whole view waiting for a pass that is clear
    everywhere."""
    owner = np.full((AREA_PX, AREA_PX), -1, np.int16)
    layers: list[tuple[Pass, np.ndarray]] = []
    for p, g in grids:
        new = drop_specks(clear_cells(g) & (owner < 0), MIN_PIECE)
        if new.mean() < MIN_SHARE and new[INNER, INNER].mean() < MIN_INNER:
            continue
        owner[new] = len(layers)
        layers.append((p, new))
        if (owner >= 0).mean() >= FULL_SHARE or len(layers) >= MAX_LAYERS:
            break
    w, s, e, n = box
    dx, dy = (e - w) / AREA_PX, (n - s) / AREA_PX

    def lon(c: float) -> float:
        return round(w + c * dx, 5)

    def lat(r: float) -> float:
        return round(n - r * dy, 5)

    out_layers = []
    for p, part in layers:
        rows, cols = np.nonzero(part)
        out_layers.append(
            SatLayer(
                id=p.id,
                time=p.time,
                platform=p.platform,
                share_pct=max(1, round(part.mean() * 100)),
                items=p.items,
                # A cell's margin round the part, so its edge isn't cut short.
                bbox=[
                    lon(max(0, cols.min() - 1)),
                    lat(min(AREA_PX, rows.max() + 2)),
                    lon(min(AREA_PX, cols.max() + 2)),
                    lat(max(0, rows.min() - 1)),
                ],
            )
        )
    mid = owner[AREA_PX // 2, AREA_PX // 2]
    labels = [
        SatLabel(lon=lon(c + 0.5), lat=lat(r + 0.5), time=layers[i][0].time)
        for i, (_, part) in enumerate(layers)
        for r, c in label_points(part)
    ]
    return SatComposite(
        layers=out_layers,
        filled_pct=round((owner >= 0).mean() * 100),
        at_location=layers[mid][0].time if mid >= 0 else None,
        latest_pass=latest,
        box=[w, s, e, n],
        boundaries=[[[lon(c), lat(r)] for r, c in line] for line in boundaries(outlined(owner))],
        labels=labels,
    )


def grow(m: np.ndarray) -> np.ndarray:
    """A mask grown by one cell in all eight directions."""
    p = np.pad(m, 1)
    h, w = m.shape
    out: np.ndarray = np.zeros_like(m)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            out |= p[dr : dr + h, dc : dc + w]
    return out


def clear_cells(g: np.ndarray) -> np.ndarray:
    """Cells a pass saw clearly (ground or snow), less those touching its cloud."""
    out: np.ndarray = ((g == G_CLEAR) | (g == G_SNOW)) & ~grow(g == G_CLOUD)
    return out


def pieces(m: np.ndarray) -> list[list[tuple[int, int]]]:
    """The connected pieces (four-way) of a mask."""
    h, w = m.shape
    seen = np.zeros_like(m, dtype=bool)
    out: list[list[tuple[int, int]]] = []
    for r0, c0 in zip(*np.nonzero(m), strict=True):
        if seen[r0, c0]:
            continue
        piece = [(int(r0), int(c0))]
        seen[r0, c0] = True
        i = 0
        while i < len(piece):
            r, c = piece[i]
            i += 1
            for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= rr < h and 0 <= cc < w and m[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    piece.append((rr, cc))
        out.append(piece)
    return out


def drop_specks(m: np.ndarray, min_cells: int) -> np.ndarray:
    """A mask without its pieces smaller than `min_cells`."""
    out = m.copy()
    for piece in pieces(m):
        if len(piece) < min_cells:
            rows, cols = zip(*piece, strict=True)
            out[list(rows), list(cols)] = False
    return out


def outlined(owner: np.ndarray) -> np.ndarray:
    """The owner grid as the dividing lines see it: pieces under half a label's size are
    left out (as if unowned), so small patches don't each get a dashed box round them.
    The imagery still shows them."""
    out = owner.copy()
    for i in range(int(owner.max()) + 1):
        for piece in pieces(owner == i):
            if len(piece) < LABEL_SHARE * owner.size / 2:
                rows, cols = zip(*piece, strict=True)
                out[list(rows), list(cols)] = -1
    return out


def boundaries(owner: np.ndarray) -> list[list[tuple[int, int]]]:
    """Lines (as (row, col) grid corners) along every cell edge between two different
    passes' parts, chained into as few polylines as they make. Edges next to cells no
    pass saw clearly aren't drawn: the coarse daily mosaic shows there already."""
    segs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    a, b = owner[:, :-1], owner[:, 1:]
    for r, c in zip(*np.nonzero((a != b) & (a >= 0) & (b >= 0)), strict=True):
        segs.append(((int(r), int(c) + 1), (int(r) + 1, int(c) + 1)))
    a, b = owner[:-1, :], owner[1:, :]
    for r, c in zip(*np.nonzero((a != b) & (a >= 0) & (b >= 0)), strict=True):
        segs.append(((int(r) + 1, int(c)), (int(r) + 1, int(c) + 1)))
    return chain(segs)


def chain(
    segs: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    """Join segments that share ends into polylines, dropping the middle point of each
    straight run."""
    ends: dict[tuple[int, int], list[int]] = {}
    for i, (p, q) in enumerate(segs):
        ends.setdefault(p, []).append(i)
        ends.setdefault(q, []).append(i)
    used = [False] * len(segs)

    def walk(line: list[tuple[int, int]]) -> None:
        while True:
            nxt = next((i for i in ends[line[-1]] if not used[i]), None)
            if nxt is None:
                return
            used[nxt] = True
            p, q = segs[nxt]
            line.append(q if p == line[-1] else p)

    out: list[list[tuple[int, int]]] = []
    # Start from loose ends first, so open lines aren't split in the middle.
    order = sorted(range(len(segs)), key=lambda i: -(len(ends[segs[i][0]]) % 2))
    for i in order:
        if used[i]:
            continue
        used[i] = True
        line = [segs[i][0], segs[i][1]]
        walk(line)
        line.reverse()
        walk(line)
        straight = [line[0]]
        for k in range(1, len(line) - 1):
            (r0, c0), (r1, c1), (r2, c2) = straight[-1], line[k], line[k + 1]
            if (r1 - r0) * (c2 - c1) != (c1 - c0) * (r2 - r1):
                straight.append(line[k])
        straight.append(line[-1])
        out.append(straight)
    return out


def _runs(values: list[int]) -> list[tuple[int, int]]:
    """Consecutive runs in a list of integers, as (first, last)."""
    out: list[tuple[int, int]] = []
    for v in sorted(values):
        if out and v == out[-1][1] + 1:
            out[-1] = (out[-1][0], v)
        else:
            out.append((v, v))
    return out


def label_points(part: np.ndarray) -> list[tuple[int, int]]:
    """Where to write a part's date: the deepest cell of each of its (at most two)
    largest connected pieces of at least LABEL_SHARE of the area."""
    big = [pc for pc in pieces(part) if len(pc) >= LABEL_SHARE * part.size]
    out = []
    for piece in sorted(big, key=len, reverse=True)[:2]:
        cells = set(piece)
        # Distance from the piece's edge, by rings inward; the last ring is the deepest.
        ring = [
            (r, c)
            for r, c in piece
            if any(n not in cells for n in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)))
        ]
        done = set(ring)
        while True:
            nxt = []
            for r, c in ring:
                for n in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if n in cells and n not in done:
                        done.add(n)
                        nxt.append(n)
            if not nxt:
                break
            ring = nxt
        out.append(min(ring))
    return out


# --- GIBS -------------------------------------------------------------------------


def latest_day(client: httpx.Client, layer: str, matrix: str) -> str | None:
    """The newest day GIBS has for a layer (its WMTS time domain)."""
    today = datetime.now(UTC).date()
    url = (
        f"{GIBS}/1.0.0/{layer}/default/{matrix}/all/"
        f"{today - timedelta(days=60)}--{today + timedelta(days=1)}.xml"
    )
    r = client.get(url, timeout=30)
    r.raise_for_status()
    m = re.findall(r"<Domain>([^<]*)</Domain>", r.text)
    days = re.findall(r"\d{4}-\d{2}-\d{2}", m[-1]) if m else []
    return max(days) if days else None


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def has_imagery(data: bytes) -> bool:
    """A VIIRS tile with imagery, not the black of a day not yet processed."""
    try:
        a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint16)
    except OSError:
        return False
    return float((a.sum(axis=2) < 15).mean()) < 0.5


def viirs_day(client: httpx.Client, lat: float, lon: float, today: date) -> str | None:
    """The newest of the last four days whose daily VIIRS mosaic has imagery here."""
    x, y = tile_xy(lat, lon, 6)
    for back in range(4):
        d = today - timedelta(days=back)
        url = f"{GIBS}/{VIIRS}/default/{d}/GoogleMapsCompatible_Level9/6/{y}/{x}.jpeg"
        try:
            r = client.get(url, timeout=30)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and has_imagery(r.content):
            return d.isoformat()
    return None


# --- the index --------------------------------------------------------------------


@dataclass
class SatResult:
    locations: int = 0
    scenes: int = 0
    checked: int = 0
    errors: list[str] = field(default_factory=list)


def read_index(path: Path) -> SatOut | None:
    try:
        return SatOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _read_checked(path: Path) -> dict[str, dict[str, list[float]]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _spot_key(loc_id: str, lat: float, lon: float) -> str:
    # A location that moves is judged afresh; so is every pass when the grid changes.
    return f"{loc_id}@{lat:.3f},{lon:.3f}#{AREA_PX}"


def _grid_path(sat_dir: Path, key: str, pid: str) -> Path:
    return sat_dir / "grids" / re.sub(r"[^A-Za-z0-9_.,@#-]", "_", key) / f"{pid}.npy"


def _load_grid(path: Path) -> np.ndarray | None:
    try:
        g: np.ndarray = np.load(path, allow_pickle=False)
    except (OSError, ValueError):
        return None
    return g if g.shape == (AREA_PX, AREA_PX) else None


def allowed_items(index: SatOut | None) -> set[str]:
    """The Sentinel-2 items the tile proxy may fetch: those in the index."""
    if index is None:
        return set()
    ids = {it.id for loc in index.locations for sc in loc.scenes for it in sc.items}
    for loc in index.locations:
        for layer in loc.composite.layers if loc.composite else []:
            ids.update(it.id for it in layer.items)
    return ids


def refresh(
    sat_dir: Path,
    client: httpx.Client,
    locations: Sequence[Location],
    *,
    days: int = 30,
    min_clear: float = 0.7,
    max_nodata: float = 0.1,
    keep: int = 3,
    now: datetime | None = None,
) -> SatResult:
    """Find each location's newest clear scenes and write the index. A location whose
    search fails keeps the scenes it had."""
    now = now or datetime.now(UTC)
    start = now - timedelta(days=days)
    out = SatResult()
    index_path = sat_dir / "index.json"
    checked_path = sat_dir / "checked.json"
    old = read_index(index_path)
    old_by_id = {loc.id: loc for loc in old.locations} if old else {}
    checked = _read_checked(checked_path)
    cutoff = (now - timedelta(days=CHECKED_DAYS)).timestamp()
    spots: list[SatLocation] = []
    keep_keys: set[str] = set()

    try:
        hls_date = latest_day(client, HLS, "GoogleMapsCompatible_Level12")
    except (httpx.HTTPError, ValueError) as e:
        out.errors.append(f"HLS dates: {e}")
        hls_date = old.hls_date if old else None

    for loc in locations:
        mid = loc.band("mid")
        lat, lon = mid.lat, mid.lon
        key = _spot_key(loc.id, lat, lon)
        keep_keys.add(key)
        seen = checked.setdefault(key, {})
        spot = SatLocation(id=loc.id, name=loc.name, lat=lat, lon=lon, scenes=[], checked_at=now)
        try:
            passes = search(client, lat, lon, start, now)
            fresh = 0
            grids: list[tuple[Pass, np.ndarray]] = []
            for p in passes:
                gpath = _grid_path(sat_dir, key, p.id)
                got = seen.get(p.id)
                grid = _load_grid(gpath) if got is not None else None
                if grid is None:
                    if fresh >= MAX_CHECKS:
                        continue
                    fresh += 1
                    out.checked += 1
                    grid = read_pass(client, p, lat, lon)
                    gpath.parent.mkdir(parents=True, exist_ok=True)
                    np.save(gpath, grid)
                    look = judge_grid(grid[INNER, INNER])
                    got = [look.clear, look.nodata, look.snow, p.time.timestamp()]
                    seen[p.id] = got
                assert got is not None
                grids.append((p, grid))
                look = Look(clear=got[0], nodata=got[1], snow=got[2])
                if len(spot.scenes) >= keep:
                    continue
                if look.clear < min_clear or look.nodata > max_nodata:
                    continue
                spot.scenes.append(
                    SatScene(
                        id=p.id,
                        time=p.time,
                        platform=p.platform,
                        clear_pct=round(look.clear * 100),
                        snow_pct=round(look.snow * 100),
                        nodata_pct=round(look.nodata * 100),
                        items=p.items,
                        hls=hls_date is not None and p.time.date().isoformat() <= hls_date,
                    )
                )
            spot.composite = stitch(
                grids,
                crop_box(lat, lon, AREA_KM),
                latest=passes[0].time if passes else None,
            )
        except (httpx.HTTPError, ValueError) as e:
            msg = f"{loc.id}: {type(e).__name__}: {e}"
            out.errors.append(msg)
            log.warning("satellite scenes for %s failed: %s", loc.id, e)
            prev = old_by_id.get(loc.id)
            spot.scenes = list(prev.scenes) if prev else []
            spot.composite = prev.composite if prev else None
            spot.checked_at = prev.checked_at if prev else None
            spot.error = "Couldn't look for new scenes; showing the last ones found."
        spots.append(spot)
        out.scenes += len(spot.scenes)

    # Forget passes older than the search window could return, and moved locations.
    checked = {
        k: {pid: v for pid, v in by.items() if len(v) > 3 and v[3] >= cutoff}
        for k, by in checked.items()
        if k in keep_keys
    }
    _prune_grids(sat_dir, checked)
    lat0 = sum(s.lat for s in spots) / len(spots) if spots else 45.0
    lon0 = sum(s.lon for s in spots) / len(spots) if spots else -118.0
    viirs = viirs_day(client, lat0, lon0, now.date())
    if viirs is None:
        out.errors.append("VIIRS: no day with imagery in the last four")
        viirs = old.viirs_date if old else None

    index = SatOut(
        generated_at=now,
        viirs_date=viirs,
        hls_date=hls_date,
        days=days,
        min_clear_pct=round(min_clear * 100),
        locations=spots,
    )
    _write(index_path, index.model_dump_json())
    _write(checked_path, json.dumps(checked, separators=(",", ":")))
    out.locations = len(spots)
    return out


def _prune_grids(sat_dir: Path, checked: dict[str, dict[str, list[float]]]) -> None:
    """Delete saved grids of passes and locations no longer remembered."""
    root = sat_dir / "grids"
    if not root.exists():
        return
    keepers = {_grid_path(sat_dir, k, pid) for k, by in checked.items() for pid in by}
    for f in root.rglob("*.npy"):
        if f not in keepers:
            f.unlink(missing_ok=True)
    for d in root.iterdir():
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
