"""The map's avalanche zones, treeline bands and the concern index's settings."""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from snowwatch import avalanche_zones as zones
from snowwatch.api.app import create_app
from snowwatch.avalanche import AvalancheDoc, AvyDay
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.settings import REPO_ROOT, Settings
from tests.helpers import FIXTURES, SEED
from tests.test_avalanche import ca_product, load

WEST: zones.Box = (31, -134, 57, -102)


def shared(name: str) -> Any:
    return json.loads(gzip.decompress((FIXTURES / "shared" / name).read_bytes()))


def layer_with_rating() -> dict[str, Any]:
    """The captured map layer, with two NWAC zones rated and one CAIC zone rated."""
    layer = shared("avalanche_us_map_layer.json.gz")
    for f in layer["features"]:
        p = f["properties"]
        if str(f["id"]) in ("3023", "3028", "2755"):
            p.update(danger_level=2, off_season=False)
    return layer


def transport(
    calls: list[str], *, us_fail: bool = False, ca_fail: bool = False
) -> httpx.MockTransport:
    caic = load("us_product_caic_2755.json")
    areas = shared("avalanche_ca_areas.json.gz")
    ids = [str(f["id"]) for f in areas["features"]]

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        calls.append(url)
        if "avalanche.org" in url and us_fail:
            return httpx.Response(500)
        if "avalanche.ca" in url and ca_fail:
            return httpx.Response(500)
        if "map-layer" in url:
            return httpx.Response(200, json=layer_with_rating())
        if "/product?" in url:
            # CAIC's product lists several zones; NWAC's lists one each.
            zone = req.url.params.get("zone_id")
            if zone == "2755":
                return httpx.Response(200, json=caic)
            nwac = load("us_product_nwac_3028_offseason.json")
            nwac["forecast_zone"] = [{"id": int(zone or 0), "name": f"Zone {zone}"}]
            nwac["product_type"] = "forecast"
            return httpx.Response(200, json=nwac)
        if url.endswith("/areas"):
            return httpx.Response(200, json=areas)
        if url.endswith("/products"):
            return httpx.Response(200, json=[ca_product(i) for i in ids])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_refresh_writes_every_zone_in_the_box(tmp_path: Path) -> None:
    calls: list[str] = []
    path = tmp_path / "avalanche" / "zones.geojson"
    with Fetcher(user_agent="t", transport=transport(calls), tries=1) as f:
        res = zones.refresh_zones(path, f, WEST)
    assert res.errors == []
    data = zones.read_zones(path)
    assert data is not None and data["box"] == list(WEST)
    ids = [f["id"] for f in data["features"]]
    assert res.us + res.ca == len(ids) and res.us > 20 and res.ca >= 1
    assert all(i.startswith(("nac:", "avcan:")) for i in ids)
    # Alaska and the east are outside the box.
    for feat in data["features"]:
        b = zones.bbox(feat["geometry"])
        assert b is not None and b[0] <= -102 and b[2] >= -134
    # One product per rated zone, and nothing for the unrated ones.
    asked = [httpx.URL(c).params["zone_id"] for c in calls if "/product?" in c]
    rated = {
        str(f["id"])
        for f in layer_with_rating()["features"]
        if f["properties"].get("danger_level", -1) >= 1 and not f["properties"].get("off_season")
    }
    assert res.products == len(asked) >= 3 and len(set(asked)) == len(asked)
    assert set(asked) <= rated and {"3023", "3028", "2755"} <= set(asked)
    caic = next(f for f in data["features"] if f["id"] == "nac:2755")
    doc = AvalancheDoc.model_validate(caic["properties"]["doc"])
    assert doc.center_id == "CAIC" and doc.days
    assert caic["properties"]["tz"] == "America/Denver"
    # Coordinates are rounded to ~10 m.
    pt = caic["geometry"]["coordinates"][0][0][0]
    assert pt == [round(pt[0], 4), round(pt[1], 4)]


def test_a_product_serves_every_zone_it_lists(tmp_path: Path) -> None:
    calls: list[str] = []
    caic = load("us_product_caic_2755.json")
    other = str(next(z["id"] for z in caic["forecast_zone"] if str(z["id"]) != "2755"))
    real = transport(calls)

    def handler(req: httpx.Request) -> httpx.Response:
        resp = real.handle_request(req)
        if "map-layer" in str(req.url):
            layer = layer_with_rating()
            src = next(f for f in layer["features"] if str(f["id"]) == "2755")
            twin = json.loads(json.dumps(src))
            twin["id"] = int(other)
            layer["features"].append(twin)
            return httpx.Response(200, json=layer)
        return resp

    path = tmp_path / "z.geojson"
    with Fetcher(user_agent="t", transport=httpx.MockTransport(handler), tries=1) as f:
        zones.refresh_zones(path, f, WEST)
    assert f"zone_id={other}" not in " ".join(calls)  # the twin needed no fetch of its own
    data = zones.read_zones(path)
    assert data is not None
    twin = next(f for f in data["features"] if f["id"] == f"nac:{other}")
    assert AvalancheDoc.model_validate(twin["properties"]["doc"]).center_id == "CAIC"


def test_a_failed_provider_keeps_its_last_zones(tmp_path: Path) -> None:
    path = tmp_path / "z.geojson"
    with Fetcher(user_agent="t", transport=transport([]), tries=1) as f:
        zones.refresh_zones(path, f, WEST)
    before = zones.read_zones(path)
    assert before is not None
    with Fetcher(user_agent="t", transport=transport([], ca_fail=True), tries=1) as f:
        res = zones.refresh_zones(path, f, WEST)
    assert res.errors and res.ca == 0
    after = zones.read_zones(path)
    assert after is not None
    ca_ids = {f["id"] for f in before["features"] if f["id"].startswith("avcan:")}
    assert ca_ids and ca_ids == {f["id"] for f in after["features"] if f["id"].startswith("avcan:")}
    with Fetcher(user_agent="t", transport=transport([], us_fail=True), tries=1) as f:
        res = zones.refresh_zones(path, f, WEST)
    assert res.us == 0 and any(
        f["id"].startswith("nac:") for f in zones.read_zones(path)["features"]
    )  # type: ignore[index]


def test_zones_out_expires_on_the_clock() -> None:
    now = datetime(2026, 12, 10, 18, tzinfo=UTC)
    doc = AvalancheDoc(
        provider="nac",
        center="X",
        center_id="X",
        zone="Z",
        link=None,
        issued_at=(now - timedelta(hours=10)).isoformat(),
        expires_at=(now + timedelta(hours=2)).isoformat(),
        days=[AvyDay(date="2026-12-10", alpine=3, treeline=2, below=1)],
    )
    geom = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}
    data = {
        "generated_at": "x",
        "features": [
            {
                "id": "nac:1",
                "geometry": geom,
                "properties": {"tz": "America/Denver", "doc": doc.model_dump()},
            },
            {"id": "nac:2", "geometry": geom, "properties": {"tz": "bad/zone"}},  # no doc: dropped
        ],
    }
    out = zones.zones_out(data, now, zones.DEFAULT_TREELINE, [])
    assert [f.id for f in out.features] == ["nac:1"]
    p = out.features[0].properties
    assert p.view.status == "current" and p.view.today_max == 3 and p.today == "2026-12-10"
    later = zones.zones_out(data, now + timedelta(hours=3), zones.DEFAULT_TREELINE, [])
    v = later.features[0].properties.view
    assert v.status == "expired" and v.doc is not None and v.doc.days == []
    assert zones.zones_out(None, now, zones.DEFAULT_TREELINE, []).features == []


def test_tidy_and_overlaps() -> None:
    poly = {
        "type": "Polygon",
        "coordinates": [[[-120.000001, 47], [-120.000002, 47], [-119, 47], [-119, 48], [-120, 47]]],
    }
    t = zones.tidy(poly)
    assert t is not None and t["type"] == "MultiPolygon"
    assert t["coordinates"][0][0] == [[-120.0, 47], [-119, 47], [-119, 48], [-120, 47]]
    assert zones.tidy({"type": "Point", "coordinates": [0, 0]}) is None
    assert zones.tidy({"type": "Polygon", "coordinates": [[[0, 0], [0, 0]]]}) is None
    assert zones.overlaps(t, WEST) and not zones.overlaps(t, (10, 0, 20, 10))


def test_treeline_config(tmp_path: Path) -> None:
    cfg = zones.load_treeline(REPO_ROOT / "config" / "treeline.yaml")
    assert cfg.rules[-1].name == "Default" and len(cfg.rules) > 20
    assert any(r.center == "NWAC" and r.zone == "Mt Hood" for r in cfg.rules)
    assert zones.load_treeline(tmp_path / "missing.yaml") is zones.DEFAULT_TREELINE
    with pytest.raises(ValidationError):
        zones.TreelineConfig.model_validate(
            {"rules": [{"name": "x", "band": [1, 2], "center": "A"}]}
        )
    with pytest.raises(ValidationError):
        zones.TreelineRule(name="x", band=[2000, 1500])
    # Edits are picked up without a restart.
    f = tmp_path / "t.yaml"
    f.write_text("rules:\n  - {name: A, band: [1000, 1500]}\n")
    assert zones.load_treeline(f).rules[0].band == [1000, 1500]
    f.write_text(
        "rules:\n  - {name: B, band: [1100, 1600]}\n"
        "locations: {crystal: [1400, 1800], nope: [1, 2]}\n"
    )
    import os

    os.utime(f, (1, 2))  # a different mtime even on coarse clocks
    cfg = zones.load_treeline(f)
    assert cfg.rules[0].name == "B"
    locs = service.load_yaml(SEED)
    spots = zones.treeline_spots(cfg, locs)
    assert [s.location_id for s in spots] == ["crystal"] and spots[0].band == [1400, 1800]


def test_map_box_takes_in_every_location() -> None:
    locs = service.load_yaml(SEED)
    assert zones.map_box(WEST, locs) == WEST  # the seed locations are inside
    far = locs[0].model_copy(
        update={"bands": [b.model_copy(update={"lat": 60.0, "lon": -140.0}) for b in locs[0].bands]}
    )
    s, w, n, e = zones.map_box(WEST, [far])
    assert n == 61 and w == -141 and s == 31 and e == -102


# --- the API ----------------------------------------------------------------------


def app_client(settings: Settings, conn: sqlite3.Connection, **over: Any) -> TestClient:
    service.import_yaml(conn, SEED, max_locations=25)
    s = settings.model_copy(update={"static_dir": settings.data_dir / "none", **over})
    return TestClient(create_app(s))


def test_zones_endpoint(settings: Settings, conn: sqlite3.Connection) -> None:
    c = app_client(settings, conn)
    assert c.get("/api/avalanche/zones.geojson").status_code == 503
    with Fetcher(user_agent="t", transport=transport([]), tries=1) as f:
        zones.refresh_zones(settings.zones_path, f, WEST)
    r = c.get("/api/avalanche/zones.geojson")
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "public, max-age=60"
    out = r.json()
    assert out["type"] == "FeatureCollection" and out["features"]
    assert out["treeline"][-1]["name"] == "Default" and out["spot_km"] == 40
    assert out["problem_slope_deg"] == 30
    f = next(x for x in out["features"] if x["id"] == "nac:2755")
    assert f["properties"]["view"]["location_id"] == "nac:2755"
    plain = c.get("/api/avalanche/zones.geojson", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == out


def test_concern_settings_are_for_everyone_unless_off(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    c = app_client(settings, conn, owner_password="correct horse battery")
    assert c.app.state.settings.hazard_index == "on"  # the default
    r = c.get("/api/map/concern")  # not signed in: there are no visitor accounts
    assert r.status_code == 200 and "max-age=300" in r.headers["cache-control"]
    body = r.json()
    assert body["classes"] == [1.5, 2.5, 3.5] and body["slope"][0] == [25, 0.5]
    assert (
        body["caption"].startswith("Experimental estimate") and "Not a forecast" in body["caption"]
    )
    c.app.state.settings = c.app.state.settings.model_copy(update={"hazard_index": "off"})
    assert c.get("/api/map/concern").status_code == 404


@pytest.mark.parametrize(
    ("value", "want"),
    [("on", "on"), ("OFF", "off"), ("true", "on"), ("0", "off"), ("public", "on"), ("owner", "on")],
)
def test_hazard_index_setting(value: str, want: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAZARD_INDEX", value)
    assert Settings().hazard_index == want


def test_hazard_index_rejects_nonsense(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAZARD_INDEX", "maybe")
    with pytest.raises(ValidationError):
        Settings()
