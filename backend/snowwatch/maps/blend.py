"""Meshing weather sources as numbers, so the map has no visible joins.

Every source is first put on the region's grid as numbers: an amount (an hourly rate in mm
of water, or a depth) and, for the timeline, a type code. Each has a weight per pixel:
1 well inside its domain, falling smoothly to 0 over about 100 km at its edge
(`feather`), times any preference for where it should be used (`north_weight`: Canada's
models in Canada, NOAA's in the US).

Sources are then laid down in order of preference (`mosaic`). The first takes its weight;
each later one takes its weight of whatever is left. So well inside the preferred source
there is no averaging with a second model (which would smear two slightly different
storms into one weaker one); the cross-fade happens only in the last ~100 km before the
preferred source ends. Amounts are the weighted mean, and the type comes from the source
with the largest weight that has a type there. Colours are applied once, afterwards.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from snowwatch.maps.palette import MIX_T, NONE, RAIN_T, SNOW_T
from snowwatch.maps.region import Region, spread

FEATHER_KM = 100.0
# Degrees north across which Canada's models hand over to NOAA's (the border is 49°N
# from the Pacific to beyond the box's east edge).
BORDER = (48.5, 49.5)
WET_MM = 0.1  # the lightest hourly amount the ramps draw
# A source types any amount down to this (mm over its period), well under what is drawn,
# so a pixel that is only wet once sources are blended still finds a type.
TRACE_MM = 0.01
# Share of the water falling as snow above which a pixel is snow, or at least mixed; and
# the share falling as freezing rain or ice pellets above which it is mixed.
SNOW_FRAC = 0.6
MIX_FRAC = 0.2
ICE_FRAC = 0.3
FILL_PX = 8  # a wet pixel without a type takes one from this many pixels away (~12 km)


def feather_px(region: Region, km: float = FEATHER_KM) -> int:
    """About `km` on the ground in pixels, at the box's middle latitude."""
    (south, _), (north, _) = region.bounds
    metres = (region.x1 - region.x0) / region.width * math.cos(math.radians((south + north) / 2))
    return max(1, round(km * 1000 / metres))


def feather(valid: np.ndarray, radius: int) -> np.ndarray:
    """Weights for a source's domain: 0 outside and at its edge, rising smoothly to 1
    `radius` pixels inside.

    The share of valid pixels in a square window around each pixel is ½ on a straight
    edge and 1 once the window is wholly inside, so 2·share − 1 is a ramp across the
    window's half-width. Beyond the box the domain is taken to carry on as it is at the
    box's edge (the box's own edge is not a domain edge)."""
    if valid.all():
        return np.ones(valid.shape, np.float32)
    if not valid.any():
        return np.zeros(valid.shape, np.float32)
    r = int(radius)
    n = 2 * r + 1
    padded = np.pad(valid, r, mode="edge").astype(np.int32)
    total = np.pad(padded.cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32), ((1, 0), (1, 0)))
    inside = total[n:, n:] - total[:-n, n:] - total[n:, :-n] + total[:-n, :-n]
    w = np.clip(2 * inside.astype(np.float32) / (n * n) - 1, 0, 1)
    w = w * w * (3 - 2 * w)  # ease in and out, so the fade has no corner at either end
    w[~valid] = 0
    out: np.ndarray = w.astype(np.float32)
    return out


def north_weight(region: Region) -> np.ndarray:
    """Preference for Canada's models by row: 0 south of the border zone, 1 north of it."""
    _, lats = region.lonlats()
    lo, hi = BORDER
    w: np.ndarray = np.clip((lats - lo) / (hi - lo), 0, 1).astype(np.float32)
    return w[:, None]


@dataclass
class Layer:
    """One source on the region's grid."""

    name: str
    amount: np.ndarray  # NaN where the source has no data
    weight: np.ndarray | float = 1.0
    kind: np.ndarray | None = None  # type codes, for the timeline


@dataclass
class Mosaic:
    amount: np.ndarray  # NaN where no source has data
    kind: np.ndarray
    # Each source's share of the picture (mean weight), for crediting what was used.
    shares: dict[str, float] = field(default_factory=dict)


def mosaic(layers: Sequence[Layer]) -> Mosaic:
    """Lay sources down in order of preference; each takes its weight of what is left."""
    if not layers:
        raise ValueError("nothing to blend")
    shape = layers[0].amount.shape
    left = np.ones(shape, np.float32)
    num = np.zeros(shape, np.float32)
    den = np.zeros(shape, np.float32)
    kind = np.zeros(shape, np.uint8)
    best = np.zeros(shape, np.float32)
    shares: dict[str, float] = {}
    for layer in layers:
        have = np.isfinite(layer.amount)
        w = (left * layer.weight).astype(np.float32)
        w[~have] = 0
        num += w * np.nan_to_num(layer.amount, nan=0.0)
        den += w
        if layer.kind is not None:
            take = (w > best) & (layer.kind != NONE)
            kind[take] = layer.kind[take]
            best[take] = w[take]
        left -= w
        np.clip(left, 0, 1, out=left)
        shares[layer.name] = shares.get(layer.name, 0.0) + float(w.mean())
    amount = np.full(shape, np.nan, np.float32)
    np.divide(num, den, out=amount, where=den > 1e-4)
    return Mosaic(amount, kind, shares)


def kinds_from_parts(
    total: np.ndarray, snow: np.ndarray, ice: np.ndarray | float, wet: float = TRACE_MM
) -> np.ndarray:
    """Type codes from how the water is split: `snow` as water, `ice` (freezing rain and
    ice pellets), the rest rain. Below `wet` in all, no type."""
    water = np.nan_to_num(total, nan=0.0)
    safe = np.maximum(water, 1e-6)
    snow_share = np.nan_to_num(snow, nan=0.0) / safe
    ice_share = np.nan_to_num(ice, nan=0.0) / safe
    out = np.full(water.shape, RAIN_T, np.uint8)
    out[(snow_share >= MIX_FRAC) | (ice_share >= ICE_FRAC)] = MIX_T
    out[(snow_share >= SNOW_FRAC) & (ice_share < ICE_FRAC)] = SNOW_T
    out[water < wet] = NONE
    return out


def fill_kinds(kinds: np.ndarray, wet: np.ndarray) -> np.ndarray:
    """A type for every wet pixel: its own, the nearest within a few pixels, else rain."""
    out = kinds if (kinds[wet] != NONE).all() else spread(kinds, FILL_PX)
    out = out.copy()
    out[wet & (out == NONE)] = RAIN_T
    out[~wet] = NONE
    return out
