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
    """A palette (or, for fine frames, grayscale) PNG we wrote back to its indices (None
    if it isn't one)."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("P", "L"):
            return None
        return np.asarray(im)
    except (OSError, ValueError):
        return None


# ---- Precipitation frames: the fine palette ----------------------------------------
#
# Radar, nowcast and forecast frames carry numbers, not colours: each pixel is an index
# meaning a type and a rate (each type's rates in many small log steps), written as a
# grayscale PNG (gray = index). The browser smooths those numbers and colours them at the
# screen's own resolution (frontend/src/lib/map/precipGl.ts), so storms have smooth,
# sharp outlines and continuous colour at any zoom, rather than a stretched picture's
# blurred pixels. The index describes the steps (`fine_spec`), so the browser needs no
# copy of them. Frames drawn this way say so (`palette: "fine"`); older ones are palette
# PNGs on PALETTE. FINE_PALETTE/FINE_ALPHA give the same colours here (tests, previews).

FINE = "fine"
FINE_FROM = 0.03  # mm of water an hour: the lightest drawn, faintly
FINE_SOLID = 0.15  # fully opaque from here
# Type code → (ramp, number of steps, top of the last step). Steps ~16% apart (mix ~30%,
# a short ramp of two colours): smooth to the eye once the map blends neighbouring
# pixels, and half the file of 7% steps.
FINE_RAMPS: list[tuple[int, list[tuple[float, str]], int, float]] = [
    (SNOW_T, SNOW, 36, 6.0),
    (MIX_T, MIX, 20, 6.0),
    (RAIN_T, RAIN, 72, 60.0),
]


def _to_oklab(c: RGB) -> np.ndarray:
    """sRGB to OKLab (Ottosson, 2020): mixing there keeps colours bright and clean, where
    mixing sRGB values passes through muddy shades (dark green to yellow via olive)."""
    lin = np.array([((v / 255 + 0.055) / 1.055) ** 2.4 if v > 10 else v / 255 / 12.92 for v in c])
    m1 = np.array(
        [
            [0.4122214708, 0.5363325363, 0.0514459929],
            [0.2119034982, 0.6806995451, 0.1073969566],
            [0.0883024619, 0.2817188376, 0.6299787005],
        ]
    )
    m2 = np.array(
        [
            [0.2104542553, 0.7936177850, -0.0040720468],
            [1.9779984951, -2.4285922050, 0.4505937099],
            [0.0259040371, 0.7827717662, -0.8086757660],
        ]
    )
    out: np.ndarray = m2 @ np.cbrt(m1 @ lin)
    return out


def _from_oklab(lab: np.ndarray) -> RGB:
    m2 = np.array(
        [
            [1.0, 0.3963377774, 0.2158037573],
            [1.0, -0.1055613458, -0.0638541728],
            [1.0, -0.0894841775, -1.2914855480],
        ]
    )
    m1 = np.array(
        [
            [4.0767416621, -3.3077115913, 0.2309699292],
            [-1.2684380046, 2.6097574011, -0.3413193965],
            [-0.0041960863, -0.7034186147, 1.7076147010],
        ]
    )
    lin = np.clip(m1 @ (m2 @ lab) ** 3, 0, 1)
    srgb = [1.055 * v ** (1 / 2.4) - 0.055 if v > 0.0031308 else 12.92 * v for v in lin]
    return round(srgb[0] * 255), round(srgb[1] * 255), round(srgb[2] * 255)


def _ramp_rgb(ramp: list[tuple[float, str]], value: float) -> RGB:
    """A ramp's colour at `value`, running smoothly (in log value, mixed in OKLab) from stop
    to stop; the first stop's colour below it, the last's above it."""
    lows = [low for low, _ in ramp]
    cols = [hex_rgb(c) for _, c in ramp]
    if value <= lows[0]:
        return cols[0]
    if value >= lows[-1]:
        return cols[-1]
    for i in range(len(lows) - 1):
        if lows[i] <= value < lows[i + 1]:
            f = (np.log(value) - np.log(lows[i])) / (np.log(lows[i + 1]) - np.log(lows[i]))
            a, b = _to_oklab(cols[i]), _to_oklab(cols[i + 1])
            return _from_oklab(a + (b - a) * f)
    return cols[-1]


def _fine_tables() -> tuple[list[RGB], bytes, np.ndarray, np.ndarray, dict[int, tuple[int, int]]]:
    rgb: list[RGB] = [(0, 0, 0)]
    alpha = [0]
    kind = np.zeros(256, np.uint8)
    value = np.full(256, np.nan, np.float32)
    offsets: dict[int, tuple[int, int]] = {}
    for code, ramp, n, top in FINE_RAMPS:
        offsets[code] = (len(rgb), n)
        edges = np.geomspace(FINE_FROM, top, n + 1)
        for i in range(n):
            v = float(np.sqrt(edges[i] * edges[i + 1]))
            kind[len(rgb)] = code
            value[len(rgb)] = v
            rgb.append(_ramp_rgb(ramp, v))
            a = np.clip(np.log(v / FINE_FROM) / np.log(FINE_SOLID / FINE_FROM), 0, 1)
            alpha.append(round(255 * (0.25 + 0.75 * a)))
    rgb += [(0, 0, 0)] * (256 - len(rgb))
    alpha += [0] * (256 - len(alpha))
    return rgb, bytes(alpha), kind, value, offsets


FINE_PALETTE, FINE_ALPHA, FINE_KIND, FINE_VALUE, _FINE_AT = _fine_tables()


def fine_index(amount: np.ndarray, kind: np.ndarray) -> np.ndarray:
    """Rates (mm of water an hour) and type codes to the fine palette's indices; below
    FINE_FROM, NaN, or without a type, clear (0)."""
    out = np.zeros(amount.shape, np.uint8)
    a = np.nan_to_num(amount, nan=0.0)
    for code, _, n, top in FINE_RAMPS:
        sel = (kind == code) & (a >= FINE_FROM)
        if not sel.any():
            continue
        start, _ = _FINE_AT[code]
        step = np.floor(np.log(a[sel] / FINE_FROM) / np.log(top / FINE_FROM) * n)
        out[sel] = (np.clip(step, 0, n - 1) + start).astype(np.uint8)
    return out


def fine_values(indexed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A fine-palette frame back to rates (0 where clear) and type codes."""
    return np.nan_to_num(FINE_VALUE[indexed], nan=0.0), FINE_KIND[indexed]


def encode_fine(indexed: np.ndarray) -> bytes:
    """Fine-palette indices as a grayscale PNG (gray = index), for the browser to colour."""
    buf = io.BytesIO()
    Image.fromarray(indexed, "L").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def preview_fine(indexed: np.ndarray) -> np.ndarray:
    """Fine-palette indices as RGBA, coloured as the steps are (for tests and previews;
    the map colours them in the browser, smoothly)."""
    pal = np.array([(*c, a) for c, a in zip(FINE_PALETTE, FINE_ALPHA, strict=True)], np.uint8)
    out: np.ndarray = pal[indexed]
    return out


def fine_spec() -> dict[str, object]:
    """The fine steps as the index describes them to the browser: each type's first
    index, number of steps and top rate, the lightest rate drawn and where it's solid."""
    names = {SNOW_T: "snow", MIX_T: "mix", RAIN_T: "rain"}
    return {
        "from": FINE_FROM,
        "solid": FINE_SOLID,
        "ramps": [
            {"type": names[code], "start": _FINE_AT[code][0], "steps": n, "top": top}
            for code, _, n, top in FINE_RAMPS
        ],
    }


def rate_band(code: int, value: float) -> tuple[int, float, float] | None:
    """A typed rate to its step on the type's ramp: (type, lower bound, upper bound, NaN
    for the top step), as RATE_BANDS gives for PALETTE frames. None below the ramp's first
    step (drawn faintly, but too light to call wet)."""
    ramp = {SNOW_T: SNOW, MIX_T: MIX, RAIN_T: RAIN}.get(code)
    if ramp is None or not value >= ramp[0][0]:
        return None
    for j, (low, _) in enumerate(ramp):
        high = ramp[j + 1][0] if j + 1 < len(ramp) else float("nan")
        if not value >= high:  # also true for the top step's NaN
            return code, float(low), high
    return None
