"""Building the snow-by-elevation grids (bins.py) for the snow totals' windows.

The same walks as totals.py, with precipitation and the snow level instead of the
models' own snow:

- Canada: the chain HRDPS → RDPS → GDPS in steps ending on the synoptic hours. Each step
  takes all precipitation since the run began (`HRDPS.CONTINENTAL_PR`,
  `…_Precip-Accum`) differenced within the run, the ratio from the 2 m temperature at the
  step's end (as the plain totals), and the snow level as the mean of its values half
  way through the step and at its end.
- The US: NBM's 1-hour sums to the first 6-hour boundary, then 6-hour blocks (a block only
  partly inside a window counts in proportion), with `APCP`, NBM's own ratio (`SNOWLR`,
  the mean of its non-zero values at the block's start and end) and `SNOWLVL` (the mean
  at the block's start and end).

The snow level comes from, in order, HRDPS-WEonG (inside its domain, to 48 h),
RDPS-WEonG (to 84 h), GDPS-WEonG (to 144 h) and then NBM's `SNOWLVL`, which covers
southern Canada too, for each pixel the first that has a value; the US takes NBM's.
GeoMet's codes for "snow reaches the ground" are filled as the Snow level layer fills them.

Each walk hands its running total to `emit` at every window end; render.py joins the two
sides across the border and writes them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np

from snowwatch.config import SlrBand
from snowwatch.maps import bins
from snowwatch.maps.geomet import (
    Grid,
    Net,
    capabilities_dims,
    on_region,
    parse_times,
    ts_iso,
    wcs_grid,
)
from snowwatch.maps.layers import CODE_FILL_CELLS, fill_codes
from snowwatch.maps.region import Region
from snowwatch.maps.sources.nbm import BLOCK_H, HOURLY_TO_H, LAST_H, Nbm
from snowwatch.maps.sources.rdps_gdps import Run
from snowwatch.maps.totals import SYNOPTIC_S, TEMP_RANGE, ratio_grid

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
SNOW_LEVEL_LAYERS = (
    ("hrdps", "HRDPS-WEonG_2.5km_SnowLevelHeight"),
    ("rdps", "RDPS-WEonG_10km_SnowLevelHeight"),
    ("gdps", "GDPS-WEonG_15km_SnowLevelHeight"),
)
LEVEL_RANGE = (0.0, 9000.0)
AMOUNT_RANGE = (0.0, 5000.0)
NBM_LEVEL = ("SNOWLVL", "0 m above mean sea level")
NBM_RATIO = ("SNOWLR", "surface")
NBM_3H_TO = 192  # NBM files are hourly to 48 h, 3-hourly to 192 h, 6-hourly to 264 h
HRDPS_INSIDE = 0.999  # HRDPS-WEonG's level counts only well inside its domain (0 outside)

Emit = Callable[[int, np.ndarray], None]


@dataclass
class LevelRun:
    """A GeoMet snow-level layer's newest run."""

    name: str
    layer: str
    ref: str
    times: list[int]


def level_runs(net: Net) -> list[LevelRun]:
    """The WEonG snow-level layers GeoMet has, finest first."""
    out = []
    for name, layer in SNOW_LEVEL_LAYERS:
        dims = capabilities_dims(net, layer)
        times = parse_times(dims.get("time", ""))
        if times:
            out.append(LevelRun(name, layer, dims.get("reference_time.default", ""), times))
    return out


def nbm_has(lead: int) -> bool:
    """Whether NBM publishes a file at this forecast hour."""
    if lead < 1 or lead > LAST_H:
        return False
    if lead <= HOURLY_TO_H:
        return True
    return lead % (3 if lead <= NBM_3H_TO else 6) == 0


class SnowLevels:
    """The snow level (m) on the region at a time, from the first source with a value at
    each pixel (see the module docstring). Remembers the last few times asked."""

    def __init__(
        self,
        net: Net,
        region: Region,
        runs: Sequence[LevelRun],
        nbm: Nbm | None,
        hrdps_weight: np.ndarray | None,
        cache_dir: Path | None = None,
    ) -> None:
        self.net = net
        self.region = region
        self.runs = list(runs)
        self.nbm = nbm
        self.hrdps_weight = hrdps_weight
        self.cache_dir = cache_dir
        self.used: set[str] = set()
        self._memo: dict[int, np.ndarray | None] = {}

    def _geomet(self, run: LevelRun, t: int) -> np.ndarray | None:
        g = wcs_grid(
            self.net,
            run.layer,
            ts_iso(t),
            self.region,
            ref=run.ref or None,
            cache_dir=self.cache_dir,
        )
        if g is None:
            return None
        g = Grid(fill_codes(g.data, CODE_FILL_CELLS, 0.0), g.lon0, g.lat0, g.dlon, g.dlat)
        v = on_region(g, self.region, LEVEL_RANGE, smooth=True)
        if run.name == "hrdps":
            if self.hrdps_weight is None:
                return None  # its grids hold 0 outside the domain: unusable without it
            v = np.where(self.hrdps_weight >= HRDPS_INSIDE, v, np.nan)
        return v

    def at(self, t: int) -> np.ndarray | None:
        if t in self._memo:
            return self._memo[t]
        out: np.ndarray | None = None
        for run in self.runs:
            if t not in run.times:
                continue
            v = self._geomet(run, t)
            if v is None or not np.isfinite(v).any():
                continue
            self.used.add(run.name)
            out = v if out is None else np.where(np.isnan(out), v, out)
            if not np.isnan(out).any():
                break
        if self.nbm is not None and (out is None or np.isnan(out).any()):
            lead = self.nbm.lead(t)
            if nbm_has(lead):
                v = self.nbm.field(lead, *NBM_LEVEL)
                if v is not None:
                    v = np.where((v >= LEVEL_RANGE[0]) & (v <= LEVEL_RANGE[1]), v, np.nan)
                    if np.isfinite(v).any():
                        self.used.add("nbm")
                        out = v if out is None else np.where(np.isnan(out), v, out)
        if len(self._memo) > 4:
            self._memo.pop(min(self._memo))
        self._memo[t] = out
        return out

    def mean(self, times: Sequence[int]) -> np.ndarray | None:
        """The mean snow level over several times (each pixel over the times it has)."""
        got = [v for v in (self.at(t) for t in times) if v is not None]
        if not got:
            return None
        stack = np.stack(got)
        have = np.isfinite(stack)
        n = have.sum(0)
        out = np.full(stack.shape[1:], np.nan, np.float32)
        np.divide(np.where(have, stack, 0).sum(0), n, out=out, where=n > 0)
        return out


def _mean_positive(values: Sequence[np.ndarray | None]) -> np.ndarray | None:
    """The mean of the positive values at each pixel (NaN where none are)."""
    got = [v for v in values if v is not None]
    if not got:
        return None
    stack = np.stack(got)
    good = np.isfinite(stack) & (stack > 0)
    n = good.sum(0)
    out = np.full(stack.shape[1:], np.nan, np.float32)
    np.divide(np.where(good, stack, 0).sum(0), n, out=out, where=n > 0)
    return out


def north_bins(
    net: Net,
    region: Region,
    t0: int,
    ends: list[int],
    chain: list[Run],
    bands: Sequence[SlrBand],
    levels: SnowLevels,
    emit: Emit,
    cache_dir: Path | None = None,
    domain: dict[str, np.ndarray] | None = None,
) -> dict[str, str]:
    """Canada's snow by elevation from t0 to each end (handed to `emit`); returns the
    runs used (model → run start, ISO). Stops where no run covers a step, as
    totals.north_totals does; `domain` fades HRDPS into the next model the same way."""
    used: dict[str, str] = {}
    if not ends or not chain:
        return used
    last = max(ends)
    points = sorted(
        {t0, *ends} | {t for t in range(t0 - t0 % SYNOPTIC_S + SYNOPTIC_S, last, SYNOPTIC_S)}
    )
    cache: dict[tuple[str, str, int], np.ndarray | None] = {}
    lift = bins.Lift(bands)

    def grid(run: Run, layer: str, t: int, valid: tuple[float, float]) -> np.ndarray | None:
        key = (run.model.name, layer, t)
        if key not in cache:
            g = wcs_grid(net, layer, ts_iso(t), region, ref=run.ref or None, cache_dir=cache_dir)
            cache[key] = None if g is None else on_region(g, region, valid, smooth=True)
        return cache[key]

    def inputs(run: Run, a: int, b: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Water (mm), the model's own snow (cm) and its ratio for one step."""
        m = run.model
        sa, sb = grid(run, m.accum, a, AMOUNT_RANGE), grid(run, m.accum, b, AMOUNT_RANGE)
        if sa is None or sb is None:
            return None
        ratio = ratio_grid(grid(run, m.temp, b, TEMP_RANGE), bands)
        own = np.clip(sb - sa, 0, None) * ratio / 10
        pa = grid(run, m.total, a, AMOUNT_RANGE) if m.total else None
        pb = grid(run, m.total, b, AMOUNT_RANGE) if m.total else None
        if pa is None or pb is None:
            water = np.full(sa.shape, np.nan, np.float32)  # no water: the model's own snow
        else:
            water = np.clip(pb - pa, 0, None)
        r = np.broadcast_to(np.asarray(ratio, np.float32), sa.shape)
        return water, np.nan_to_num(own, nan=0.0), r

    acc = np.zeros((*bins.shape_for(region), len(bins.ELEVS)), np.float32)
    want = set(ends)
    for a, b in pairwise(points):
        covering = [r for r in chain if a in r.times and b in r.times]
        if not covering:
            break
        run = covering[0]
        got = inputs(run, a, b)
        if got is None:
            log.warning(
                "snow by elevation: %s missing at %s or %s", run.model.name, ts_iso(a), ts_iso(b)
            )
            break
        water, own, ratio = got
        used[run.model.name] = run.ref
        w = domain.get(run.model.name) if domain else None
        if w is not None and len(covering) > 1:
            under = inputs(covering[1], a, b)
            if under is not None:
                water = w * water + (1 - w) * under[0]
                own = w * own + (1 - w) * under[1]
                ratio = w * ratio + (1 - w) * under[2]
                used[covering[1].model.name] = covering[1].ref
        mid = a + ((b - a) // 2) // HOUR * HOUR
        level = levels.mean([t for t in (mid, b) if t > a])
        # Without the water, the model's own snow goes into every band.
        sl = None if level is None else bins.half(level)
        water_h = bins.half(water)
        if sl is not None:
            sl = np.where(np.isfinite(water_h), sl, np.nan)
        bins.add_period(
            acc,
            water_h,
            sl,
            bins.model_ratio(bins.half(ratio), water_h.shape),
            bins.half(own),
            lift,
        )
        if b in want:
            emit(b, acc)
        for k in [k for k in cache if k[2] < b]:
            del cache[k]
    return used


def south_bins(
    nbm: Nbm | None,
    t0: int,
    ends: list[int],
    bands: Sequence[SlrBand],
    emit: Emit,
) -> bool:
    """The US's snow by elevation from t0 to each end (handed to `emit`), from one NBM
    run. False if nothing could be added."""
    if nbm is None or not ends:
        return False
    start = nbm.lead(t0)
    if start < 0:
        return False
    region = nbm.region
    lift = bins.Lift(bands)
    acc = np.zeros((*bins.shape_for(region), len(bins.ELEVS)), np.float32)
    block_memo: dict[int, tuple[np.ndarray | None, np.ndarray] | None] = {}
    # A block's end is the next block's start: keep the last few fields decoded.
    fields: dict[tuple[int, str], np.ndarray | None] = {}

    def field(h: int, spec: tuple[str, str]) -> np.ndarray | None:
        key = (h, spec[0])
        if key not in fields:
            if len(fields) >= 4:
                fields.pop(next(iter(fields)))
            fields[key] = nbm.field(h, *spec)
        return fields[key]

    def block_inputs(b: int) -> tuple[np.ndarray | None, np.ndarray] | None:
        """The snow level and ratio for the 6-hour block ending at forecast hour b, on
        the band grid."""
        if b not in block_memo:
            hours = [h for h in (b - BLOCK_H, b) if nbm_has(h)]
            levels = []
            ratios = []
            for h in hours:
                lv = field(h, NBM_LEVEL)
                if lv is not None:
                    levels.append(np.where((lv >= 0) & (lv <= LEVEL_RANGE[1]), lv, np.nan))
                ratios.append(field(h, NBM_RATIO))
            level = None
            if levels:
                stack = np.stack(levels)
                have = np.isfinite(stack)
                n = have.sum(0)
                mean = np.full(stack.shape[1:], np.nan, np.float32)
                np.divide(np.where(have, stack, 0).sum(0), n, out=mean, where=n > 0)
                level = bins.half(mean)
            ratio = _mean_positive(ratios)
            shape = bins.shape_for(region)
            r = bins.model_ratio(None if ratio is None else bins.half(ratio), shape)
            block_memo.clear()
            block_memo[b] = (level, r)
        return block_memo[b]

    lead = start
    added = False
    for end in sorted(ends):
        stop = nbm.lead(end)
        if stop <= lead:
            continue
        h = lead
        while h < stop:
            b = (h // BLOCK_H + 1) * BLOCK_H
            whole = h % BLOCK_H == 0 and h + BLOCK_H <= stop
            if not whole and h + 1 <= HOURLY_TO_H:
                apcp, asnow = nbm.sums(h + 1, 1, ["APCP", "ASNOW"])
                step, share = 1, 1.0
            else:
                apcp, asnow = nbm.sums(b, BLOCK_H, ["APCP", "ASNOW"])
                step = min(b, stop) - h
                share = step / BLOCK_H
            if apcp is None:
                log.info("snow by elevation: NBM stops at hour %d", h)
                return added
            got = block_inputs(b)
            assert got is not None
            level, ratio = got
            own = None if asnow is None else bins.half(np.nan_to_num(asnow, nan=0.0) * 100)
            water = bins.half(apcp)
            sl = None if level is None else np.where(np.isfinite(water), level, np.nan)
            bins.add_period(acc, water, sl, ratio, own, lift, share)
            added = True
            h += step
        emit(end, acc)
        lead = stop
    return added
