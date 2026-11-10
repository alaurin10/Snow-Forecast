"""Nightly housekeeping for tables that would otherwise grow forever.

- forecast_daily: after two weeks, only the forecasts made up to two days ahead are
  kept (what the scorecard compares with observations); everything goes after
  FORECAST_DAYS. The trend chart only reads the last few days of runs.
- runs, jobs: finished ones older than HISTORY_DAYS go, unless a stored forecast
  still refers to the run.
- flag_log: flags last raised more than HISTORY_DAYS ago.
- obs_daily: observations older than FORECAST_DAYS.

Snapshots (newest 8 per location), avalanche forecasts, the raw cache and map
tiles have their own pruning.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

FORECAST_DAYS = 400
HISTORY_DAYS = 90
FULL_DETAIL_DAYS = 14
SCORED_LEAD_DAYS = 2


def prune(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict[str, int]:
    """Delete old rows. Returns how many went from each table."""
    now = now or datetime.now(UTC)
    detail = (now - timedelta(days=FULL_DETAIL_DAYS)).isoformat(timespec="seconds")
    history = (now - timedelta(days=HISTORY_DAYS)).isoformat(timespec="seconds")
    oldest_day = (now - timedelta(days=FORECAST_DAYS)).date().isoformat()
    history_day = (now - timedelta(days=HISTORY_DAYS)).date().isoformat()
    out: dict[str, int] = {}
    with conn:
        out["forecast_daily"] = (
            conn.execute(
                "DELETE FROM forecast_daily WHERE issued_at < ? "
                "AND target_date > date(issued_at, ?)",
                (detail, f"+{SCORED_LEAD_DAYS} days"),
            ).rowcount
            + conn.execute(
                "DELETE FROM forecast_daily WHERE target_date < ?", (oldest_day,)
            ).rowcount
        )
        out["obs_daily"] = conn.execute(
            "DELETE FROM obs_daily WHERE date < ?", (oldest_day,)
        ).rowcount
        # Avalanche alerts are keyed by date and use run 0; other flags by run.
        first_recent_run = conn.execute(
            "SELECT MIN(id) FROM runs WHERE started_at >= ?", (history,)
        ).fetchone()[0]
        out["flag_log"] = conn.execute(
            "DELETE FROM flag_log WHERE (type = 'avalanche_danger' AND key < ?) "
            "OR (type != 'avalanche_danger' AND last_run < ?)",
            (history_day, first_recent_run or 0),
        ).rowcount
        out["jobs"] = conn.execute(
            "DELETE FROM jobs WHERE status IN ('done', 'failed') AND created_at < ?", (history,)
        ).rowcount
        out["runs"] = conn.execute(
            "DELETE FROM runs WHERE status != 'running' AND started_at < ? "
            "AND NOT EXISTS (SELECT 1 FROM snapshots s WHERE s.run_id = runs.id) "
            "AND NOT EXISTS (SELECT 1 FROM forecast_daily f WHERE f.run_id = runs.id)",
            (history,),
        ).rowcount
    return out


def recover_interrupted(conn: sqlite3.Connection) -> tuple[int, int]:
    """At worker start: runs and jobs left `running` by a crash or restart are marked
    failed (a job that keeps crashing the worker must not be retried forever; the owner
    can press Refresh). Returns (runs, jobs) fixed."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with conn:
        runs = conn.execute(
            "UPDATE runs SET status = 'failed', finished_at = ?, "
            "errors_json = '[\"interrupted: the worker stopped during this run\"]' "
            "WHERE status = 'running'",
            (stamp,),
        ).rowcount
        jobs = conn.execute(
            "UPDATE jobs SET status = 'failed', finished_at = ?, "
            "error = 'interrupted: the worker restarted; try again' WHERE status = 'running'",
            (stamp,),
        ).rowcount
    return runs, jobs
