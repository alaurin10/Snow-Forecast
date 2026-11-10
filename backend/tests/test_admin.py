"""Owner sign-in, lookups, auto-detect and the Manage API."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from snowwatch import jobs
from snowwatch.api.app import create_app
from snowwatch.api.auth import COOKIE, logout_all
from snowwatch.api.ratelimit import LoginThrottle
from snowwatch.capture import load_fixture
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.lookups import catalog_rows, save_catalog, save_zones, zone_rows
from snowwatch.settings import Settings
from snowwatch.store import repo
from tests.helpers import FIXTURES, SEED

PASSWORD = "correct horse battery"
H = {"Origin": "http://testserver"}


def fake_upstream(req: httpx.Request) -> httpx.Response:
    """Elevation, timezone and NWS /points, as the live services answer."""
    url = str(req.url)
    if "/v1/elevation" in url:
        n = len(req.url.params["latitude"].split(","))
        return httpx.Response(200, json={"elevation": [1500.0, 2100.0, 1800.0][:n]})
    if "/v1/forecast" in url:
        return httpx.Response(200, json={"timezone": "America/Los_Angeles"})
    if "api.weather.gov/points" in url:
        lat = float(req.url.path.split("/")[-1].split(",")[0])
        if lat > 49:
            return httpx.Response(404, json={"title": "Invalid point"})
        return httpx.Response(
            200,
            json={
                "properties": {
                    "cwa": "SEW",
                    "radarStation": "KATX",
                    "relativeLocation": {"properties": {"city": "Mazama", "state": "WA"}},
                }
            },
        )
    return httpx.Response(404)


@pytest.fixture
def app_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "owner_password": PASSWORD,
            "static_dir": settings.data_dir / "none",
        }
    )


@pytest.fixture
def client(app_settings: Settings, conn: sqlite3.Connection) -> TestClient:
    service.import_yaml(conn, SEED, max_locations=25)
    # Lookups from the captured responses, plus a tiny ski-area catalog.
    repo.save_stations(conn, load_fixture(FIXTURES / "shared" / "snotel_stations_WA.json.gz"))
    save_zones(
        conn,
        zone_rows(
            load_fixture(FIXTURES / "shared" / "avalanche_us_map_layer.json.gz"),
            load_fixture(FIXTURES / "shared" / "avalanche_ca_areas.json.gz"),
        ),
        ["nac", "avcan"],
    )
    save_catalog(conn, catalog_rows(CATALOG["features"]))
    app = create_app(app_settings)
    app.state.make_fetcher = lambda: Fetcher(
        user_agent="t", transport=httpx.MockTransport(fake_upstream), sleep=lambda s: None
    )
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 200
    return c


def guest(client: TestClient) -> TestClient:
    """Another browser on the same app, not signed in."""
    return TestClient(client.app)


CATALOG = {
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-121.40, 46.85]},
            "properties": {
                "id": "ski-1",
                "name": "Testpeak Ski Area",
                "status": "operating",
                "activities": ["downhill"],
                "places": [
                    {
                        "iso3166_1Alpha2": "US",
                        "iso3166_2": "US-WA",
                        "localized": {"en": {"region": "Washington"}},
                    }
                ],
                "statistics": {"minElevation": 1400, "maxElevation": 2050},
                "websites": ["https://testpeak.example"],
            },
        },
        {  # not downhill: skipped
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-121.0, 47.0]},
            "properties": {
                "id": "x",
                "name": "Nordic Only",
                "status": "operating",
                "activities": ["nordic"],
                "places": [{"iso3166_1Alpha2": "US"}],
            },
        },
        {  # outside US/CA: skipped
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [7.0, 46.0]},
            "properties": {
                "id": "y",
                "name": "Alpine Resort",
                "status": "operating",
                "activities": ["downhill"],
                "places": [{"iso3166_1Alpha2": "CH"}],
            },
        },
    ]
}


def test_me_and_roles(client: TestClient) -> None:
    assert client.get("/api/me").json() == {"is_owner": True, "owner_login_enabled": True}
    other = guest(client)
    assert other.get("/api/me").json() == {"is_owner": False, "owner_login_enabled": True}
    assert other.get("/api/admin/locations").status_code == 401
    assert other.post("/api/admin/lookups/refresh", headers=H).status_code == 401


def test_login_sets_a_strict_http_only_cookie(client: TestClient) -> None:
    other = guest(client)
    r = other.post("/api/auth/login", json={"password": PASSWORD}, headers=H)
    cookie = r.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert "secure" not in cookie  # ENV=dev; prod adds Secure


def test_wrong_password_and_lockout(client: TestClient) -> None:
    other = guest(client)
    for _ in range(LoginThrottle.FREE_TRIES):
        r = other.post("/api/auth/login", json={"password": "nope"}, headers=H)
        assert r.status_code == 401
    r = other.post("/api/auth/login", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert other.get("/api/me").json()["is_owner"] is False


def test_logout_ends_the_session(client: TestClient) -> None:
    token = client.cookies.get(COOKIE)
    assert client.post("/api/auth/logout", headers=H).json()["is_owner"] is False
    replay = guest(client)
    replay.cookies.set(COOKIE, token or "", path="/api")
    assert replay.get("/api/admin/locations").status_code == 401


def test_logout_all_and_expiry(client: TestClient, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE owner_sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    assert client.get("/api/me").json()["is_owner"] is False
    assert logout_all(conn) == 1


def test_cross_site_requests_are_refused(client: TestClient) -> None:
    assert client.post("/api/admin/lookups/refresh").status_code == 403  # no Origin
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/admin/lookups/refresh", headers=evil).status_code == 403
    assert client.get("/api/admin/locations").status_code == 200  # reads need no Origin
    r = guest(client).post("/api/auth/login", json={"password": PASSWORD}, headers=evil)
    assert r.status_code == 403


def test_owner_sign_in_off_without_a_long_password(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    for pw in ("", "short"):
        s = settings.model_copy(
            update={"owner_password": pw, "static_dir": settings.data_dir / "x"}
        )
        c = TestClient(create_app(s))
        assert c.get("/api/me").json() == {"is_owner": False, "owner_login_enabled": False}
        assert c.post("/api/auth/login", json={"password": pw or "x"}, headers=H).status_code == 404


def test_catalog_search_and_lookup_counts(client: TestClient) -> None:
    hits = client.get("/api/admin/catalog/search?q=testpeak", headers=H).json()
    assert [h["name"] for h in hits] == ["Testpeak Ski Area"]
    assert client.get(
        "/api/admin/catalog/search?q=ski%20testpeak", headers=H
    ).json()  # any word order
    assert not client.get("/api/admin/catalog/search?q=nordic", headers=H).json()  # not downhill
    counts = client.get("/api/admin/lookups", headers=H).json()
    assert counts["ski_areas"] == 1 and counts["snotel_stations"] == 79 and counts["avy_zones"] > 90


def test_resolve_resort_from_catalog(client: TestClient) -> None:
    body = {
        "kind": "resort",
        "catalog_id": "ski-1",
        "pins": [{"band": "mid", "lat": 46.85, "lon": -121.40}],
    }
    r = client.post("/api/admin/locations/resolve", json=body, headers=H).json()
    assert r["id"] == "testpeak-ski-area" and r["country"] == "US" and r["region"] == "Washington"
    assert [b["elev_m"] for b in r["bands"]] == [1400, 1790, 2050]  # mid = base + 60% of vertical
    assert r["nws_office"] == "SEW" and r["tz"] == "America/Los_Angeles"
    assert r["avy"]["provider"] == "nac" and r["avy"]["center_id"] == "NWAC"
    assert r["links"]["Resort website"] == "https://testpeak.example"
    assert r["warnings"] == []


def test_resolve_backcountry_pins(client: TestClient) -> None:
    body = {
        "kind": "backcountry",
        "name": "Maple Loop",
        "pins": [
            {"band": "base", "lat": 48.518, "lon": -120.735},
            {"band": "summit", "lat": 48.53, "lon": -120.75},
        ],
    }
    r = client.post("/api/admin/locations/resolve", json=body, headers=H).json()
    assert [b["label"] for b in r["bands"]] == ["Trailhead", "Mid", "High point"]
    assert [b["elev_m"] for b in r["bands"]] == [1500, 1860, 2100]
    assert r["bands"][2]["lat"] == 48.53  # each band keeps its own pin
    # Distance and height both count: Rainy Pass station, at the trailhead, beats
    # Harts Pass, which is closer in height but about 20 km away.
    assert r["snotel"] == "711:WA:SNTL"
    assert len(r["snotel_candidates"]) == 3
    assert r["avy"]["zone_id"] == "3029"  # NWAC East Slopes North
    assert r["region"] == f"{r['avy_name']}, WA"


def test_resolve_canada(client: TestClient) -> None:
    body = {
        "kind": "resort",
        "name": "North Hill",
        "pins": [{"band": "mid", "lat": 50.06, "lon": -122.95, "elev_m": 1800}],
    }
    r = client.post("/api/admin/locations/resolve", json=body, headers=H).json()
    assert r["country"] == "CA" and r["nws_office"] is None and r["snotel_candidates"] == []
    assert r["avy"]["provider"] == "avcan"


def test_resolve_warns_when_nws_is_down(client: TestClient) -> None:
    def nws_down(req: httpx.Request) -> httpx.Response:
        if "api.weather.gov" in str(req.url):
            return httpx.Response(503)
        return fake_upstream(req)

    client.app.state.make_fetcher = lambda: Fetcher(  # type: ignore[attr-defined]
        user_agent="t", transport=httpx.MockTransport(nws_down), sleep=lambda s: None, tries=1
    )
    body = {
        "kind": "resort",
        "name": "South Hill",
        "pins": [{"band": "mid", "lat": 46.85, "lon": -121.4, "elev_m": 1800}],
    }
    r = client.post("/api/admin/locations/resolve", json=body, headers=H).json()
    assert any("National Weather Service" in w for w in r["warnings"])


def test_create_update_archive_and_jobs(client: TestClient, conn: sqlite3.Connection) -> None:
    body = {
        "kind": "resort",
        "catalog_id": "ski-1",
        "pins": [{"band": "mid", "lat": 46.85, "lon": -121.40}],
    }
    draft = client.post("/api/admin/locations/resolve", json=body, headers=H).json()
    loc = {
        k: draft[k]
        for k in (
            "id",
            "name",
            "kind",
            "region",
            "country",
            "tz",
            "bands",
            "snotel",
            "nws_office",
            "radar_station",
            "avy",
            "links",
        )
    }
    r = client.post("/api/admin/locations", json=loc, headers=H)
    assert r.status_code == 201 and r.json()["job_id"]
    job = client.get(f"/api/admin/jobs/{r.json()['job_id']}", headers=H).json()
    assert (
        job["kind"] == "pull"
        and job["location_id"] == "testpeak-ski-area"
        and job["status"] == "queued"
    )
    assert client.post("/api/admin/locations", json=loc, headers=H).status_code == 409

    loc["name"] = "Testpeak"
    r = client.put("/api/admin/locations/testpeak-ski-area", json=loc, headers=H)
    assert r.status_code == 200 and r.json()["job_id"] is None  # name only: no re-pull
    loc["active"] = False
    client.put("/api/admin/locations/testpeak-ski-area", json=loc, headers=H)
    ids = [x["id"] for x in client.get("/api/admin/locations", headers=H).json()]
    assert "testpeak-ski-area" in ids
    assert "testpeak-ski-area" not in [x["id"] for x in client.get("/api/locations").json()]

    assert client.post("/api/admin/locations/crystal/refresh", headers=H).json()["kind"] == "pull"
    assert client.delete("/api/admin/locations/crystal", headers=H).json() == {"ok": True}
    assert service.get_location(conn, "crystal") is not None  # archived, not deleted
    assert "crystal" not in [x["id"] for x in client.get("/api/admin/locations", headers=H).json()]


def test_reorder_and_budget(client: TestClient) -> None:
    order = ["sunshine", "crystal", "snoqualmie", "rainy", "whistler", "revelstoke"]
    assert client.put("/api/admin/locations/order", json=order, headers=H).json() == {"ok": True}
    assert [x["id"] for x in client.get("/api/locations").json()] == order
    b = client.get("/api/admin/budget", headers=H).json()
    assert b["active"] == 6 and b["max_locations"] == 25 and 600 < b["total"] < 1200


def test_location_cap(client: TestClient, app_settings: Settings, conn: sqlite3.Connection) -> None:
    app = client.app
    app.state.settings = app_settings.model_copy(update={"max_locations": 6})  # type: ignore[attr-defined]
    loc = json.loads(service.get_location(conn, "crystal").model_dump_json())  # type: ignore[union-attr]
    loc["id"] = "crystal-two"
    r = client.post("/api/admin/locations", json=loc, headers=H)
    assert r.status_code == 409 and "at most 6" in r.json()["detail"]


def test_lookups_job_is_queued(client: TestClient, conn: sqlite3.Connection) -> None:
    j = client.post("/api/admin/lookups/refresh", headers=H).json()
    assert j["kind"] == "lookups" and jobs.pending(conn) == 1


def test_catalog_rows_use_polygon_centroids() -> None:
    feat = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-121.0, 47.0], [-121.2, 47.0], [-121.2, 47.2], [-121.0, 47.2], [-121.0, 47.0]]
            ],
        },
        "properties": {
            "id": "p",
            "name": "Poly",
            "status": "operating",
            "activities": ["downhill"],
            "places": [
                {"iso3166_1Alpha2": "CA", "localized": {"en": {"region": "British Columbia"}}}
            ],
        },
    }
    (row,) = catalog_rows([feat])
    assert row[2] == "CA" and row[3] == "British Columbia"
    assert row[4] == pytest.approx(47.1) and row[5] == pytest.approx(-121.1)


def test_catalog_query_normalises_names(conn: sqlite3.Connection) -> None:
    from snowwatch.api.admin import catalog_query

    names = [
        "Mt Baker",
        "Mt. Hood Meadows Ski Resort",
        "Mount Bachelor",
        "Saint-Sauveur",
        "Big Sky Resort",
    ]
    with conn:
        conn.executemany(
            "INSERT INTO catalog_ski_areas (id, name, lat, lon, updated_at) "
            "VALUES (?, ?, 0, 0, '')",
            [(str(i), n) for i, n in enumerate(names)],
        )

    def find(q: str) -> list[str]:
        where, params = catalog_query(q)
        return [
            r[0]
            for r in conn.execute(
                f"SELECT name FROM catalog_ski_areas WHERE {where} ORDER BY name", params
            )
        ]

    assert find("Mt. Baker") == ["Mt Baker"]
    assert find("mount hood") == ["Mt. Hood Meadows Ski Resort"]
    assert find("mt bachelor") == ["Mount Bachelor"]
    assert find("st sauveur") == ["Saint-Sauveur"]
    assert find("sky big") == ["Big Sky Resort"]


def test_webcams_round_trip(client: TestClient, conn: sqlite3.Connection) -> None:
    loc = client.get("/api/admin/locations", headers=H).json()[0]
    loc["webcams"] = [
        {
            "name": "Summit",
            "url": "https://example.com/cams",
            "image_url": "https://example.com/c.jpg",
        },
        {"name": "Base", "url": "https://example.com/base"},
    ]
    assert client.put(f"/api/admin/locations/{loc['id']}", json=loc, headers=H).status_code == 200
    saved = service.get_location(conn, loc["id"])
    assert saved is not None and [w.name for w in saved.webcams] == ["Summit", "Base"]
    assert saved.webcams[1].image_url is None
    assert "image_url: https://example.com/c.jpg" in service.export_yaml(conn)
    loc["webcams"] = [{"name": "Bad", "url": "javascript:alert(1)"}]
    assert client.put(f"/api/admin/locations/{loc['id']}", json=loc, headers=H).status_code == 422


def test_a_tiny_catalog_answer_never_wipes_the_stored_one(conn: sqlite3.Connection) -> None:
    from snowwatch.lookups import SuspiciousUpdateError

    save_catalog(conn, catalog_rows(CATALOG["features"]))
    with pytest.raises(SuspiciousUpdateError):
        save_catalog(conn, [])
    assert conn.execute("SELECT COUNT(*) FROM catalog_ski_areas").fetchone()[0] > 0


def test_lookup_refresh_parts_fail_on_their_own(conn: sqlite3.Connection) -> None:
    from snowwatch.lookups import refresh

    def answer(req: httpx.Request) -> httpx.Response:
        if "avalanche.org" in str(req.url):
            return httpx.Response(200, json=["not", "a", "layer"])  # reshaped
        return httpx.Response(503)

    f = Fetcher(
        user_agent="t", transport=httpx.MockTransport(answer), sleep=lambda s: None, tries=1
    )
    out = refresh(conn, f)
    assert all(str(v).startswith("failed") for v in out.values()), out
