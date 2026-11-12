"""Recent satellite imagery for the map (docs/MAP-PLAN.md, B6).

Every six hours the worker looks at the Sentinel-2 passes (Microsoft Planetary
Computer) over the 24 x 24 km round each location and makes two kinds of view, drawn
and cut into map tiles by `satrender`:

- **Stitched** (shown first): the newest clear view. Every pass of the last `days` is
  read once as a 96 x 96 grid of 250 m cells (no data, clear, cloud or its shadow,
  snow) from its scene classification (SCL). `stitch` gives each cell to the newest
  pass that saw it clearly, ignoring scraps (see its notes); the newest whole scene
  fills what is left. The parts' outlines and dates go in the index for the map.
- **Scenes**: the newest whole passes of the last `scene_days` that cover the whole
  area (at most `max_nodata` without data) and see most of it (`min_clear` free of
  cloud). Coherent pictures, with no joins in the area.

A scene's own cloud percentage covers a 110 km tile and says little about one valley,
hence the grids. A pass is cut into 110 km MGRS tiles, each its own STAC item; a "pass"
here is the datatake, with every item of it over the area, merged.

The index (`data/sat/index.json`, served at /api/sat) also names the newest day of
NASA GIBS's daily VIIRS mosaic with imagery here (today's is black until the afternoon
pass is processed), drawn under everything. Judged passes are remembered in
`data/sat/checked.json` and `grids/`, so each refresh only reads new passes.
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

from snowwatch.maps import satrender
from snowwatch.models import Location

log = logging.getLogger("snowwatch.sat")

PC = "https://planetarycomputer.microsoft.com/api"
STAC_SEARCH = f"{PC}/stac/v1/search"
PC_DATA = f"{PC}/data/v1"
COLLECTION = "sentinel-2-l2a"
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
VIIRS = "VIIRS_NOAA20_CorrectedReflectance_TrueColor"
VIIRS_SNOW = "VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1"

# The area round each location: 24 x 24 km on the ground, as a 96 x 96 grid of 250 m
# cells, in Web Mercator like the map and the pictures. INNER is its middle 8 km.
AREA_KM = 12.0
AREA_PX = 96
INNER = slice(AREA_PX // 2 - 16, AREA_PX // 2 + 16)
# Cells of a pass's grid: no data, clear ground, cloud or cloud shadow, clear snow, and
# thin haze (see HAZE_BLUE): not clear, but without cloud's margin.
G_NODATA, G_CLEAR, G_CLOUD, G_SNOW, G_HAZE = 0, 1, 2, 3, 4
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
MAX_LAYERS = 6
# A mostly cloudy pass's "clear" gaps are often haze the mask missed: a pass must see at
# least this share of the area it covers clearly to be used at all.
MIN_PASS_CLEAR = 0.15
# Then the parts are made compact: each cell goes to the commonest pass among the
# REGION_R cells round it that saw it clearly (ties to the newer), REGION_PASSES times,
# and pieces under MIN_REGION of the area join a neighbouring pass that saw them.
REGION_R = 2
REGION_PASSES = 3
MIN_REGION = 0.015
# A part is dated on the map if it is at least this share of the area.
PART_SHARE = 0.01
# SCL classes: 0 no data, 3 cloud shadow, 8 and 9 cloud, 10 thin cirrus, 11 snow.
NO_DATA = 0
CLOUDY = (3, 8, 9, 10)
SNOW = 11
# SCL misses some bright cloud (on 4 Nov 2026 a long band over Snoqualmie was "clear").
# Cloud is bright in blue and in shortwave infrared; snow is bright in blue only, bare
# rock not that bright in blue. So B02 over 0.30 and B11 over 0.25 also count as cloud
# (L2A values: reflectance x 10,000 + 1,000). On a snowy limestone scene at Sunshine it
# flagged an extra 0.5% of the area, in specks.
BRIGHT_BLUE = 4000
BRIGHT_SWIR = 3500
# Thin haze SCL calls clear (Revelstoke, 30 Oct 2026: a grey veil over the valley)
# lifts blue reflectance above what the same ground shows on its clearest day. A clear
# cell is haze if its blue is HAZE_BLUE (0.08) above the lowest blue any pass of the
# window saw there, it isn't snow (NDSI under HAZE_NDSI), and its shortwave infrared
# hasn't dropped by HAZE_SWIR_DROP from that clearest day's (snow absorbs SWIR, so
# partial new snow, which also lifts blue, lowers it; haze doesn't). Needs two passes
# that saw the cell. On the six seed areas it flagged 1-5% of crisp passes.
HAZE_BLUE = 800
HAZE_NDSI = 0.4
HAZE_SWIR_DROP = 200
OFFSET = 1000  # L2A values are reflectance x 10,000 plus this
# New passes judged per location per refresh (each is one or two small requests);
# the rest wait for the next refresh.
MAX_CHECKS = 40
# How much longer than the scene window a judged pass is remembered.
CHECKED_EXTRA_DAYS = 15

ITEM_ID = re.compile(r"S2[A-D]_MSIL2A_\d{8}T\d{6}_R\d{3}_T\d{2}[A-Z]{3}_\d{8}T\d{6}")
ATTRIBUTION = [
    "Contains modified Copernicus Sentinel data",
    "Microsoft Planetary Computer",
    "NASA GIBS (VIIRS)",
]

Quad = Annotated[list[float], Field(min_length=4, max_length=4)]
Pair = Annotated[list[float], Field(min_length=2, max_length=2)]
Box = tuple[float, float, float, float]  # Web Mercator x0, y0, x1, y1


class SatItem(BaseModel):
    """One Sentinel-2 tile of a pass."""

    id: str
    bbox: Quad  # west, south, east, north


class SatScene(BaseModel):
    """One pass that covers the whole area and sees most of it: a coherent picture."""

    id: str  # the pass (datatake), e.g. S2C_MSIL2A_20261110T182601_R127
    time: datetime
    platform: str  # Sentinel-2A, -2B or -2C
    clear_pct: int  # of the area: no cloud or shadow
    snow_pct: int  # of the area seen clearly: snow
    nodata_pct: int  # of the area: outside the pass
    view: str  # its tiles: /api/sat/tiles/<view>/<mode>/<z>/<x>/<y>.webp


class SatLayer(BaseModel):
    """One pass in a stitched view."""

    id: str
    time: datetime
    platform: str
    share_pct: int  # of the area this pass supplies


class SatPart(BaseModel):
    """Where one pass supplies a stitched view, for the map's outlines and dates."""

    time: datetime
    share_pct: int
    polygons: list[list[list[Pair]]]  # polygons, each its outer ring then holes; lon/lat


class SatComposite(BaseModel):
    """The newest clear view of the area, stitched from passes (see `stitch`)."""

    view: str  # its tiles, as for a scene
    layers: list[SatLayer]  # newest first
    parts: list[SatPart]
    lines: list[list[Pair]] = []  # where two passes' parts meet, lon/lat
    filled_pct: int  # of the area some pass saw clearly
    at_location: datetime | None  # when the cell under the location was seen
    latest_pass: datetime | None  # the newest pass looked at, clear or not


class SatLocation(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    box: Quad | None = None  # west, south, east, north of the drawn area
    scenes: list[SatScene] = []  # newest first
    composite: SatComposite | None = None
    checked_at: datetime | None = None
    error: str | None = None


class SatOut(BaseModel):
    """The map's recent satellite imagery: daily VIIRS everywhere, and per location a
    stitched newest-clear view and the newest whole clear scenes."""

    generated_at: datetime | None = None
    viirs_date: str | None = None  # the newest day of daily VIIRS with imagery here
    days: int = 30  # how far back stitched views look
    scene_days: int = 60  # how far back whole scenes are looked for
    min_clear_pct: int = 85  # a whole scene sees at least this much of the area
    zooms: list[int] = [9, 13]  # of the views' tiles
    locations: list[SatLocation] = []
    attribution: list[str] = ATTRIBUTION


# --- the area ----------------------------------------------------------------------

R_EARTH = 6378137.0


def merc(lat: float, lon: float) -> tuple[float, float]:
    return (
        math.radians(lon) * R_EARTH,
        math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH,
    )


def unmerc(x: float, y: float) -> tuple[float, float]:
    """Latitude and longitude of a Web Mercator point."""
    return (
        math.degrees(2 * math.atan(math.exp(y / R_EARTH)) - math.pi / 2),
        math.degrees(x / R_EARTH),
    )


def area_box(lat: float, lon: float, km: float = AREA_KM) -> Box:
    """The square of +-`km` on the ground round a point, in Web Mercator metres."""
    x, y = merc(lat, lon)
    h = km * 1000 / math.cos(math.radians(lat))
    return (round(x - h, 2), round(y - h, 2), round(x + h, 2), round(y + h, 2))


def box_lonlat(box: Box) -> list[float]:
    s, w = unmerc(box[0], box[1])
    n, e = unmerc(box[2], box[3])
    return [round(w, 6), round(s, 6), round(e, 6), round(n, 6)]


# --- judging a pass ---------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    clear: float  # share of cells with data that are free of cloud and shadow
    nodata: float  # share of all cells without data
    snow: float  # share of cells with data that are snow


def classify(
    scl: np.ndarray, blue: np.ndarray | None = None, swir: np.ndarray | None = None
) -> np.ndarray:
    """Grid cells from SCL classes (and, given, blue and shortwave infrared, for the
    bright cloud SCL misses): no data, clear, cloud (or its shadow), snow."""
    g = np.full(scl.shape, G_CLEAR, np.uint8)
    g[scl == SNOW] = G_SNOW
    cloud = np.isin(scl, CLOUDY)
    if blue is not None and swir is not None:
        cloud |= (blue > BRIGHT_BLUE) & (swir > BRIGHT_SWIR)
    g[cloud] = G_CLOUD
    g[scl == NO_DATA] = G_NODATA
    return g


def merge_grids(grids: Iterable[np.ndarray]) -> np.ndarray:
    """One grid from several tiles' grids of a pass: each cell from the first with data.
    A grid is cells (2-D) or cells then band values (3-D, cells first)."""
    out: np.ndarray | None = None
    for g in grids:
        if out is None:
            out = g.copy()
        else:
            gap = (out[0] if out.ndim == 3 else out) == G_NODATA
            out = np.where(gap, g, out)
    if out is None:
        raise ValueError("no grids")
    return out


def dehaze(stack: Sequence[np.ndarray]) -> list[np.ndarray]:
    """Cells of each pass (from its grid with band values, see `item_grid`), with the
    thin haze SCL called clear marked as haze (see HAZE_BLUE)."""
    if not stack:
        return []
    cells = [g[0].copy() for g in stack]
    blue = np.stack(
        [np.where(c == G_CLEAR, g[1], np.inf) for c, g in zip(cells, stack, strict=True)]
    )
    lowest = blue.min(axis=0)
    clearest = blue.argmin(axis=0)
    swir_then = np.take_along_axis(
        np.stack([g[3] for g in stack]).astype(np.float32), clearest[None], axis=0
    )[0]
    seen = np.isfinite(blue).sum(axis=0) >= 2
    for c, g in zip(cells, stack, strict=True):
        green = g[2].astype(np.float32) - OFFSET
        swir = g[3].astype(np.float32) - OFFSET
        ndsi = (green - swir) / np.maximum(green + swir, 1)
        haze = (
            (c == G_CLEAR)
            & seen
            & (g[1] > lowest + HAZE_BLUE)
            & (ndsi < HAZE_NDSI)
            & (g[3] >= swir_then - HAZE_SWIR_DROP)
        )
        c[haze] = G_HAZE
    return cells


def judge_grid(g: np.ndarray) -> Look:
    """How much of a grid (or part of one) a pass saw, and saw clearly."""
    valid = g != G_NODATA
    n = int(valid.sum())
    if n == 0:
        return Look(clear=0.0, nodata=1.0, snow=0.0)
    return Look(
        clear=1 - int(((g == G_CLOUD) | (g == G_HAZE)).sum()) / n,
        nodata=1 - n / g.size,
        snow=int((g == G_SNOW).sum()) / n,
    )


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


def search(client: httpx.Client, box: Box, start: datetime, end: datetime) -> list[Pass]:
    w, s, e, n = box_lonlat(box)
    body = {
        "collections": [COLLECTION],
        "bbox": [w, s, e, n],
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": 300,
        "sortby": [{"field": "datetime", "direction": "desc"}],
        "fields": {
            "include": ["id", "bbox", "properties.datetime", "properties.platform"],
            "exclude": ["assets", "links", "geometry"],
        },
    }
    r = client.post(STAC_SEARCH, json=body, timeout=40)
    r.raise_for_status()
    return group_passes(r.json().get("features") or [])


def item_grid(client: httpx.Client, item: str, box: Box) -> np.ndarray | None:
    """One item's grid of the area, row 0 north, in Web Mercator: its cells (from SCL,
    blue and shortwave infrared) then its blue, green and SWIR values, as a (4, n, n)
    array; None where the item doesn't reach."""
    x0, y0, x1, y1 = box
    url = f"{PC_DATA}/item/bbox/{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}/{AREA_PX}x{AREA_PX}.npy"
    params = {
        "collection": COLLECTION,
        "item": item,
        "assets": ["SCL", "B02", "B03", "B11"],
        "coord_crs": "epsg:3857",
        "dst_crs": "epsg:3857",
    }
    r = client.get(url, params=params, timeout=40)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    a: np.ndarray = np.load(io.BytesIO(r.content), allow_pickle=False)
    if a.shape != (5, AREA_PX, AREA_PX):
        raise ValueError(f"unexpected grid shape {a.shape}")
    scl = np.where(a[4] > 0, a[0], NO_DATA)  # the last band is the mask
    cells = classify(scl, a[1], a[3]).astype(np.uint16)
    return np.stack([cells, a[1], a[2], a[3]]).astype(np.uint16)


def read_pass(client: httpx.Client, p: Pass, box: Box) -> np.ndarray:
    """A pass's grid over the area, reading as few of its tiles as it takes."""
    grids: list[np.ndarray] = []
    for it in p.items:
        g = item_grid(client, it.id, box)
        if g is None:
            continue
        grids.append(g)
        if not (merge_grids(grids)[0] == G_NODATA).any():
            break
    if not grids:
        return np.zeros((4, AREA_PX, AREA_PX), np.uint16)
    return merge_grids(grids)


# --- stitching --------------------------------------------------------------------


@dataclass
class Plan:
    """Which pass supplies each cell of a stitched view (-1: none)."""

    layers: list[Pass]
    owner: np.ndarray
    latest: datetime | None = None

    def filled(self) -> float:
        return float((self.owner >= 0).mean())


def stitch(
    grids: Sequence[tuple[Pass, np.ndarray]],
    fallback: Sequence[tuple[Pass, np.ndarray]] = (),
    latest: datetime | None = None,
) -> Plan:
    """The newest clear view of the area from passes' grids (given newest first).

    Newest first, each pass takes the cells it saw clearly (ground or snow) that no
    newer pass did, less those touching its cloud and without specks. A pass adding
    less than MIN_SHARE of the area (or MIN_INNER near the location) is left out; it
    stops once FULL_SHARE is filled or at MAX_LAYERS. So a sliver of new clear ground
    (a pass whose swath ends a few km away, or a gap in today's cloud) is shown, with
    older clear passes round it, rather than the whole view waiting for a pass that is
    clear everywhere. `fallback` (the newest whole scene, if it is older than `grids`
    reach) then fills what is left, so the view has few holes."""
    owner = np.full((AREA_PX, AREA_PX), -1, np.int16)
    layers: list[Pass] = []
    oks: list[np.ndarray] = []
    seen_ids: set[str] = set()
    for p, g in [*grids, *fallback]:
        if p.id in seen_ids:
            continue
        seen_ids.add(p.id)
        if judge_grid(g).clear < MIN_PASS_CLEAR:
            continue
        ok = clear_cells(g)
        new = drop_specks(ok & (owner < 0), MIN_PIECE)
        if new.mean() < MIN_SHARE and new[INNER, INNER].mean() < MIN_INNER:
            continue
        owner[new] = len(layers)
        layers.append(p)
        oks.append(ok)
        if (owner >= 0).mean() >= FULL_SHARE or len(layers) >= MAX_LAYERS:
            break
    owner = regionalize(owner, oks)
    # Passes left with nothing after that are dropped, the rest renumbered.
    used = [i for i in range(len(layers)) if (owner == i).any()]
    remap = np.full(len(layers) + 1, -1, np.int16)
    for new_i, old_i in enumerate(used):
        remap[old_i] = new_i
    owner = np.where(owner >= 0, remap[owner], -1).astype(np.int16)
    return Plan([layers[i] for i in used], owner, latest)


def box_count(m: np.ndarray, r: int) -> np.ndarray:
    """How many True cells are in the (2r+1)-square round each cell."""
    h, w = m.shape
    a = np.pad(m.astype(np.int32), r)
    cs = np.cumsum(np.pad(a, ((0, 0), (1, 0))), axis=1)
    rows = cs[:, 2 * r + 1 :] - cs[:, :w]
    cs = np.cumsum(np.pad(rows, ((1, 0), (0, 0))), axis=0)
    out: np.ndarray = cs[2 * r + 1 :, :] - cs[:h, :]
    return out


def regionalize(owner: np.ndarray, oks: Sequence[np.ndarray]) -> np.ndarray:
    """Make the parts compact (see REGION_R): fewer, rounder parts, a little less new."""
    if not oks:
        return owner
    out = owner.copy()
    for _ in range(REGION_PASSES):
        counts = np.stack(
            [np.where(ok, box_count(out == i, REGION_R), -1) for i, ok in enumerate(oks)]
        )
        best = counts.argmax(axis=0)  # ties to the lower index: the newer pass
        top = counts.max(axis=0)
        out = np.where(top > 0, best, out).astype(np.int16)
    # Small pieces join the neighbouring pass they touch most that saw them.
    for i in range(len(oks)):
        for piece in pieces(out == i):
            if len(piece) >= MIN_REGION * out.size:
                continue
            rows, cols = (np.array(v) for v in zip(*piece, strict=True))
            mask = np.zeros_like(out, dtype=bool)
            mask[rows, cols] = True
            ring = grow(mask) & ~mask
            near = out[ring]
            near = near[(near >= 0) & (near != i)]
            for j in np.bincount(near).argsort()[::-1] if near.size else []:
                if np.bincount(near)[j] == 0:
                    break
                if oks[j][rows, cols].mean() >= 0.8:
                    take = oks[j][rows, cols]
                    out[rows[take], cols[take]] = j
                    break
    return out


def composite_out(plan: Plan, view: str, box: Box) -> SatComposite:
    """The index's description of a stitched view: its passes, and each part's outline
    and date for the map."""
    x0, _, x1, y1 = box
    cell = (x1 - x0) / AREA_PX

    def lonlat(pt: tuple[float, float]) -> list[float]:
        lat, lon = unmerc(x0 + pt[0] * cell, y1 - pt[1] * cell)
        return [round(lon, 5), round(lat, 5)]  # ~1 m

    shown = outlined(plan.owner)
    parts = []
    layers = []
    for i, p in enumerate(plan.layers):
        share = float((plan.owner == i).mean())
        layers.append(
            SatLayer(
                id=p.id, time=p.time, platform=p.platform, share_pct=max(1, round(share * 100))
            )
        )
        if (shown == i).mean() < PART_SHARE:
            continue
        polys = [[[lonlat(pt) for pt in ring] for ring in poly] for poly in polygons(shown == i)]
        if polys:
            parts.append(SatPart(time=p.time, share_pct=max(1, round(share * 100)), polygons=polys))
    mid = int(plan.owner[AREA_PX // 2, AREA_PX // 2])
    lines = [[lonlat(pt) for pt in simplify_line(smooth_line(line))] for line in boundaries(shown)]
    return SatComposite(
        view=view,
        layers=layers,
        parts=parts,
        lines=[ln for ln in lines if len(ln) >= 2],
        filled_pct=round(plan.filled() * 100),
        at_location=plan.layers[mid].time if mid >= 0 else None,
        latest_pass=plan.latest,
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
    """The owner grid as the outlines see it: pieces under PART_SHARE of the area are
    left out (as if unowned), so small patches don't each get a dashed box and a date.
    The imagery still shows them."""
    out = owner.copy()
    for i in range(int(owner.max()) + 1):
        for piece in pieces(owner == i):
            if len(piece) < PART_SHARE * owner.size:
                rows, cols = zip(*piece, strict=True)
                out[list(rows), list(cols)] = -1
    return out


def boundaries(owner: np.ndarray) -> list[list[tuple[int, int]]]:
    """Lines (as (x, y) grid corners) along every cell edge between two different
    passes' parts, chained into as few polylines as they make. Edges at the area's edge
    or next to cells no pass saw aren't drawn."""
    segs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    a, b = owner[:, :-1], owner[:, 1:]
    for r, c in zip(*np.nonzero((a != b) & (a >= 0) & (b >= 0)), strict=True):
        segs.append(((int(c) + 1, int(r)), (int(c) + 1, int(r) + 1)))
    a, b = owner[:-1, :], owner[1:, :]
    for r, c in zip(*np.nonzero((a != b) & (a >= 0) & (b >= 0)), strict=True):
        segs.append(((int(c), int(r) + 1), (int(c) + 1, int(r) + 1)))
    return chain(segs)


def chain(
    segs: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    """Join segments that share ends into polylines (closed ones end where they start)."""
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
        out.append(line)
    return out


def smooth_line(line: Sequence[tuple[float, float]], times: int = 2) -> list[tuple[float, float]]:
    """Round off a line's grid stairs as `smooth` does a ring; ends stay put, and a
    closed line (ending where it starts) is smoothed as a ring."""
    pts = [(float(x), float(y)) for x, y in line]
    if len(pts) > 3 and pts[0] == pts[-1]:
        ring = smooth(pts[:-1], times)
        return [*ring, ring[0]]
    for _ in range(times):
        out = [pts[0]]
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            out += [
                (0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by),
                (0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by),
            ]
        out.append(pts[-1])
        pts = out
    return pts


def simplify_line(
    line: Sequence[tuple[float, float]], tol: float = 0.4
) -> list[tuple[float, float]]:
    pts = list(line)
    return pts if len(pts) < 4 else _dp(pts, tol)


def rings(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """The boundary rings of a mask's cells, as grid corners (x = column, y = row).

    Each region's outer ring and each hole's ring are closed lists of corners (first
    not repeated). Outer rings have a positive signed area, holes a negative one. Where
    two cells touch only at a corner they stay in separate rings."""
    m = np.pad(mask, 1)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        edges.setdefault(a, []).append(b)

    # Round each cell clockwise on screen (y down), only where the neighbour is outside.
    for r, c in zip(*np.nonzero(mask), strict=True):
        r, c = int(r), int(c)
        if not m[r, c + 1]:  # above
            add((c, r), (c + 1, r))
        if not m[r + 1, c + 2]:  # right
            add((c + 1, r), (c + 1, r + 1))
        if not m[r + 2, c + 1]:  # below
            add((c + 1, r + 1), (c, r + 1))
        if not m[r + 1, c]:  # left
            add((c, r + 1), (c, r))
    out: list[list[tuple[int, int]]] = []
    while edges:
        start = next(iter(edges))
        ring = [start]
        prev = start
        cur = edges[start].pop()
        if not edges[start]:
            del edges[start]
        while cur != start:
            ring.append(cur)
            nxt = edges[cur]
            if len(nxt) > 1:
                # Two ways on (cells meeting at a corner): turn right, keeping the cell
                # on the right, so the two cells' rings don't cross.
                dx, dy = cur[0] - prev[0], cur[1] - prev[1]
                right = (cur[0] - dy, cur[1] + dx)
                pick = right if right in nxt else nxt[0]
            else:
                pick = nxt[0]
            nxt.remove(pick)
            if not nxt:
                del edges[cur]
            prev, cur = cur, pick
        out.append(_straight(ring))
    return out


def _straight(ring: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """A ring without the corners in the middle of straight runs."""
    n = len(ring)
    keep = []
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) != (b[1] - a[1]) * (c[0] - b[0]):
            keep.append(b)
    return keep


def signed_area(ring: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )


def _inside(pt: tuple[float, float], ring: Sequence[tuple[float, float]]) -> bool:
    x, y = pt
    inside = False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i - 1], ring[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def smooth(ring: Sequence[tuple[float, float]], times: int = 2) -> list[tuple[float, float]]:
    """Round off a closed ring's grid stairs (Chaikin's corner cutting)."""
    pts = [(float(x), float(y)) for x, y in ring]
    for _ in range(times):
        out = []
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % len(pts)]
            out += [
                (0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by),
                (0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by),
            ]
        pts = out
    return pts


def simplify(ring: Sequence[tuple[float, float]], tol: float = 0.4) -> list[tuple[float, float]]:
    """A closed ring with fewer points, none moved more than `tol` (Douglas-Peucker)."""
    pts = list(ring)
    if len(pts) < 8:
        return pts
    # Split at the point farthest from the first, and simplify both halves as lines.
    far = max(
        range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2
    )
    a = _dp(pts[: far + 1], tol)
    b = _dp([*pts[far:], pts[0]], tol)
    return a[:-1] + b[:-1]


def _dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1.0
        best, at = 0.0, -1
        for k in range(i + 1, j):
            d = abs(dy * (pts[k][0] - x1) - dx * (pts[k][1] - y1)) / norm
            if d > best:
                best, at = d, k
        if best > tol and at > 0:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [p for p, k in zip(pts, keep, strict=True) if k]


def polygons(mask: np.ndarray, min_hole: int = MIN_PIECE) -> list[list[list[tuple[float, float]]]]:
    """A mask's regions as polygons (outer ring, then its holes), smoothed, in grid
    corner coordinates. Holes smaller than `min_hole` cells are dropped."""
    outer: list[tuple[list[tuple[int, int]], float]] = []
    holes: list[tuple[list[tuple[int, int]], float]] = []
    for ring in rings(mask):
        a = signed_area(ring)
        (outer if a > 0 else holes).append((ring, abs(a)))
    polys: list[list[list[tuple[float, float]]]] = [[simplify(smooth(r))] for r, _ in outer]
    for ring, a in holes:
        if a < min_hole:
            continue
        # The middle of the hole's first edge is inside the polygon that has it.
        p = ((ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2)
        homes = [i for i, (r, _) in enumerate(outer) if _inside(p, r)]
        if homes:
            best = min(homes, key=lambda i: outer[i][1])
            polys[best].append(simplify(smooth(ring)))
    return polys


# --- GIBS -------------------------------------------------------------------------


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
    fetched: int = 0  # pictures fetched to draw views
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
    return f"{loc_id}@{lat:.3f},{lon:.3f}#{AREA_PX}mc"


def _grid_path(sat_dir: Path, key: str, pid: str) -> Path:
    return sat_dir / "grids" / re.sub(r"[^A-Za-z0-9_.,@#-]", "_", key) / f"{pid}.npy"


def _load_grid(path: Path) -> np.ndarray | None:
    try:
        g: np.ndarray = np.load(path, allow_pickle=False)
    except (OSError, ValueError):
        return None
    return g if g.shape == (4, AREA_PX, AREA_PX) else None


def refresh(
    sat_dir: Path,
    client: httpx.Client,
    locations: Sequence[Location],
    *,
    days: int = 30,
    scene_days: int = 60,
    min_clear: float = 0.85,
    max_nodata: float = 0.03,
    keep: int = 3,
    now: datetime | None = None,
    renderer: satrender.Renderer | None = None,
) -> SatResult:
    """Judge new passes, choose and draw each location's views, and write the index. A
    location that fails keeps the views it had."""
    now = now or datetime.now(UTC)
    out = SatResult()
    index_path = sat_dir / "index.json"
    checked_path = sat_dir / "checked.json"
    old = read_index(index_path)
    old_by_id = {loc.id: loc for loc in old.locations} if old else {}
    checked = _read_checked(checked_path)
    cutoff = (now - timedelta(days=scene_days + CHECKED_EXTRA_DAYS)).timestamp()
    draw = renderer or satrender.Renderer(sat_dir, client)
    spots: list[SatLocation] = []
    keep_keys: set[str] = set()
    used_crops: dict[str, set[str]] = {}

    for loc in locations:
        mid = loc.band("mid")
        lat, lon = mid.lat, mid.lon
        key = _spot_key(loc.id, lat, lon)
        keep_keys.add(key)
        seen = checked.setdefault(key, {})
        box = area_box(lat, lon)
        spot = SatLocation(
            id=loc.id, name=loc.name, lat=lat, lon=lon, box=box_lonlat(box), checked_at=now
        )
        try:
            passes = search(client, box, now - timedelta(days=scene_days), now)
            fresh = 0
            grids: list[tuple[Pass, np.ndarray]] = []
            for p in passes:
                gpath = _grid_path(sat_dir, key, p.id)
                grid = _load_grid(gpath) if p.id in seen else None
                if grid is None:
                    if fresh >= MAX_CHECKS:
                        continue
                    fresh += 1
                    out.checked += 1
                    grid = read_pass(client, p, box)
                    gpath.parent.mkdir(parents=True, exist_ok=True)
                    np.save(gpath, grid)
                    seen[p.id] = [p.time.timestamp()]
                grids.append((p, grid))
            grids = list(zip([p for p, _ in grids], dehaze([g for _, g in grids]), strict=True))
            # Whole scenes: cover the area, and see most of it.
            whole = []
            for p, g in grids:
                look = judge_grid(g)
                if look.nodata <= max_nodata and look.clear >= min_clear:
                    whole.append((p, g, look))
                if len(whole) >= keep:
                    break
            recent = [(p, g) for p, g in grids if p.time >= now - timedelta(days=days)]
            plan = stitch(
                recent,
                fallback=[(p, g) for p, g, _ in whole[:1]],
                latest=passes[0].time if passes else None,
            )
            crops = used_crops.setdefault(key_dir(key), set())
            for p, _, look in whole:
                spot.scenes.append(
                    SatScene(
                        id=p.id,
                        time=p.time,
                        platform=p.platform,
                        clear_pct=round(look.clear * 100),
                        snow_pct=round(look.snow * 100),
                        nodata_pct=round(look.nodata * 100),
                        view=draw.scene(key_dir(key), p, box),
                    )
                )
                crops.add(p.id)
            if plan.layers:
                view = draw.stitched(key_dir(key), plan.layers, plan.owner, box)
                spot.composite = composite_out(plan, view, box)
                crops.update(p.id for p in plan.layers)
        except (httpx.HTTPError, ValueError, OSError) as e:
            msg = f"{loc.id}: {type(e).__name__}: {e}"
            out.errors.append(msg)
            log.warning("satellite views for %s failed: %s", loc.id, e)
            prev = old_by_id.get(loc.id)
            spot.scenes = list(prev.scenes) if prev else []
            spot.composite = prev.composite if prev else None
            spot.box = prev.box if prev else spot.box
            spot.checked_at = prev.checked_at if prev else None
            spot.error = "Couldn't look for new imagery; showing the last found."
            crops = used_crops.setdefault(key_dir(key), set())
            crops.update(sc.id for sc in spot.scenes)
            if spot.composite:
                crops.update(x.id for x in spot.composite.layers)
        spots.append(spot)
        out.scenes += len(spot.scenes)

    # Forget passes older than the scene window could return, and moved locations.
    checked = {
        k: {pid: v for pid, v in by.items() if v and v[-1] >= cutoff}
        for k, by in checked.items()
        if k in keep_keys
    }
    _prune_grids(sat_dir, checked)
    views = {sc.view for s in spots for sc in s.scenes}
    views |= {s.composite.view for s in spots if s.composite}
    draw.prune(views, used_crops)
    lat0 = sum(s.lat for s in spots) / len(spots) if spots else 45.0
    lon0 = sum(s.lon for s in spots) / len(spots) if spots else -118.0
    viirs = viirs_day(client, lat0, lon0, now.date())
    if viirs is None:
        out.errors.append("VIIRS: no day with imagery in the last four")
        viirs = old.viirs_date if old else None

    index = SatOut(
        generated_at=now,
        viirs_date=viirs,
        days=days,
        scene_days=scene_days,
        min_clear_pct=round(min_clear * 100),
        zooms=[satrender.ZOOMS[0], satrender.ZOOMS[-1]],
        locations=spots,
    )
    _write(index_path, index.model_dump_json())
    _write(checked_path, json.dumps(checked, separators=(",", ":")))
    out.locations = len(spots)
    out.fetched = draw.fetched
    return out


def key_dir(key: str) -> str:
    """Where a location's pass pictures are kept: its key without the grid version (the
    pictures depend only on the area), as a directory name."""
    return re.sub(r"[^A-Za-z0-9_.,@-]", "_", key.split("#")[0])


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
