"""Forecast snow totals over windows from 12 hours to 10 days, for Canada and the US.

Canada (and the north of the box): Environment Canada's running snow water since each run
began, chained by lead time from the finest model that reaches it:

  HRDPS 2.5 km  (0–48 h)  →  RDPS 10 km  (to 84 h)  →  GDPS 15 km  (to 240 h)

Each piece is a difference within one run (WCS pinned to that run), in steps that end on
the 6-hour synoptic times, and each step's water becomes depth with a snow-to-liquid ratio
from the 2 m temperature at the step's end (the forecast's `slr_bands`; 10:1 where the
temperature is missing).

The US (and the south of the box): NOAA NBM's snow depth (`ASNOW`), which already uses
NBM's own ratio (see sources/nbm.py).

The two meet in a linear blend between 48.5 and 49.5°N; where one side has no data the
other fills in. (Milestone 2's last task replaces this with a per-pixel blend in data space,
docs/MAP-PLAN.md decision 8.)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np

from snowwatch.config import SlrBand
from snowwatch.maps.files import save_npy
from snowwatch.maps.geomet import Net, on_region, ts_iso, wcs_grid
from snowwatch.maps.region import Region
from snowwatch.maps.sources.nbm import Nbm
from snowwatch.maps.sources.rdps_gdps import Run

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
SYNOPTIC_S = 6 * HOUR
# Window lengths in hours: 12 h, 24 h, 48 h, 3, 5, 7 and 10 days.
WINDOWS = (12, 24, 48, 72, 120, 168, 240)
# A window longer than two days ends on a synoptic hour (00/06/12/18 UTC), where NBM's
# 6-hour sums end; and it is dropped if the models stop well short of it.
SHORT_H = 48
MIN_SHARE = 0.9
SEAM = (48.5, 49.5)  # degrees north: all south below, all north above, linear between
DEFAULT_RATIO = 10.0
TEMP_RANGE = (-90.0, 60.0)


def window_ends(t0: int, last: int, windows: Sequence[int] = WINDOWS) -> list[tuple[int, int]]:
    """(window hours, end time) for each window the models reach.

    Windows to two days end exactly; a run ending sooner shortens the last one, as before.
    Longer windows end on the synoptic hour at or before, and are dropped if the models
    stop before 90% of the window."""
    out: list[tuple[int, int]] = []
    prev = t0
    for w in windows:
        end = t0 + w * HOUR
        if w > SHORT_H:
            end -= end % SYNOPTIC_S
            if min(end, last) - t0 < MIN_SHARE * w * HOUR:
                continue
        end = min(end, last)
        if end <= prev:
            continue
        out.append((w, end))
        prev = end
    return out


def ratio_grid(temp_c: np.ndarray | None, bands: Sequence[SlrBand]) -> np.ndarray | float:
    """Snow-to-liquid ratio per pixel from the 2 m temperature (analysis/slr.py's bands:
    the first band whose lower bound the temperature reaches; the coldest band below)."""
    if temp_c is None or not bands:
        return DEFAULT_RATIO
    out = np.full(temp_c.shape, bands[-1].ratio, np.float32)
    for b in reversed(bands):
        if b.min_c is not None:
            out[temp_c >= b.min_c] = b.ratio
    out[np.isnan(temp_c)] = DEFAULT_RATIO
    return out


@dataclass
class North:
    """The Canadian chain's totals at each window end, and the runs it used."""

    cm: dict[int, np.ndarray] = field(default_factory=dict)
    runs: dict[str, str] = field(default_factory=dict)


def north_totals(
    net: Net,
    region: Region,
    t0: int,
    ends: list[int],
    chain: list[Run],
    bands: Sequence[SlrBand],
) -> North:
    """Snow depth (cm) from t0 to each end, chaining the runs (finest first)."""
    out = North()
    if not ends or not chain:
        return out
    last = max(ends)
    points = sorted(
        {t0, *ends} | {t for t in range(t0 - t0 % SYNOPTIC_S + SYNOPTIC_S, last, SYNOPTIC_S)}
    )
    cache: dict[tuple[str, int], np.ndarray | None] = {}

    def grid(run: Run, layer: str, t: int, valid: tuple[float, float]) -> np.ndarray | None:
        key = (layer, t)
        if key not in cache:
            g = wcs_grid(net, layer, ts_iso(t), region, ref=run.ref or None)
            cache[key] = None if g is None else on_region(g, region, valid)
        return cache[key]

    total = np.zeros((region.height, region.width), np.float32)
    want = set(ends)
    for a, b in pairwise(points):
        run = next((r for r in chain if a in r.times and b in r.times), None)
        if run is None:
            log.info("snow totals: no Canadian run covers %s–%s", ts_iso(a), ts_iso(b))
            break
        start = grid(run, run.model.accum, a, (0, 5000))
        stop = grid(run, run.model.accum, b, (0, 5000))
        if start is None or stop is None:
            log.warning("snow totals: %s missing at %s or %s", run.model.name, ts_iso(a), ts_iso(b))
            break
        water = np.clip(stop - start, 0, None)
        temp = grid(run, run.model.temp, b, TEMP_RANGE)
        total += np.nan_to_num(water * ratio_grid(temp, bands) / 10, nan=0.0)
        out.runs[run.model.name] = run.ref
        if b in want:
            out.cm[b] = total.copy()
        # Drop grids the walk has passed.
        for k in [k for k in cache if k[1] < b]:
            del cache[k]
    return out


def south_totals(nbm: Nbm | None, t0: int, ends: list[int]) -> dict[int, np.ndarray]:
    """NBM snow depth (cm) from t0 to each end, from the run's 1- and 6-hour sums."""
    out: dict[int, np.ndarray] = {}
    if nbm is None:
        return out
    start = nbm.lead(t0)
    if start < 0:
        return out
    total: np.ndarray | None = None
    lead = start
    for end in sorted(ends):
        stop = nbm.lead(end)
        if stop <= lead:
            continue
        part = nbm.snow_cm(lead, stop)
        if part is None:
            log.info("snow totals: NBM stops before %s", ts_iso(end))
            break
        total = part if total is None else total + part
        out[end] = total.copy()
        lead = stop
    return out


def seam_weight(region: Region) -> np.ndarray:
    """Weight of the northern source for each row: 0 south of the seam, 1 north of it."""
    _, lats = region.lonlats()
    lo, hi = SEAM
    w: np.ndarray = np.clip((lats - lo) / (hi - lo), 0, 1).astype(np.float32)
    return w[:, None]


def blend(north: np.ndarray | None, south: np.ndarray | None, weight: np.ndarray) -> np.ndarray:
    """North and south joined across the seam; either fills in where the other has nothing."""
    if north is None and south is None:
        raise ValueError("nothing to blend")
    if north is None:
        assert south is not None
        return south
    if south is None:
        return north
    w = np.broadcast_to(weight, north.shape)
    w = np.where(np.isnan(south), 1.0, np.where(np.isnan(north), 0.0, w))
    out: np.ndarray = w * np.nan_to_num(north) + (1 - w) * np.nan_to_num(south)
    out[np.isnan(north) & np.isnan(south)] = np.nan
    return out.astype(np.float32)


def save_grid(cm: np.ndarray, path: Path) -> None:
    """Keep the numbers (float16 cm) for later uses: tap-for-numbers, terrain adjustment."""
    save_npy(path, cm.astype(np.float16))
