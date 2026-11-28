"""Milestone 4, refresh and retention: the model watcher, data-driven runs, the spot
cache's expiry, faster runs and thinner history."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from snowwatch import jobs, modelwatch
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.modelwatch import ModelRun, Planner
from snowwatch.pipeline import RunMemo, run_all
from snowwatch.scheduler import Worker, build_scheduler
from snowwatch.settings import Settings
from snowwatch.store import repo, retention
from snowwatch.store.db import connect
from tests.conftest import make_location
from tests.helpers import SEED, captured_at, config, fixture_transport

T0 = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
US = modelwatch.folders_for(config().models_for("US"))
CA = modelwatch.folders_for(config().models_for("CA"))


def runs(**avail: datetime) -> dict[str, ModelRun]:
    return {f: ModelRun(f, t - timedelta(hours=1), t) for f, t in avail.items()}


# --- the planner, with a fake clock ---------------------------------------------------


def test_folders_follow_each_countrys_models() -> None:
    assert {"ncep_hrrr_conus", "ncep_nbm_conus", "ncep_gfs013", "ecmwf_ifs025"} <= US
    assert "cmc_gem_hrdps" in CA and "ncep_hrrr_conus" not in CA
    assert set(modelwatch.all_folders()) == US | CA
    from snowwatch.checks import MODEL_FOLDERS

    assert set(MODEL_FOLDERS) == US | CA


def test_a_new_run_queues_its_locations_after_the_preload() -> None:
    p = Planner()
    uses = {"crystal": US, "whistler": CA}
    p.last_run = {"crystal": T0 - timedelta(hours=1), "whistler": T0 - timedelta(hours=1)}
    # The first look only records what's there.
    assert p.observe(runs(ncep_hrrr_conus=T0), uses, T0) == []
    assert p.take_due(uses, T0 + timedelta(minutes=10)) == []
    # HRRR's next run: Crystal (US) only, 5 minutes later.
    t = T0 + timedelta(hours=1)
    assert p.observe(runs(ncep_hrrr_conus=t), uses, t) == ["ncep_hrrr_conus"]
    assert p.take_due(uses, t + timedelta(minutes=4)) == []
    assert p.take_due(uses, t + timedelta(minutes=5)) == ["crystal"]
    p.ran(["crystal"], t + timedelta(minutes=5))
    assert p.take_due(uses, t + timedelta(minutes=6)) == []
    # The same run seen again queues nothing.
    assert p.observe(runs(ncep_hrrr_conus=t), uses, t + timedelta(minutes=10)) == []


def test_at_most_one_run_per_40_minutes_and_at_least_one_per_3_hours() -> None:
    p = Planner()
    uses = {"crystal": US, "whistler": CA}
    p.observe(runs(ncep_hrrr_conus=T0, ncep_nbm_conus=T0), uses, T0)
    p.ran(["crystal", "whistler"], T0)
    # NBM lands 10 minutes after the run: held until 40 minutes have passed.
    t = T0 + timedelta(minutes=10)
    p.observe(runs(ncep_nbm_conus=t), uses, t)
    assert p.reasons(["crystal"]) == ["ncep_nbm_conus"]
    assert p.take_due(uses, t + timedelta(minutes=20)) == []
    assert p.next_due(t) == T0 + timedelta(minutes=40)
    assert p.take_due(uses, T0 + timedelta(minutes=40)) == ["crystal"]
    p.ran(["crystal"], T0 + timedelta(minutes=40))
    # No new runs for Canada: Whistler still runs every 3 hours.
    assert p.take_due(uses, T0 + timedelta(hours=2, minutes=59)) == []
    assert "whistler" in p.take_due(uses, T0 + timedelta(hours=3))


def test_a_location_never_run_runs_at_once() -> None:
    assert Planner().take_due(["new"], T0) == ["new"]


def test_read_runs_reads_each_meta_json() -> None:
    def get(url: str) -> Any:
        if "dwd_icon" in url:
            raise RuntimeError("HTTP 503")
        return {"last_run_initialisation_time": 1764590400, "last_run_availability_time": 0}

    got, errors = modelwatch.read_runs(get, ["ecmwf_ifs025", "dwd_icon"])
    assert got["ecmwf_ifs025"].init == datetime(2025, 12, 1, 12, tzinfo=UTC)
    assert got["ecmwf_ifs025"].available is None
    assert "503" in errors["dwd_icon"]


def test_runs_for_labels_each_model_by_its_first_folder() -> None:
    inits = {"ncep_gfs013": "2026-12-01T18:00:00+00:00", "ncep_hrrr_conus": "x"}
    assert modelwatch.runs_for(["gfs_seamless", "icon_seamless", "ncep_hrrr_conus"], inits) == {
        "gfs_seamless": "2026-12-01T18:00:00+00:00",
        "ncep_hrrr_conus": "x",
    }


# --- the worker -----------------------------------------------------------------------


def meta_transport(avail: dict[str, int]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        folder = req.url.path.split("/")[2]
        t = avail.get(folder, 1_764_000_000)
        return httpx.Response(
            200,
            json={"last_run_initialisation_time": t - 3600, "last_run_availability_time": t},
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def local(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", open_meteo_url="http://om:8080")


def test_data_refresh_only_with_a_server(local: Settings, settings: Settings) -> None:
    assert Worker(local, config()).data_refresh
    assert not Worker(settings, config()).data_refresh
    fixed = config().model_copy(
        update={"schedule": config().schedule.model_copy(update={"refresh": "fixed"})}
    )
    assert not Worker(local, fixed).data_refresh
    ids = {j.id for j in build_scheduler(Worker(local, config())).get_jobs()}
    assert {"watch_models", "data_run", "prune_raw"} <= ids
    assert not any(i.startswith("run-") for i in ids)
    ids = {j.id for j in build_scheduler(Worker(settings, config())).get_jobs()}
    assert "watch_models" in ids and "data_run" not in ids and "run-00:30" in ids


def test_watcher_records_runs_and_queues_locations(
    local: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(local.database)
    w = Worker(local, config())
    service.import_yaml(conn, SEED, max_locations=25)
    avail = {"ncep_hrrr_conus": 1_764_590_000}
    monkeypatch.setattr(
        Worker, "_fetcher", lambda self: Fetcher(user_agent="t", transport=meta_transport(avail))
    )
    w.watch_models()
    rows = repo.model_runs(conn)
    assert set(rows) == set(modelwatch.all_folders())
    first = rows["ncep_hrrr_conus"]
    assert first.available_at == "2025-12-01T11:53:20+00:00"
    ran: list[list[str] | None] = []
    monkeypatch.setattr(Worker, "full_run", lambda self, ensembles, only=None: ran.append(only))
    # Every location ran an hour ago: nothing to do until a model moves.
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    w.planner.last_run = {loc.id: hour_ago for loc in service.list_locations(conn)}
    w.data_run()
    assert ran == []
    avail["ncep_hrrr_conus"] += 3600
    w.watch_models()
    assert repo.model_runs(conn)["ncep_hrrr_conus"].changed_at >= first.changed_at
    w.planner.preload_s = 0
    for loc_id in list(w.planner.due):
        w.planner.due[loc_id] = datetime.now(UTC)
    w.data_run()
    us = sorted(loc.id for loc in service.list_locations(conn) if loc.country == "US")
    assert ran and sorted(ran[0] or []) == us


def test_last_runs_seed_the_planner(local: Settings) -> None:
    conn = connect(local.database)
    from snowwatch.store.db import migrate

    migrate(conn)
    service.import_yaml(conn, SEED, max_locations=25)
    f = Fetcher(user_agent="t", transport=fixture_transport(), sleep=lambda s: None)
    run_all(conn, f, config(), now=captured_at(), spacing_s=0, only=["crystal"])
    w = Worker(local, config())
    assert set(w.planner.last_run) == {"crystal"}


# --- faster runs ----------------------------------------------------------------------


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def test_a_pooled_run_matches_a_one_at_a_time_run(seeded: sqlite3.Connection) -> None:
    def run(workers: int) -> dict[str, Any]:
        f = Fetcher(user_agent="t", transport=fixture_transport(), sleep=lambda s: None)
        run_id, results = run_all(
            seeded, f, config(), now=captured_at(), spacing_s=0, workers=workers, ensembles=True
        )
        assert [r.location_id for r in results] == [
            loc.id for loc in service.list_locations(seeded)
        ]
        assert all(r.ok for r in results)
        out = {}
        for loc in service.list_locations(seeded):
            snap = repo.latest_snapshot(seeded, loc.id)
            assert snap is not None and snap.run_id == run_id
            out[loc.id] = snap.model_dump(exclude={"run_id", "generated_at"})
        return out

    assert run(1) == run(4)


def test_snapshots_carry_the_model_runs(seeded: sqlite3.Connection) -> None:
    repo.save_model_runs(
        seeded,
        {
            "ncep_gfs013": ("2026-11-04T18:00:00+00:00", "2026-11-04T21:40:00+00:00"),
            "cmc_gem_hrdps": ("2026-11-04T12:00:00+00:00", "2026-11-04T16:00:00+00:00"),
            "ncep_hrrr_conus": ("2026-11-04T22:00:00+00:00", "2026-11-04T23:10:00+00:00"),
        },
    )
    f = Fetcher(user_agent="t", transport=fixture_transport(), sleep=lambda s: None)
    run_all(seeded, f, config(), now=captured_at(), spacing_s=0, only=["crystal", "whistler"])
    crystal = repo.latest_snapshot(seeded, "crystal")
    whistler = repo.latest_snapshot(seeded, "whistler")
    assert crystal is not None and whistler is not None
    assert crystal.model_runs == {
        "gfs_seamless": "2026-11-04T18:00:00+00:00",
        "ncep_hrrr_conus": "2026-11-04T22:00:00+00:00",
    }
    assert whistler.model_runs == {
        "gfs_seamless": "2026-11-04T18:00:00+00:00",
        "gem_hrdps_continental": "2026-11-04T12:00:00+00:00",
    }


def test_snotel_daily_is_fetched_every_6_hours(seeded: sqlite3.Connection) -> None:
    calls: list[str] = []
    t = [0.0]
    memo = RunMemo(clock=lambda: t[0])

    def run() -> None:
        f = Fetcher(user_agent="t", transport=fixture_transport(log=calls), sleep=lambda s: None)
        res = run_all(
            seeded, f, config(), now=captured_at(), spacing_s=0, only=["crystal"], memo=memo
        )[1]
        assert res[0].ok

    def daily() -> int:
        return sum(c.endswith("snotel_daily") for c in calls)

    def hourly() -> int:
        return sum(c.endswith("snotel_hourly") for c in calls)

    run()
    assert daily() == 1 and hourly() == 1
    t[0] += 3600
    run()
    assert daily() == 1 and hourly() == 2  # hourly values every run
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and snap.snotel is not None  # still there from the memo
    t[0] += 6 * 3600
    run()
    assert daily() == 2


def test_queued_jobs_are_served_between_a_runs_locations(
    seeded: sqlite3.Connection,
) -> None:
    served: list[int] = []
    f = Fetcher(user_agent="t", transport=fixture_transport(), sleep=lambda s: None)
    run_all(
        seeded,
        f,
        config(),
        now=captured_at(),
        spacing_s=0,
        between=lambda: served.append(1),
    )
    assert len(served) == 6


def test_worker_serves_jobs_inside_a_run(local: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    w = Worker(local, config())
    conn = connect(local.database)
    service.upsert_location(conn, make_location(), max_locations=25)
    jobs.enqueue(conn, "lookups", None, "test")
    looked: list[bool] = []
    monkeypatch.setattr(Worker, "refresh_lookups", lambda self, locked=False: looked.append(locked))
    with w.lock:  # as a run holds it
        w.process_jobs()  # the scheduler's own turn waits…
        assert looked == []
        w._jobs_between()  # …the run serves the queue between its locations
    assert looked == [True]


# --- the spot cache expires on the watcher's stamp ------------------------------------


def test_spots_expire_when_their_countrys_models_update() -> None:
    from tests.test_spots import Clock, fake_service

    clock, calls = Clock(), []
    wall = [1_000_000.0]
    stamps: dict[str, float] = {"US": 999_000.0}
    svc = fake_service(clock, calls, stamp=stamps.get, wall=lambda: wall[0])
    svc.get(46.935, -121.475, "v")  # Crystal's fixture: a US snapshot
    clock.t += 2 * 3600  # past cache_minutes, but no model has moved
    wall[0] += 2 * 3600
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 1
    stamps["CA"] = wall[0]  # Canada's models don't concern it
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 1
    stamps["US"] = wall[0] + 60  # a new US run, ready in a minute
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 1
    wall[0] += 61
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 2
    clock.t += 3 * 3600 + 1  # never older than 3 h
    wall[0] += 3 * 3600 + 1
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 3


def test_model_stamps_per_country(local: Settings) -> None:
    from snowwatch.spots import _model_stamps
    from snowwatch.store.db import migrate

    conn = connect(local.database)
    migrate(conn)
    assert _model_stamps(local, config()) == {}
    t = datetime(2026, 12, 1, 12, tzinfo=UTC)
    repo.save_model_runs(conn, {"ncep_hrrr_conus": ("a", "b")}, now=t)
    got = _model_stamps(local, config())
    assert got == {"US": t.timestamp() + modelwatch.PRELOAD_S}


# --- retention ------------------------------------------------------------------------


def test_thinning_keeps_6_hour_runs_and_each_days_last() -> None:
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 12, 1, 0, 30, tzinfo=UTC)  # 30 Nov 16:30 in Seattle
    hourly = [(i, start + timedelta(hours=i)) for i in range(72)]
    cutoff = start + timedelta(hours=48)
    drop = set(retention.runs_to_drop(hourly, tz, cutoff))
    kept = [(i, t) for i, t in hourly if i not in drop]
    assert all(t >= cutoff for i, t in hourly if i >= 48 and i not in drop) and not (
        drop & set(range(48, 72))
    )
    old = [(i, t) for i, t in kept if t < cutoff]
    by_day: dict[Any, int] = {}
    for i, t in hourly:
        by_day[t.astimezone(tz).date()] = i
    day_last = set(by_day.values())
    for (_, a), (j, b) in pairwise(old):
        assert b - a >= timedelta(hours=6) or j in day_last
    # Each local day's last run is kept (the scorecard's run).
    assert not (day_last & drop)
    assert 8 <= len(old) <= 14  # from 48
    # Stable: thinning what's left drops nothing more.
    assert retention.runs_to_drop(kept, tz, cutoff) == []


def test_prune_thins_hourly_forecasts(conn: sqlite3.Connection) -> None:
    from tests.test_retention import add_forecast, add_run

    service.upsert_location(conn, make_location(), max_locations=25)
    now = datetime(2027, 1, 10, 12, tzinfo=UTC)
    first = now - timedelta(days=4)
    for h in range(96):
        t = first + timedelta(hours=h)
        rid = add_run(conn, t)
        add_forecast(conn, rid, t, (t + timedelta(days=1)).date().isoformat())
    before = conn.execute("SELECT COUNT(*) FROM forecast_daily").fetchone()[0]
    out = retention.prune(conn, now=now)
    after = conn.execute("SELECT COUNT(*) FROM forecast_daily").fetchone()[0]
    assert before == 96 and out["forecast_daily"] == before - after
    assert 48 + 6 <= after <= 48 + 14
    assert retention.prune(conn, now=now)["forecast_daily"] == 0


def test_raw_responses_are_kept_6_hours(tmp_path: Path) -> None:
    import os
    import time

    from snowwatch.http import prune_raw

    old, new = tmp_path / "a" / "old.json.gz", tmp_path / "a" / "new.json.gz"
    old.parent.mkdir()
    for p in (old, new):
        p.write_bytes(b"x")
    os.utime(old, (time.time() - 7 * 3600,) * 2)
    os.utime(new, (time.time() - 5 * 3600,) * 2)
    assert prune_raw(tmp_path) == 1 and new.exists()


def test_snapshot_documents_have_model_runs_in_the_schema() -> None:
    from snowwatch.doc import Snapshot

    assert "model_runs" in Snapshot.model_json_schema()["properties"]
    assert (
        json.loads(Snapshot.model_validate_json(_minimal()).model_dump_json())["model_runs"] == {}
    )


def _minimal() -> str:
    from tests.helpers import fixture_snapshot

    d = json.loads(fixture_snapshot("crystal").model_dump_json())
    d.pop("model_runs", None)
    return json.dumps(d)


def test_status_lists_each_models_run(settings: Settings, conn: sqlite3.Connection) -> None:
    from fastapi.testclient import TestClient

    from snowwatch.api.app import create_app

    client = TestClient(create_app(settings))
    body = client.get("/api/status").json()
    assert body["model_runs"] == [] and body["refresh"] == "fixed"
    repo.save_model_runs(
        conn,
        {
            "ncep_gfs013": ("2026-12-01T18:00:00+00:00", "2026-12-01T21:40:00+00:00"),
            "ncep_hrrr_conus": ("2026-12-01T22:00:00+00:00", "2026-12-01T23:05:00+00:00"),
        },
    )
    rows = client.get("/api/status").json()["model_runs"]
    assert [(r["label"], r["init_time"][11:13]) for r in rows] == [("GFS", "18"), ("HRRR", "22")]
    local = settings.model_copy(update={"open_meteo_url": "http://om:8080"})
    assert TestClient(create_app(local)).get("/api/status").json()["refresh"] == "data"
