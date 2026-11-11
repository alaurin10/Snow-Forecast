"""US hourly forecast from NOAA's HRRR (3 km), read straight from NOAA's GRIB2 files on AWS.

HRRR runs every hour to 18 hours ahead, and the 00, 06, 12 and 18 UTC runs to 48 hours.
Each valid hour is drawn from the newest run that reaches it. For an hour we fetch five
small messages by byte range (about 0.3 MB in all):

  APCP   precipitation over the hour (mm of water)
  CSNOW, CRAIN, CFRZR, CICEP   the type at the end of the hour (yes/no each)

and hand the amount and a type code to the blend (blend.py). Freezing rain and ice pellets
count as mix, and so does snow and rain together. The type flags are for the end of the
hour while the amount covers all of it, so a wet pixel without a type takes the nearest
type within a few pixels, else rain. Messages are cached on disk: an hour is wanted again
whenever another model's run changes.

Bucket: noaa-hrrr-bdp-pds (NOAA Open Data Dissemination), free, no key.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from snowwatch.maps import grib
from snowwatch.maps.blend import TRACE_MM, fill_kinds
from snowwatch.maps.geomet import Net
from snowwatch.maps.palette import MIX_T, RAIN_T, SNOW_T
from snowwatch.maps.region import Region

log = logging.getLogger("snowwatch.precip")

BUCKET = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
HOUR = 3600
HOURLY_BACK_H = 8  # hourly runs older than this are beaten by a newer one at every hour
LONG_BACK_H = 14  # how far back to look for a run that reaches 48 h


def file_url(run: int, fhour: int) -> str:
    d = datetime.fromtimestamp(run, UTC)
    return f"{BUCKET}/hrrr.{d:%Y%m%d}/conus/hrrr.t{d:%H}z.wrfsfcf{fhour:02d}.grib2"


def published(net: Net, run: int) -> list[int]:
    """The forecast hours of a run already on the bucket (each has its `.idx`)."""
    d = datetime.fromtimestamp(run, UTC)
    prefix = f"hrrr.{d:%Y%m%d}/conus/hrrr.t{d:%H}z.wrfsfcf"
    r = net.get(f"{BUCKET}/", {"list-type": "2", "prefix": prefix, "max-keys": "200"})
    if r is None:
        return []
    return sorted({int(h) for h in re.findall(r"wrfsfcf(\d\d)\.grib2\.idx</Key>", r.text)})


def slots(net: Net, now: int) -> dict[int, tuple[int, int]]:
    """Valid time → (run, forecast hour), from the newest run that reaches each hour."""
    top = now - now % HOUR
    runs = [top - h * HOUR for h in range(HOURLY_BACK_H + 1)]
    runs += [r for r in (top - h * HOUR for h in range(LONG_BACK_H + 1)) if r % (6 * HOUR) == 0]
    runs = sorted(set(runs), reverse=True)
    with ThreadPoolExecutor(4) as pool:
        found = dict(zip(runs, pool.map(lambda r: published(net, r), runs), strict=True))
    out: dict[int, tuple[int, int]] = {}
    for run in runs:  # newest first: the first run to reach an hour keeps it
        for f in found[run]:
            if f >= 1:
                out.setdefault(run + f * HOUR, (run, f))
    return out


def patterns(fhour: int) -> list[str]:
    """APCP over the hour (not since the run began), then the four type flags."""
    return [
        rf":APCP:surface:{fhour - 1}-{fhour} hour acc fcst:",
        r":CSNOW:surface:",
        r":CRAIN:surface:",
        r":CFRZR:surface:",
        r":CICEP:surface:",
    ]


def kinds(csnow: np.ndarray, crain: np.ndarray, cfrzr: np.ndarray, cicep: np.ndarray) -> np.ndarray:
    """HRRR's four yes/no type flags to our type codes."""
    out = np.zeros(csnow.shape, np.uint8)
    snow, rain = csnow > 0.5, crain > 0.5
    out[rain] = RAIN_T
    out[snow] = SNOW_T
    out[(snow & rain) | (cfrzr > 0.5) | (cicep > 0.5)] = MIX_T
    return out


def fields(
    net: Net,
    run: int,
    fhour: int,
    region: Region,
    grids_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """The hour's precipitation (mm, NaN off HRRR's grid) and type codes on the region."""
    raw = grib.fetch_messages(net, file_url(run, fhour), patterns(fhour), cache_dir)
    grids = [grib.on_region(m, region, grids_dir) for m in raw]
    apcp = grids[0]
    if apcp is None:
        return None
    flags = [g if g is not None else np.zeros_like(apcp) for g in grids[1:]]
    wet = np.nan_to_num(apcp) >= TRACE_MM
    return apcp, fill_kinds(kinds(*flags), wet)
