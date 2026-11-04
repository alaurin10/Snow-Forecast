from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from snowwatch.analysis.periods import build_periods, period_label

LA = ZoneInfo("America/Los_Angeles")


def hours_from(start: datetime, n: int) -> list[int]:
    t0 = int(start.timestamp())
    return [t0 + 3600 * i for i in range(n)]


def test_partial_first_period_and_labels() -> None:
    hours = hours_from(datetime(2026, 11, 4, 13, tzinfo=LA), 72)
    ps = build_periods(hours, LA, date(2026, 11, 4))
    assert [p.label for p in ps[:4]] == ["Today", "Tonight", "Thu", "Thu night"]
    assert len(ps[0].hours) == 5  # 13:00–17:00
    assert ps[1].key == "2026-11-04-night" and len(ps[1].hours) == 12


def test_small_hours_belong_to_last_night() -> None:
    hours = hours_from(datetime(2026, 11, 5, 2, tzinfo=LA), 30)
    ps = build_periods(hours, LA, date(2026, 11, 5))
    assert ps[0].key == "2026-11-04-night" and ps[0].label == "Overnight"
    assert ps[1].label == "Today"


def test_trailing_fragment_dropped() -> None:
    hours = hours_from(datetime(2026, 11, 4, 6, tzinfo=LA), 12 + 12 + 5)
    ps = build_periods(hours, LA, date(2026, 11, 4))
    assert [len(p.hours) for p in ps] == [12, 12]


def test_spring_forward_night_has_11_hours() -> None:
    # 14 Mar 2027: clocks jump from 02:00 to 03:00 in Los Angeles.
    hours = hours_from(datetime(2027, 3, 13, 6, tzinfo=LA), 48)
    ps = build_periods(hours, LA, date(2027, 3, 13))
    night = next(p for p in ps if p.key == "2027-03-13-night")
    assert len(night.hours) == 11
    assert len(next(p for p in ps if p.key == "2027-03-14-day").hours) == 12


def test_fall_back_night_has_13_hours() -> None:
    # 7 Nov 2027: 01:00–02:00 happens twice.
    hours = hours_from(datetime(2027, 11, 6, 6, tzinfo=LA), 48)
    ps = build_periods(hours, LA, date(2027, 11, 6))
    assert len(next(p for p in ps if p.key == "2027-11-06-night").hours) == 13


def test_label_for_later_days() -> None:
    assert period_label(date(2026, 11, 6), "night", date(2026, 11, 4)) == "Fri night"
