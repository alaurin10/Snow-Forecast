"""Forecasts anywhere (spots, docs/OPEN-METEO-PLAN.md milestone 2): bands from the
terrain, the US/Canada outline, names, cache keys, limits, the ensemble allowance, and a
spot built from the saved fixtures."""

from __future__ import annotations

import gzip
import json
import math
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from snowwatch import spots
from snowwatch.api.app import create_app
from snowwatch.capture import load_fixture
from snowwatch.doc import Snapshot
from snowwatch.http import fetcher_for
from snowwatch.locations.service import import_yaml
from snowwatch.settings import REPO_ROOT, Settings
from snowwatch.spots import (
    OutsideCoverage,
    SpotBusy,
    SpotContext,
    SpotService,
    SpotUnavailable,
    build_spot,
    choose_bands,
    country_at,
    ensemble_cell,
    geohash,
    load_borders,
    ring_points,
    round_point,
    spot_name,
)
from snowwatch.store import repo
from tests.conftest import make_location
from tests.helpers import FIXTURES, captured_at, config, seed, synthetic_clouds

BORDERS = REPO_ROOT / "config" / "borders.geojson"
LOCAL = "http://om.test"

# --- bands from the terrain -----------------------------------------------------------


def test_bands_near_the_top() -> None:
    b = choose_bands(2000, [1200, 1500, 1990, 1700])
    assert (b.base, b.mid, b.summit, b.method, b.band) == (1200, 1680, 2000, "top", "summit")


def test_bands_near_the_bottom() -> None:
    b = choose_bands(900, [950, 1400, 1900, 1200])
    assert (b.base, b.mid, b.summit, b.method, b.band) == (900, 1500, 1900, "bottom", "base")


def test_bands_on_a_slope() -> None:
    b = choose_bands(1500, [1000, 1300, 1800, 2100])
    assert (b.base, b.mid, b.summit, b.method, b.band) == (1000, 1500, 2100, "slope", "mid")


def test_bands_on_flat_ground() -> None:
    b = choose_bands(600, [550, 610, 700, 580])
    assert (b.base, b.mid, b.summit, b.method, b.band) == (300, 600, 900, "flat", "mid")


@pytest.mark.parametrize(
    ("h", "ring"),
    [
        (1000, [700, 1000, 1010]),  # top, 310 m of relief: mid pulled clear of both ends
        (700, [700, 760, 1010]),  # bottom, likewise
        (1000, [880, 1300]),  # slope just above the bottom edge: base pushed down
        (1180, [880, 1300]),  # slope just below the top edge: summit pushed up
    ],
)
def test_bands_stay_150_m_apart(h: float, ring: list[float]) -> None:
    b = choose_bands(h, ring)
    assert b.mid - b.base >= 150 and b.summit - b.mid >= 150
    assert h in (b.base, b.mid, b.summit)


def test_ring_points_are_one_and_two_and_a_half_km_out() -> None:
    from snowwatch.geo import haversine_km

    pts = ring_points(47.0, -121.0)
    assert len(pts) == 25 and pts[0] == (47.0, -121.0)
    assert all(abs(haversine_km(47, -121, *p) - 1.0) < 0.01 for p in pts[1:13])
    assert all(abs(haversine_km(47, -121, *p) - 2.5) < 0.01 for p in pts[13:])


# --- country -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lat", "lon", "country"),
    [
        (46.935, -121.475, "US"),  # Crystal Mountain
        (50.115, -122.949, "CA"),  # Whistler
        (51.3, -117.5, "CA"),  # Rogers Pass
        (39.6, -106.0, "US"),  # Colorado
        (61.1, -149.7, "US"),  # Alaska
        (49.03, -119.0, "CA"),  # just north of the 49th parallel
        (48.97, -119.0, "US"),  # just south
        (45.0, -73.4, "US"),  # the Quebec/New York line
        (45.05, -73.4, "CA"),
        (47.92, -124.64, "US"),  # the Olympic coast, on the rocks
        (31.0, -110.0, None),  # Sonora, Mexico
        (45.0, -135.0, None),  # the Pacific
        (64.0, -19.0, None),  # Iceland
    ],
)
def test_country_from_the_outline(lat: float, lon: float, country: str | None) -> None:
    assert country_at(load_borders(BORDERS), lat, lon) == country


def test_outline_is_small() -> None:
    assert BORDERS.stat().st_size < 400_000


# --- names and keys -------------------------------------------------------------------


def test_name_from_a_peak_then_a_location_then_coordinates() -> None:
    crystal = make_location(id="crystal", name="Crystal Mountain")
    mid = crystal.band("mid")  # 47.0, -121.0
    on = [("Silver King", 47.003, -121.0), ("Far Peak", 47.2, -121.0)]
    name, peak = spot_name(47.0, -121.0, on, (crystal, 0.0))  # 0.33 km: on it
    assert name == "Silver King" and peak is not None and peak.bearing is None
    # Within 6 km: where it is from the peak, from the peak's side.
    near = [("Silver King", 47.0 - 1.2 / 111.2, -121.0)]
    name, peak = spot_name(47.0, -121.0, near, (crystal, 30.0))
    assert name == "1.2 km N of Silver King"
    assert peak is not None and peak.name == "Silver King" and peak.bearing == "N"
    assert spot_name(47.0, -121.0, [("P", 47.0 - 0.6 / 111.2, -121.0)], None)[0] == ("600 m N of P")
    # Farther from any peak: from a saved location, then the coordinates.
    lat, lon = 47.0 + 6 / 111.2 * math.cos(math.radians(45)), -121.0
    lon += 6 / (111.2 * math.cos(math.radians(47))) * math.sin(math.radians(45))
    assert spot_name(lat, lon, on[1:], (crystal, 6.0)) == ("6 km NE of Crystal Mountain", None)
    assert spot_name(mid.lat, mid.lon, [], (crystal, 0.3))[0] == "Near Crystal Mountain"
    assert spot_name(47.5, -121.0, [], (crystal, 55.6))[0] == "47.500° N, 121.000° W"
    assert spot_name(47.5, -121.0, [], None)[0] == "47.500° N, 121.000° W"


def test_peaks_from_the_label_tiles() -> None:
    """A real label tile (OpenFreeMap, zoom 11, east of Stevens Pass), read without any
    vector-tile library."""
    from snowwatch import peaks

    tile = (FIXTURES.parent / "labels" / "11-335-714.pbf").read_bytes()
    points = peaks.layer_points(tile, "mountain_peak")
    assert len(points) == 70
    asked: list[tuple[int, int, int]] = []

    def get(z: int, x: int, y: int) -> bytes | None:
        asked.append((z, x, y))
        return tile if (x, y) == (335, 714) else None

    found = peaks.peaks_near(get, 47.70, -120.93, z=11)
    assert len(asked) == 9 and (11, 335, 714) in asked  # the tile and the eight round it
    by_name = {n: (a, b) for n, a, b in found}
    lat, lon = by_name["Big Chiwaukum"]
    assert abs(lat - 47.7024) < 0.001 and abs(lon - -120.9346) < 0.001
    name, peak = spot_name(47.705, -120.93, found, None)
    assert name == "Big Chiwaukum" and peak is not None
    # Bad data is skipped, not raised.
    assert peaks.peaks_near(lambda z, x, y: b"\x0a\xff", 47.7, -120.93, z=11) == []


def test_geohash_and_ids() -> None:
    assert geohash(57.64911, 10.40744) == "u4pruyd"  # the textbook example
    loc = spots.spot_location(46.935, -121.475, choose_bands(1500, [1000, 2000]), "US", "A spot")
    assert loc.id == "spot-" + geohash(46.935, -121.475) and len(loc.id) == 12
    assert [b.label for b in loc.bands] == ["Lower", "This spot", "Upper"]
    assert {b.lat for b in loc.bands} == {46.935} and loc.tz is None


def test_cache_keys() -> None:
    assert round_point(46.93549, -121.47451) == (46.935, -121.475)
    assert round_point(46.9346, -121.4754) == round_point(46.9354, -121.4746)
    assert ensemble_cell(46.93, -121.47, 1840) == (47.0, -121.5, 1800, "47,-121.5,1800")
    assert ensemble_cell(46.87, -121.37, 1849)[3] == "46.75,-121.25,1800"
    assert ensemble_cell(46.87, -121.37, 1851)[3] == "46.75,-121.25,1900"


# --- a spot built from the saved fixtures -------------------------------------------------


def terrain(lat: float, lon: float) -> float:
    """A cone 2,400 m high at (47, -121), falling 300 m a km: the summit of any spot there."""
    from snowwatch.geo import haversine_km

    return max(800.0, 2400.0 - 300.0 * haversine_km(lat, lon, 47.0, -121.0))


def spot_transport(log: list[str] | None = None, *, down: bool = False) -> httpx.MockTransport:
    """The self-hosted server answering any point with Crystal's saved responses, the
    terrain above for elevation, and NWS and the public ensemble API likewise."""
    crystal = FIXTURES / "crystal"

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url.copy_with(query=None))
        params = dict(req.url.params)
        if log is not None:
            log.append(f"{req.url.host} {req.url.path} {params.get('models', '')}".strip())
        if down and req.url.host == "om.test":
            raise httpx.ConnectError("refused")
        if url.endswith("/v1/elevation"):
            lats = [float(x) for x in params["latitude"].split(",")]
            lons = [float(x) for x in params["longitude"].split(",")]
            return httpx.Response(
                200, json={"elevation": [terrain(a, b) for a, b in zip(lats, lons, strict=True)]}
            )
        if url.endswith("/v1/ensemble"):
            return httpx.Response(
                200, json=load_fixture(crystal / f"ens_{params['models']}.json.gz")
            )
        if url.endswith("/alerts/active"):
            return httpx.Response(200, json=load_fixture(crystal / "nws_alerts.json.gz"))
        hourly = params.get("hourly", "").split(",")
        if "cloud_cover_850hPa" in hourly:
            return httpx.Response(200, json=synthetic_clouds(params))
        if "daily" in params:
            return httpx.Response(200, json=load_fixture(crystal / "blend.json.gz"))
        name = "upper" if "wind_speed_850hPa" in hourly else "multi"
        return httpx.Response(
            200, json=one_model(load_fixture(crystal / f"{name}.json.gz"), params)
        )

    return httpx.MockTransport(handler)


def one_model(data: Any, params: dict[str, str]) -> Any:
    """A saved multi-model answer as the server gives it for a one-model request: that
    model's columns, without the suffix."""
    models = params.get("models", "").split(",")
    if len(models) != 1:
        return data
    suffix = f"_{models[0]}"

    def point(p: dict[str, Any]) -> dict[str, Any]:
        h = p.get("hourly") or {}
        keep = {k[: -len(suffix)]: v for k, v in h.items() if k.endswith(suffix)}
        return {**p, "hourly": {"time": h.get("time", []), **keep}}

    return [point(p) for p in data] if isinstance(data, list) else point(data)


def no_tiles(z: int, x: int, y: int) -> bytes | None:
    """No label tiles (the tests make no network calls)."""
    return None


def spot_settings(settings: Settings, mode: str = "public") -> Settings:
    return settings.model_copy(update={"open_meteo_url": LOCAL, "open_meteo_ensembles": mode})


def build(
    settings: Settings,
    conn: sqlite3.Connection | None,
    *,
    lat: float = 47.0,
    lon: float = -121.0,
    log: list[str] | None = None,
    spot_used: float = 0.0,
    local_ensembles: bool = False,
    down: bool = False,
) -> Snapshot:
    opts: dict[str, Any] = {"transport": spot_transport(log, down=down), "tries": 1}
    if local_ensembles:
        opts |= {"ensemble_stale": lambda s: None, "ensemble_check": None}
    s = spot_settings(settings, "local" if local_ensembles else "public")
    with fetcher_for(s, **opts) as f:
        ctx = SpotContext(
            borders=load_borders(BORDERS),
            locations=list(seed().values()),
            peaks=[],
            conn=conn,
            spot_used=spot_used,
            alerts=lambda a, b: f.get_json(
                "https://api.weather.gov/alerts/active", {"point": f"{a},{b}"}, source="nws"
            ),
        )
        snap = build_spot(f, config(), ctx, lat, lon, captured_at())
        if conn is not None:
            repo.record_usage(conn, f, public_as=repo.SPOT_HOST)
        return snap


def test_spot_built_from_the_fixtures(settings: Settings, conn: sqlite3.Connection) -> None:
    log: list[str] = []
    snap = build(settings, conn, log=log)
    assert snap.spot is not None and snap.location.id.startswith("spot-")
    assert snap.spot.method == "top" and snap.spot.band == "summit"
    elevs = [b.elev_m for b in snap.bands]
    assert snap.spot.elev_m == 2400 and elevs[2] == 2400
    assert elevs[0] == pytest.approx(1650, abs=10) and elevs[1] == pytest.approx(2100, abs=5)
    assert [b.label for b in snap.bands] == ["Lower", "Middle", "This spot"]
    assert snap.location.tz == "America/Los_Angeles"  # from the forecast
    assert snap.location.name == "37 km E of Crystal Mountain"
    assert snap.spot.nearest is not None and snap.spot.nearest.id == "crystal"
    assert snap.spot.ensembles == "fresh" and set(snap.ensembles) == set(config().ensembles)
    assert snap.run_id is None and snap.snotel is None and len(snap.alerts) >= 0
    # Forecasts from the server only; ensembles from the public API (OPEN_METEO_ENSEMBLES
    # public); no station, SNOTEL or BC requests.
    # One model per request for the multi-model forecast and upper air (6 + 5), joined.
    assert sum("/v1/forecast" in x for x in log) == 1 + 6 + 5 + 1
    mid = snap.bands[1]
    assert set(mid.periods[0].models) >= {"gfs_seamless", "ecmwf_ifs025", "ncep_hrrr_conus"}
    assert sum(v is not None for v in mid.periods[0].models.values()) >= 4
    assert snap.backcountry is not None and snap.ridge is not None  # upper air came through
    assert all(x.startswith(("om.test", "ensemble-api", "api.weather.gov")) for x in log)
    assert sum(x.startswith("ensemble-api") for x in log) == 3
    # The ensembles are kept for nearby spots, and their weight goes on the spots' row.
    used = repo.usage_today(conn).by_host
    assert used[repo.SPOT_HOST] == pytest.approx(11.8, abs=0.5)
    log.clear()
    again = build(settings, conn, log=log)  # a second visitor (the API would have it cached)
    assert again.spot is not None and again.spot.ensembles == "cached"
    assert not any(x.startswith("ensemble-api") for x in log)
    assert len(again.model_dump_json()) < 360_000


def test_spot_ensembles_from_the_server_need_no_allowance(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    log: list[str] = []
    snap = build(settings, conn, log=log, spot_used=5000, local_ensembles=True)
    assert snap.spot is not None and snap.spot.ensembles == "fresh"
    assert sum(x.startswith("om.test /v1/ensemble") for x in log) == 3
    assert not any(x.startswith("ensemble-api") for x in log)
    assert repo.usage_today(conn).by_host.get(repo.SPOT_HOST, 0) == 0
    rows = conn.execute("SELECT DISTINCT source FROM spot_ensembles").fetchall()
    assert [r[0] for r in rows] == ["local"]


def test_spot_builds_without_ensembles_when_the_allowance_is_spent(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    log: list[str] = []
    snap = build(settings, conn, log=log, spot_used=config().spots.ensemble_allowance - 1)
    assert snap.spot is not None and snap.spot.ensembles == "allowance_spent"
    assert snap.ensembles == {} and not any(x.startswith("ensemble-api") for x in log)
    assert snap.bands[1].periods  # the forecast itself is all there


def test_spot_without_a_database_still_builds(settings: Settings) -> None:
    snap = build(settings, None)
    assert snap.spot is not None and snap.spot.ensembles == "fresh"


def test_spot_outside_the_us_and_canada(settings: Settings) -> None:
    with pytest.raises(OutsideCoverage, match="US and Canada"):
        build(settings, None, lat=31.0, lon=-110.0)


def test_spot_when_the_server_is_down(settings: Settings) -> None:
    log: list[str] = []
    with pytest.raises(SpotUnavailable):
        build(settings, None, log=log, down=True)
    # No public fallback for spots, not even for elevation (alerts are asked for alongside).
    assert log and not any("open-meteo" in x for x in log)


def test_spot_names_a_nearby_peak(settings: Settings) -> None:
    opts: dict[str, Any] = {"transport": spot_transport(), "tries": 1}
    with fetcher_for(spot_settings(settings), **opts) as f:
        ctx = SpotContext(
            borders=load_borders(BORDERS),
            locations=list(seed().values()),
            peaks=[("Cone Peak", 47.005, -121.0)],
        )
        snap = build_spot(f, config(), ctx, 47.0, -121.0, captured_at())
    assert snap.location.name == "600 m S of Cone Peak"
    assert snap.spot is not None and snap.spot.peak is not None
    assert (snap.spot.peak.name, snap.spot.peak.bearing) == ("Cone Peak", "S")


def test_read_peaks(tmp_path: Path) -> None:
    path = tmp_path / "ski.geojson"
    assert spots.read_peaks(path) == []
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-121.5, 46.9]},
                        "properties": {"kind": "peak", "name": "Silver King", "ele": 2100},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-121.4, 46.9]},
                        "properties": {"kind": "hut", "name": "A hut"},
                    },
                ],
            }
        )
    )
    assert spots.read_peaks(path) == [("Silver King", 46.9, -121.5)]


# --- the service: cache and limits --------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def fake_service(clock: Clock, calls: list[tuple[float, float]], **kw: Any) -> SpotService:
    snap = Snapshot.model_validate(json.loads(fixture_doc()))

    def make(lat: float, lon: float) -> Snapshot:
        calls.append((lat, lon))
        if lat < 0:
            raise SpotUnavailable("server down")
        return snap

    return SpotService(config(), make, clock=clock, **kw)


def fixture_doc() -> str:
    from tests.helpers import fixture_snapshot

    return fixture_snapshot("crystal").model_dump_json()


def test_service_caches_by_point_until_the_models_update() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    a = svc.get(46.9351, -121.4751, "v")
    b = svc.get(46.9349, -121.4749, "v")  # the same ~100 m
    assert a is b and calls == [(46.935, -121.475)]
    assert json.loads(gzip.decompress(a.gz))["location"]["id"] == "crystal"
    clock.t += config().spots.cache_minutes * 60 + 1
    svc.get(46.935, -121.475, "v")
    assert len(calls) == 2


def test_service_keeps_the_newest_few_hundred() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    svc.max_entries = 3
    svc.visitor.burst = svc.site.burst = 100
    for i in range(5):
        svc.get(47 + i / 100, -121, f"v{i}")
    assert svc.cached(47.0, -121) is None and svc.cached(47.04, -121) is not None


def test_service_limits_new_spots_per_visitor_and_site() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    for i in range(8):
        svc.get(47 + i / 100, -121, "visitor")
    with pytest.raises(SpotBusy) as e:
        svc.get(48, -121, "visitor")
    assert e.value.visitor
    svc.get(47.0, -121, "visitor")  # cached: still fine
    svc.get(48, -121, "someone else")
    clock.t += 15
    svc.get(48.5, -121, "visitor")  # one more every 15 s
    svc.site.burst = 0  # the site's hourly allowance used up
    svc.site._buckets.clear()
    with pytest.raises(SpotBusy) as e:
        svc.get(49, -121, "a third")
    assert not e.value.visitor


def test_service_answers_fast_while_the_server_is_down() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    with pytest.raises(SpotUnavailable):
        svc.get(-47, -121, "v")
    with pytest.raises(SpotUnavailable):
        svc.get(47, -121, "v")  # not tried: the server just failed
    assert calls == [(-47, -121)]
    clock.t += 31
    svc.get(47, -121, "v")
    assert len(calls) == 2


# --- the API -------------------------------------------------------------------------------


@pytest.fixture
def spot_client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    import_yaml(conn, REPO_ROOT / "config" / "seed-locations.yaml", max_locations=25)
    conn.commit()
    s = spot_settings(settings)
    app = create_app(s)
    app.state.spots = spots.make_service(
        s,
        config(),
        lambda: fetcher_for(s, transport=spot_transport(), tries=1),
        label_tile=no_tiles,
    )
    return TestClient(app)


def test_api_spot(spot_client: TestClient, conn: sqlite3.Connection) -> None:
    r = spot_client.get("/api/spot", params={"lat": 47.0, "lon": -121.0})
    assert r.status_code == 200, r.text
    assert r.headers["content-encoding"] == "gzip" and r.headers["etag"]
    body = r.json()
    assert body["spot"]["band"] == "summit" and body["location"]["kind"] == "backcountry"
    again = spot_client.get(
        "/api/spot",
        params={"lat": 47.0001, "lon": -121.0001},
        headers={"If-None-Match": r.headers["etag"]},
    )
    assert again.status_code == 304
    plain = spot_client.get(
        "/api/spot", params={"lat": 47.0, "lon": -121.0}, headers={"Accept-Encoding": "identity"}
    )
    assert "content-encoding" not in plain.headers and plain.json() == body
    assert spot_client.get("/api/spot", params={"lat": 31, "lon": -110}).status_code == 422
    assert spot_client.get("/api/spot", params={"lat": 95, "lon": -110}).status_code == 422
    # The spot's public ensembles were recorded on the spots' row of the ledger.
    assert repo.usage_today(conn).by_host.get(repo.SPOT_HOST, 0) > 0


def test_api_spot_burst_gives_429(spot_client: TestClient) -> None:
    codes = [
        spot_client.get("/api/spot", params={"lat": 47 + i / 100, "lon": -121}).status_code
        for i in range(10)
    ]
    assert codes[:8] == [200] * 8 and codes[8:] == [429, 429]


def test_api_spot_needs_the_self_hosted_server(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    client = TestClient(create_app(settings))
    r = client.get("/api/spot", params={"lat": 47.0, "lon": -121.0})
    assert r.status_code == 503 and "self-hosted" in r.json()["detail"]
    s = spot_settings(settings)
    app = create_app(s)
    app.state.spots = spots.make_service(
        s,
        config(),
        lambda: fetcher_for(s, transport=spot_transport(down=True), tries=1),
        label_tile=no_tiles,
    )
    r = TestClient(app).get("/api/spot", params={"lat": 47.0, "lon": -121.0})
    assert r.status_code == 503 and r.headers["retry-after"] == "30"


def test_api_spot_nearby_has_the_zone_and_its_rating(
    spot_client: TestClient, settings: Settings
) -> None:
    from datetime import UTC, datetime

    empty = spot_client.get("/api/spot/nearby", params={"lat": 47.0, "lon": -121.0}).json()
    assert empty["zone_id"] is None and empty["avalanche"] is None and empty["stations"] == []
    assert empty["location_id"] == spots.spot_id(47.0, -121.0)
    today = datetime.now(UTC).date()
    doc = {
        "provider": "nac",
        "center": "NWAC",
        "center_id": "NWAC",
        "zone": "Test Zone",
        "link": None,
        "issued_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "days": [{"date": today.isoformat(), "alpine": 3, "treeline": 2, "below": 1}],
    }
    square = [[-121.2, 46.8], [-120.8, 46.8], [-120.8, 47.2], [-121.2, 47.2], [-121.2, 46.8]]
    settings.zones_path.parent.mkdir(parents=True, exist_ok=True)
    settings.zones_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "generated_at": None,
                "features": [
                    {
                        "type": "Feature",
                        "id": "nac:1",
                        "geometry": {"type": "Polygon", "coordinates": [square]},
                        "properties": {"tz": "UTC", "doc": doc},
                    }
                ],
            }
        )
    )
    body = spot_client.get("/api/spot/nearby", params={"lat": 47.0, "lon": -121.0}).json()
    assert body["zone_id"] == "nac:1" and body["zone_name"] == "Test Zone"
    assert body["avalanche"]["status"] == "current" and body["avalanche"]["today_max"] == 3
    outside = spot_client.get("/api/spot/nearby", params={"lat": 48.0, "lon": -121.0}).json()
    assert outside["zone_id"] is None and outside["avalanche"] is None


def test_meta_says_whether_spots_are_offered(settings: Settings) -> None:
    assert TestClient(create_app(settings)).get("/api/meta").json()["local_forecasts"] is False
    on = TestClient(create_app(spot_settings(settings))).get("/api/meta").json()
    assert on["local_forecasts"] is True


def test_spot_requests_run_at_once(settings: Settings) -> None:
    """A cold area waits for the slowest request, not the sum: with every answer taking
    0.3 s, the build takes about two of them (the terrain, then the bands' forecasts)."""
    import time as clock

    inner = spot_transport()

    def slow(req: httpx.Request) -> httpx.Response:
        clock.sleep(0.3)
        return inner.handle_request(req)

    times: dict[str, float] = {}
    opts: dict[str, Any] = {"transport": httpx.MockTransport(slow), "tries": 1}
    with fetcher_for(spot_settings(settings), **opts) as f:
        ctx = SpotContext(borders=load_borders(BORDERS), locations=[], peaks=[])
        t0 = clock.monotonic()
        snap = build_spot(f, config(), ctx, 47.0, -121.0, captured_at(), times)
        took = clock.monotonic() - t0
    assert snap.spot is not None and len(snap.ensembles) == 3
    # 18 requests one after another would take 5.4 s.
    assert took < 1.5, took
    assert set(times) >= {
        "elevation",
        "blend",
        "multi gfs_seamless",
        "upper gfs_seamless",
        "clouds",
    }
    assert {k for k in times if k.startswith("ens_")} == {f"ens_{s}" for s in config().ensembles}


def test_merge_models_rebuilds_the_multi_model_answer() -> None:
    from snowwatch.analysis.series import parse_points, split_models
    from snowwatch.sources.openmeteo import merge_models

    combined = load_fixture(FIXTURES / "crystal" / "multi.json.gz")
    models = config().models_for("US")
    merged = merge_models({m: one_model(combined, {"models": m}) for m in models})
    assert len(merged) == 3
    for got, want in zip(parse_points(merged), parse_points(combined), strict=True):
        assert split_models(got, models) == split_models(want, models)
    # A model whose hours differ is lined up on the first one's, with gaps as None.
    a = {"timezone": "UTC", "hourly": {"time": [0, 3600, 7200], "snowfall": [1, 2, 3]}}
    b = {"timezone": "UTC", "hourly": {"time": [3600, 7200, 10800], "snowfall": [5, 6, 7]}}
    out = merge_models({"x": a, "y": b})
    assert out["hourly"] == {
        "time": [0, 3600, 7200],
        "snowfall_x": [1, 2, 3],
        "snowfall_y": [None, 5, 6],
    }
    with pytest.raises(ValueError):
        merge_models({})


def test_early_builds_cost_nobody_anything() -> None:
    """The map starts a spot when its panel opens: within an allowance of its own, never
    waiting, and the button then finds it made."""
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    got = svc.early(47.0, -121.0, "v")
    assert got is not None and calls == [(47.0, -121.0)]
    # The button finds it made, and the visitor's own builds are untouched.
    assert svc.get(47.0, -121.0, "v") is got
    for i in range(8):
        svc.get(48 + i / 100, -121, "v")
    # Its own allowance: 6, then one every 10 s; past it, skipped at once.
    svc2 = fake_service(Clock(), [])
    assert all(svc2.early(47 + i / 100, -121, "w") is not None for i in range(6))
    assert svc2.early(47.5, -121, "w") is None
    svc2.get(47.6, -121, "w")  # the button still works
    # A server just failed: skipped, not tried.
    svc3 = fake_service(Clock(), calls := [])
    with pytest.raises(SpotUnavailable):
        svc3.early(-47, -121, "v")
    assert svc3.early(47, -121, "v") is None and calls == [(-47, -121)]


def test_early_build_never_waits_for_a_busy_server() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls, max_builds=1)
    assert svc._builds.acquire(blocking=False)  # someone else's build is running
    assert svc.early(47.0, -121.0, "v") is None and calls == []
    svc._builds.release()


def test_api_spot_early(spot_client: TestClient) -> None:
    r = spot_client.get("/api/spot", params={"lat": 47.0, "lon": -121.0, "early": 1})
    assert r.status_code == 200 and r.json()["spot"]["band"] == "summit"
    # The button's request is then served from the cache.
    again = spot_client.get("/api/spot", params={"lat": 47.0, "lon": -121.0})
    assert again.status_code == 200 and again.headers["etag"] == r.headers["etag"]
    # Outside the US and Canada, or skipped: 204, never an error.
    out = spot_client.get("/api/spot", params={"lat": 31, "lon": -110, "early": 1})
    assert out.status_code == 204
    codes = {
        spot_client.get(
            "/api/spot", params={"lat": 47 + i / 100, "lon": -121, "early": 1}
        ).status_code
        for i in range(1, 10)
    }
    assert codes == {200, 204}


def test_the_owner_has_no_early_allowance_to_keep_to() -> None:
    clock, calls = Clock(), []
    svc = fake_service(clock, calls)
    assert all(svc.early(47 + i / 100, -121, "me", owner=True) is not None for i in range(20))
    assert all(svc.early(48 + i / 100, -121, "v") is not None for i in range(6))
    assert svc.early(48.5, -121, "v") is None  # visitors still have theirs
    # The site's hourly cap still applies to the owner.
    svc.site.burst = 0
    svc.site._buckets.clear()
    assert svc.early(49, -121, "me", owner=True) is None


def test_api_spot_early_for_the_signed_in_owner(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    import_yaml(conn, REPO_ROOT / "config" / "seed-locations.yaml", max_locations=25)
    conn.commit()
    s = spot_settings(settings).model_copy(update={"owner_password": "correct horse battery"})
    app = create_app(s)
    app.state.spots = spots.make_service(
        s,
        config(),
        lambda: fetcher_for(s, transport=spot_transport(), tries=1),
        label_tile=no_tiles,
    )
    client = TestClient(app)
    origin = {"Origin": "http://testserver"}
    r = client.post("/api/auth/login", json={"password": "correct horse battery"}, headers=origin)
    assert r.status_code == 200
    codes = [
        client.get("/api/spot", params={"lat": 47 + i / 100, "lon": -121, "early": 1}).status_code
        for i in range(10)
    ]
    assert codes == [200] * 10


def test_spot_named_from_the_label_tiles_and_never_held_up_by_them(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as clock

    opts: dict[str, Any] = {"transport": spot_transport(), "tries": 1}
    with fetcher_for(spot_settings(settings), **opts) as f:
        ctx = SpotContext(
            borders=load_borders(BORDERS),
            locations=[],
            peaks=[],
            tile_peaks=lambda a, b: [("Tile Peak", 47.0 + 1.5 / 111.2, -121.0)],
        )
        snap = build_spot(f, config(), ctx, 47.0, -121.0, captured_at())
    assert snap.location.name == "1.5 km S of Tile Peak"
    # A tile server that doesn't answer costs at most the wait, then the name comes from
    # elsewhere (here, the coordinates).
    monkeypatch.setattr(spots, "PEAKS_WAIT_S", 0.3)

    def stuck(a: float, b: float) -> list[spots.Peak]:
        clock.sleep(3)
        return []

    with fetcher_for(spot_settings(settings), **opts) as f:
        ctx = SpotContext(borders=load_borders(BORDERS), locations=[], peaks=[], tile_peaks=stuck)
        t0 = clock.monotonic()
        snap = build_spot(f, config(), ctx, 47.0, -121.0, captured_at())
        took = clock.monotonic() - t0
    assert took < 2.5 and snap.location.name == "47.000° N, 121.000° W"
