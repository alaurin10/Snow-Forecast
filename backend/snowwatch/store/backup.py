"""Nightly backups: a consistent copy of the database plus a readable location list."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from snowwatch.locations import service

KEEP = 14


def backup(conn: sqlite3.Connection, backup_dir: Path, *, today: date, keep: int = KEEP) -> Path:
    """`VACUUM INTO` a dated copy, export locations.yaml, keep the newest `keep` of each."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.strftime("%Y%m%d")
    target = backup_dir / f"snowwatch-{stamp}.db"
    target.unlink(missing_ok=True)  # VACUUM INTO refuses to overwrite
    conn.execute("VACUUM INTO ?", (str(target),))
    (backup_dir / f"locations-{stamp}.yaml").write_text(service.export_yaml(conn))
    for pattern in ("snowwatch-*.db", "locations-*.yaml"):
        for old in sorted(backup_dir.glob(pattern))[:-keep]:
            old.unlink()
    return target


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("VACUUM")
