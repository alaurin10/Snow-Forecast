"""Retention keeps the tables bounded without losing what the app still reads."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from snowwatch.locations import service
from snowwatch.store import retention
from tests.conftest import make_location

NOW = datetime(2027, 6, 1, 12, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def add_run(conn: sqlite3.Connection, started: datetime, status: str = "ok") -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (kind, started_at, finished_at, status) VALUES ('full', ?, ?, ?)",
            (iso(started), iso(started), status),
        )
    return int(cur.lastrowid or 0)


def add_forecast(conn: sqlite3.Connection, run_id: int, issued: datetime, target: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO forecast_daily (location_id, run_id, issued_at, target_date, source, "
            "snow_cm) VALUES ('testhill', ?, ?, ?, 'cons', 1.0)",
            (run_id, iso(issued), target),
        )


def test_prune_keeps_what_the_scorecard_and_trend_need(conn: sqlite3.Connection) -> None:
    service.upsert_location(conn, make_location(), max_locations=25)
    old = NOW - timedelta(days=30)
    old_run = add_run(conn, old)
    add_forecast(conn, old_run, old, "2027-05-02")  # 1 day ahead: scored, kept
    add_forecast(conn, old_run, old, "2027-05-09")  # 8 days ahead: dropped
    recent = NOW - timedelta(days=2)
    new_run = add_run(conn, recent)
    add_forecast(conn, new_run, recent, "2027-06-08")  # recent: all detail kept
    ancient = NOW - timedelta(days=500)
    gone_run = add_run(conn, ancient)
    add_forecast(conn, gone_run, ancient, (ancient + timedelta(days=1)).date().isoformat())
    stuck = add_run(conn, ancient, status="running")

    out = retention.prune(conn, now=NOW)

    targets = {r[0] for r in conn.execute("SELECT target_date FROM forecast_daily")}
    assert targets == {"2027-05-02", "2027-06-08"}
    runs = {r[0] for r in conn.execute("SELECT id FROM runs")}
    assert runs == {old_run, new_run, stuck}  # referenced, or still running
    assert out["forecast_daily"] == 2 and out["runs"] == 1


def test_prune_old_jobs_and_flags(conn: sqlite3.Connection) -> None:
    service.upsert_location(conn, make_location(), max_locations=25)
    recent_run = add_run(conn, NOW - timedelta(days=1))
    old_day = (NOW - timedelta(days=120)).date().isoformat()
    with conn:
        conn.executemany(
            "INSERT INTO flag_log (location_id, type, key, first_run, last_run) "
            "VALUES ('testhill', ?, ?, ?, ?)",
            [
                ("powder_day", "a", 0, 0),  # last raised before any recent run
                ("powder_day", "b", recent_run, recent_run),
                ("avalanche_danger", old_day, 0, 0),
                ("avalanche_danger", NOW.date().isoformat(), 0, 0),  # today: keep
            ],
        )
        conn.execute(
            "INSERT INTO jobs (kind, created_at, status) VALUES ('pull', ?, 'done')",
            (iso(NOW - timedelta(days=200)),),
        )
    out = retention.prune(conn, now=NOW)
    keys = {r[0] for r in conn.execute("SELECT key FROM flag_log")}
    assert keys == {"b", NOW.date().isoformat()}
    assert out["jobs"] == 1


def test_recover_interrupted_runs_and_jobs(conn: sqlite3.Connection) -> None:
    run = add_run(conn, NOW, status="running")
    with conn:
        conn.execute(
            "INSERT INTO jobs (kind, created_at, status) VALUES ('pull', ?, 'running')", (iso(NOW),)
        )
    assert retention.recover_interrupted(conn) == (1, 1)
    status = conn.execute("SELECT status FROM runs WHERE id = ?", (run,)).fetchone()[0]
    assert status == "failed"
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "failed"
