"""SQLite connection setup and migrations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open the database in WAL mode. Read-only connections never create the file."""
    if readonly:
        # API requests open their connection in a FastAPI dependency, which can run
        # on a different worker thread from the endpoint. Each connection still
        # serves one request at a time, so cross-thread use is safe here.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending `migrations/NNN_*.sql` files in order. Returns the versions applied."""
    done = applied_migrations(conn)
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in done:
            continue
        conn.executescript(f"BEGIN;\n{path.read_text()}\nCOMMIT;")
        with conn:
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utcnow_iso()),
            )
        applied.append(version)
    return applied


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in rows}
