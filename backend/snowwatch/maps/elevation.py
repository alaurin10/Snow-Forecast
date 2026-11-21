"""The ground's height on the map's grid: the mean elevation under each pixel, from
Mapterhorn's elevation tiles (the same ones the map's 3D terrain and the terrain-adjusted
snow tiles use, tiles_render.py).

The Temperature layer (layers.py) brings each model's temperature from the model's own
ground down or up to this one. Each pixel is ~1.5–2 km across, so it holds the mean of the
ground under it (peaks and valleys averaged): the right height for the pixel's mean
temperature. The finer detail, zoomed in, is the map's own drape (frontend).

Worked out once per box and kept on disk (the ground doesn't change): `DEM_DRAWING` is in
the file's name, so a change to how it's built builds it again.
"""

from __future__ import annotations

import hashlib
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from snowwatch.maps.files import save_npy_file
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import WORLD, Region
from snowwatch.maps.tiles_render import DEM_URL, TILE, terrarium

log = logging.getLogger("snowwatch.precip")

DEM_DRAWING = 1
MAX_ZOOM = 7  # ~0.9 km a pixel here: finer would only cost downloads
# Below this share of tiles answering (404s count: open sea), the source is taken to be
# failing rather than the box to be mostly sea.
MIN_ANSWERED = 0.9


def zoom_for(region: Region) -> int:
    """The coarsest zoom whose tile pixels are at most half the region's (so each region
    pixel averages a few of them)."""
    px = (region.x1 - region.x0) / region.width
    z = math.ceil(math.log2(2 * WORLD / (TILE * px / 2)))
    return max(0, min(MAX_ZOOM, z))


def _path(cache_dir: Path, region: Region) -> Path:
    h = hashlib.sha1(f"{region.key}|{DEM_DRAWING}".encode()).hexdigest()[:16]
    return cache_dir / f"elev-{h}.npy"


def region_elevation(net: Net, region: Region, cache_dir: Path) -> np.ndarray | None:
    """Metres above sea level for each pixel of the region (0 over the sea), or None if
    the elevation tiles can't be had just now."""
    path = _path(cache_dir, region)
    try:
        have = np.load(path)
        if have.shape == (region.height, region.width):
            out: np.ndarray = have.astype(np.float32)
            return out
    except (OSError, ValueError):
        pass
    elev = build(net, region)
    if elev is not None:
        save_npy_file(path, elev.astype(np.float32))
    return elev


def build(net: Net, region: Region, z: int | None = None) -> np.ndarray | None:
    """Fetch the tiles over the region and average them onto its pixels."""
    z = zoom_for(region) if z is None else z
    world_px = TILE * 2**z

    def px(x: float) -> float:
        return float((x + WORLD) / (2 * WORLD) * world_px)

    def py(y: float) -> float:
        return float((WORLD - y) / (2 * WORLD) * world_px)

    gx0, gx1 = px(region.x0), px(region.x1)
    gy0, gy1 = py(region.y1), py(region.y0)
    tx0, tx1 = int(gx0 // TILE), int((gx1 - 1e-6) // TILE)
    ty0, ty1 = int(gy0 // TILE), int((gy1 - 1e-6) // TILE)
    coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    mosaic = np.zeros(((ty1 - ty0 + 1) * TILE, (tx1 - tx0 + 1) * TILE), np.float32)

    def one(c: tuple[int, int]) -> tuple[tuple[int, int], np.ndarray | None, bool]:
        x, y = c
        data, missing = net.found(DEM_URL.format(z=z, x=x % 2**z, y=y))
        if data is None:
            return c, None, missing
        elev = terrarium(data)
        if elev is None or elev.shape != (TILE, TILE):
            return c, None, False
        return c, elev, True

    answered = 0
    with ThreadPoolExecutor(6) as pool:
        for (x, y), elev, ok in pool.map(one, coords):
            answered += ok
            if elev is not None:
                r, c = (y - ty0) * TILE, (x - tx0) * TILE
                # Below sea level is open water or a few dry basins: as sea level.
                mosaic[r : r + TILE, c : c + TILE] = np.maximum(elev, 0)
    if answered < MIN_ANSWERED * len(coords):
        log.warning("elevation tiles: %d of %d answered", answered, len(coords))
        return None

    # Each region pixel: the mean of the tile pixels whose centres fall inside it (at least
    # the one it lies in).
    def spans(start: float, stop: float, n: int, offset: int, size: int) -> tuple[Any, Any]:
        edges = start + np.arange(n + 1) * (stop - start) / n - offset
        lo = np.clip(np.rint(edges[:-1]).astype(int), 0, size - 1)
        hi = np.clip(np.rint(edges[1:]).astype(int), 0, size)
        return lo, np.maximum(hi, lo + 1)

    c0, c1 = spans(gx0, gx1, region.width, tx0 * TILE, mosaic.shape[1])
    r0, r1 = spans(gy0, gy1, region.height, ty0 * TILE, mosaic.shape[0])
    total = np.zeros((mosaic.shape[0] + 1, mosaic.shape[1] + 1), np.float64)
    total[1:, 1:] = mosaic.cumsum(0, dtype=np.float64).cumsum(1)
    r0, r1 = r0[:, None], r1[:, None]
    c0, c1 = c0[None, :], c1[None, :]
    s = total[r1, c1] - total[r0, c1] - total[r1, c0] + total[r0, c0]
    n = np.maximum((r1 - r0) * (c1 - c0), 1)
    out: np.ndarray = (s / n).astype(np.float32)
    return out
