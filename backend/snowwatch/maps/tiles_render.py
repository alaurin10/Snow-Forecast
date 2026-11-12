"""Terrain-adjusted snow totals as map tiles (docs/MAP-PLAN.md A4), drawn by the api.

`GET /api/snowtiles/{id}/{z}/{x}/{y}.png` (zoom 5–11, 512 px): for each pixel of the tile,
its elevation from the Mapterhorn tile with the same address (Terrarium-encoded WebP,
kept in the tile cache under data/tiles/dem/), and the snow at that elevation from the
window's grid by elevation (bins.py: bilinear between cells, linear between bands),
painted on the snow totals' colours. Drawn tiles are kept under
data/maps/snowtiles/<id>/ until the worker drops that grid. Nothing is fetched but the
elevation tiles.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from snowwatch.maps import bins
from snowwatch.maps.files import write_atomic
from snowwatch.maps.palette import PALETTE, TOTAL, index_ramp
from snowwatch.maps.region import WORLD
from snowwatch.tiles import TileCache

TILE = 512  # Mapterhorn's tiles are 512 px, so one elevation tile per snow tile
MIN_Z = 5
MAX_Z = 11  # beyond, the map stretches zoom 11 (about 25 m a pixel here)
DEM_URL = "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"
TILES_ID = re.compile(r"[0-9a-f]{16}")


class Unavailable(Exception):
    """The elevation tile couldn't be had just now (not "there is none")."""


def terrarium(data: bytes) -> np.ndarray | None:
    """Elevation (m) from a Terrarium-encoded image: R × 256 + G + B / 256 − 32768."""
    try:
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), np.float32)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    out: np.ndarray = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    return out


def elevation(cache: TileCache, z: int, x: int, y: int) -> np.ndarray:
    """The tile's elevation grid. Sea level where Mapterhorn has no tile (it answers 404
    over open sea); Unavailable when it can't be reached."""
    path = cache.root / "dem" / str(z) / str(x) / str(y)
    data, status = cache.through_status(path, DEM_URL.format(z=z, x=x, y=y))
    if data is None:
        if status == 404:
            return np.zeros((TILE, TILE), np.float32)
        raise Unavailable
    elev = terrarium(data)
    if elev is None:
        raise Unavailable
    if elev.shape != (TILE, TILE):
        im = Image.fromarray(elev, "F").resize((TILE, TILE), Image.Resampling.BILINEAR)
        elev = np.asarray(im, np.float32)
    return elev


def pixel_mercator(z: int, x: int, y: int, size: int = TILE) -> tuple[np.ndarray, np.ndarray]:
    """Web Mercator metres of each pixel centre's column (x) and row (y) in a tile."""
    n = 2**z
    step = 2 * WORLD / n / size
    mx = -WORLD + x * 2 * WORLD / n + (np.arange(size) + 0.5) * step
    my = WORLD - y * 2 * WORLD / n - (np.arange(size) + 0.5) * step
    return mx, my


def overlaps(grid: np.ndarray, meta: dict[str, Any], z: int, x: int, y: int) -> bool:
    """Whether the tile touches the box the grid covers."""
    mx, my = pixel_mercator(z, x, y, 2)
    rows, cols = bins.cell_coords(meta["bounds"], meta["width"], meta["height"], mx, my)
    h, w = grid.shape[:2]
    # Two samples a side, a quarter tile in: widen by a tile's half to cover its edges.
    dr, dc = abs(rows[1] - rows[0]), abs(cols[1] - cols[0])
    return bool(
        rows.min() - dr <= h - 0.5
        and rows.max() + dr >= -0.5
        and cols.min() - dc <= w - 0.5
        and cols.max() + dc >= -0.5
    )


def snow_cm(
    grid: np.ndarray, meta: dict[str, Any], z: int, x: int, y: int, elev: np.ndarray
) -> np.ndarray:
    """Snow (cm) for each pixel of a tile; NaN outside the box the grid covers."""
    size = elev.shape[0]
    mx, my = pixel_mercator(z, x, y, size)
    rows, cols = bins.cell_coords(meta["bounds"], meta["width"], meta["height"], mx, my)
    h, w = grid.shape[:2]
    inside_r = (rows >= -0.5) & (rows <= h - 0.5)
    inside_c = (cols >= -0.5) & (cols <= w - 0.5)
    out = np.full((size, size), np.nan, np.float32)
    if not inside_r.any() or not inside_c.any():
        return out
    R, C = np.meshgrid(rows[inside_r], cols[inside_c], indexing="ij")
    sub = elev[np.ix_(inside_r, inside_c)]
    out[np.ix_(inside_r, inside_c)] = bins.sample(grid, R, C, sub)
    return out


def encode(indices: np.ndarray) -> bytes:
    """A palette PNG with index 0 transparent (quick to write: tiles are drawn on demand)."""
    im = Image.fromarray(indices, "P")
    im.putpalette([v for c in PALETTE for v in c])
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=0, compress_level=6)
    return buf.getvalue()


def read_meta(totals_dir: Path, tiles_id: str) -> dict[str, Any] | None:
    try:
        meta = json.loads((totals_dir / f"bins-{tiles_id}.json").read_text())
        (_, _), (_, _) = meta["bounds"]
        int(meta["width"]), int(meta["height"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return meta if isinstance(meta, dict) else None


def tile(
    totals_dir: Path,
    tiles_dir: Path,
    cache: TileCache,
    tiles_id: str,
    z: int,
    x: int,
    y: int,
) -> bytes | None:
    """One drawn tile (PNG), from the cache of drawn tiles or drawn now. None if there is
    no such grid or tile; Unavailable if its elevation can't be had just now."""
    if not TILES_ID.fullmatch(tiles_id) or not (MIN_Z <= z <= MAX_Z):
        return None
    if not (0 <= x < 2**z and 0 <= y < 2**z):
        return None
    path = tiles_dir / tiles_id / str(z) / str(x) / f"{y}.png"
    try:
        return path.read_bytes()
    except OSError:
        pass
    grid = bins.load(totals_dir / f"bins-{tiles_id}.npy")
    meta = read_meta(totals_dir, tiles_id)
    if grid is None or meta is None:
        return None
    if overlaps(grid, meta, z, x, y):
        cm = snow_cm(grid, meta, z, x, y, elevation(cache, z, x, y))
        data = encode(index_ramp(cm, TOTAL))
    else:
        data = encode(np.zeros((TILE, TILE), np.uint8))
    write_atomic(path, data)
    return data
