"""A small job queue in SQLite: the API queues work, the worker claims it."""

from __future__ import annotations

import sqlite3
from typing import Any

from snowwatch.store.db import utcnow_iso


def enqueue(
    conn: sqlite3.Connection,
    kind: str,
    location_id: str | None = None,
    requested_by: str | None = None,
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, location_id, requested_by, created_at) VALUES (?, ?, ?, ?)",
            (kind, location_id, requested_by, utcnow_iso()),
        )
    return int(cur.lastrowid or 0)


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Atomically mark the oldest queued job as running and return it."""
    with conn:
        row = conn.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ("
            "  SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
            ") AND status = 'queued' RETURNING *",
            (utcnow_iso(),),
        ).fetchone()
    return dict(row) if row else None


def finish(conn: sqlite3.Connection, job_id: int, *, error: str | None = None) -> None:
    with conn:
        conn.execute(
            "UPDATE jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            ("failed" if error else "done", utcnow_iso(), error, job_id),
        )


def pending(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'").fetchone()[0])
