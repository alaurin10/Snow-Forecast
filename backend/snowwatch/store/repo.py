"""Reads and writes for runs, snapshots, the ensemble cache and history tables."""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from snowwatch.analysis.build import DailyRecord
from snowwatch.doc import Alert, Snapshot, Snotel
from snowwatch.store.db import utcnow_iso

SNAPSHOTS_KEPT = 8


def _gz(data: Any) -> bytes:
    return gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)


def _ungz(blob: bytes) -> Any:
    return json.loads(gzip.decompress(blob))


def start_run(conn: sqlite3.Connection, kind: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (kind, started_at, status) VALUES (?, ?, 'running')",
            (kind, utcnow_iso()),
        )
    return int(cur.lastrowid or 0)


def finish_run(
    conn: sqlite3.Connection, run_id: int, status: str, errors: list[str], weight: float
) -> None:
    with conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, errors_json = ?, api_weight = ? "
            "WHERE id = ?",
            (utcnow_iso(), status, json.dumps(errors), round(weight, 2), run_id),
        )


def recent_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) | {"errors": json.loads(r["errors_json"])} for r in rows]


def save_snapshot(conn: sqlite3.Connection, location_id: str, run_id: int, snap: Snapshot) -> int:
    """Store the document and keep the newest SNAPSHOTS_KEPT. Returns the gzipped size."""
    blob = gzip.compress(snap.model_dump_json().encode(), mtime=0)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (location_id, run_id, created_at, doc_gz) "
            "VALUES (?, ?, ?, ?)",
            (location_id, run_id, utcnow_iso(), blob),
        )
        conn.execute(
            "DELETE FROM snapshots WHERE location_id = ? AND run_id NOT IN "
            "(SELECT run_id FROM snapshots WHERE location_id = ? ORDER BY run_id DESC LIMIT ?)",
            (location_id, location_id, SNAPSHOTS_KEPT),
        )
    return len(blob)


def latest_snapshot(conn: sqlite3.Connection, location_id: str) -> Snapshot | None:
    row = conn.execute(
        "SELECT doc_gz FROM snapshots WHERE location_id = ? ORDER BY run_id DESC LIMIT 1",
        (location_id,),
    ).fetchone()
    return Snapshot.model_validate_json(gzip.decompress(row["doc_gz"])) if row else None


def put_ensemble(
    conn: sqlite3.Connection, location_id: str, system: str, data: Any, fetched_at: str
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO ensemble_cache (location_id, system, fetched_at, doc_gz) "
            "VALUES (?, ?, ?, ?)",
            (location_id, system, fetched_at, _gz(data)),
        )


def cached_ensembles(
    conn: sqlite3.Connection, location_id: str, *, now: datetime, max_age_h: float
) -> dict[str, Any]:
    """Ensemble responses no older than max_age_h, by system."""
    cutoff = (now - timedelta(hours=max_age_h)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT system, doc_gz FROM ensemble_cache WHERE location_id = ? AND fetched_at >= ?",
        (location_id, cutoff),
    )
    return {r["system"]: _ungz(r["doc_gz"]) for r in rows}


def save_daily(
    conn: sqlite3.Connection,
    location_id: str,
    run_id: int,
    issued_at: str,
    records: Iterable[DailyRecord],
) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO forecast_daily "
            "(location_id, run_id, issued_at, target_date, source, snow_cm, water_mm) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (location_id, run_id, issued_at, r.target_date, r.source, r.snow_cm, r.water_mm)
                for r in records
            ],
        )


def save_alerts(
    conn: sqlite3.Connection, location_id: str, run_id: int, alerts: Iterable[Alert]
) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO alerts (location_id, run_id, event, headline, severity, onset, ends, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (location_id, run_id, a.event, a.headline, a.severity, a.onset, a.ends, a.url)
                for a in alerts
            ],
        )


def save_obs(conn: sqlite3.Connection, location_id: str, snotel: Snotel) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO obs_daily "
            "(location_id, station, date, depth_cm, swe_mm, tmin_c, tmax_c, precip_mm) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
            [
                (location_id, snotel.triplet, d.date, d.depth_cm, d.swe_mm, d.precip_mm)
                for d in snotel.daily
            ],
        )


def station_meta(conn: sqlite3.Connection, triplet: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM snotel_stations WHERE triplet = ?", (triplet,)).fetchone()
    if row is None:
        return None
    return {
        "stationTriplet": row["triplet"],
        "name": row["name"],
        "elevation": row["elev_m"] / 0.3048,
    }


def save_stations(conn: sqlite3.Connection, stations: Iterable[Mapping[str, Any]]) -> int:
    rows = [
        (
            s["stationTriplet"],
            s.get("name") or s["stationTriplet"],
            s.get("stateCode"),
            s.get("latitude"),
            s.get("longitude"),
            None if s.get("elevation") is None else float(s["elevation"]) * 0.3048,
            utcnow_iso(),
        )
        for s in stations
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO snotel_stations "
            "(triplet, name, state, lat, lon, elev_m, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)
