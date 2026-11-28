"""The ensemble budget planner (docs/OPEN-METEO-PLAN.md, milestone 4).

Ensembles are the one thing a self-hosted Open-Meteo server can't answer from the
public data, so without milestone 1b's downloads (or while a system falls back) they
come from the public API and count against its daily limit (10,000 weighted calls).
This picks the richest tier that fits 90 % of that limit less the spots' allowance,
counting only the systems on the public API (those the server answers are free).
Without a server there are no spots, and the forecasts' own public calls come off first:

1. all three bands, every scheduled run (GEFS 4, ECMWF ENS 4, GEPS 2 a day)
2. all three bands, 2 runs a day each
3. mid only, every scheduled run
4. mid only, 2 runs a day each

It's worked out from the active locations each time it's asked (each run, `snowwatch
budget`, Manage), so adding locations drops a tier on its own. Without a self-hosted
server the forecasts also spend public calls; they're counted first.

Tier 1 at 50 locations: 50 × 3 × ((3.54 + 5.83) × 4 + 2.4 × 2) ≈ 6,340 a day, plus 2,000
for spots, within 9,000.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from snowwatch.config import ForecastConfig
from snowwatch.models import Location
from snowwatch.sources.openmeteo import ensemble_request, local_daily_weight

USABLE_SHARE = 0.9  # of the public daily limit; the rest is margin


@dataclass(frozen=True)
class Tier:
    n: int
    bands: bool  # all three bands (else mid only)
    max_runs: int | None  # runs a day per system (None: every scheduled one)

    @property
    def label(self) -> str:
        where = "3 bands" if self.bands else "mid only"
        runs = "every run" if self.max_runs is None else f"{self.max_runs} runs a day"
        return f"{where}, {runs}"


TIERS = (
    Tier(1, True, None),
    Tier(2, True, 2),
    Tier(3, False, None),
    Tier(4, False, 2),
)


def runs_for(cfg: ForecastConfig, system: str, tier: Tier) -> list[str]:
    """A system's public-API times (UTC) at this tier: evenly spaced when fewer."""
    times = cfg.schedule.runs_for(system)
    if tier.max_runs is None or len(times) <= tier.max_runs:
        return times
    step = len(times) / tier.max_runs
    return [times[int(i * step)] for i in range(tier.max_runs)]


def ensemble_weight(
    locs: Iterable[Location], cfg: ForecastConfig, tier: Tier, public: Collection[str]
) -> float:
    """A day of public ensembles for these locations at this tier (`public`: the
    systems on the public API)."""
    total = 0.0
    for loc in locs:
        for system in cfg.ensembles:
            if system in public:
                req = ensemble_request(loc, system, bands=tier.bands)
                total += req.weight * len(runs_for(cfg, system, tier))
    return round(total, 1)


@dataclass(frozen=True)
class Plan:
    tier: Tier
    weight: float  # public ensembles a day at that tier
    available: float  # what ensembles may spend a day
    fits: bool  # False: even tier 4 doesn't fit (it's used anyway)
    weights: tuple[tuple[Tier, float], ...]  # every tier's weight, for Manage
    public: tuple[str, ...]  # the systems counted (on the public API)


def plan(
    locs: list[Location],
    cfg: ForecastConfig,
    *,
    budget: float,
    public: Collection[str],
    local_forecasts: bool = True,
) -> Plan:
    """The richest tier that fits. Without a self-hosted server (`local_forecasts`
    False) there are no spots (they need the server), and the forecasts' own daily
    weight is taken off instead."""
    available = USABLE_SHARE * budget
    if local_forecasts:
        available -= cfg.spots.ensemble_allowance
    else:
        available -= sum(local_daily_weight(loc, cfg) for loc in locs)
    weights = tuple((t, ensemble_weight(locs, cfg, t, public)) for t in TIERS)
    for t, w in weights:
        if w <= available:
            return Plan(t, w, round(available, 1), True, weights, tuple(public))
    t, w = weights[-1]
    return Plan(t, w, round(available, 1), False, weights, tuple(public))


def last_due(times: list[str], now: datetime) -> datetime | None:
    """The latest of these daily times (UTC) at or before `now`."""
    now = now.astimezone(UTC)
    best: datetime | None = None
    for t in times:
        h, m = (int(x) for x in t.split(":"))
        at = datetime.combine(now.date(), time(h, m), UTC)
        if at > now:
            at -= timedelta(days=1)
        if best is None or at > best:
            best = at
    return best


def ensemble_due(fetched_at: datetime | None, times: list[str], now: datetime) -> bool:
    """Whether a system on the public API should be asked again: never asked, or one of
    its times has passed since the last answer."""
    if fetched_at is None:
        return True
    last = last_due(times, now)
    return last is not None and fetched_at < last
