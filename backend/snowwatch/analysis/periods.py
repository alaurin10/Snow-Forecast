"""Day and night periods.

Day is 06–18 and night 18–06 local time, and a night belongs to the evening's
date. Hours are grouped by their local wall-clock hour, so a night that spans
a daylight-saving change has 11 or 13 hours.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from snowwatch.analysis.series import local

Kind = Literal["day", "night"]


@dataclass(frozen=True)
class Period:
    date: date
    kind: Kind
    label: str
    hours: tuple[int, ...]

    @property
    def key(self) -> str:
        return f"{self.date.isoformat()}-{self.kind}"


def period_of(
    ts: int, tz: ZoneInfo, day_start: int = 6, night_start: int = 18
) -> tuple[date, Kind]:
    t = local(ts, tz)
    if day_start <= t.hour < night_start:
        return t.date(), "day"
    if t.hour >= night_start:
        return t.date(), "night"
    return t.date() - timedelta(days=1), "night"


def period_label(d: date, kind: Kind, today: date) -> str:
    if d == today:
        return "Today" if kind == "day" else "Tonight"
    if d < today:  # the small hours of last night
        return "Overnight"
    wd = d.strftime("%a")
    return wd if kind == "day" else f"{wd} night"


def build_periods(
    hours: Sequence[int],
    tz: ZoneInfo,
    today: date,
    *,
    n: int = 20,
    min_hours: int = 6,
    day_start: int = 6,
    night_start: int = 18,
) -> list[Period]:
    """Group consecutive hours (from now on) into at most n periods.

    The first period may be partial. Any later period shorter than min_hours
    (in practice the trailing fragment where the data ends) is dropped.
    """
    groups: dict[tuple[date, Kind], list[int]] = {}
    order: list[tuple[date, Kind]] = []
    for h in hours:
        k = period_of(h, tz, day_start, night_start)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(h)
    kept = [k for i, k in enumerate(order) if i == 0 or len(groups[k]) >= min_hours]
    return [
        Period(d, kind, period_label(d, kind, today), tuple(groups[(d, kind)]))
        for d, kind in kept[:n]
    ]
