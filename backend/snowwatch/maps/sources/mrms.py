"""NOAA's Multi-Radar/Multi-Sensor precipitation (MRMS), to check and type the radar over
the US (docs/RADAR-PLAN.md, M3).

MRMS is NOAA's own mosaic of the US radars with its quality control applied: ground
clutter, beam blockage, anomalous propagation and non-weather echoes are removed, and
each wet pixel says whether it is rain or snow. Environment Canada's composite (our main
radar, radar_eccc.py) carries the same US radars without that control: Mt. Rainier's
summit showed as heavy rain in it, and MRMS shows nothing there.

  noaa-mrms-pds.s3.amazonaws.com/CONUS/<product>/<YYYYMMDD>/
      MRMS_<product>_<YYYYMMDD>-<HHMMSS>.grib2.gz          every 2 minutes

  PrecipRate_00.00   mm/h; -3 where no radar sees (beyond range, the sea, Mexico)
  PrecipFlag_00.00   0 none, 1 warm stratiform rain, 3 snow, 6 convective rain, 7 rain
                     with hail, 10 cool stratiform rain, 91/96 tropical; -3 no coverage
  RadarQualityIndex_00.00
                     0..1, how well the radars see the air near the ground: low where the
                     beam is blocked by a ridge or passes high over a valley; -3 beyond
                     range (coverage.py reads it to find where radar is blind)

Both are 0.01° latitude/longitude grids over 20–55°N, 130–60°W (3500 × 7000), packed as
a PNG inside the GRIB2 message (template 5.41): value = (R + X·2^E) / 10^D. Decoded with
the GRIB library the grid is ~200 MB of float64; read straight from its PNG it is a 50 MB
16-bit image, sampled onto the region at once (~0.3 s). Free, no key.
"""

from __future__ import annotations

import gzip
import io
import logging
import struct
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from PIL import Image

from snowwatch.maps.geomet import Net
from snowwatch.maps.palette import NONE, RAIN_T, SNOW_T
from snowwatch.maps.region import Region

log = logging.getLogger("snowwatch.precip")

BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
RATE = "PrecipRate_00.00"
FLAG = "PrecipFlag_00.00"
QUALITY = "RadarQualityIndex_00.00"
NO_COVERAGE = -3.0
# The grid: cell centres from 54.995°N down and from 129.995°W east, 0.01° apart.
NORTH = 54.995
WEST = -129.995
STEP = 0.01
ROWS, COLS = 3500, 7000
EVERY_S = 120  # a scan every 2 minutes
SNOW_FLAGS = (3,)
RAIN_FLAGS = (1, 6, 7, 10, 91, 96)


def url(product: str, t: int) -> str:
    d = datetime.fromtimestamp(t, UTC)
    return f"{BUCKET}/CONUS/{product}/{d:%Y%m%d}/MRMS_{product}_{d:%Y%m%d}-{d:%H%M%S}.grib2.gz"


@dataclass
class Scan:
    """One MRMS scan on the region's grid."""

    t: int
    rate: np.ndarray  # mm/h, 0 where dry; NaN where no radar sees or outside MRMS
    kind: np.ndarray  # type codes (snow, rain) where wet, else NONE

    @property
    def covered(self) -> np.ndarray:
        out: np.ndarray = np.isfinite(self.rate)
        return out


def _cells(region: Region) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each of the region's rows and columns, MRMS's row and column (clipped), and
    which pixels fall inside MRMS's grid."""
    lons, lats = region.lonlats()
    rows = np.rint((NORTH - lats) / STEP).astype(np.int64)
    cols = np.rint((lons - WEST) / STEP).astype(np.int64)
    inside = ((rows >= 0) & (rows < ROWS))[:, None] & ((cols >= 0) & (cols < COLS))[None, :]
    return np.clip(rows, 0, ROWS - 1), np.clip(cols, 0, COLS - 1), inside


def _signed(v: int, bits: int) -> int:
    """GRIB2's sign-and-magnitude integers (the top bit is the sign)."""
    top = 1 << (bits - 1)
    return -(v & (top - 1)) if v & top else v


def _png_field(raw: bytes) -> tuple[np.ndarray, float, int, int] | None:
    """A PNG-packed message's packed values (rows × columns, as stored) and its reference
    value R, binary scale E and decimal scale D; None if it isn't packed that way."""
    off, template, ref, e, d, png = 16, -1, 0.0, 0, 0, b""
    while off + 5 <= len(raw) and raw[off : off + 4] != b"7777":
        n = int.from_bytes(raw[off : off + 4], "big")
        num = raw[off + 4]
        if n < 5:
            return None
        if num == 5:
            template = int.from_bytes(raw[off + 9 : off + 11], "big")
            ref = struct.unpack(">f", raw[off + 11 : off + 15])[0]
            e = _signed(int.from_bytes(raw[off + 15 : off + 17], "big"), 16)
            d = _signed(int.from_bytes(raw[off + 17 : off + 19], "big"), 16)
        elif num == 7:
            png = raw[off + 5 : off + n]
        off += n
    if template != 41 or not png:
        return None
    Image.MAX_IMAGE_PIXELS = max(Image.MAX_IMAGE_PIXELS or 0, ROWS * COLS + 1)
    with Image.open(io.BytesIO(png)) as im:
        packed = np.asarray(im)
    if packed.shape != (ROWS, COLS):
        return None
    return packed, ref, e, d


def _sample(raw: bytes, region: Region) -> np.ndarray | None:
    """A message's values at the region's pixels (nearest cell), NaN outside the grid."""
    rows, cols, inside = _cells(region)
    try:
        packed = _png_field(raw)
    except (OSError, ValueError, struct.error):
        packed = None
    if packed is not None:
        x, ref, e, d = packed
        picked = x[np.ix_(rows, cols)].astype(np.float32)
        del x
        out: np.ndarray = ((ref + picked * np.float32(2.0**e)) / np.float32(10.0**d)).astype(
            np.float32
        )
        out[~inside] = np.nan
        return out
    return _sample_grib(raw, rows, cols, inside)


def _sample_grib(
    raw: bytes, rows: np.ndarray, cols: np.ndarray, inside: np.ndarray
) -> np.ndarray | None:
    """As `_sample`, through the GRIB library (any packing; ~200 MB at its peak)."""
    import gribberish  # type: ignore[import-untyped]

    try:
        msg = gribberish.parse_grib_message(raw, 0)
        if tuple(msg.metadata.grid_shape) != (ROWS, COLS):
            log.warning("MRMS grid is %s, not %s", msg.metadata.grid_shape, (ROWS, COLS))
            return None
        values = np.asarray(msg.data()).reshape(ROWS, COLS)
    except Exception as e:  # gribberish raises its own error types
        log.warning("undecodable MRMS message: %s", e)
        return None
    # Straight to the region's pixels: picking rows first would copy a 100 MB slab.
    out: np.ndarray = values[np.ix_(rows, cols)].astype(np.float32)
    del values, msg
    out[~inside] = np.nan
    return out


def _get(net: Net, product: str, t: int) -> bytes | None:
    r = net.get(url(product, t), tries=1)
    if r is None:
        return None
    try:
        return gzip.decompress(r.content)
    except (OSError, EOFError, zlib.error):
        return None


def scan(net: Net, t: int, region: Region) -> Scan | None:
    """The MRMS scan at t (or the one 2 minutes before, if t's isn't out yet) on the
    region; None if MRMS has neither, or the region is outside it."""
    for when in (t, t - EVERY_S):
        raw = _get(net, RATE, when)
        if raw is None:
            continue
        rate = _sample(raw, region)
        del raw
        if rate is None:
            return None
        if not np.isfinite(rate).any():
            return None
        rate[rate <= NO_COVERAGE + 0.5] = np.nan
        rate[np.isfinite(rate) & (rate < 0)] = 0.0
        kind = np.zeros(rate.shape, np.uint8)
        flag_raw = _get(net, FLAG, when)
        flag = _sample(flag_raw, region) if flag_raw is not None else None
        del flag_raw
        if flag is not None:
            wet = rate > 0
            kind[wet & np.isin(flag, SNOW_FLAGS)] = SNOW_T
            kind[wet & np.isin(flag, RAIN_FLAGS)] = RAIN_T
        kind[~(rate > 0)] = NONE
        return Scan(when, rate, kind)
    return None


def quality(net: Net, t: int, region: Region) -> np.ndarray | None:
    """MRMS's radar quality index (0..1) on the region near time t: 0 beyond the radars'
    range, NaN outside MRMS's grid. None if MRMS has none of the last few scans' (it is
    sometimes a few minutes behind the rates)."""
    for back in range(4):
        raw = _get(net, QUALITY, t - (t % EVERY_S) - back * EVERY_S)
        if raw is None:
            continue
        q = _sample(raw, region)
        del raw
        if q is None or not np.isfinite(q).any():
            return None
        q[np.isfinite(q) & (q < 0)] = 0.0
        out: np.ndarray = np.minimum(q, 1.0)
        return out
    return None
