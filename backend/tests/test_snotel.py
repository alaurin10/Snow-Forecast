from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from snowwatch.sources.snotel import parse_snotel, start_of_day
from snowwatch.store.db import MIGRATIONS_DIR, connect


def awdb(element: str, values: list[tuple[str, float]]) -> dict[str, Any]:
    return {
        "stationElement": {"elementCode": element},
        "values": [{"date": d, "value": v} for d, v in values],
    }


def test_start_of_day_is_the_next_date() -> None:
    assert start_of_day("2026-11-14") == "2026-11-15"
    assert start_of_day("2026-11-30 00:00") == "2026-12-01"
    assert start_of_day("2026-12-31") == "2027-01-01"


def test_daily_values_land_on_the_day_they_open() -> None:
    # Morse Lake, Nov 2026, as AWDB serves it: the daily depth for 14 Nov (6 in) is the
    # hourly reading at 15 Nov 00:00, and 15 Nov's (8 in) is 16 Nov 00:00's. The 2 in
    # fell on 15 Nov.
    daily = [
        {
            "stationTriplet": "642:WA:SNTL",
            "data": [
                awdb("SNWD", [("2026-11-13", 7), ("2026-11-14", 6), ("2026-11-15", 8)]),
                awdb("WTEQ", [("2026-11-13", 2.7), ("2026-11-14", 2.7), ("2026-11-15", 2.8)]),
                awdb("PREC", [("2026-11-13", 6.3), ("2026-11-14", 6.7), ("2026-11-15", 7.4)]),
            ],
        }
    ]
    out = parse_snotel("642:WA:SNTL", daily, [])
    by = {r.date: r for r in out.daily}
    assert sorted(by) == ["2026-11-14", "2026-11-15", "2026-11-16"]
    assert by["2026-11-15"].depth_cm == pytest.approx(6 * 2.54)
    assert by["2026-11-16"].depth_cm == pytest.approx(8 * 2.54)
    assert by["2026-11-16"].precip_mm == pytest.approx(7.4 * 25.4)
    # With no hourly readings the depth now is the latest daily one.
    assert out.depth_cm == pytest.approx(8 * 2.54)


def test_migration_moves_stored_snotel_days_only(tmp_path: Path) -> None:
    db = connect(tmp_path / "db.sqlite")
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem >= "007":
            break
        db.executescript(path.read_text())
    db.execute("PRAGMA foreign_keys = OFF")
    rows = [
        ("crystal", "642:WA:SNTL", "2026-11-14", 15.2),
        ("crystal", "642:WA:SNTL", "2026-11-15", 20.3),
        ("whistler", "3A25P:BC:ASWS", "2026-11-15", 28.0),
    ]
    with db:
        db.executemany(
            "INSERT INTO obs_daily (location_id, station, date, depth_cm) VALUES (?, ?, ?, ?)",
            rows,
        )
    db.executescript((MIGRATIONS_DIR / "007_snotel_start_of_day.sql").read_text())
    got = db.execute(
        "SELECT location_id, station, date, depth_cm FROM obs_daily ORDER BY station, date"
    ).fetchall()
    assert [tuple(r) for r in got] == [
        ("whistler", "3A25P:BC:ASWS", "2026-11-15", 28.0),
        ("crystal", "642:WA:SNTL", "2026-11-15", 15.2),
        ("crystal", "642:WA:SNTL", "2026-11-16", 20.3),
    ]
