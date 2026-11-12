"""Snow on the ground in the US: NOAA NOHRSC's SNODAS analysis, daily at 06 UTC, 1 km.

NSIDC publishes each day as a tar of gzipped flat files (`G02158`, masked to the
conterminous US, ~5 MB):

  noaadata.apps.nsidc.org/NOAA/G02158/masked/YYYY/MM_Mon/SNODAS_YYYYMMDD.tar

Snow depth is product 1036 (`us_ssmv11036tS__T0001TTNATS<YYYYMMDD>05HP001.dat.gz`):
big-endian int16 in millimetres, -9999 for no data, on a 30 arc-second lat/lon grid
whose size and corners are in the matching `.txt.gz` header (6935 × 3351, 24.95–52.87°N,
124.73–66.94°W on 11 Nov 2026). Free, no key.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from datetime import UTC, datetime, timedelta

import numpy as np

from snowwatch.maps.geomet import Grid, Net

BASE = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked"
DEPTH = re.compile(r"us_ssmv11036tS__T0001TTNATS(\d{8})05HP001\.(txt|dat)\.gz$")


def month_url(d: datetime) -> str:
    return f"{BASE}/{d:%Y}/{d:%m_%b}/"


def latest(net: Net, now: int) -> str | None:
    """The newest day published (YYYYMMDD), looking at this month and the last."""
    today = datetime.fromtimestamp(now, UTC)
    for d in (today, today.replace(day=1) - timedelta(days=1)):
        r = net.get(month_url(d))
        if r is None:
            continue
        days = re.findall(r"SNODAS_(\d{8})\.tar", r.text)
        if days:
            return str(max(days))
    return None


def day_ts(day: str) -> int:
    """The analysis time of a day (06 UTC) as Unix seconds."""
    return int(datetime.strptime(day, "%Y%m%d").replace(hour=6, tzinfo=UTC).timestamp())


def fetch(net: Net, day: str) -> bytes | None:
    d = datetime.strptime(day, "%Y%m%d")
    r = net.get(f"{month_url(d)}SNODAS_{day}.tar")
    return None if r is None else r.content


def header(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def depth_grid(tar_bytes: bytes) -> Grid | None:
    """Snow depth (mm, int16; -9999 no data) from a day's tar, or None if it isn't there."""
    parts: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
            for m in tar.getmembers():
                hit = DEPTH.search(m.name)
                f = tar.extractfile(m) if hit else None
                if hit and f is not None:
                    parts[hit.group(2)] = gzip.decompress(f.read())
    except (tarfile.TarError, OSError, EOFError):
        return None
    if set(parts) != {"txt", "dat"}:
        return None
    h = header(parts["txt"].decode("latin-1"))
    try:
        cols, rows = int(h["Number of columns"]), int(h["Number of rows"])
        lon0 = float(h["Minimum x-axis coordinate"])
        lat0 = float(h["Maximum y-axis coordinate"])
        dlon, dlat = float(h["X-axis resolution"]), float(h["Y-axis resolution"])
    except (KeyError, ValueError):
        return None
    raw = parts["dat"]
    if len(raw) != rows * cols * 2:
        return None
    data = np.frombuffer(raw, ">i2").reshape(rows, cols)
    return Grid(data, lon0, lat0, dlon, dlat)
