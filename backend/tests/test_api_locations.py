from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from snowwatch.api.app import create_app
from snowwatch.http import Fetcher
from snowwatch.inputs import load_responses
from snowwatch.locations import service
from snowwatch.pipeline import run_location
from snowwatch.settings import Settings
from snowwatch.store import repo
from tests.helpers import FIXTURES, SEED, captured_at, config


@pytest.fixture
def client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    service.import_yaml(conn, SEED, max_locations=25)
    fetcher = Fetcher(user_agent="t")
    for i in range(2):  # two runs, so the trend has history
        run_id = repo.start_run(conn, "test")
        for loc in service.list_locations(conn):
            if loc.id == "sunshine":
                continue  # never pulled
            res = run_location(
                conn,
                loc,
                fetcher,
                config(),
                run_id=run_id,
                now=captured_at() + timedelta(hours=6 * i),
                ensembles=False,
                responses=load_responses(FIXTURES / loc.id),
            )
            assert res.ok
        repo.finish_run(conn, run_id, "ok", [], 0)
    return TestClient(
        create_app(settings.model_copy(update={"static_dir": settings.data_dir / "none"}))
    )


def test_location_list(client: TestClient) -> None:
    r = client.get("/api/locations")
    assert r.status_code == 200 and "max-age=300" in r.headers["cache-control"]
    items = r.json()
    assert [i["id"] for i in items] == [
        "crystal",
        "snoqualmie",
        "rainy",
        "whistler",
        "revelstoke",
        "sunshine",
    ]
    whistler = items[3]
    assert whistler["run_id"] == 2 and whistler["next5_cm"] > 10
    assert [b["band"] for b in whistler["bands"]] == ["base", "mid", "summit"]
    assert items[5]["run_id"] is None and items[5]["next5_cm"] is None


def test_snapshot_is_sent_gzipped_with_etag(client: TestClient) -> None:
    r = client.get("/api/locations/whistler", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["etag"] == '"2"'
    assert r.headers["content-encoding"] == "gzip"
    doc = r.json()  # httpx decodes gzip
    assert doc["location"]["id"] == "whistler" and len(doc["bands"]) == 3
    assert (
        client.get("/api/locations/whistler", headers={"If-None-Match": '"2"'}).status_code == 304
    )


def test_snapshot_without_gzip(client: TestClient) -> None:
    r = client.get("/api/locations/crystal", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers
    assert json.loads(r.content)["run_id"] == 2
    assert len(gzip.compress(r.content)) < 60 * 1024


def test_missing_snapshot_and_unknown_location(client: TestClient) -> None:
    assert client.get("/api/locations/sunshine").status_code == 404
    assert client.get("/api/locations/nowhere").status_code == 404
    assert client.get("/api/locations/nowhere/trend").status_code == 404


def test_trend(client: TestClient) -> None:
    t = client.get("/api/locations/rainy/trend").json()
    assert [r["run_id"] for r in t["runs"]] == [1, 2]
    first = t["runs"][0]
    assert first["daily"] and first["next5_cm"] is not None
    assert first["next5_cm"] == pytest.approx(
        sum(v for d, v in sorted(first["daily"].items())[:5]), abs=0.2
    )


def test_runs(client: TestClient) -> None:
    runs = client.get("/api/runs?limit=5").json()
    assert [r["id"] for r in runs] == [2, 1] and runs[0]["status"] == "ok"


def test_no_database_is_503(settings: Settings) -> None:
    c = TestClient(
        create_app(settings.model_copy(update={"static_dir": settings.data_dir / "none"}))
    )
    assert c.get("/api/locations").status_code == 503


def test_schema_command(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from snowwatch.cli import main

    out = tmp_path / "schema.json"
    assert main(["schema", "--out", str(out)]) == 0
    schema = json.loads(out.read_text())
    assert {"Snapshot", "LocationSummary", "TrendOut", "PeriodOut"} <= set(schema["$defs"])


def test_overview_rows(client: TestClient) -> None:
    rows = client.get("/api/overview").json()
    assert [r["id"] for r in rows][:2] == ["crystal", "snoqualmie"]
    whistler = next(r for r in rows if r["id"] == "whistler")
    assert len(whistler["periods"]) == 20 and whistler["periods"][0]["key"]
    assert whistler["next5_cm"] > 10 and whistler["run_id"] == 2
    crystal = next(r for r in rows if r["id"] == "crystal")
    assert crystal["snow_depth_cm"] is not None  # SNOTEL Morse Lake
    sunshine = next(r for r in rows if r["id"] == "sunshine")
    assert sunshine["run_id"] is None and sunshine["periods"] == []


def test_map_wind_has_every_window(client: TestClient) -> None:
    out = client.get("/api/map/wind").json()
    assert out["min_snow_cm"] == 2 and out["min_wind_kmh"] == 15
    assert out["locations"]
    for loc in out["locations"]:
        assert {"past48", "next24", "next72"} <= {r["window"] for r in loc["roses"]}
        assert -90 < loc["lat"] < 90 and loc["generated_at"]
        assert all(len(r["sectors"]) == 8 for r in loc["roses"])
        assert {f["type"] for f in loc["flags"]} <= {"rapid_warming", "rain_on_snow"}


def test_overview_cache_follows_new_runs(
    client: TestClient, settings: Settings, conn: sqlite3.Connection
) -> None:
    from snowwatch.api import public

    client.get("/api/overview")
    assert public._snapshots["rainy"][0] == 2
    run_id = repo.start_run(conn, "test")
    loc = service.get_location(conn, "rainy")
    assert loc is not None
    run_location(
        conn,
        loc,
        Fetcher(user_agent="t"),
        config(),
        run_id=run_id,
        now=captured_at(),
        ensembles=False,
        responses=load_responses(FIXTURES / "rainy"),
    )
    repo.finish_run(conn, run_id, "ok", [], 0)
    rainy = next(r for r in client.get("/api/overview").json() if r["id"] == "rainy")
    assert rainy["run_id"] == 3 and public._snapshots["rainy"][0] == 3


def test_health_reports_run_details(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["last_run"]["errors"] == 0 and "api_weight" in body["last_run"]


def test_avalanche_endpoint_applies_expiry(client: TestClient, conn: sqlite3.Connection) -> None:
    from snowwatch.avalanche import AvalancheDoc, AvyDay, save

    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("America/Los_Angeles")).date()
    current = AvalancheDoc(
        provider="nac",
        center="Northwest Avalanche Center",
        center_id="NWAC",
        zone="West Slopes South",
        link="https://nwac.us",
        issued_at=(now - timedelta(hours=2)).isoformat(timespec="minutes"),
        expires_at=(now + timedelta(hours=10)).isoformat(timespec="minutes"),
        days=[
            AvyDay(date=today.isoformat(), alpine=3, treeline=2, below=1),
            AvyDay(date=(today + timedelta(days=1)).isoformat(), alpine=2, treeline=2, below=1),
        ],
    )
    save(conn, "crystal", current)
    expired = current.model_copy(
        update={"expires_at": (now - timedelta(minutes=1)).isoformat(timespec="minutes")}
    )
    save(conn, "rainy", expired)
    r = client.get("/api/avalanche")
    assert r.status_code == 200
    body = r.json()
    assert body["crystal"]["status"] == "current" and body["crystal"]["today_max"] == 3
    assert body["rainy"]["status"] == "expired" and body["rainy"]["doc"]["days"] == []
    assert body["whistler"]["status"] == "none"

    rows = {row["id"]: row for row in client.get("/api/overview").json()}
    assert rows["crystal"]["danger"] == {"level": 3, "status": "current"}
    assert rows["rainy"]["danger"] == {"level": None, "status": "expired"}

    plan = client.get("/api/plan").json()
    by_id = {row["id"]: row for row in plan["rows"]}
    if plan["date"] == today.isoformat():
        assert by_id["crystal"]["danger"] == {"level": 3, "status": "current"}
    else:
        assert by_id["crystal"]["danger"]["status"] in ("current", "not_issued")


def test_plan_a_day(client: TestClient) -> None:
    r = client.get("/api/plan")
    assert r.status_code == 200
    plan = r.json()
    assert len(plan["dates"]) == 10 and plan["date"] == plan["dates"][0]["date"]
    rows = {row["id"]: row for row in plan["rows"]}
    assert rows["sunshine"]["day"] is None  # never pulled
    assert rows["crystal"]["day"]["rating"] in ("Powder", "Great", "Good", "Fair", "Poor")
    assert rows["rainy"]["day"]["rating"] is None  # tours are never rated
    second = plan["dates"][1]["date"]
    assert client.get(f"/api/plan?date={second}").json()["date"] == second
    assert client.get("/api/plan?date=1999-01-01").status_code == 400


def test_overview_best_day(client: TestClient) -> None:
    rows = {row["id"]: row for row in client.get("/api/overview").json()}
    best = rows["whistler"]["best_day"]
    assert best is not None and best["score"] >= 3
    assert rows["rainy"]["best_day"] is None
    assert all(
        d in [p["date"] for p in rows["whistler"]["periods"]]
        for d in rows["whistler"]["powder_dates"]
    )


def test_overview_has_coordinates_and_flags(client: TestClient, conn: sqlite3.Connection) -> None:
    from snowwatch.avalanche import AvalancheDoc, AvyDay, save

    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    save(
        conn,
        "rainy",
        AvalancheDoc(
            provider="nac",
            center="NWAC",
            center_id="NWAC",
            zone="East Slopes North",
            link=None,
            issued_at=None,
            expires_at=(now + timedelta(hours=6)).isoformat(timespec="minutes"),
            days=[AvyDay(date=today, alpine=4, treeline=3, below=2)],
        ),
    )
    rows = {r["id"]: r for r in client.get("/api/overview").json()}
    assert rows["crystal"]["lat"] and rows["crystal"]["lon"]
    assert rows["whistler"]["flags"], "the fixture has a powder day at Whistler"
    rainy = rows["rainy"]["flags"]
    assert rainy[0]["type"] == "avalanche_danger" and rainy[0]["value"] == 4


def test_status_page(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert body["budget"] == 10_000 and len(body["runs"]) >= 2
    ages = {a["id"]: a for a in body["locations"]}
    assert ages["crystal"]["generated_at"] and ages["sunshine"]["generated_at"] is None
    assert isinstance(body["sources"], list)


def test_verification_endpoint(client: TestClient) -> None:
    body = client.get("/api/locations/crystal/verification").json()
    assert body["station"] == "642:WA:SNTL" and body["needs_days"] >= 1
    assert client.get("/api/locations/nope/verification").status_code == 404
