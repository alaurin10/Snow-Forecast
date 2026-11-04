from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from snowwatch.api.app import create_app
from snowwatch.settings import Settings


def add_run(conn: sqlite3.Connection, finished: datetime, status: str = "ok") -> None:
    with conn:
        conn.execute(
            "INSERT INTO runs (kind, started_at, finished_at, status) VALUES ('full', ?, ?, ?)",
            (finished.isoformat(), finished.isoformat(), status),
        )


def test_health_without_database_is_503(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "no_data"
    assert client.get("/api/livez").json() == {"ok": True}


def test_health_ok_then_stale(settings: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(settings))
    add_run(conn, datetime.now(UTC) - timedelta(hours=13))
    assert client.get("/api/health").json()["status"] == "stale"
    add_run(conn, datetime.now(UTC) - timedelta(minutes=5), status="partial")
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_failed_runs_do_not_count(settings: Settings, conn: sqlite3.Connection) -> None:
    add_run(conn, datetime.now(UTC), status="failed")
    assert TestClient(create_app(settings)).get("/api/health").status_code == 503


def test_spa_fallback_and_static_files(settings: Settings, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (static / "assets" / "app.js").write_text("js")
    client = TestClient(create_app(settings.model_copy(update={"static_dir": static})))
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/location/crystal").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "js"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/../secret").text == "<html>app</html>"
