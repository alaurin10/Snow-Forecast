from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from snowwatch import jobs
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.pipeline import run_all
from snowwatch.store import repo
from snowwatch.store.backup import backup
from tests.helpers import SEED, captured_at, config, fixture_transport


def fetcher(**kw) -> Fetcher:  # type: ignore[no-untyped-def]
    return Fetcher(user_agent="test", transport=fixture_transport(**kw), sleep=lambda s: None)


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def run(conn: sqlite3.Connection, f: Fetcher, **kw):  # type: ignore[no-untyped-def]
    return run_all(conn, f, config(), now=captured_at(), spacing_s=0, sleep=lambda s: None, **kw)


def test_full_run_stores_every_location(seeded: sqlite3.Connection) -> None:
    calls: list[str] = []
    run_id, results = run(seeded, fetcher(log=calls), ensembles=True)
    assert [r.ok for r in results] == [True] * 6
    assert not [c for c in calls if c.startswith("unmatched")]
    status = seeded.execute(
        "SELECT status, api_weight FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert status["status"] == "ok" and status["api_weight"] > 100
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and snap.run_id == run_id
    assert snap.snotel is not None and snap.snotel.name == "Morse Lake"
    n_daily = seeded.execute("SELECT COUNT(*) FROM forecast_daily").fetchone()[0]
    assert n_daily > 500
    assert seeded.execute("SELECT COUNT(*) FROM obs_daily").fetchone()[0] >= 90
    assert seeded.execute("SELECT COUNT(*) FROM ensemble_cache").fetchone()[0] == 18


def test_ensembles_are_reused_between_ensemble_runs(seeded: sqlite3.Connection) -> None:
    run(seeded, fetcher(), ensembles=True)
    calls: list[str] = []
    run(seeded, fetcher(log=calls), ensembles=False)
    assert not [c for c in calls if "/ens_" in c]
    snap = repo.latest_snapshot(seeded, "whistler")
    assert snap is not None and len(snap.ensembles) == 3


def test_stale_cache_is_refetched(seeded: sqlite3.Connection) -> None:
    run(seeded, fetcher(), ensembles=True)
    calls: list[str] = []
    later = captured_at() + timedelta(hours=14)
    run_all(
        seeded,
        fetcher(log=calls),
        config(),
        now=later,
        spacing_s=0,
        ensembles=False,
        sleep=lambda s: None,
    )
    assert len([c for c in calls if "/ens_" in c]) == 18


def test_optional_failures_are_warnings(seeded: sqlite3.Connection) -> None:
    _, results = run(
        seeded, fetcher(fail=("ens_", "upper", "nws_alerts", "snotel")), ensembles=True
    )
    assert all(r.ok for r in results)
    assert any("ens_ecmwf_ifs025" in e for r in results for e in r.errors)
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and snap.ensembles == {} and snap.snotel is None
    status = seeded.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert status == "partial"


def test_failed_location_keeps_last_snapshot(seeded: sqlite3.Connection) -> None:
    first, _ = run(seeded, fetcher(), ensembles=True)
    second, results = run(seeded, fetcher(fail=("crystal/multi",)), ensembles=False)
    by_id = {r.location_id: r for r in results}
    assert not by_id["crystal"].ok and by_id["whistler"].ok
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and snap.run_id == first
    whistler = repo.latest_snapshot(seeded, "whistler")
    assert whistler is not None and whistler.run_id == second


def test_snapshots_are_pruned(seeded: sqlite3.Connection) -> None:
    for _ in range(10):
        run(seeded, fetcher(), only=["sunshine"], ensembles=False)
    n = seeded.execute("SELECT COUNT(*) FROM snapshots WHERE location_id='sunshine'").fetchone()[0]
    assert n == repo.SNAPSHOTS_KEPT


def test_job_queue(seeded: sqlite3.Connection) -> None:
    a = jobs.enqueue(seeded, "pull", "crystal", "me@example.com")
    b = jobs.enqueue(seeded, "pull", "rainy")
    assert jobs.pending(seeded) == 2
    first = jobs.claim_next(seeded)
    assert first is not None and first["id"] == a and first["status"] == "running"
    jobs.finish(seeded, a)
    second = jobs.claim_next(seeded)
    assert second is not None and second["id"] == b
    jobs.finish(seeded, b, error="boom")
    assert jobs.claim_next(seeded) is None
    rows = {r["id"]: r["status"] for r in seeded.execute("SELECT id, status FROM jobs")}
    assert rows == {a: "done", b: "failed"}


def test_backup_keeps_newest(seeded: sqlite3.Connection, tmp_path: Path) -> None:
    from datetime import date

    for day in range(1, 18):
        backup(seeded, tmp_path, today=date(2026, 11, day))
    dbs = sorted(p.name for p in tmp_path.glob("snowwatch-*.db"))
    assert len(dbs) == 14 and dbs[-1] == "snowwatch-20261117.db"
    restored = sqlite3.connect(tmp_path / dbs[-1])
    assert restored.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 6
    assert (tmp_path / "locations-20261117.yaml").read_text().startswith("- id: crystal")
