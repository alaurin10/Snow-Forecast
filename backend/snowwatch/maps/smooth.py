"""Softening a precipitation field before it is painted, so the picture has no pixel steps.

Sources reach the region's grid at their own resolution: radar at ~1 km on ~1.5 km
pixels, HRRR and NBM (copied from the nearest cell) in ~2 px blocks. A light blur of the
amounts, scaled to the source, smooths those steps; the types are blurred as shares (each
type's presence, blurred, the largest wins), so the line between snow and rain is smooth
too rather than following the blocks. Dry pixels stay part of the blur, so an echo's edge
fades out instead of stopping at a pixel boundary.

A Gaussian blur is approximated by three box blurs (cumulative sums: no SciPy).
"""

from __future__ import annotations

import math

import numpy as np

from snowwatch.maps.palette import MIX_T, NONE, RAIN_T, SNOW_T


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Mean over 2r+1 cells along one axis, edges held at their value."""
    if r <= 0:
        return a
    m = np.moveaxis(a, axis, 0)
    c = np.cumsum(np.pad(m, ((r + 1, r), (0, 0)), mode="edge"), axis=0, dtype=np.float64)
    n = 2 * r + 1
    out: np.ndarray = ((c[n:] - c[:-n]) / n).astype(np.float32)
    return np.moveaxis(out, 0, axis)


def _blur_all(a: np.ndarray, r: int) -> np.ndarray:
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box(_box(out, r, 0), r, 1)
    return out


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """About a Gaussian blur of `sigma` pixels (three box blurs each way). Only the box
    round the non-zero cells is worked on: a frame is mostly dry."""
    if sigma <= 0:
        return a.astype(np.float32)
    # Box width for three passes to match the Gaussian's variance (Wells, 1986).
    w = math.sqrt(12 * sigma * sigma / 3 + 1)
    r = max(1, round((w - 1) / 2))
    rows = np.flatnonzero(a.any(axis=1))
    if not rows.size:
        return np.zeros(a.shape, np.float32)
    cols = np.flatnonzero(a.any(axis=0))
    m = 3 * r + 1  # how far three passes reach
    r0, r1 = max(0, rows[0] - m), min(a.shape[0], rows[-1] + 1 + m)
    c0, c1 = max(0, cols[0] - m), min(a.shape[1], cols[-1] + 1 + m)
    out = np.zeros(a.shape, np.float32)
    out[r0:r1, c0:c1] = _blur_all(a[r0:r1, c0:c1], r)
    return out


def soften(
    amount: np.ndarray, kind: np.ndarray, sigma: float, kind_sigma: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Amounts blurred by `sigma` pixels (NaN, no data, stays NaN and doesn't pull its
    neighbours down), and each pixel's type the one most present within `kind_sigma`
    (default `sigma`): types may come from a coarser product than the amounts."""
    if sigma <= 0:
        return amount, kind
    ks = sigma if kind_sigma is None else kind_sigma
    have = np.isfinite(amount)
    w = 1 - blur((~have).astype(np.float32), sigma)
    total = blur(np.where(have, amount, 0.0), sigma)
    out = np.full(amount.shape, np.nan, np.float32)
    np.divide(total, w, out=out, where=w > 1e-3)
    out[~have] = np.nan
    best = np.zeros(amount.shape, np.float32)
    k = np.zeros(kind.shape, np.uint8)
    for code in (SNOW_T, MIX_T, RAIN_T):
        if not (kind == code).any():
            continue
        share = blur((kind == code).astype(np.float32), ks)
        take = share > best
        k[take] = code
        best[take] = share[take]
    k[best <= 0] = NONE
    return out, k
