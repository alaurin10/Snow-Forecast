"""Nightly housekeeping for tables that would otherwise grow forever.

- forecast_daily: after 48 h, only runs at least 6 h apart are kept, plus each local
  day's last run (the one the scorecard scores: `verify.py`), so hourly runs (milestone
  4) don't add ~150k rows a day. After two weeks, only the forecasts made up to two days
  ahead are kept (what the scorecard compares with observations); everything goes after
  FORECAST_DAYS. The trend chart only reads the last few days of runs.
- runs, jobs: finished ones older than HISTORY_DAYS go, unless a stored forecast
  still refers to the run.
- flag_log: flags last raised more than HISTORY_DAYS ago.
- push_log: alerted events last seen more than HISTORY_DAYS ago.
- obs_daily: observations older than FORECAST_DAYS.
- ensemble_shadow: comparisons older than HISTORY_DAYS.

Snapshots (newest 24 per location), avalanche forecasts, the raw cache and map
tiles have their own pruning.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FORECAST_DAYS = 400
HISTORY_DAYS = 90
FULL_DETAIL_DAYS = 14
SCORED_LEAD_DAYS = 2
THIN_AFTER_H = 48
THIN_GAP_H = 6


def runs_to_drop(runs: list[tuple[int, datetime]], tz: ZoneInfo, cutoff: datetime) -> list[int]:
    """Of one location's runs (id, issued, in time order), those to drop: issued before
    `cutoff`, less than THIN_GAP_H after the last run kept, and not the last run of
    their local day. Running it again on what's left drops nothing more."""
    drop: list[int] = []
    last_kept: datetime | None = None
    for i, (run_id, issued) in enumerate(runs):
        nxt = runs[i + 1][1] if i + 1 < len(runs) else None
        day_last = nxt is None or nxt.astimezone(tz).date() != issued.astimezone(tz).date()
        spaced = last_kept is None or issued - last_kept >= timedelta(hours=THIN_GAP_H)
        if issued >= cutoff or day_last or spaced:
            last_kept = issued
        else:
            drop.append(run_id)
    return drop


def thin_forecasts(conn: sqlite3.Connection, now: datetime) -> int:
    """Thin forecast_daily's older runs (runs_to_drop). Returns the rows deleted."""
    cutoff = now - timedelta(hours=THIN_AFTER_H)
    zones: dict[str, ZoneInfo] = {}
    for r in conn.execute("SELECT id, tz FROM locations"):
        try:
            zones[r["id"]] = ZoneInfo(r["tz"] or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zones[r["id"]] = ZoneInfo("UTC")
    by_loc: dict[str, list[tuple[int, datetime]]] = {}
    for r in conn.execute(
        "SELECT location_id, run_id, MIN(issued_at) AS issued FROM forecast_daily "
        "GROUP BY location_id, run_id ORDER BY location_id, issued"
    ):
        issued = datetime.fromisoformat(r["issued"])
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=UTC)
        by_loc.setdefault(r["location_id"], []).append((r["run_id"], issued))
    deleted = 0
    for loc_id, runs in by_loc.items():
        for run_id in runs_to_drop(runs, zones.get(loc_id, ZoneInfo("UTC")), cutoff):
            deleted += conn.execute(
                "DELETE FROM forecast_daily WHERE location_id = ? AND run_id = ?",
                (loc_id, run_id),
            ).rowcount
    return deleted


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
            thin_forecasts(conn, now)
            + conn.execute(
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
        out["push_log"] = conn.execute(
            "DELETE FROM push_log WHERE last_seen_at < ?", (history,)
        ).rowcount
        out["api_usage"] = conn.execute(
            "DELETE FROM api_usage WHERE day < ?", (history_day,)
        ).rowcount
        out["ensemble_shadow"] = conn.execute(
            "DELETE FROM ensemble_shadow WHERE at < ?", (history,)
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
