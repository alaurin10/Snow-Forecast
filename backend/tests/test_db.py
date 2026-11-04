from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from snowwatch.store.db import connect, migrate, table_names

EXPECTED = {
    "locations",
    "jobs",
    "runs",
    "snapshots",
    "ensemble_cache",
    "forecast_daily",
    "obs_daily",
    "obs_hourly",
    "alerts",
    "avalanche",
    "flag_log",
    "catalog_ski_areas",
    "snotel_stations",
    "avy_zones",
    "schema_migrations",
}


def test_migrate_creates_every_table_once(tmp_path: Path) -> None:
    conn = connect(tmp_path / "db.sqlite")
    assert migrate(conn) == ["001_init"]
    assert table_names(conn) >= EXPECTED
    assert migrate(conn) == []


def test_wal_mode_and_foreign_keys(tmp_path: Path) -> None:
    conn = connect(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_readonly_connection_does_not_create_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect(path, readonly=True)
    assert not path.exists()
