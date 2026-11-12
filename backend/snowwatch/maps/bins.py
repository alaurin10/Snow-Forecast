"""Snow totals by elevation (docs/MAP-PLAN.md A4): the numbers behind the terrain-adjusted
snow map.

Model grids are 2.5–15 km and mountains aren't, so a model's snow total is a guess for
the whole cell. Instead of one total per pixel we keep one per elevation band, on a grid
of half the pictures' resolution (~3 km a cell over the West box), and let the terrain
pick: the tile renderer (tiles_render.py) and tap-for-numbers read each spot's
elevation and interpolate between the bands.

For each period (an hour to six) and each band's elevation z:

  snow cm += water mm × phase(z − snow level) × ratio(z) / 10

- `water` is the model's precipitation (all types) over the period.
- `phase` is the share falling as snow: 0 more than 150 m below the model's snow level,
  1 more than 150 m above it, a straight line between (the mix band the Snow level
  layer's drape shows).
- `ratio` is the model's own snow-to-liquid ratio (NBM's `SNOWLR` in the US; the
  forecast's temperature bands from the 2 m temperature in Canada, as the plain totals
  use). That ratio describes the air at the model's ground, which in a storm with rain in
  the valleys is warm, so on ground well above the snow level a ratio wetter than
  average is raised: unchanged up to where a typical cooling with height (6.5 °C a km,
  from +1 °C at the snow level) reaches the wettest band's lower bound, then raised
  gradually to the average band's ratio by where it reaches the next band's (with the
  default bands, ~240 m and ~670 m above the snow level). It is never lowered, and never
  raised above that average ratio.

The water is never taken as less than the model's own snow for the cell needs at the
model's ratio (NBM's separately blended snowfall can exceed its precipitation at its
ratio), so above the snow level a band never gets less snow than the model gives the
cell. Where a period has no snow level, every band gets the model's own snow for the cell
(no terrain adjustment there, rather than a guess).

Layout: (rows, columns, bands) float16, so one cell's bands sit together on disk and a
tile reads only the cells it needs (memory-mapped).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from snowwatch.config import SlrBand
from snowwatch.maps.files import save_npy_file
from snowwatch.maps.region import Region

BIN_M = 250  # elevation step between bands
TOP_M = 4500  # the highest band (Mt Whitney, the box's highest point, is 4,421 m)
ELEVS = np.arange(0, TOP_M + 1, BIN_M, dtype=np.float32)  # 19 bands: 0, 250 … 4,500 m
MIX_M = 150  # half the width of the rain/snow mix band around the snow level
FACTOR = 2  # band grid cells per picture pixel, each way
SNOW_LEVEL_C = 1.0  # a typical temperature at the snow level
LAPSE_C_PER_M = 0.0065  # a typical cooling with height
DEFAULT_RATIO = 10.0  # where the model gives none
MAX_RATIO = 30.0  # anything above is noise


def shape_for(region: Region) -> tuple[int, int]:
    """The band grid's rows and columns for a region."""
    return math.ceil(region.height / FACTOR), math.ceil(region.width / FACTOR)


def half(values: np.ndarray) -> np.ndarray:
    """A picture-sized array on the band grid: the mean of each 2 × 2 block, ignoring
    NaN (NaN only where the whole block is). An odd last row or column repeats."""
    h, w = values.shape
    H, W = math.ceil(h / FACTOR), math.ceil(w / FACTOR)
    a = np.pad(
        values.astype(np.float32), ((0, H * FACTOR - h), (0, W * FACTOR - w)), mode="edge"
    ).reshape(H, FACTOR, W, FACTOR)
    have = np.isfinite(a)
    n = have.sum(axis=(1, 3))
    total = np.where(have, a, 0).sum(axis=(1, 3))
    out = np.full((H, W), np.nan, np.float32)
    np.divide(total, n, out=out, where=n > 0)
    return out


def phase(height_above: np.ndarray) -> np.ndarray:
    """The share of precipitation falling as snow at a height above the snow level (m)."""
    out: np.ndarray = np.clip((height_above + MIX_M) / (2 * MIX_M), 0, 1)
    return out


class Lift:
    """Raising a wet model ratio on ground well above the snow level (see the module
    docstring). Built from the forecast's ratio bands (warmest first); with fewer than
    two bands that have a lower bound, nothing is raised."""

    def __init__(self, bands: Sequence[SlrBand]) -> None:
        bounded = [b for b in bands if b.min_c is not None]
        self.on = len(bounded) >= 2
        if self.on:
            first, second = bounded[0], bounded[1]
            assert first.min_c is not None and second.min_c is not None
            self.from_m = (SNOW_LEVEL_C - first.min_c) / LAPSE_C_PER_M
            self.to_m = (SNOW_LEVEL_C - second.min_c) / LAPSE_C_PER_M
            self.ratio = float(second.ratio)

    def __call__(self, ratio: np.ndarray, height_above: np.ndarray) -> np.ndarray:
        if not self.on:
            return ratio
        span = max(self.to_m - self.from_m, 1.0)
        w = np.clip((height_above - self.from_m) / span, 0, 1)
        out: np.ndarray = ratio + w * np.maximum(self.ratio - ratio, 0)
        return out


def model_ratio(ratio: np.ndarray | float | None, shape: tuple[int, int]) -> np.ndarray:
    """A model's ratio as an array, DEFAULT_RATIO where it gives none (NaN, zero or less:
    NBM's `SNOWLR` is 0 where nothing falls) and capped where it's implausible."""
    if ratio is None:
        return np.full(shape, DEFAULT_RATIO, np.float32)
    r = np.broadcast_to(np.asarray(ratio, np.float32), shape)
    out: np.ndarray = np.where(np.isfinite(r) & (r > 0), np.minimum(r, MAX_RATIO), DEFAULT_RATIO)
    return out.astype(np.float32)


def add_period(
    acc: np.ndarray,
    water: np.ndarray,
    snow_level: np.ndarray | None,
    ratio: np.ndarray,
    own_snow_cm: np.ndarray | None,
    lift: Lift,
    share: float = 1.0,
) -> None:
    """Add one period to a running (rows, columns, bands) total, all on the band grid.

    `water` mm of precipitation, `snow_level` m (NaN where unknown), `ratio` the model's
    (see model_ratio), `own_snow_cm` the model's own snow for the cell, used where the
    snow level is unknown. `share` scales the whole period (a block only partly inside)."""
    w = np.nan_to_num(water, nan=0.0).clip(0, None) * share
    own = None if own_snow_cm is None else np.nan_to_num(own_snow_cm, nan=0.0).clip(0) * share
    if own is not None:
        # Never less water than the model's own snow needs at its ratio: NBM blends its
        # snowfall and its precipitation separately, and beyond two days its snowfall is
        # often more than its precipitation at its ratio would make. Without this, ground
        # above the snow level could get less snow than the model gives the whole cell.
        w = np.maximum(w, own * 10 / ratio)
    known = np.zeros(w.shape, bool) if snow_level is None else np.isfinite(snow_level)
    sl = np.zeros(w.shape, np.float32) if snow_level is None else np.nan_to_num(snow_level)
    unknown = np.zeros(w.shape, np.float32) if own is None else own
    for k, z in enumerate(ELEVS):
        above = z - sl
        acc[..., k] += np.where(known, w * phase(above) * lift(ratio, above) / 10, unknown)


def join(
    north: np.ndarray | None, south: np.ndarray | None, us_weight: np.ndarray | float
) -> np.ndarray:
    """Canada's bands and the US's as one (float16): the US's where its weight is 1,
    Canada's where it is 0, a weighted mean between (`us_weight` on the band grid, 0
    where the US has no data). Like totals.join, band by band (so either side can be a
    memory-mapped file)."""
    if north is None and south is None:
        raise ValueError("nothing to join")
    if north is None:
        assert south is not None
        return south
    if south is None:
        return north
    w = np.asarray(us_weight, np.float32)
    out = np.empty(north.shape, np.float16)
    for k in range(north.shape[-1]):
        s = np.asarray(south[..., k], np.float32)
        n = np.asarray(north[..., k], np.float32)
        out[..., k] = w * s + (1 - w) * n
    return out


def save(path: Path, acc: np.ndarray) -> None:
    save_npy_file(path, acc if acc.dtype == np.float16 else acc.astype(np.float16))


def load(path: Path) -> np.ndarray | None:
    """A band grid, memory-mapped (only the cells read come off the disk)."""
    try:
        arr = np.load(path, mmap_mode="r")
    except (OSError, ValueError):
        return None
    if arr.ndim != 3 or arr.shape[2] != len(ELEVS):
        return None
    out: np.ndarray = arr
    return out


def sample(grid: np.ndarray, rows: np.ndarray, cols: np.ndarray, elev_m: np.ndarray) -> np.ndarray:
    """Snow (cm) at points: `rows` and `cols` in the band grid's cell units (cell centres
    at whole numbers), bilinear in space and linear between bands by `elev_m`. Points
    beyond the grid take its edge; NaN elevation reads as sea level."""
    h, w, k = grid.shape
    r = np.clip(rows, 0, h - 1)
    c = np.clip(cols, 0, w - 1)
    r0 = np.minimum(np.floor(r).astype(np.int64), max(h - 2, 0))
    c0 = np.minimum(np.floor(c).astype(np.int64), max(w - 2, 0))
    r1 = np.minimum(r0 + 1, h - 1)
    c1 = np.minimum(c0 + 1, w - 1)
    fr = (r - r0).astype(np.float32)
    fc = (c - c0).astype(np.float32)
    kf = np.clip(np.nan_to_num(elev_m, nan=0.0) / BIN_M, 0, k - 1)
    k0 = np.minimum(np.floor(kf).astype(np.int64), max(k - 2, 0))
    k1 = np.minimum(k0 + 1, k - 1)
    fk = (kf - k0).astype(np.float32)
    # Read only the block of cells the points touch.
    ra, rb = int(r0.min()), int(r1.max()) + 1
    ca, cb = int(c0.min()), int(c1.max()) + 1
    block = np.nan_to_num(np.asarray(grid[ra:rb, ca:cb, :], np.float32), nan=0.0)
    r0, r1, c0, c1 = r0 - ra, r1 - ra, c0 - ca, c1 - ca

    def at(rr: np.ndarray, cc: np.ndarray) -> np.ndarray:
        lo = block[rr, cc, k0]
        hi = block[rr, cc, k1]
        out: np.ndarray = lo + (hi - lo) * fk
        return out

    top = at(r0, c0) * (1 - fc) + at(r0, c1) * fc
    bottom = at(r1, c0) * (1 - fc) + at(r1, c1) * fc
    out: np.ndarray = top * (1 - fr) + bottom * fr
    return out


def cell_coords(
    region_bounds: Sequence[Sequence[float]],
    width: int,
    height: int,
    mx: np.ndarray,
    my: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Web Mercator metres → the band grid's (row, column) in cell units, for a picture of
    `width` × `height` over `region_bounds` ([[south, west], [north, east]])."""
    from snowwatch.maps.region import merc_x, merc_y

    (south, west), (north, east) = region_bounds
    x0, x1, y0, y1 = merc_x(west), merc_x(east), merc_y(south), merc_y(north)
    px = (mx - x0) / (x1 - x0) * width  # picture pixels from the left edge
    py = (y1 - my) / (y1 - y0) * height  # from the top
    return py / FACTOR - 0.5, px / FACTOR - 0.5
