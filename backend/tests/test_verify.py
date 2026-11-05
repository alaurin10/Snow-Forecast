"""The scorecard: next-day forecasts against station observations, by hand."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from snowwatch.locations import service
from snowwatch.verify import MIN_DAYS, verification
from tests.conftest import make_location

STATION = "999:WA:SNTL"
START = date(2026, 12, 1)


@pytest.fixture
def hill(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.upsert_location(conn, make_location(snotel=STATION), max_locations=25)
    with conn:
        conn.execute(
            "INSERT INTO snotel_stations (triplet, name, state, lat, lon, elev_m, updated_at) "
            "VALUES (?, 'Test Snotel', 'WA', 47, -121, 1400, 'x')",
            (STATION,),
        )
    return conn


def add_obs(conn: sqlite3.Connection, depths: list[float | None], swe: list[float | None]) -> None:
    with conn:
        for i, (d, w) in enumerate(zip(depths, swe, strict=True)):
            conn.execute(
                "INSERT INTO obs_daily (location_id, station, date, depth_cm, swe_mm) "
                "VALUES ('testhill', ?, ?, ?, ?)",
                (STATION, (START + timedelta(days=i)).isoformat(), d, w),
            )


def add_forecast(
    conn: sqlite3.Connection, run_id: int, issued: str, target: date, **cm: float
) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs (id, kind, started_at, status) VALUES (?, 'full', ?, 'ok')",
            (run_id, issued),
        )
        for source, v in cm.items():
            conn.execute(
                "INSERT INTO forecast_daily (location_id, run_id, issued_at, target_date, source, "
                "snow_cm) VALUES ('testhill', ?, ?, ?, ?, ?)",
                (run_id, issued, target.isoformat(), source, v),
            )


def test_bias_mae_and_big_days(hill: sqlite3.Connection) -> None:
    # Depth at the start of each day: +10, +0, +20, +5 cm over four days.
    add_obs(hill, [100, 110, 110, 130, 135], [None] * 5)
    forecasts = [(8.0, 12.0), (2.0, 3.0), (10.0, 14.0), (5.0, 6.0)]
    for i, (raw, slr) in enumerate(forecasts):
        target = START + timedelta(days=i)
        # Issued the evening before (UTC 03:30 = 19:30 PT the day before).
        add_forecast(
            hill, 10 + i, f"{target.isoformat()}T03:30:00+00:00", target, cons=raw, cons_slr=slr
        )
        # A later run issued after the day began must be ignored.
        add_forecast(hill, 50 + i, f"{target.isoformat()}T21:30:00+00:00", target, cons=99.0)
    out = verification(hill, make_location(snotel=STATION))
    assert out.n_days == 4 and out.station_name == "Test Snotel" and out.station_elev_m == 1400
    assert not out.ready and out.needs_days == MIN_DAYS - 4
    rows = {r.source: r for r in out.rows}
    assert [r.source for r in out.rows][:2] == ["cons", "cons_slr"]
    cons = rows["cons"]
    # errors: -2, +2, -10, 0 → bias -2.5, MAE 3.5
    assert (cons.n, cons.bias_cm, cons.mae_cm) == (4, -2.5, 3.5)
    # Big days (≥ 7.62 cm): observed on days 1 and 3; forecast on days 1 and 3.
    assert (cons.hits, cons.misses, cons.false_alarms) == (2, 0, 0)
    slr = rows["cons_slr"]
    # errors: +2, +3, -6, +1 → bias 0, MAE 3
    assert (slr.bias_cm, slr.mae_cm) == (0.0, 3.0)
    assert [p.observed_cm for p in out.pairs] == [10, 0, 20, 5]
    assert all(not p.from_swe for p in out.pairs)


def test_snow_water_stands_in_without_a_depth_sensor(hill: sqlite3.Connection) -> None:
    add_obs(hill, [None, None, None], [100, 120, 120])
    for i in range(2):
        target = START + timedelta(days=i)
        add_forecast(hill, 10 + i, f"{target.isoformat()}T03:30:00+00:00", target, cons=15.0)
    out = verification(hill, make_location(snotel=STATION), swe_ratio=10)
    # 20 mm of water at 10:1 = 20 cm, then nothing.
    assert [(p.observed_cm, p.from_swe) for p in out.pairs] == [(20.0, True), (0.0, True)]


def test_ready_after_a_week(hill: sqlite3.Connection) -> None:
    add_obs(hill, [100.0] * (MIN_DAYS + 1), [None] * (MIN_DAYS + 1))
    for i in range(MIN_DAYS):
        target = START + timedelta(days=i)
        add_forecast(hill, 10 + i, f"{target.isoformat()}T03:30:00+00:00", target, cons=0.0)
    out = verification(hill, make_location(snotel=STATION))
    assert out.ready and out.needs_days == 0 and out.since == START.isoformat()


def test_no_station(hill: sqlite3.Connection) -> None:
    out = verification(hill, make_location())
    assert out.station is None and out.n_days == 0 and out.rows == []
