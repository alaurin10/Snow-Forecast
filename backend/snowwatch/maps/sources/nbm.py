"""US forecast to 11 days from NOAA's National Blend of Models (2.5 km), from NOAA's GRIB2
files on AWS.

What the files hold (probed 10 Nov 2026; it differs from the plan's first reading):

- The 00, 06, 12 and 18 UTC runs reach 264 h: hourly files to 48 h, then 3-hourly to
  192 h, then 6-hourly.
- `APCP` over 1 hour is in every file. `APCP` and `ASNOW` over 6 hours are in the files at
  every 6th hour (6, 12, … 264). `ASNOW` over 1 hour is in the hourly files only (to 48 h).
  The 3-hourly files between hold no 3-hour sums and no `ASNOW`.
- Probability and percentile messages share the plain message's name (see grib.find).
- `ASNOW` is a depth in metres with NBM's own snow-to-liquid ratio; `APCP` is mm of water.

So beyond 48 h we work in 6-hour blocks (a 3-hour frame takes its share of its block from
how RDPS splits the same six hours; see render.py). Each run is fetched once: messages are
cached on disk (grib.fetch_messages).

Bucket: noaa-nbm-grib2-pds (NOAA Open Data Dissemination), free, no key.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from snowwatch.maps import grib
from snowwatch.maps.blend import kinds_from_parts
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import Region

log = logging.getLogger("snowwatch.precip")

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
HOUR = 3600
LAST_H = 264
HOURLY_TO_H = 48  # 1-hour APCP and ASNOW exist to here
BLOCK_H = 6


def file_url(run: int, fhour: int) -> str:
    d = datetime.fromtimestamp(run, UTC)
    return f"{BUCKET}/blend.{d:%Y%m%d}/{d:%H}/core/blend.t{d:%H}z.core.f{fhour:03d}.co.grib2"


def latest_run(net: Net, now: int, cycles: Iterable[int] = (0, 12)) -> int | None:
    """The newest run at one of these UTC hours whose last file is published."""
    hours = {int(c) % 24 for c in cycles}
    top = now - now % HOUR
    for back in range(0, 72):
        run = top - back * HOUR
        if datetime.fromtimestamp(run, UTC).hour not in hours:
            continue
        if net.get(file_url(run, LAST_H) + ".idx") is not None:
            return run
    return None


def pattern(var: str, start: int, end: int) -> str:
    return rf":{var}:surface:{start}-{end} hour acc fcst:"


class Nbm:
    """One NBM run's fields on the region, fetched (and cached) as they are asked for."""

    def __init__(
        self,
        net: Net,
        run: int,
        region: Region,
        cache_dir: Path | None = None,
        grids_dir: Path | None = None,
    ) -> None:
        self.net = net
        self.run = run
        self.region = region
        self.cache_dir = cache_dir
        self.grids_dir = grids_dir
        self._lock = threading.Lock()
        self._last: tuple[tuple[int, int], tuple[np.ndarray, np.ndarray] | None] | None = None

    def lead(self, t: int) -> int:
        """Hours from the run's start to valid time t."""
        return (t - self.run) // HOUR

    def sums(self, end: int, hours: int, vars_: list[str]) -> list[np.ndarray | None]:
        """Amounts over the `hours` before forecast hour `end`, one array per variable
        (APCP in mm of water, ASNOW in metres of snow)."""
        raw = grib.fetch_messages(
            self.net,
            file_url(self.run, end),
            [pattern(v, end - hours, end) for v in vars_],
            self.cache_dir,
        )
        return [grib.on_region(m, self.region, self.grids_dir) for m in raw]

    def field(self, fhour: int, var: str, level: str) -> np.ndarray | None:
        """A value at one forecast hour (such as `SNOWLVL` at `0 m above mean sea level`,
        or `GUST` at `10 m above ground`) on the region, or None if the file lacks it."""
        raw = grib.fetch_messages(
            self.net,
            file_url(self.run, fhour),
            [rf":{var}:{level}:{fhour} hour fcst:"],
            self.cache_dir,
        )
        return grib.on_region(raw[0], self.region, self.grids_dir)

    def precip(self, end: int, hours: int) -> tuple[np.ndarray, np.ndarray] | None:
        """Water (mm) over the period and its type codes, or None if NBM hasn't it.

        The last answer is kept: two 3-hour frames share one 6-hour block."""
        with self._lock:
            if self._last is not None and self._last[0] == (end, hours):
                return self._last[1]
            apcp, asnow = self.sums(end, hours, ["APCP", "ASNOW"])
            got = None
            if apcp is not None:
                if asnow is None:
                    asnow = np.zeros_like(apcp)
                got = apcp, kinds(apcp, asnow)
            self._last = ((end, hours), got)
            return got

    def snow_cm(self, start: int, end: int) -> np.ndarray | None:
        """Snow depth (cm) forecast between two forecast hours, using 1-hour sums where a
        6-hour block doesn't fit and they exist, and 6-hour blocks otherwise; a block only
        partly inside counts in proportion. None if a field is missing."""
        total: np.ndarray | None = None
        blocks: dict[int, np.ndarray | None] = {}
        h = start
        while h < end:
            whole = h % BLOCK_H == 0 and h + BLOCK_H <= end
            if not whole and h + 1 <= HOURLY_TO_H:
                (part,), step, share = self.sums(h + 1, 1, ["ASNOW"]), 1, 1.0
            else:
                b = (h // BLOCK_H + 1) * BLOCK_H
                if b not in blocks:
                    blocks = {b: self.sums(b, BLOCK_H, ["ASNOW"])[0]}  # keep only the latest
                part = blocks[b]
                step = min(b, end) - h
                share = step / BLOCK_H
            if part is None:
                return None
            add = np.nan_to_num(part, nan=0.0) * (100 * share)
            total = add if total is None else total + add
            h += step
        return total


def kinds(apcp: np.ndarray, asnow_m: np.ndarray) -> np.ndarray:
    """Type codes from how much of the water fell as snow (snow depth at 10:1 as water;
    10:1 is on the wet side for NBM's ratios, so colder snow lands well above a share of 1)."""
    return kinds_from_parts(apcp, np.nan_to_num(asnow_m, nan=0.0) * 1000 / 10, 0.0)
