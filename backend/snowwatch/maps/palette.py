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
    hex_rgb(c) for ramp in (SNOW, MIX, RAIN, TOTAL) for _, c in ramp
]

# Precipitation type codes, as the compositing uses them.
NONE, SNOW_T, MIX_T, RAIN_T = 0, 1, 2, 3

# Palette index → type code (TOTAL colours carry no type).
_KIND_OF_INDEX = np.zeros(256, np.uint8)
_KIND_OF_INDEX[1 : 1 + len(SNOW)] = SNOW_T
_KIND_OF_INDEX[1 + len(SNOW) : 1 + len(SNOW) + len(MIX)] = MIX_T
_KIND_OF_INDEX[1 + len(SNOW) + len(MIX) : 1 + len(SNOW) + len(MIX) + len(RAIN)] = RAIN_T


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


def paint_total(cm: np.ndarray) -> np.ndarray:
    """Snow totals (cm) to RGBA on the TOTAL ramp; below the first step is clear."""
    out = np.zeros((*cm.shape, 4), np.uint8)
    lows = np.array([low for low, _ in TOTAL])
    idx = np.digitize(np.nan_to_num(cm, nan=-1.0), lows)  # 0 = below the first step
    for i, (_, color) in enumerate(TOTAL, start=1):
        out[idx == i] = (*hex_rgb(color), 255)
    return out


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
