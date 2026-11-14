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


def test_security_headers_and_inline_script_hash(settings: Settings, tmp_path: Path) -> None:
    import base64
    import hashlib

    static = tmp_path / "static"
    (static / "_app" / "immutable").mkdir(parents=True)
    boot = "start({ base: '' });"
    (static / "index.html").write_text(f"<html><script>{boot}</script><script src=x.js></script>")
    (static / "_app" / "immutable" / "a1.js").write_text("js")
    client = TestClient(create_app(settings.model_copy(update={"static_dir": static})))
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(boot.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]
    assert "frame-ancestors 'none'" in csp
    assert "https://tiles.mapterhorn.com" in csp.split("connect-src")[1].split(";")[0]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-cache"
    assert "strict-transport-security" not in r.headers  # dev
    assert "immutable" in client.get("/_app/immutable/a1.js").headers["cache-control"]
    assert client.get("/api/livez").headers["x-frame-options"] == "DENY"


def test_production_hides_api_docs_and_sends_hsts(settings: Settings) -> None:
    dev = TestClient(create_app(settings))
    assert dev.get("/api/docs").status_code == 200
    prod = TestClient(create_app(settings.model_copy(update={"env": "prod"})))
    assert prod.get("/api/docs").status_code == 404
    assert prod.get("/api/openapi.json").status_code == 404
    assert "max-age" in prod.get("/api/livez").headers["strict-transport-security"]


def test_meta_reports_version_and_thresholds(settings: Settings) -> None:
    from snowwatch import __version__

    s = settings.model_copy(update={"git_commit": "abc1234"})
    body = TestClient(create_app(s)).get("/api/meta").json()
    assert body["version"] == __version__ and body["commit"] == "abc1234"
    assert body["powder_cm"] == 15 and body["storm_cm"] == 30
    assert body["open_meteo_daily_budget"] == 10_000
    assert body["hazard_index"] is True
    off = s.model_copy(update={"hazard_index": "off"})
    assert TestClient(create_app(off)).get("/api/meta").json()["hazard_index"] is False


def test_requests_get_an_id(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert len(client.get("/api/livez").headers["x-request-id"]) == 12
    assert (
        client.get("/api/livez", headers={"X-Request-ID": "abc"}).headers["x-request-id"] == "abc"
    )
