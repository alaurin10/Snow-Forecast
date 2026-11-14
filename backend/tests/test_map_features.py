"""The map's snow stations, field reports and ATES files (docs/MAP-PLAN.md, B7.4, B7.5, B9)."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from snowwatch import observations, overlays, stations
from snowwatch.api.app import create_app
from snowwatch.http import Fetcher
from snowwatch.settings import Settings

BOX = (31.0, -134.0, 57.0, -102.0)
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)

# --- snow stations ------------------------------------------------------------------

SNOTEL_META = [
    {
        "stationTriplet": "908:WA:SNTL",
        "stationId": "908",
        "name": "Olallie Meadows",
        "elevation": 4010.0,
        "latitude": 47.37,
        "longitude": -121.44,
        "dataTimeZone": -8.0,
    },
    # Outside the box.
    {"stationTriplet": "1:AK:SNTL", "latitude": 61.0, "longitude": -149.0, "dataTimeZone": -9},
    # Silent for days: left off.
    {"stationTriplet": "2:WA:SNTL", "latitude": 47.0, "longitude": -121.0, "dataTimeZone": -8},
]


def awdb(trip: str, values: list[tuple[str, float | None]]) -> dict[str, Any]:
    return {
        "stationTriplet": trip,
        "data": [
            {
                "stationElement": {"elementCode": "SNWD"},
                "values": [{"date": d, "value": v} for d, v in values],
            }
        ],
    }


def hourly() -> list[dict[str, Any]]:
    # Local standard time (UTC-8): 09:00 is 17:00 UTC.
    start = datetime(2026, 11, 10, 0, 0)
    vals: list[tuple[str, float | None]] = []
    for h in range(0, 58):
        t = start + timedelta(hours=h)
        depth = 10.0 if t < datetime(2026, 11, 11, 12) else 16.0
        vals.append((t.strftime("%Y-%m-%d %H:%M"), depth))
    vals.append(("2026-11-12 10:00", -3.0))  # a fault: ignored
    return [
        awdb("908:WA:SNTL", vals),
        awdb("2:WA:SNTL", [("2026-11-01 00:00", 5.0)]),
    ]


def daily() -> list[dict[str, Any]]:
    return [awdb("908:WA:SNTL", [(f"2026-11-{d:02d}", float(d)) for d in range(4, 12)])]


BC_WFS = {
    "features": [
        {
            "properties": {
                "LOCATION_ID": "3A25P",
                "LOCATION_NAME": "Squamish River Upper",
                "STATUS": "Active",
                "LATITUDE": 50.14,
                "LONGITUDE": -123.43,
                "ELEVATION": 1340,
            }
        },
        {
            "properties": {
                "LOCATION_ID": "OLD",
                "STATUS": "Inactive",
                "LATITUDE": 50,
                "LONGITUDE": -1,
            }
        },
    ]
}


def bc_csv() -> str:
    rows = ["DATE(UTC),3A25P Squamish River Upper,9Z99P Not In List"]
    t = datetime(2026, 11, 4, 0, 0)
    while t <= datetime(2026, 11, 12, 17, 0):
        depth = 20 + (t - datetime(2026, 11, 4)).days
        rows.append(f"{t:%Y-%m-%d %H:%M},{depth},5")
        t += timedelta(hours=1)
    return "\n".join(rows) + "\n"


def station_transport(fail: set[str] | None = None) -> httpx.MockTransport:
    fail = fail or set()

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "wcc.sc.egov.usda.gov" in url:
            if "snotel" in fail:
                return httpx.Response(500)
            if "/stations" in url:
                return httpx.Response(200, json=SNOTEL_META)
            duration = req.url.params["duration"]
            assert req.url.params["stationTriplets"] == "*:*:SNTL"
            return httpx.Response(200, json=hourly() if duration == "HOURLY" else daily())
        if "openmaps.gov.bc.ca" in url:
            return httpx.Response(500) if "bc" in fail else httpx.Response(200, json=BC_WFS)
        if url.endswith("/SD.csv"):
            return httpx.Response(200, text=bc_csv(), headers={"content-type": "text/csv"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_stations_refresh_reads_both_networks(tmp_path: Path) -> None:
    path = tmp_path / "stations.json"
    with Fetcher(user_agent="t", transport=station_transport(), tries=1) as f:
        out = stations.refresh(path, f, BOX, NOW)
    assert out.errors == []
    by = {s.id: s for s in out.stations}
    assert set(by) == {"908:WA:SNTL", "3A25P:BC:ASWS"}
    s = by["908:WA:SNTL"]
    assert s.network == "snotel" and s.name == "Olallie Meadows" and s.elev_m == 1222
    # The newest good reading, 09:00 local, is 17:00 UTC; the fault after it is skipped.
    assert s.obs_time == "2026-11-12T17:00+00:00"
    assert s.depth_cm == pytest.approx(16 * 2.54, abs=0.1)
    assert s.change24_cm == pytest.approx(6 * 2.54, abs=0.1)
    assert [d.date for d in s.daily] == [f"2026-11-{d:02d}" for d in range(4, 12)]
    assert s.url == "https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=908"
    bc = by["3A25P:BC:ASWS"]
    assert bc.network == "bc" and bc.elev_m == 1340 and bc.depth_cm == 28
    assert bc.change24_cm == 1
    # A week of local-midnight readings, ending today.
    assert len(bc.daily) == stations.DAYS and bc.daily[-1].date == "2026-11-12"
    assert bc.daily[-1].depth_cm == 28
    assert stations.read(path) == out


def test_stations_keep_a_failed_networks_old_stations(tmp_path: Path) -> None:
    path = tmp_path / "stations.json"
    with Fetcher(user_agent="t", transport=station_transport(), tries=1) as f:
        stations.refresh(path, f, BOX, NOW)
    with Fetcher(user_agent="t", transport=station_transport({"snotel"}), tries=1) as f:
        out = stations.refresh(path, f, BOX, NOW + timedelta(hours=1))
    assert [e.split(":")[0] for e in out.errors] == ["snotel"]
    assert {s.network for s in out.stations} == {"snotel", "bc"}
    with Fetcher(user_agent="t", transport=station_transport({"snotel", "bc"}), tries=1) as f:
        out = stations.refresh(tmp_path / "new.json", f, BOX, NOW)
    assert out.stations == [] and len(out.errors) == 2


# --- field reports ------------------------------------------------------------------


def min_item(i: int, lat: float, lon: float, when: str, **counts: int) -> dict[str, Any]:
    return {
        "id": f"0000000{i}-1b77-11f1-9993-0a58a9feac02",
        "userID": "auth0|someone",
        "username": "A Person",
        "title": f"Report {i}",
        "datetime": when,
        "location": {"latitude": lat, "longitude": lon},
        "region": "Purcells",
        "observations": {"avalanche": 0, "incident": 0, "quick": 1, "snowpack": 0} | counts,
        "imageCount": 2,
    }


def min_transport(pages: list[list[dict[str, Any]]], status: int = 200) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.avalanche.ca"
        assert req.url.params["fromdate"] == "2026-10-29"
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        page = int(req.url.params["page"])
        return httpx.Response(
            200,
            json={"items": {"data": pages[page - 1]}, "page": page, "totalPages": len(pages)},
        )

    return httpx.MockTransport(handler)


def test_observations_keep_reports_in_the_box_without_names(tmp_path: Path) -> None:
    pages = [
        [
            min_item(1, 51.3, -117.1, "2026-11-10T05:00:00.000Z", avalanche=1),
            min_item(2, 60.0, -135.5, "2026-11-11T05:00:00.000Z"),  # Yukon: outside
            {"id": "bad"},
        ],
        [
            min_item(3, 50.1, -122.9, "2026-11-11T19:00:00.000Z", snowpack=2),
            min_item(1, 51.3, -117.1, "2026-11-10T05:00:00.000Z", avalanche=1),  # repeated
            min_item(4, 50.1, -122.9, "2026-10-01T19:00:00.000Z"),  # too old
        ],
    ]
    path = tmp_path / "obs.geojson"
    with Fetcher(user_agent="t", transport=min_transport(pages), tries=1) as f:
        out = observations.refresh(path, f, BOX, 14, NOW)
    props = [x.properties for x in out.features]
    assert [p.title for p in props] == ["Report 3", "Report 1"]
    assert props[0].kinds == ["snowpack", "quick"] and props[1].kinds == ["avalanche", "quick"]
    assert props[0].time == "2026-11-11T19:00+00:00"
    assert props[0].url == (
        "https://avalanche.ca/mountain-information-network/submissions/"
        "00000003-1b77-11f1-9993-0a58a9feac02"
    )
    text = path.read_text()
    assert "A Person" not in text and "auth0" not in text
    # The network failing keeps the file as it was.
    with Fetcher(user_agent="t", transport=min_transport([], status=500), tries=1) as f:
        again = observations.refresh(path, f, BOX, 14, NOW)
    assert len(again.features) == 2 and again.errors
    assert json.loads(path.read_text())["features"][0]["properties"]["title"] == "Report 3"


def test_observations_days_are_capped(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["fromdate"])
        return httpx.Response(200, json={"items": {"data": []}, "totalPages": 0})

    with Fetcher(user_agent="t", transport=httpx.MockTransport(handler), tries=1) as f:
        out = observations.refresh(tmp_path / "o.geojson", f, BOX, 90, NOW)
    assert out.days == 30 and seen == ["2026-10-13"]


# --- ATES files ---------------------------------------------------------------------

KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<StyleMap id="ates_complex"><Pair><styleUrl>#s1</styleUrl></Pair></StyleMap>
<Placemark><name>Upper bowl</name>
  <ExtendedData><Data name="ATES_Rating"><value>Challenging</value></Data></ExtendedData>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>
    -117.1,51.1,0 -117.0,51.1,0 -117.0,51.2,0 -117.1,51.2,0 -117.1,51.1,0
  </coordinates></LinearRing></outerBoundaryIs>
  <innerBoundaryIs><LinearRing><coordinates>
    -117.06,51.14 -117.04,51.14 -117.04,51.16 -117.06,51.14
  </coordinates></LinearRing></innerBoundaryIs></Polygon>
</Placemark>
<Placemark><name>Couloir</name><styleUrl>#ates_complex</styleUrl>
  <MultiGeometry>
    <LineString><coordinates>-117.2,51.0 -117.21,51.01</coordinates></LineString>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      -117.3,51.0 -117.2,51.0 -117.2,51.1 -117.3,51.0
    </coordinates></LinearRing></outerBoundaryIs></Polygon>
  </MultiGeometry>
</Placemark>
<Placemark><name>Hut</name><Point><coordinates>-117.0,51.0</coordinates></Point></Placemark>
<Placemark><name>Mystery</name><description>ask the guide</description>
  <LineString><coordinates>-117.4,51.0 -117.41,51.01 bad,coord</coordinates></LineString>
</Placemark>
</Document></kml>"""


def kmz(kml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", kml)
        z.writestr("files/icon.png", b"png")
    return buf.getvalue()


def test_ates_ratings_from_kml_and_kmz() -> None:
    for name, data in (("area.kml", KML), ("area.kmz", kmz(KML))):
        feats = overlays.read_file(name, data)
        got = [(f.properties.name, f.properties.rating, f.geometry["type"]) for f in feats]
        assert got == [
            ("Upper bowl", "challenging", "Polygon"),
            ("Couloir", "complex", "LineString"),
            ("Couloir", "complex", "Polygon"),
            ("Mystery", "unrated", "LineString"),
        ]
        assert len(feats[0].geometry["coordinates"]) == 2  # with its hole
        assert feats[0].properties.file == name


def test_ates_ratings_from_geojson_and_words() -> None:
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "A", "ates_class": 3},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[-117, 51], [-116.9, 51], [-116.9, 51.1], [-117, 51]]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"Name": "B", "notes": "Simple terrain, mostly trees"},
                "geometry": {"type": "LineString", "coordinates": [[-117, 51], [-117.01, 51.01]]},
            },
            {"type": "Feature", "properties": None, "geometry": {"type": "Point"}},
        ],
    }
    feats = overlays.read_file("x.geojson", json.dumps(gj).encode())
    assert [(f.properties.name, f.properties.rating) for f in feats] == [
        ("A", "complex"),
        ("B", "simple"),
    ]
    assert overlays.rating_of(["Non-avalanche terrain"]) == "non"
    assert overlays.rating_of(["ATES 4"]) == "extreme"
    assert overlays.rating_of(["", "nothing here"]) == "unrated"


@pytest.mark.parametrize(
    ("name", "data", "why"),
    [
        ("a.kml", b"<kml><Document></Document></kml>", "no polygons"),
        ("a.kml", b"not xml", "not valid KML"),
        ("a.kmz", b"not a zip", "not a KMZ"),
        ("a.kmz", b"PK\x05\x06" + b"\0" * 18, "no KML"),
        ("a.geojson", b"[1, 2]", "feature collection"),
        ("a.txt", b"x", "only .kmz"),
        (
            "a.kml",
            b'<?xml version="1.0"?><!DOCTYPE k [<!ENTITY a "aa">]><kml>&a;</kml>',
            "entity",
        ),
    ],
)
def test_ates_files_that_cannot_be_read(name: str, data: bytes, why: str) -> None:
    with pytest.raises(overlays.BadOverlay, match=why):
        overlays.read_file(name, data)


def test_ates_names() -> None:
    assert overlays.valid_name("Rogers Pass ATES.kmz")
    assert not overlays.valid_name("../x.kmz")
    assert not overlays.valid_name(".hidden.kmz")
    assert not overlays.valid_name("x.exe")


# --- the API ------------------------------------------------------------------------

PASSWORD = "correct horse battery"
H = {"Origin": "http://testserver"}


@pytest.fixture
def client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    s = settings.model_copy(
        update={"owner_password": PASSWORD, "static_dir": settings.data_dir / "none"}
    )
    return TestClient(create_app(s))


def test_api_serves_stations_and_reports_gzipped(client: TestClient, settings: Settings) -> None:
    assert client.get("/api/map/stations").status_code == 503
    assert client.get("/api/avalanche/observations.geojson").status_code == 503
    with Fetcher(user_agent="t", transport=station_transport(), tries=1) as f:
        stations.refresh(settings.stations_path, f, BOX, NOW)
    r = client.get("/api/map/stations", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert len(r.json()["stations"]) == 2
    raw = client.get("/api/map/stations", headers={"Accept-Encoding": "gzip"})
    assert raw.json() == r.json()
    settings.obs_path.parent.mkdir(parents=True, exist_ok=True)
    settings.obs_path.write_text(
        observations.ObsOut(generated_at="x", days=14, features=[]).model_dump_json()
    )
    r = client.get("/api/avalanche/observations.geojson")
    assert r.status_code == 200 and r.json()["features"] == []
    # The ski map is now served the same way.
    settings.osm_path.parent.mkdir(parents=True)
    settings.osm_path.write_text('{"type":"FeatureCollection","features":[]}')
    r = client.get("/api/osm/ski.geojson", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.json()["features"] == []


def test_nearby_lists_close_stations_and_reports(
    client: TestClient, settings: Settings, conn: sqlite3.Connection
) -> None:
    from snowwatch.locations.service import import_yaml
    from snowwatch.settings import REPO_ROOT

    import_yaml(conn, REPO_ROOT / "config" / "seed-locations.yaml", max_locations=25)
    conn.commit()
    assert client.get("/api/locations/nowhere/nearby").status_code == 404
    # Before the worker's first fetch: empty, not an error.
    empty = client.get("/api/locations/snoqualmie/nearby").json()
    assert empty["stations"] == [] and empty["reports"] == []
    assert empty["stations_at"] is None and empty["reports_at"] is None

    def station(sid: str, lat: float, lon: float) -> stations.MapStation:
        return stations.MapStation(
            id=sid,
            name=sid,
            network="snotel",
            lat=lat,
            lon=lon,
            elev_m=1200,
            obs_time=None,
            depth_cm=50,
            change24_cm=5,
            daily=[],
        )

    settings.stations_path.parent.mkdir(parents=True, exist_ok=True)
    settings.stations_path.write_text(
        stations.StationsOut(
            generated_at="2026-11-12T18:00:00+00:00",
            stations=[
                station("far", 45.0, -121.4),  # Oregon
                station("near", 47.45, -121.42),
                station("nearest", 47.42, -121.41),
            ],
        ).model_dump_json()
    )

    def report(rid: str, lat: float, lon: float, time: str) -> observations.ObsFeature:
        return observations.ObsFeature(
            geometry={"type": "Point", "coordinates": [lon, lat]},
            properties=observations.ObsProps(
                id=rid, title=rid, time=time, region="x", kinds=["quick"], images=0, url=None
            ),
        )

    settings.obs_path.parent.mkdir(parents=True, exist_ok=True)
    settings.obs_path.write_text(
        observations.ObsOut(
            generated_at="2026-11-12T18:00:00+00:00",
            days=14,
            features=[
                report("old", 47.4, -121.4, "2026-11-01T19:00+00:00"),
                report("new", 47.5, -121.5, "2026-11-11T19:00+00:00"),
                report("away", 51.3, -117.1, "2026-11-12T19:00+00:00"),
            ],
        ).model_dump_json()
    )
    body = client.get("/api/locations/snoqualmie/nearby").json()
    assert [s["station"]["id"] for s in body["stations"]] == ["nearest", "near"]
    assert body["stations"][0]["distance_km"] < body["stations"][1]["distance_km"] < 60
    assert [r["report"]["id"] for r in body["reports"]] == ["new", "old"]
    assert body["reports_days"] == 14 and body["radius_km"] == 60


def test_owner_manages_ates_files(client: TestClient, settings: Settings) -> None:
    assert client.get("/api/overlays/ates.geojson").status_code == 404
    # Visitors can't add files.
    assert client.put("/api/admin/overlays/a.kmz", content=kmz(KML), headers=H).status_code == 401
    assert client.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 200
    r = client.put("/api/admin/overlays/Rogers%20Pass.kmz", content=kmz(KML), headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["features"] == 4 and r.json()["ratings"]["complex"] == 2
    bad = client.put("/api/admin/overlays/b.kml", content=b"<kml/>", headers=H)
    assert bad.status_code == 400 and "no polygons" in bad.json()["detail"]
    assert client.put("/api/admin/overlays/x.exe", content=b"x", headers=H).status_code == 400
    # A broken file dropped in by hand is listed with why, and draws nothing.
    (settings.overlays_dir / "hand.kml").write_text("oops")
    files = client.get("/api/admin/overlays").json()
    assert [(f["name"], f["error"] is None) for f in files] == [
        ("Rogers Pass.kmz", True),
        ("hand.kml", False),
    ]
    out = client.get("/api/overlays/ates.geojson").json()
    assert len(out["features"]) == 4 and len(out["files"]) == 2
    assert client.delete("/api/admin/overlays/hand.kml", headers=H).json() == {"ok": True}
    assert client.delete("/api/admin/overlays/hand.kml", headers=H).status_code == 404
    out = client.get("/api/overlays/ates.geojson").json()
    assert [f["name"] for f in out["files"]] == ["Rogers Pass.kmz"]
