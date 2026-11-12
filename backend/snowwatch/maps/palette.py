"""Our colours for the map's pictures, palette PNGs, and simple compositing.

Keep the ramps in step with frontend/src/lib/radar.ts.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import numpy as np
from PIL import Image

RGB = tuple[int, int, int]

# Lower bound in mm of water per hour (≈ cm of snow per hour for snow), colour.
SNOW = [(0.1, "#c6dbef"), (0.5, "#8fbfe6"), (1, "#4a90d9"), (2, "#2c5fb8"), (3, "#6a3fb0")]
MIX = [(0.1, "#f4a6c6"), (1, "#e0457b")]
RAIN = [
    (0.1, "#a6dba0"),
    (0.5, "#5aae61"),
    (1, "#1b7837"),
    (2.5, "#f4d03f"),
    (5, "#ee8a2a"),
    (10, "#d7301f"),
]
# Snowfall totals: lower bound in cm of snow (the model's water equivalent at 10:1).
# Steps sit on whole inches (1, 3, 6, 9, 12, 18, 24, 36, 48) so both units read cleanly.
TOTAL = [
    (2.54, "#cfe8f8"),
    (7.62, "#8cc8ef"),
    (15.24, "#4a98e0"),
    (22.86, "#2b5cc2"),
    (30.48, "#6a3fb0"),
    (45.72, "#a535a3"),
    (60.96, "#e0457b"),
    (91.44, "#f08a24"),
    (121.92, "#f4d03f"),
]
# Snow level: lower bound in metres above sea level, a band every 250 m. "0" also holds
# snow reaching the ground everywhere (GeoMet's codes -1 and -2, NBM's 0).
SNOWLEVEL: list[tuple[float, str]] = [
    (0, "#5b2a86"),
    (250, "#6b44b5"),
    (500, "#4e5fc9"),
    (750, "#3b7dd8"),
    (1000, "#2f9be0"),
    (1250, "#33b4d6"),
    (1500, "#3fc6b8"),
    (1750, "#5ed19a"),
    (2000, "#8fd97a"),
    (2250, "#bfe06a"),
    (2500, "#e6e35c"),
    (2750, "#f6cf4f"),
    (3000, "#f7ad45"),
    (3250, "#f28a3b"),
    (3500, "#e5653a"),
    (3750, "#cf4339"),
    (4000, "#a82f3a"),
]
# Wind (gusts at 10 m, or the free-air wind at ridge level): lower bound in km/h.
WIND: list[tuple[float, str]] = [
    (20, "#d9f0d3"),
    (30, "#acdca5"),
    (40, "#f7e08a"),
    (50, "#f6b94f"),
    (60, "#ef8a3c"),
    (80, "#d9472f"),
    (100, "#a3243f"),
    (120, "#6b1f5c"),
]
# Snow on the ground: lower bound in cm, on whole inches (1, 4, 8, 12, 24, 36, 48, 72, 96,
# 120 in).
DEPTH: list[tuple[float, str]] = [
    (2.54, "#e8f4f2"),
    (10.16, "#c3e6e1"),
    (20.32, "#94d3cc"),
    (30.48, "#5fbcb4"),
    (60.96, "#2f9f9a"),
    (91.44, "#1b7f86"),
    (121.92, "#155f78"),
    (182.88, "#1d3f6b"),
    (243.84, "#2c2160"),
    (304.8, "#4b0f55"),
]


def hex_rgb(h: str) -> RGB:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ramp_color(ramp: list[tuple[float, str]], value: float) -> RGB | None:
    out = None
    for low, color in ramp:
        if value >= low:
            out = hex_rgb(color)
    return out


# Every colour a frame can hold: index 0 is transparent.
PALETTE: list[RGB] = [(0, 0, 0)] + [
    hex_rgb(c) for ramp in (SNOW, MIX, RAIN, TOTAL, SNOWLEVEL, WIND, DEPTH) for _, c in ramp
]

# Precipitation type codes, as the compositing uses them.
NONE, SNOW_T, MIX_T, RAIN_T = 0, 1, 2, 3

# Palette index → type code (TOTAL colours carry no type).
_KIND_OF_INDEX = np.zeros(256, np.uint8)
_KIND_OF_INDEX[1 : 1 + len(SNOW)] = SNOW_T
_KIND_OF_INDEX[1 + len(SNOW) : 1 + len(SNOW) + len(MIX)] = MIX_T
_KIND_OF_INDEX[1 + len(SNOW) + len(MIX) : 1 + len(SNOW) + len(MIX) + len(RAIN)] = RAIN_T


# Palette index → (type code, lower bound, upper bound) of a timeline colour, in mm of water
# an hour; the top step of a ramp has no upper bound (NaN).
RATE_BANDS: dict[int, tuple[int, float, float]] = {}
_i = 1
for _code, _ramp in ((SNOW_T, SNOW), (MIX_T, MIX), (RAIN_T, RAIN)):
    for _j, (_low, _) in enumerate(_ramp):
        _high = _ramp[_j + 1][0] if _j + 1 < len(_ramp) else float("nan")
        RATE_BANDS[_i] = (_code, float(_low), float(_high))
        _i += 1


def kinds_of(indexed: np.ndarray) -> np.ndarray:
    """A palette frame's indices to type codes (snow, mix, rain or none)."""
    out: np.ndarray = _KIND_OF_INDEX[indexed]
    return out


def rgb_mask(img: np.ndarray, color: RGB) -> np.ndarray:
    """Solid pixels of exactly this colour."""
    m: np.ndarray = ((img[..., 3] > 0) & (img[..., 0] == color[0]) & (img[..., 1] == color[1])) & (
        img[..., 2] == color[2]
    )
    return m


def repaint(
    img: np.ndarray, fn: Callable[[int, int, int], RGB | None], min_alpha: int = 24
) -> np.ndarray:
    """Map each distinct colour through `fn`; drop faint and unmapped pixels."""
    out = np.zeros_like(img)
    solid = img[..., 3] >= min_alpha
    if not solid.any():
        return out
    packed = (
        (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2]
    )
    keys, inverse = np.unique(packed[solid], return_inverse=True)
    lut = np.zeros((len(keys), 4), np.uint8)
    for i, k in enumerate(keys.tolist()):
        c = fn((k >> 16) & 255, (k >> 8) & 255, k & 255)
        if c:
            lut[i] = (*c, 255)
    out[solid] = lut[inverse]
    return out


def _paint_ramp(
    out: np.ndarray, values: np.ndarray, where: np.ndarray, ramp: list[tuple[float, str]]
) -> None:
    lows = np.array([low for low, _ in ramp])
    idx = np.digitize(np.nan_to_num(values, nan=-1.0), lows)  # 0 = below the first step
    for i, (_, color) in enumerate(ramp, start=1):
        out[where & (idx == i)] = (*hex_rgb(color), 255)


def paint_typed(rate: np.ndarray, kinds: np.ndarray) -> np.ndarray:
    """Hourly rates (mm of water an hour) and type codes to RGBA on the SNOW, MIX and RAIN
    ramps. Below a ramp's first step, or without a type, is clear."""
    out = np.zeros((*rate.shape, 4), np.uint8)
    for code, ramp in ((SNOW_T, SNOW), (MIX_T, MIX), (RAIN_T, RAIN)):
        _paint_ramp(out, rate, kinds == code, ramp)
    return out


def paint_ramp(values: np.ndarray, ramp: list[tuple[float, str]]) -> np.ndarray:
    """Values to RGBA on a ramp; below its first step, or NaN, is clear."""
    out = np.zeros((*values.shape, 4), np.uint8)
    lows = np.array([low for low, _ in ramp])
    idx = np.digitize(np.nan_to_num(values, nan=-1e9), lows)  # 0 = below the first step
    for i, (_, color) in enumerate(ramp, start=1):
        out[idx == i] = (*hex_rgb(color), 255)
    return out


def _ramp_offset(ramp: list[tuple[float, str]]) -> int:
    """Where a ramp's first colour sits in PALETTE (0 is transparent)."""
    at = 1
    for r in (SNOW, MIX, RAIN, TOTAL, SNOWLEVEL, WIND, DEPTH):
        if r is ramp:
            return at
        at += len(r)
    raise ValueError("not one of the palette's ramps")


def index_ramp(values: np.ndarray, ramp: list[tuple[float, str]]) -> np.ndarray:
    """Values straight to palette indices on one of the palette's ramps (0: below its first
    step, or NaN). The same picture as `snap(paint_ramp(values, ramp))`, without matching
    every pixel's colour."""
    lows = np.array([low for low, _ in ramp])
    step = np.digitize(np.nan_to_num(values, nan=-1e9), lows)  # 0 = below the first step
    out: np.ndarray = np.where(step > 0, step + _ramp_offset(ramp) - 1, 0).astype(np.uint8)
    return out


def paint_total(cm: np.ndarray) -> np.ndarray:
    """Snow totals (cm) to RGBA on the TOTAL ramp; below the first step is clear."""
    return paint_ramp(cm, TOTAL)


def over(top: np.ndarray | None, bottom: np.ndarray) -> np.ndarray:
    """Opaque-or-clear layering: top's solid pixels replace bottom's."""
    if top is None:
        return bottom
    out = bottom.copy()
    solid = top[..., 3] > 0
    out[solid] = top[solid]
    return out


def snap(img: np.ndarray, region: object = None) -> np.ndarray:
    """Each pixel to the nearest palette colour (index 0 = clear)."""
    out = np.zeros(img.shape[:2], np.uint8)
    solid = img[..., 3] > 0
    if not solid.any():
        return out
    pal = np.array(PALETTE[1:], np.int32)
    px = img[solid][:, :3].astype(np.int32)
    keys, inverse = np.unique(px, axis=0, return_inverse=True)
    d = ((keys[:, None, :] - pal[None, :, :]) ** 2).sum(-1)
    out[solid] = (d.argmin(1) + 1).astype(np.uint8)[inverse.reshape(-1)]
    return out


def encode(indexed: np.ndarray) -> bytes:
    """A small palette PNG with index 0 transparent."""
    im = Image.fromarray(indexed, "P")
    im.putpalette([v for c in PALETTE for v in c])
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True, transparency=0)
    return buf.getvalue()


def decode_indices(data: bytes) -> np.ndarray | None:
    """A palette PNG we wrote back to its indices (None if it isn't one)."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.mode != "P":
            return None
        return np.asarray(im)
    except (OSError, ValueError):
        return None
