"""Ensemble statistics: period and window totals, and running totals per system.

The prototype pooled every member that covered a day, so when the ECMWF
ensemble ended a day before GEFS its 15-day band silently switched to GEFS
members only and dipped. Here running totals are computed per system on a
fixed member set, the pooled band covers only the days every system reaches,
and anything past that is a labelled single-system tail.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from snowwatch.analysis.series import Hourly, mean, pct, total


@dataclass
class Stats:
    p10: float | None
    p50: float | None
    p90: float | None
    mean: float | None
    n: int

    def scaled(self, k: float) -> Stats:
        def f(x: float | None) -> float | None:
            return None if x is None else x * k

        return Stats(f(self.p10), f(self.p50), f(self.p90), f(self.mean), self.n)


def member_totals(members: Sequence[Hourly], hours: Sequence[int]) -> list[float]:
    """Totals for the members that cover every hour."""
    return [t for m in members if (t := total(m, hours)) is not None]


def pooled(systems: Mapping[str, Sequence[Hourly]]) -> list[Hourly]:
    return [m for members in systems.values() for m in members]


def stats(values: Sequence[float], min_members: int) -> Stats | None:
    if len(values) < min_members:
        return None
    return Stats(pct(values, 0.1), pct(values, 0.5), pct(values, 0.9), mean(values), len(values))


def exceedance(values: Sequence[float], threshold: float) -> int | None:
    """Percent of members at or above threshold."""
    if not values:
        return None
    return round(100 * sum(v >= threshold for v in values) / len(values))


@dataclass
class RunningDay:
    systems: dict[str, Stats | None] = field(default_factory=dict)
    pooled: Stats | None = None
    tail: str | None = None  # set once the pooled band has stopped: the system that carries on


def running_totals(
    systems: Mapping[str, Sequence[Hourly]],
    days: Sequence[Sequence[int]],
    *,
    min_members: int = 10,
    tail_preference: Sequence[str] = ("gfs_seamless", "gem_global", "ecmwf_ifs025"),
) -> list[RunningDay]:
    """Cumulative totals day by day.

    Each system keeps the members that cover the first day; it ends on the
    first day any of them stops. Percentiles of a fixed member set's running
    totals can only grow, so no band dips.
    """
    out: list[RunningDay] = []
    fixed = {
        s: [m for m in members if days and total(m, days[0]) is not None]
        for s, members in systems.items()
    }
    cum: dict[str, list[float] | None] = {
        s: [0.0] * len(members) if len(members) >= min_members else None
        for s, members in fixed.items()
    }
    for hours in days:
        day = RunningDay()
        for s, members in fixed.items():
            acc = cum[s]
            if acc is None:
                day.systems[s] = None
                continue
            daily = [total(m, hours) for m in members]
            if any(v is None for v in daily):
                cum[s] = None
                day.systems[s] = None
                continue
            cum[s] = acc = [a + (v or 0.0) for a, v in zip(acc, daily, strict=True)]
            day.systems[s] = stats(acc, min_members)
        live = [s for s in fixed if cum.get(s) is not None]
        if fixed and len(live) == len(fixed):
            day.pooled = stats([v for s in live for v in (cum[s] or [])], min_members)
        else:
            # The pooled band stops here. Name the system whose own band (drawn
            # for every day it covers) carries on, so nothing is spliced.
            day.tail = next((s for s in tail_preference if s in live), None)
        out.append(day)
    return out
