"""Snow that fell in the last 24, 48 and 72 hours in the US: NOAA NOHRSC's National
Snowfall Analysis (version 2.1), updated at 00 and 12 UTC.

  www.nohrsc.noaa.gov/snowfall_v2/data/YYYYMM/sfav2_CONUS_{24h,48h,72h}_YYYYMMDDHH.tif

Each is a float32 GeoTIFF on a 0.04° lat/lon grid (1500 × 850, 126–66°W, 21–55°N),
-99999 for no data, the time in the name being the window's end. **The GeoTIFF is in
inches**, though the netCDF beside it says metres (checked 12 Nov 2026: the netCDF's
maximum was 0.151 m, the GeoTIFF's 5.944, which is 0.151 m in inches). Free, no key.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from snowwatch.maps.geomet import Grid, Net, read_grid

BASE = "https://www.nohrsc.noaa.gov/snowfall_v2/data"
WINDOWS = (24, 48, 72)
NAME = re.compile(r"sfav2_CONUS_(\d+)h_(\d{10})\.tif")
CM_PER_IN = 2.54


def latest(net: Net, now: int, windows: tuple[int, ...] = WINDOWS) -> dict[int, str]:
    """The newest file name for each window, from this month's listing and the last."""
    today = datetime.fromtimestamp(now, UTC)
    best: dict[int, tuple[str, str]] = {}  # window → (stamp, name)
    for d in (today, today.replace(day=1) - timedelta(days=1)):
        r = net.get(f"{BASE}/{d:%Y%m}/")
        if r is None:
            continue
        for m in NAME.finditer(r.text):
            h, stamp = int(m.group(1)), m.group(2)
            if h in windows and (h not in best or stamp > best[h][0]):
                best[h] = (stamp, m.group(0))
        if len(best) == len(windows):
            break
    return {h: name for h, (_, name) in best.items()}


def _stamp(name: str) -> str:
    m = NAME.fullmatch(name)
    if m is None:
        raise ValueError(f"not a snowfall analysis file: {name}")
    return m.group(2)


def end_ts(name: str) -> int:
    """A file's window end as Unix seconds."""
    return int(datetime.strptime(_stamp(name), "%Y%m%d%H").replace(tzinfo=UTC).timestamp())


def fetch(net: Net, name: str) -> Grid | None:
    """A window's snowfall grid in inches (-99999 for no data)."""
    r = net.get(f"{BASE}/{_stamp(name)[:6]}/{name}")
    return None if r is None else read_grid(r.content)
