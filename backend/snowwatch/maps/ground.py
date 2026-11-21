"""The ground's height under the map's box, at about a weather model's resolution.

NBM gives its clouds' bases and tops in metres above *its* ground: a 2.5 km grid whose
peaks are lower and valleys higher than the real ones. To put a cloud at a height above
sea level that the map can hold against the real terrain, add the ground as the model
sees it: here, Mapterhorn's elevation (the tiles the map's 3D terrain uses) at zoom 5
(~1.5 km a pixel over the box), averaged over about a model cell.

The terrain doesn't change, so the grid is built once per box and kept on disk.
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from snowwatch.maps.files import save_npy
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import WORLD, Region
from snowwatch.maps.tiles_render import DEM_URL, terrarium

log = logging.getLogger("snowwatch.precip")

ZOOM = 5
TILE = 512  # Mapterhorn's tiles
CELL_KM = 2.5  # averaged over about NBM's cell


def path_for(cache_dir: Path, region: Region) -> Path:
    key = hashlib.sha1(f"ground|{ZOOM}|{CELL_KM}|{region.key}".encode()).hexdigest()[:16]
    return cache_dir / f"ground-{key}.npy"


def ground(net: Net, region: Region, cache_dir: Path | None = None) -> np.ndarray | None:
    """Metres above sea level for every pixel of the region (0 over the sea), or None if
    the elevation tiles couldn't all be had (it's tried again next time)."""
    path = path_for(cache_dir, region) if cache_dir is not None else None
    if path is not None and path.exists():
        try:
            have: np.ndarray = np.load(path)
            if have.shape == (region.height, region.width):
                return have
        except (OSError, ValueError):
            pass
    out = _build(net, region)
    if out is not None and path is not None:
        save_npy(path, out)
    return out


def _tile(net: Net, z: int, x: int, y: int) -> np.ndarray | None:
    """One tile's elevation; zeros where Mapterhorn has none (open sea answers 404)."""
    url = DEM_URL.format(z=z, x=x, y=y)
    try:
        r = net.client.get(url, timeout=20)
    except Exception as e:  # httpx errors, or a stand-in client's
        log.debug("elevation tile %s: %s", url, e)
        return None
    if r.status_code == 404:
        return np.zeros((TILE, TILE), np.float32)
    if r.status_code != 200:
        return None
    elev = terrarium(r.content)
    if elev is None or elev.shape != (TILE, TILE):
        return None
    return elev


def _build(net: Net, region: Region) -> np.ndarray | None:
    world_px = TILE * 2**ZOOM

    def px(v: float) -> float:
        return float((v + WORLD) / (2 * WORLD) * world_px)

    gx0, gx1 = px(region.x0), px(region.x1)
    gy0, gy1 = world_px - px(region.y1), world_px - px(region.y0)
    tx0, tx1 = int(gx0 // TILE), int((gx1 - 1) // TILE)
    ty0, ty1 = int(gy0 // TILE), int((gy1 - 1) // TILE)
    coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(4) as pool:
        tiles = list(pool.map(lambda c: _tile(net, ZOOM, c[0], c[1]), coords))
    missing = sum(t is None for t in tiles)
    if missing:
        log.warning("ground: %d of %d elevation tiles missing", missing, len(tiles))
        return None
    mosaic = np.zeros(((ty1 - ty0 + 1) * TILE, (tx1 - tx0 + 1) * TILE), np.float32)
    for (x, y), t in zip(coords, tiles, strict=True):
        mosaic[(y - ty0) * TILE : (y - ty0 + 1) * TILE, (x - tx0) * TILE : (x - tx0 + 1) * TILE] = t
    # Average over about a model cell first, at the tiles' own resolution.
    lat_mid = float(np.mean([b[0] for b in region.bounds]))
    m_per_px = 2 * WORLD / world_px * np.cos(np.radians(lat_mid))
    mosaic = _box_mean(np.maximum(mosaic, 0.0), max(1, round(CELL_KM * 1000 / m_per_px)))
    cols = gx0 + (np.arange(region.width) + 0.5) * (gx1 - gx0) / region.width - tx0 * TILE
    rows = gy0 + (np.arange(region.height) + 0.5) * (gy1 - gy0) / region.height - ty0 * TILE
    c = np.clip(cols.astype(int), 0, mosaic.shape[1] - 1)
    r = np.clip(rows.astype(int), 0, mosaic.shape[0] - 1)
    out: np.ndarray = mosaic[r][:, c].astype(np.float32)
    return out


def _box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """The mean over a k × k box centred on each cell (edges repeated)."""
    if k <= 1:
        return a
    lo = k // 2
    p = np.pad(a, ((lo, k - 1 - lo), (lo, k - 1 - lo)), mode="edge").astype(np.float64)
    s = p.cumsum(0).cumsum(1)
    s = np.pad(s, ((1, 0), (1, 0)))
    h, w = a.shape
    total = s[k : k + h, k : k + w] - s[:h, k : k + w] - s[k : k + h, :w] + s[:h, :w]
    out: np.ndarray = (total / (k * k)).astype(np.float32)
    return out
