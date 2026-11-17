"""Precipitation frames as numbers, for the map to colour on the graphics chip
(docs/RADAR-PLAN.md, M1).

A frame is a few byte planes:

  rate   one byte a pixel: 0 dry, 1..127 log-spaced from RATE_MIN to RATE_MAX mm of water
         an hour (6% a step; finer costs bytes and shows no difference once interpolated).
         The map interpolates the codes (between pixels and between frames) and only then
         colours, so an echo's edge runs smoothly through the light rates.
  snow   the share of the precipitation that is snow, 0..255, at a quarter of the region's
  mix    resolution; likewise the share that is mixed or freezing. Rain is the rest.
  filled (radar and nowcast frames only, when there is any) the share of the water that
         the forecast filled in where no radar sees (coverage.py), 0..255, at the type
         planes' resolution: the map draws it lighter and hatched, or leaves it out.

The type planes are *filled across dry ground* from the nearest precipitation: at an
echo's edge the map interpolates between a wet pixel and a dry one, and a dry pixel that
said "no type" (or "rain", by default) would bleed a wrong type into the edge. That was
the earlier attempt's "snow over Seattle".

Planes are stored at the resolution their source has: radar full, hourly models half,
3- and 6-hourly models a quarter (`ds`: how many region pixels a rate pixel spans).

The file is one gzip stream (so it is served as `application/gzip` and no proxy tries to
compress it again; the browser inflates it with DecompressionStream) of a 16-byte header
and the planes, each row stored as differences from the row above (smooth fields compress
to a fraction that way).

    b"SWF1"  u16 rate width  u16 rate height  u16 type width  u16 type height
    u8 ds    u8 type planes (2, or 3 with `filled`)    2 bytes spare     (little-endian)

Nothing here goes through an image decoder: bytes in, bytes out.
"""

from __future__ import annotations

import gzip
import math
import struct
import zlib
from dataclasses import dataclass

import numpy as np

from snowwatch.maps.palette import MIX_T, NONE, SNOW_T

MAGIC = b"SWF1"
EXT = "bin"
MEDIA_TYPE = "application/gzip"
# mm of water an hour at code 1: half the lightest rate drawn (palette.FINE_FROM), so an
# edge has something to interpolate through, and above the ~0.04 GeoMet's nowcast reads
# over most of its domain.
RATE_MIN = 0.05
RATE_MAX = 100.0  # at code 1 + RATE_STEPS
RATE_STEPS = 126
_SPAN = math.log(RATE_MAX / RATE_MIN)
TYPE_DS = 4  # region pixels per type pixel
HEADER = struct.Struct("<4sHHHHBBH")


def rate_codes(amount: np.ndarray) -> np.ndarray:
    """mm of water an hour to codes (0 dry or no data, 1..127 from RATE_MIN up)."""
    a = np.nan_to_num(amount, nan=0.0).astype(np.float32)
    out = np.zeros(a.shape, np.uint8)
    wet = a >= RATE_MIN
    code = 1 + np.rint(RATE_STEPS * np.log(a[wet] / RATE_MIN) / _SPAN)
    out[wet] = np.clip(code, 1, 1 + RATE_STEPS).astype(np.uint8)
    return out


def code_rates(codes: np.ndarray) -> np.ndarray:
    """Codes back to mm of water an hour (0 for dry). Also takes fractional codes."""
    c = codes.astype(np.float32)
    out: np.ndarray = np.where(c >= 1, RATE_MIN * np.exp((c - 1) / RATE_STEPS * _SPAN), 0.0)
    return out.astype(np.float32)


def _blocks(a: np.ndarray, f: int) -> np.ndarray:
    """`a` in f×f blocks: shape (rows, cols, f*f), the last row and column repeated to
    fill the final block."""
    if f == 1:
        return a[..., None]
    h, w = a.shape
    ph, pw = -h % f, -w % f
    if ph or pw:
        a = np.pad(a, ((0, ph), (0, pw)), mode="edge")
    hh, ww = a.shape[0] // f, a.shape[1] // f
    return a.reshape(hh, f, ww, f).swapaxes(1, 2).reshape(hh, ww, f * f)


def downsample(amount: np.ndarray, f: int) -> np.ndarray:
    """The mean over f×f blocks (no data counts as dry)."""
    a: np.ndarray = np.nan_to_num(amount, nan=0.0).astype(np.float32)
    if f == 1:
        return a
    out: np.ndarray = _blocks(a, f).mean(-1)
    return out


def fill_holes(values: np.ndarray, have: np.ndarray) -> np.ndarray:
    """Every cell without a value takes one from the nearest cells that have (push-pull:
    halve the grid until every cell has a value, then fill each finer level's holes from
    the coarser one). With no values at all, zeros."""
    v = np.where(have, values, 0.0).astype(np.float32)
    w = have.astype(np.float32)
    if not have.any():
        return np.zeros(values.shape, np.float32)
    levels: list[tuple[np.ndarray, np.ndarray]] = [(v, w)]
    while (levels[-1][1] == 0).any() and min(levels[-1][0].shape) > 1:
        pv, pw = levels[-1]
        bw = _blocks(pw, 2).sum(-1)
        bv = _blocks(pv * pw, 2).sum(-1)
        nv = np.zeros(bw.shape, np.float32)
        np.divide(bv, bw, out=nv, where=bw > 0)
        levels.append((nv, (bw > 0).astype(np.float32)))
    if (levels[-1][1] == 0).any():  # a 1-wide strip still holding a hole
        lv, lw = levels[-1]
        levels[-1] = (np.where(lw > 0, lv, float(lv[lw > 0].mean())), np.ones_like(lw))
    for i in range(len(levels) - 2, -1, -1):
        fv, fw = levels[i]
        cv = levels[i + 1][0]
        up = np.repeat(np.repeat(cv, 2, 0), 2, 1)[: fv.shape[0], : fv.shape[1]]
        levels[i] = (np.where(fw > 0, fv, up), np.ones_like(fw))
    filled: np.ndarray = levels[0][0]
    return filled


def _smooth3(a: np.ndarray) -> np.ndarray:
    """A 3×3 mean (edges held), to take the steps off a filled field."""
    p = np.pad(a, 1, mode="edge")
    out = np.zeros(a.shape, np.float32)
    for dr in range(3):
        for dc in range(3):
            out += p[dr : dr + a.shape[0], dc : dc + a.shape[1]]
    return out / 9


def type_shares(kind: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Type codes on the region's grid to the snow share and the mix share (0..255) at a
    quarter of its resolution, filled across untyped ground."""
    typed = _blocks((kind != NONE).astype(np.float32), TYPE_DS).sum(-1)
    have = typed > 0
    out = []
    for code in (SNOW_T, MIX_T):
        n = _blocks((kind == code).astype(np.float32), TYPE_DS).sum(-1)
        share = np.zeros(n.shape, np.float32)
        np.divide(n, typed, out=share, where=have)
        filled = _smooth3(fill_holes(share, have))
        out.append(np.clip(np.rint(filled * 255), 0, 255).astype(np.uint8))
    return out[0], out[1]


def kinds_from_shares(snow: np.ndarray, mix: np.ndarray) -> np.ndarray:
    """The type each pixel shows: the largest of snow, mix and rain (the rest)."""
    from snowwatch.maps.palette import RAIN_T

    s, m = snow.astype(np.float32), mix.astype(np.float32)
    r = 255 - s - m
    out = np.full(s.shape, RAIN_T, np.uint8)
    out[(m >= r) & (m > s)] = MIX_T
    out[(s >= r) & (s >= m)] = SNOW_T
    return out


def _filter(plane: np.ndarray) -> bytes:
    """Each row as the difference from the row above (mod 256)."""
    out = plane.copy()
    out[1:] -= plane[:-1]
    return out.tobytes()


def _unfilter(data: bytes, h: int, w: int) -> np.ndarray:
    rows = np.frombuffer(data, np.uint8).reshape(h, w)
    out: np.ndarray = np.cumsum(rows, axis=0, dtype=np.uint64).astype(np.uint8)
    return out


@dataclass
class DataFrame:
    """A frame's planes as stored."""

    rate: np.ndarray  # codes, (h, w)
    snow: np.ndarray  # share 0..255, (th, tw)
    mix: np.ndarray
    ds: int  # region pixels per rate pixel
    filled: np.ndarray | None = None  # share 0..255 at the type planes' size, if any

    def rates(self) -> np.ndarray:
        return code_rates(self.rate)


def filled_plane(filled: np.ndarray) -> np.ndarray:
    """The share filled in (0..1 on the region's grid) at the type planes' resolution,
    0..255."""
    share = _blocks(np.nan_to_num(filled, nan=0.0).astype(np.float32), TYPE_DS).mean(-1)
    out: np.ndarray = np.clip(np.rint(share * 255), 0, 255).astype(np.uint8)
    return out


def encode(
    amount: np.ndarray, kind: np.ndarray, ds: int = 1, filled: np.ndarray | None = None
) -> bytes:
    """A frame's file from rates (mm of water an hour) and type codes on the region's
    grid, the rate kept at 1/ds of that grid; with `filled` (0..1, the share of the
    water the forecast filled in) as a third plane if any of it is."""
    rate = rate_codes(downsample(amount, ds))
    snow, mix = type_shares(kind)
    planes = [snow, mix]
    if filled is not None:
        f = filled_plane(filled)
        if f.any():
            planes.append(f)
    th, tw = snow.shape
    head = HEADER.pack(MAGIC, rate.shape[1], rate.shape[0], tw, th, ds, len(planes), 0)
    body = head + _filter(rate) + b"".join(_filter(p) for p in planes)
    # mtime 0: the same frame is the same bytes, so its name (a hash) doesn't change.
    return gzip.compress(body, 9, mtime=0)


def decode(data: bytes) -> DataFrame | None:
    """A frame's planes from its file; None if it isn't one."""
    try:
        raw = gzip.decompress(data)
    except (OSError, EOFError, zlib.error):
        return None
    if len(raw) < HEADER.size:
        return None
    magic, w, h, tw, th, ds, planes, _ = HEADER.unpack_from(raw)
    if magic != MAGIC or planes not in (2, 3) or not ds:
        return None
    raw = raw[HEADER.size :]
    n, tn = w * h, tw * th
    if len(raw) != n + planes * tn:
        return None
    return DataFrame(
        _unfilter(raw[:n], h, w),
        _unfilter(raw[n : n + tn], th, tw),
        _unfilter(raw[n + tn : n + 2 * tn], th, tw),
        ds,
        _unfilter(raw[n + 2 * tn :], th, tw) if planes == 3 else None,
    )


def _axis(n_out: int, n_in: int, span: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each of n_out cells along an axis that n_in cells cover `span` of: the two
    source cells either side of its centre and the weight of the second."""
    pos = (np.arange(n_out) + 0.5) * n_in / span - 0.5
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, n_in - 1)
    i1 = np.minimum(i0 + 1, n_in - 1)
    f = np.clip(pos - i0, 0, 1).astype(np.float32)
    return i0, i1, f


def _resize(a: np.ndarray, height: int, width: int, span: tuple[float, float]) -> np.ndarray:
    """`a` sampled bilinearly onto a (height, width) grid of which it covers `span`
    (rows, columns) pixels, cell centres lining up. Rows first, then columns, so only a
    few arrays of the output's size exist at once."""
    h, w = a.shape
    r0, r1, fr = _axis(height, h, span[0])
    a = a.astype(np.float32)
    tall = a[r0] * (1 - fr)[:, None]
    tall += a[r1] * fr[:, None]
    c0, c1, fc = _axis(width, w, span[1])
    out: np.ndarray = tall[:, c0] * (1 - fc)[None, :]
    out += tall[:, c1] * fc[None, :]
    return out


def mixed(a: DataFrame, b: DataFrame, f: float) -> DataFrame:
    """Two frames kept at the same resolution mixed (rates as mm an hour, then coded
    again), f of the way from a to b: at their own size, before anything is enlarged."""
    if f <= 0 or a is b:
        return a
    ra = code_rates(a.rate)
    rate = rate_codes(ra + (code_rates(b.rate) - ra) * f)
    snow = np.rint(a.snow + (b.snow.astype(np.float32) - a.snow) * f).astype(np.uint8)
    mix = np.rint(a.mix + (b.mix.astype(np.float32) - a.mix) * f).astype(np.uint8)
    return DataFrame(rate, snow, mix, a.ds)


def on_grid(frame: DataFrame, height: int, width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A frame back on the region's grid: rates (mm of water an hour), and the snow and
    mix shares (0..1), each interpolated as the map does."""
    rh, rw = frame.rate.shape
    codes = _resize(frame.rate, height, width, (rh * frame.ds, rw * frame.ds))
    th, tw = frame.snow.shape
    span = (th * TYPE_DS, tw * TYPE_DS)
    snow = _resize(frame.snow, height, width, span) / 255
    mix = _resize(frame.mix, height, width, span) / 255
    return code_rates(codes), snow, mix
