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


def add_station_days(conn: sqlite3.Connection, days: list[dict[str, float | None]]) -> None:
    with conn:
        for i, row in enumerate(days):
            conn.execute(
                "INSERT INTO obs_daily (location_id, station, date, depth_cm, swe_mm, tmin_c, "
                "precip_mm) VALUES ('testhill', ?, ?, ?, ?, ?, ?)",
                (
                    STATION,
                    (START + timedelta(days=i)).isoformat(),
                    row.get("depth"),
                    row.get("swe"),
                    row.get("tmin"),
                    row.get("precip"),
                ),
            )


def add_water(conn: sqlite3.Connection, run_id: int, target: date, **mm: float) -> None:
    issued = f"{target.isoformat()}T03:30:00+00:00"
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs (id, kind, started_at, status) VALUES (?, 'full', ?, 'ok')",
            (run_id, issued),
        )
        for source, (snow, water) in mm.items():
            conn.execute(
                "INSERT INTO forecast_daily (location_id, run_id, issued_at, target_date, source, "
                "snow_cm, water_mm) VALUES ('testhill', ?, ?, ?, ?, ?, ?)",
                (run_id, issued, target.isoformat(), source, snow, water),
            )


def test_depth_leaves_out_bare_and_warm_days_but_the_gauge_scores_them(
    hill: sqlite3.Connection,
) -> None:
    # Day 0: bare ground (2 cm), 20 mm in the gauge, nothing stuck.
    # Day 1: a snowpack, above freezing all day; 10 mm of rain, the depth settles.
    # Day 2: a snowpack, cold; 14 mm caught, 12 cm of new snow.
    # Day 3: the gauge's season total resets (a fault): no water score.
    add_station_days(
        hill,
        [
            {"depth": 2, "tmin": -1, "precip": 100},
            {"depth": 30, "tmin": 1.5, "precip": 120},
            {"depth": 28, "tmin": -4, "precip": 130},
            {"depth": 40, "tmin": -6, "precip": 144},
            {"depth": 40, "tmin": -6, "precip": 0},
        ],
    )
    forecasts = [
        ((14.0, 20.0), (8.0, 16.0)),
        ((0.0, 12.0), (0.0, 10.0)),
        ((10.5, 15.0), (9.0, 12.0)),
        ((0.0, 0.0), (0.0, 0.0)),
    ]
    for i, (cons, gfs) in enumerate(forecasts):
        add_water(
            hill,
            10 + i,
            START + timedelta(days=i),
            cons=cons,
            cons_slr=(cons[0] * 2, cons[1]),
            gfs_seamless=gfs,
        )
    out = verification(hill, make_location(snotel=STATION), settled_ratio=8)
    assert [p.skip for p in out.pairs] == ["bare", "warm", None, None]
    assert (out.skipped_bare, out.skipped_warm) == (1, 1)
    # Depth scored on days 2 and 3 only.
    assert out.n_days == 2
    rows = {r.source: r for r in out.rows}
    assert [r.source for r in out.rows][:3] == ["cons", "cons_slr", "cons_settled"]
    # Settled: 10.5 cm at 7:1 is 15 mm of snow water; at 8:1, 12 cm. Observed 12, 0.
    assert [p.cons_settled_cm for p in out.pairs] == [16.0, 0.0, 12.0, 0.0]
    assert (rows["cons_settled"].n, rows["cons_settled"].bias_cm) == (2, 0.0)
    # Water scored on days 0–2; day 3's reset is no catch.
    assert out.n_water_days == 3
    assert [p.observed_water_mm for p in out.pairs] == [20.0, 10.0, 14.0, None]
    water = {r.source: r for r in out.water_rows}
    assert set(water) == {"cons", "gfs_seamless"}  # cons_slr's water is the consensus's
    # cons: 20−20, 12−10, 15−14 → bias +1, MAE 1; big days (≥ 12.7 mm): 0 and 2.
    assert (water["cons"].n, water["cons"].bias_mm, water["cons"].mae_mm) == (3, 1.0, 1.0)
    assert (water["cons"].hits, water["cons"].misses, water["cons"].false_alarms) == (2, 0, 0)
    # gfs: 16−20, 10−10, 12−14 → bias −2, MAE 2; it missed day 2's big day.
    assert (water["gfs_seamless"].bias_mm, water["gfs_seamless"].misses) == (-2.0, 1)


def test_ready_on_the_gauge_alone(hill: sqlite3.Connection) -> None:
    # Bare ground all along (as at Paradise early in the season): no depth score, but a
    # week of gauge catches makes the scorecard ready.
    add_station_days(hill, [{"depth": 0, "precip": 10.0 * i} for i in range(MIN_DAYS + 1)])
    for i in range(MIN_DAYS):
        add_water(hill, 10 + i, START + timedelta(days=i), cons=(7.0, 10.0))
    out = verification(hill, make_location(snotel=STATION))
    assert out.n_days == 0 and out.rows == []
    assert out.n_water_days == MIN_DAYS and out.ready
    assert out.water_rows[0].mae_mm == 0.0


def test_the_forecast_at_the_station_is_scored_beside_the_mid_band(
    hill: sqlite3.Connection,
) -> None:
    # The mid band sits above the station and forecasts more; the forecast for the
    # station's own spot and elevation is closer.
    add_station_days(
        hill,
        [{"depth": 50 + 10 * i, "tmin": -3, "precip": 100 + 12.0 * i} for i in range(3)],
    )
    for i in range(2):
        add_water(
            hill,
            10 + i,
            START + timedelta(days=i),
            cons=(14.0, 20.0),
            stn_cons=(8.75, 12.0),
        )
    out = verification(hill, make_location(snotel=STATION), settled_ratio=8)
    rows = {r.source: r for r in out.rows}
    # 8.75 cm at 7:1 is 12.5 mm of snow water; settled at 8:1, 10 cm: observed 10, 10.
    assert [r.source for r in out.rows] == ["cons", "cons_settled", "stn_settled"]
    assert (rows["stn_settled"].n, rows["stn_settled"].mae_cm) == (2, 0.0)
    assert rows["cons_settled"].bias_cm == 6.0  # 16 cm settled at mid
    water = {r.source: r for r in out.water_rows}
    assert [r.source for r in out.water_rows] == ["cons", "stn_cons"]
    assert (water["cons"].bias_mm, water["stn_cons"].bias_mm) == (8.0, 0.0)
    assert [(p.stn_settled_cm, p.stn_water_mm) for p in out.pairs] == [(10.0, 12.0)] * 2


def test_column_ratio_is_scored_beside_the_others(hill: sqlite3.Connection) -> None:
    from snowwatch.verify import headline_source
    from tests.helpers import config

    add_obs(hill, [100, 110, 110], [None] * 3)
    for i, (raw, slr, col) in enumerate([(8.0, 12.0, 10.0), (2.0, 3.0, 1.0)]):
        target = START + timedelta(days=i)
        add_forecast(
            hill,
            10 + i,
            f"{target.isoformat()}T03:30:00+00:00",
            target,
            cons=raw,
            cons_slr=slr,
            cons_col=col,
        )
    out = verification(hill, make_location(snotel=STATION), headline="cons_col")
    assert [r.source for r in out.rows][:3] == ["cons", "cons_slr", "cons_col"]
    col = next(r for r in out.rows if r.source == "cons_col")
    assert (col.n, col.bias_cm) == (2, 0.5)  # errors 0, +1
    assert [p.cons_col_cm for p in out.pairs] == [10.0, 1.0]
    assert "cons_col" not in {r.source for r in out.water_rows}
    assert headline_source(config().model_copy(update={"depth_method": "column"})) == "cons_col"
