"""Flags (plan 4.7): each rule against a real snapshot nudged to trigger it."""

from __future__ import annotations

import sqlite3

import pytest

from snowwatch.analysis.flags import FlagConfig, avalanche_flag, compute_flags, flag_key
from snowwatch.doc import Alert, Snapshot
from snowwatch.store import repo
from tests.helpers import fixture_snapshot

CFG = FlagConfig()


def snap(loc: str = "crystal") -> Snapshot:
    s = fixture_snapshot(loc).model_copy(deep=True)
    s.alerts = []
    return s


def types(s: Snapshot, chances: list[float | None] | None = None) -> dict[str, list[object]]:
    out: dict[str, list[object]] = {}
    for f in compute_flags(s, CFG, chances or []):
        out.setdefault(f.type, []).append(f)
    return out


def test_powder_day_needs_six_inches_not_heavy() -> None:
    s = snap()
    d = s.days[2]
    d.overnight_cm, d.day_cm, d.quality = 10, 6, "Light"
    found = types(s)["powder_day"]
    assert [f.date for f in found] == [d.date]  # type: ignore[attr-defined]
    d.quality = "Heavy & wet"
    assert "powder_day" not in types(s)


def test_storm_from_consensus_or_ensemble_chance() -> None:
    s = snap()
    for p in s.bands[1].periods[:10]:
        p.snow_cm = 0
    assert "storm_incoming" not in types(s)
    for p in s.bands[1].periods[3:7]:
        p.snow_cm = 9
    (storm,) = types(s)["storm_incoming"]
    assert storm.period_key == s.bands[1].periods[3].key and storm.value == 36  # type: ignore[attr-defined]
    for p in s.bands[1].periods[:10]:
        p.snow_cm = 0
    (by_chance,) = types(s, [None, 0.5])["storm_incoming"]
    assert by_chance.value2 == 50  # type: ignore[attr-defined]


def test_big_storm_is_a_warning() -> None:
    s = snap()
    for p in s.bands[1].periods[:4]:
        p.snow_cm = 15
    assert types(s)["storm_incoming"][0].severity == "warning"  # type: ignore[attr-defined]


def test_model_outlier() -> None:
    s = snap()
    day = s.daily[9]
    assert day.pooled_cum is not None
    day.pooled_cum.p90 = 10
    day.models_cum = {"gfs_seamless": 40.0, "ecmwf_ifs025": 12.0}
    (f,) = types(s)["model_outlier"]
    assert f.model == "gfs_seamless"  # type: ignore[attr-defined]


def test_low_confidence() -> None:
    s = snap()
    e = s.bands[1].windows["next5"].ens
    assert e is not None
    e.p10, e.p50, e.p90 = 0, 2, 20
    assert "low_confidence" in types(s)
    e.p10, e.p50, e.p90 = 8, 10, 14
    assert "low_confidence" not in types(s)


def test_rain_on_snow_needs_snow_on_the_ground() -> None:
    s = snap()
    assert s.backcountry is not None
    s.bands[1].periods[1].rain_mm = 12
    s.backcountry.warming.rain_on_snow_mm = 12
    assert "rain_on_snow" in types(s)
    s.backcountry.warming.rain_on_snow_mm = None
    assert "rain_on_snow" not in types(s)


def test_snow_level_crossings() -> None:
    s = snap()
    h = s.bands[1].hourly
    base, mid = s.bands[0].elev_m, s.bands[1].elev_m
    h.snow_level_m = [base + 200] * 10 + [base - 100] * (len(h.t) - 10)
    (low,) = types(s)["snow_level_crossing"]
    assert low.detail == "below_base"  # type: ignore[attr-defined]
    h.snow_level_m = [mid - 50] * 5 + [mid + 300] * (len(h.t) - 5)
    details = {f.detail for f in types(s)["snow_level_crossing"]}  # type: ignore[attr-defined]
    assert "above_mid" in details


def test_wind_hold_and_best_day_are_for_resorts() -> None:
    s = snap()
    s.days[1].gust_max_kmh = 80
    got = types(s)
    assert got["wind_hold"][0].date == s.days[1].date  # type: ignore[attr-defined]
    assert "best_day" in got
    tour = snap("rainy")
    tour.days[1].gust_max_kmh = 80
    assert "wind_hold" not in types(tour) and "best_day" not in types(tour)


def test_wind_loading() -> None:
    s = snap("rainy")
    assert s.ridge is not None
    top = s.bands[2].hourly
    top.snow_cm = [0.6] * len(top.t)  # 14 cm a day
    s.ridge.kmh = [45.0] * len(s.ridge.kmh)
    (f,) = types(s)["wind_loading"]
    assert f.value2 == 45  # type: ignore[attr-defined]
    s.ridge.kmh = [20.0] * len(s.ridge.kmh)
    assert "wind_loading" not in types(s)


def test_rapid_warming_and_refreeze() -> None:
    s = snap()
    bc = s.backcountry
    assert bc is not None
    bc.warming.fl_rise_m, bc.warming.temp_rise_c = 1200, 3
    assert "rapid_warming" in types(s)
    bc.warming.fl_rise_m, bc.warming.temp_rise_c = 200, 2
    assert "rapid_warming" not in types(s)
    night = next(n for n in bc.refreeze if n.band == "mid")
    night.status = "Good"
    day = next(p for p in s.bands[1].periods if p.kind == "day" and p.date == night.date)
    day.tmax_c = 9
    assert types(s)["refreeze"][0].date == night.date  # type: ignore[attr-defined]


def test_nws_alerts_are_warnings_first() -> None:
    s = snap()
    s.alerts = [
        Alert(
            event="Winter Storm Warning",
            headline=None,
            severity=None,
            onset=None,
            ends=None,
            url=None,
        )
    ]
    flags = compute_flags(s, CFG)
    assert flags[0].type == "nws_alert" and flags[0].severity == "warning"


def test_avalanche_flag_only_for_high_danger() -> None:
    assert avalanche_flag(3, None) is None
    f = avalanche_flag(4, "2026-12-01")
    assert f is not None and f.severity == "warning"


def test_flag_log_marks_first_run_and_reraises(conn: sqlite3.Connection) -> None:
    from snowwatch.locations import service
    from tests.conftest import make_location

    service.upsert_location(conn, make_location(), max_locations=25)
    loc = make_location().id

    def add_run(run_id: int) -> None:
        with conn:
            conn.execute(
                "INSERT INTO runs (id, kind, started_at, status) VALUES (?, 'full', 'x', 'ok')",
                (run_id,),
            )
            conn.execute(
                "INSERT INTO snapshots (location_id, run_id, created_at, doc_gz) "
                "VALUES (?, ?, 'x', x'00')",
                (loc, run_id),
            )

    key = ("powder_day", "2026-12-05")
    add_run(1)
    assert repo.record_flags(conn, loc, 2, [key]) == {key: 2}
    add_run(2)
    assert repo.record_flags(conn, loc, 3, [key]) == {key: 2}  # still the same flag
    add_run(3)
    add_run(4)  # run 4 had no such flag
    assert repo.record_flags(conn, loc, 5, [key]) == {key: 5}  # back again: new


@pytest.mark.parametrize("loc", ["crystal", "whistler", "rainy"])
def test_flag_keys_are_stable(loc: str) -> None:
    flags = fixture_snapshot(loc).flags
    keys = [(f.type, flag_key(f)) for f in flags]
    assert len(keys) == len(set(keys))
