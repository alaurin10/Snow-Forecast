"""Snow totals as numbers, for the map to colour on the graphics chip (docs/RADAR-PLAN.md,
"Snow total like the radar").

The Snow total layer used to be a picture of the whole box zoomed out and, zoomed in,
tiles the server painted on request from the snow by elevation and the terrain
(tiles_render.py): slow to arrive, especially in 3D, and again for every window. Now the
map gets the numbers once, as the radar does, and does the terrain adjustment itself
with the elevation tiles it already has.

A *step* is the snow from the totals' start to one moment: every 6 hours for two days,
then every 12 hours to five days and every 24 hours to ten (STEP_WINDOWS). The slider
runs through them, the map blending between the two either side, so it moves smoothly
from 12 hours to 10 days.

A step's file is one gzip stream (served as `application/gzip`, inflated in the
browser) of a 16-byte header and byte planes, each row stored as the difference from the
row above (as dataframe.py):

    b"SWT1"  u16 area width  u16 area height  u16 band width  u16 band height
    u8 bands  u8 band step / 50 m  2 bytes spare         (little-endian)

  area   the plain total (cm, the models' own snow per cell) at half the region's
         resolution: what the map shows zoomed out.
  bands  the snow at each elevation from 0 m every BAND_M (bins.py's grid, every other
         band and halved again: about 6 km a cell), one plane per band, lowest first:
         zoomed in, each pixel takes the snow at its own elevation. Absent (0 bands)
         where the snow by elevation couldn't be worked out.

Each byte is a code: 0 none, 1..255 log-spaced from CM_MIN to CM_MAX cm (3.4% a step).

The Temperature layer's frames use the same container (layers.py, `encode_temp`), with
codes linear in °C (TEMP_MIN, every TEMP_STEP) and two bands: the temperature at sea level
and at TEMP_TOP_M, so the map gets it at any elevation by the same reading of the bands
(the layer assumes a straight line with height). Its area plane is the temperature at the
mean ground under each area pixel.

The Snow level layer's frames (layers.py, `encode_level`) do the same with the height
above the snow level (m, codes linear from LEVEL_MIN every LEVEL_STEP): an exact straight
line with height, so each pixel gets its own elevation minus the snow level there, and the
map colours that as rain, mix or snow (palette.SNOWLINE).
"""

from __future__ import annotations

import gzip
import math
import struct
import zlib
from dataclasses import dataclass

import numpy as np

from snowwatch.maps import bins

MAGIC = b"SWT1"
EXT = "bin"
HEADER = struct.Struct("<4sHHHHBBH")
CM_MIN = 0.2
CM_MAX = 1000.0
CODES = 254  # codes 1..255
_SPAN = math.log(CM_MAX / CM_MIN)
BAND_EVERY = 2  # every other of bins.py's bands
BAND_M = int(bins.BIN_M * BAND_EVERY)  # 500 m
AREA_DS = 2  # region pixels per area pixel
BAND_DS = 2  # band-grid cells per band pixel (bins.FACTOR region pixels per cell)

# The steps the slider runs through: every 6 h to two days, every 12 h to five, every
# 24 h to ten. They include every window the totals have (totals.WINDOWS).
STEP_WINDOWS = (
    *range(6, 49, 6),
    *range(60, 121, 12),
    *range(144, 241, 24),
)


# Temperature codes: 1..255 for TEMP_MIN, TEMP_MIN + TEMP_STEP … (−70 to 57 °C), 0 none.
TEMP_MIN = -70.0
TEMP_STEP = 0.5
TEMP_TOP_M = 4500  # the upper band (the box's highest ground is 4,421 m)


def temp_codes(c: np.ndarray) -> np.ndarray:
    """°C to codes (0 for no data), clamped to the codes' range."""
    a = np.asarray(c, np.float32)
    out = np.zeros(a.shape, np.uint8)
    have = np.isfinite(a)
    code = 1 + np.rint((a[have] - TEMP_MIN) / TEMP_STEP)
    out[have] = np.clip(code, 1, 1 + CODES).astype(np.uint8)
    return out


def code_temp(codes: np.ndarray) -> np.ndarray:
    """Codes back to °C (NaN for none); takes fractional codes too."""
    c = np.asarray(codes, np.float32)
    out: np.ndarray = np.where(c >= 1, TEMP_MIN + (c - 1) * TEMP_STEP, np.nan)
    return out.astype(np.float32)


def encode_temp(here: np.ndarray, sea: np.ndarray, lapse_c_per_m: float) -> bytes:
    """A temperature frame's file: the temperature at the ground (°C on the region's grid)
    as the area plane, and the temperature at sea level and at TEMP_TOP_M (along the
    layer's cooling with height) as two bands on the band grid."""
    area = temp_codes(_halve(here))
    sea4 = _halve(_halve(sea))
    planes = [area, temp_codes(sea4), temp_codes(sea4 - lapse_c_per_m * TEMP_TOP_M)]
    ah, aw = area.shape
    bh, bw = sea4.shape
    head = HEADER.pack(MAGIC, aw, ah, bw, bh, 2, TEMP_TOP_M // 50, 0)
    body = head + b"".join(_filter(p) for p in planes)
    return gzip.compress(body, 9, mtime=0)


# Height above the snow level: codes 1..255 for LEVEL_MIN, LEVEL_MIN + LEVEL_STEP … (−8,225
# to 4,475 m), 0 none. Offset by half a step so the mix band's edges (±150 m) fall between
# two codes: the map colours each code whole, and the edges stay where they belong.
LEVEL_MIN = -8225.0
LEVEL_STEP = 50.0


def _linear_codes(a: np.ndarray, lo: float, step: float) -> np.ndarray:
    a = np.asarray(a, np.float32)
    out = np.zeros(a.shape, np.uint8)
    have = np.isfinite(a)
    out[have] = np.clip(1 + np.rint((a[have] - lo) / step), 1, 1 + CODES).astype(np.uint8)
    return out


def level_codes(m: np.ndarray) -> np.ndarray:
    """Metres above the snow level to codes (0 for no data), clamped to the codes' range."""
    return _linear_codes(m, LEVEL_MIN, LEVEL_STEP)


def code_level(codes: np.ndarray) -> np.ndarray:
    """Codes back to metres above the snow level (NaN for none)."""
    c = np.asarray(codes, np.float32)
    out: np.ndarray = np.where(c >= 1, LEVEL_MIN + (c - 1) * LEVEL_STEP, np.nan)
    return out.astype(np.float32)


def encode_level(above: np.ndarray, level: np.ndarray) -> bytes:
    """A snow level frame's file: the ground's height above the snow level (m, on the
    region's grid) as the area plane, and the height above it of sea level and of
    TEMP_TOP_M as two bands, so any elevation reads off the straight line between them."""
    area = level_codes(_halve(above))
    level4 = _halve(_halve(level))
    planes = [area, level_codes(-level4), level_codes(TEMP_TOP_M - level4)]
    ah, aw = area.shape
    bh, bw = level4.shape
    head = HEADER.pack(MAGIC, aw, ah, bw, bh, 2, TEMP_TOP_M // 50, 0)
    body = head + b"".join(_filter(p) for p in planes)
    return gzip.compress(body, 9, mtime=0)


def cm_codes(cm: np.ndarray) -> np.ndarray:
    """cm to codes (0 for none, below CM_MIN, or no data)."""
    a = np.nan_to_num(np.asarray(cm, np.float32), nan=0.0)
    out = np.zeros(a.shape, np.uint8)
    have = a >= CM_MIN
    code = 1 + np.rint(CODES * np.log(np.minimum(a[have], CM_MAX) / CM_MIN) / _SPAN)
    out[have] = np.clip(code, 1, 1 + CODES).astype(np.uint8)
    return out


def code_cm(codes: np.ndarray) -> np.ndarray:
    """Codes back to cm (0 for none); takes fractional codes too."""
    c = np.asarray(codes, np.float32)
    out: np.ndarray = np.where(c >= 1, CM_MIN * np.exp((c - 1) / CODES * _SPAN), 0.0)
    return out.astype(np.float32)


def _halve(a: np.ndarray) -> np.ndarray:
    """2 × 2 block means ignoring NaN (bins.half)."""
    return bins.half(np.asarray(a, np.float32))


def _filter(plane: np.ndarray) -> bytes:
    out = plane.copy()
    out[1:] -= plane[:-1]
    return out.tobytes()


def _unfilter(data: bytes, h: int, w: int) -> np.ndarray:
    rows = np.frombuffer(data, np.uint8).reshape(h, w)
    out: np.ndarray = np.cumsum(rows, axis=0, dtype=np.uint64).astype(np.uint8)
    return out


def area_plane(cm: np.ndarray) -> np.ndarray:
    """The plain total (cm on the region's grid) as the area plane's codes."""
    return cm_codes(_halve(cm))


def encode(area: np.ndarray, grid: np.ndarray | None) -> bytes:
    """A step's file from its area plane (area_plane) and the snow by elevation on
    bins.py's grid ((rows, columns, bands), or None)."""
    planes = [area]
    bh = bw = 0
    if grid is not None:
        for k in range(0, grid.shape[-1], BAND_EVERY):
            band = cm_codes(_halve(np.asarray(grid[..., k], np.float32)))
            planes.append(band)
        bh, bw = planes[1].shape
    ah, aw = area.shape
    head = HEADER.pack(MAGIC, aw, ah, bw, bh, len(planes) - 1, BAND_M // 50, 0)
    body = head + b"".join(_filter(p) for p in planes)
    # mtime 0: the same step is the same bytes, so its name (a hash) doesn't change.
    return gzip.compress(body, 9, mtime=0)


@dataclass
class Step:
    area: np.ndarray  # codes, (ah, aw)
    bands: np.ndarray  # codes, (k, bh, bw); k may be 0
    band_m: int


def decode(data: bytes) -> Step | None:
    """A step's planes from its file; None if it isn't one."""
    try:
        raw = gzip.decompress(data)
    except (OSError, EOFError, zlib.error):
        return None
    if len(raw) < HEADER.size:
        return None
    magic, aw, ah, bw, bh, k, step50, _ = HEADER.unpack_from(raw)
    if magic != MAGIC or not aw or not ah:
        return None
    raw = raw[HEADER.size :]
    n, bn = aw * ah, bw * bh
    if len(raw) != n + k * bn:
        return None
    area = _unfilter(raw[:n], ah, aw)
    bands = np.zeros((k, bh, bw), np.uint8)
    for i in range(k):
        bands[i] = _unfilter(raw[n + i * bn : n + (i + 1) * bn], bh, bw)
    return Step(area, bands, step50 * 50)
