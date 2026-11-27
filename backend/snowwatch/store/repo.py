"""Reads and writes for runs, snapshots, the ensemble cache and history tables."""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from snowwatch.analysis.build import DailyRecord
from snowwatch.doc import Snapshot, Snotel
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


def save_obs(conn: sqlite3.Connection, location_id: str, snotel: Snotel) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO obs_daily "
            "(location_id, station, date, depth_cm, swe_mm, tmin_c, tmax_c, precip_mm) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    location_id,
                    snotel.triplet,
                    d.date,
                    d.depth_cm,
                    d.swe_mm,
                    d.tmin_c,
                    d.tmax_c,
                    d.precip_mm,
                )
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
        "elevation": None if row["elev_m"] is None else row["elev_m"] / 0.3048,
        "latitude": row["lat"],
        "longitude": row["lon"],
    }


def save_station_rows(conn: sqlite3.Connection, rows: Iterable[Mapping[str, Any]]) -> int:
    """Stations already in table shape: triplet, name, state, lat, lon, elev_m."""
    now = utcnow_iso()
    values = [
        (r["triplet"], r["name"], r.get("state"), r["lat"], r["lon"], r.get("elev_m"), now)
        for r in rows
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO snotel_stations "
            "(triplet, name, state, lat, lon, elev_m, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            values,
        )
    return len(values)


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


def record_flags(
    conn: sqlite3.Connection, location_id: str, run_id: int, flags: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], int]:
    """Log this run's flags (type, key) and return when each was first raised.

    A flag that was missing from the location's previous run counts as raised
    again now, so it reads as new (and would alert) when it comes back.
    """
    prev = conn.execute(
        "SELECT MAX(run_id) FROM snapshots WHERE location_id = ? AND run_id < ?",
        (location_id, run_id),
    ).fetchone()[0]
    out: dict[tuple[str, str], int] = {}
    with conn:
        for ftype, key in flags:
            row = conn.execute(
                "SELECT first_run, last_run FROM flag_log "
                "WHERE location_id = ? AND type = ? AND key = ?",
                (location_id, ftype, key),
            ).fetchone()
            if row is None or prev is None or row["last_run"] < prev:
                first = run_id
            else:
                first = row["first_run"]
            conn.execute(
                "INSERT INTO flag_log (location_id, type, key, first_run, last_run) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (location_id, type, key) DO UPDATE SET "
                "first_run = excluded.first_run, last_run = excluded.last_run",
                (location_id, ftype, key, first, run_id),
            )
            out[(ftype, key)] = first
    return out


def save_source_status(conn: sqlite3.Connection, stats: Mapping[str, Any]) -> None:
    """Fold a fetcher's per-source counts (`http.SourceStat`) into `source_status`."""
    today = utcnow_iso()[:10]
    with conn:
        for source, st in stats.items():
            row = conn.execute("SELECT * FROM source_status WHERE source = ?", (source,)).fetchone()
            same_day = row is not None and row["day"] == today
            conn.execute(
                "INSERT OR REPLACE INTO source_status (source, last_ok_at, last_error_at, "
                "last_error, day, calls_today, errors_today, weight_today) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source,
                    st.last_ok_at or (row["last_ok_at"] if row else None),
                    st.last_error_at or (row["last_error_at"] if row else None),
                    st.last_error or (row["last_error"] if row else None),
                    today,
                    (row["calls_today"] if same_day else 0) + st.ok + st.errors,
                    (row["errors_today"] if same_day else 0) + st.errors,
                    round((row["weight_today"] if same_day else 0.0) + st.weight, 2),
                ),
            )


LOCAL_HOST = "local"  # the self-hosted Open-Meteo server's row (http.LOCAL_HOST)


def utc_day(now: datetime | None = None) -> str:
    """The usage ledger's day: the UTC date, when the public daily limit resets."""
    return (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()


def add_usage(
    conn: sqlite3.Connection,
    day: str,
    host: str,
    weight: float,
    requests: int,
    *,
    fallbacks: int = 0,
    seconds: float = 0.0,
) -> None:
    """Add requests to one host's row for the day."""
    with conn:
        conn.execute(
            "INSERT INTO api_usage (day, host, weight, requests, fallbacks, seconds) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (day, host) DO UPDATE SET "
            "weight = weight + excluded.weight, requests = requests + excluded.requests, "
            "fallbacks = fallbacks + excluded.fallbacks, seconds = seconds + excluded.seconds",
            (day, host, round(weight, 2), requests, fallbacks, round(seconds, 3)),
        )


@dataclass
class Usage:
    """One day of Open-Meteo requests from the ledger."""

    public_weight: float = 0.0
    public_requests: int = 0
    fallbacks: int = 0
    local_requests: int = 0
    local_seconds: float = 0.0
    by_host: dict[str, float] = field(default_factory=dict)  # public weight per host

    @property
    def local_latency_s(self) -> float | None:
        return self.local_seconds / self.local_requests if self.local_requests else None


def usage_today(conn: sqlite3.Connection, now: datetime | None = None) -> Usage:
    """Today's (UTC) Open-Meteo use, public and self-hosted."""
    out = Usage()
    rows = conn.execute("SELECT * FROM api_usage WHERE day = ?", (utc_day(now),))
    for r in rows:
        if r["host"] == LOCAL_HOST:
            out.local_requests += r["requests"]
            out.local_seconds += r["seconds"]
            continue
        out.public_weight = round(out.public_weight + r["weight"], 2)
        out.public_requests += r["requests"]
        out.fallbacks += r["fallbacks"]
        out.by_host[r["host"]] = r["weight"]
    return out


def record_usage(conn: sqlite3.Connection, fetcher: Any, now: datetime | None = None) -> None:
    """Add a fetcher's Open-Meteo requests since it last recorded (`Fetcher.take_usage`)."""
    day = utc_day(now)
    for host, u in fetcher.take_usage().items():
        add_usage(conn, day, host, u.weight, u.requests, fallbacks=u.fallbacks, seconds=u.seconds)
