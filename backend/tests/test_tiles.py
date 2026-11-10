"""The map's tile and label-font cache, and the ski runs, lifts and peaks from OpenStreetMap."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from snowwatch.api.app import create_app
from snowwatch.settings import Settings


def png(color: tuple[int, int, int], w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# ---- Map tile cache -------------------------------------------------------------


def test_tile_cache_fetches_once_repairs_esri_and_prunes(tmp_path: Path) -> None:
    import httpx

    from snowwatch.tiles import TileCache, prune

    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "arcgisonline" in str(req.url):
            im = Image.new("RGB", (256, 256), (100, 100, 100))
            for i in range(256):
                im.putpixel((i, 255), (240, 240, 240))  # the light edge
                im.putpixel((255, i), (240, 240, 240))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=95)
            return httpx.Response(
                200, content=buf.getvalue(), headers={"content-type": "image/jpeg"}
            )
        if "/9/0/0" in str(req.url):
            return httpx.Response(404)
        return httpx.Response(
            200, content=png((1, 2, 3), 4, 4), headers={"content-type": "image/png"}
        )

    cache = TileCache(tmp_path, "test", httpx.Client(transport=httpx.MockTransport(answer)))
    first = cache.get("otm", 5, 3, 4)
    again = cache.get("otm", 5, 3, 4)
    assert first is not None and again == first and len(calls) == 1
    assert "opentopomap.org/5/3/4.png" in calls[0]

    esri = cache.get("esri", 6, 10, 22)
    assert esri is not None and esri[1] == "image/jpeg"
    im = Image.open(io.BytesIO(esri[0])).convert("RGB")
    assert abs(im.getpixel((10, 255))[0] - 100) < 12  # the edge now matches the tile
    assert abs(im.getpixel((255, 10))[0] - 100) < 12
    assert "/tile/6/22/10" in calls[-1]  # Esri wants z/y/x

    assert cache.get("otm", 9, 0, 0) is None  # upstream has none
    assert cache.get("nope", 1, 0, 0) is None
    assert cache.get("otm", 3, 8, 0) is None  # off the world
    assert cache.get("otm", 18, 0, 0) is None  # beyond its zoom

    assert prune(tmp_path, now=time.time() + 100 * 86400) == 2
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_api_serves_cached_tiles(settings: Settings, monkeypatch: Any) -> None:
    from snowwatch.tiles import TileCache

    monkeypatch.setattr(
        TileCache,
        "get",
        lambda self, layer, z, x, y: (b"png", "image/png") if layer == "otm" else None,
    )
    client = TestClient(create_app(settings))
    r = client.get("/api/tiles/otm/5/3/4.png")
    assert r.status_code == 200 and r.content == b"png"
    assert "max-age" in r.headers["cache-control"]
    assert client.get("/api/tiles/nope/5/3/4.png").status_code == 404


# ---- Ski runs, lifts and peaks (OpenStreetMap) -------------------------------------


OVERPASS_SAMPLE = {
    "elements": [
        {
            "type": "way",
            "id": 1,
            "tags": {
                "piste:type": "downhill",
                "piste:difficulty": "advanced",
                "name": "Upper International",
            },
            "geometry": [{"lat": 47.44, "lon": -121.44}, {"lat": 47.445, "lon": -121.445}],
        },
        {
            "type": "way",
            "id": 2,
            "tags": {"piste:type": "skitour", "piste:name": "Slot Couloir"},
            "geometry": [{"lat": 47.46, "lon": -121.41}, {"lat": 47.465, "lon": -121.415}],
        },
        {
            "type": "way",
            "id": 3,
            "tags": {"aerialway": "chair_lift", "name": "Edelweiss"},
            "geometry": [{"lat": 47.44, "lon": -121.44}, {"lat": 47.442, "lon": -121.441}],
        },
        {
            "type": "way",
            "id": 4,
            "tags": {"aerialway": "station"},
            "geometry": [{"lat": 1, "lon": 1}] * 2,
        },
        {
            "type": "way",
            "id": 5,
            "tags": {"piste:type": "ice_skate"},
            "geometry": [{"lat": 1, "lon": 1}] * 2,
        },
        {
            "type": "node",
            "id": 6,
            "lat": 47.46,
            "lon": -121.41,
            "tags": {"natural": "peak", "name": "Snoqualmie Mountain", "ele": "2,014 m"},
        },
        {
            "type": "node",
            "id": 7,
            "lat": 47.45,
            "lon": -121.42,
            "tags": {"natural": "peak", "name": "Guye Peak"},
        },
        {
            "type": "way",
            "id": 1,
            "tags": {"piste:type": "downhill"},
            "geometry": [{"lat": 1, "lon": 1}] * 2,
        },
    ]
}


def test_osm_to_geojson_keeps_runs_lifts_and_peaks() -> None:
    from snowwatch.osm import to_geojson

    fc = to_geojson(OVERPASS_SAMPLE["elements"])
    props = [f["properties"] for f in fc["features"]]
    assert [p["kind"] for p in props] == ["run", "run", "lift", "peak", "peak"]
    assert props[0] == {
        "kind": "run",
        "type": "downhill",
        "difficulty": "advanced",
        "name": "Upper International",
    }
    assert props[1]["name"] == "Slot Couloir" and props[1]["type"] == "skitour"
    assert props[3] == {"kind": "peak", "name": "Snoqualmie Mountain", "ele": 2014}
    assert "ele" not in props[4]
    assert fc["features"][0]["geometry"]["coordinates"][0] == [-121.44, 47.44]


def test_osm_refresh_falls_back_and_keeps_fresh_files(tmp_path: Path) -> None:
    import httpx

    from snowwatch import osm

    hits: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.host)
        if req.url.host == "overpass-api.de":
            return httpx.Response(504)
        if req.url.host == "maps.mail.ru":
            # Timed out: Overpass still answers 200, with a remark and no data.
            return httpx.Response(
                200, json={"elements": [], "remark": "runtime error: Query timed out"}
            )
        assert b"piste" in req.content
        return httpx.Response(200, json=OVERPASS_SAMPLE)

    client = httpx.Client(transport=httpx.MockTransport(answer))
    path = tmp_path / "osm" / "ski.geojson"
    pts = [(47.42, -121.42)]
    assert osm.refresh(path, pts, client, now=1000.0, pause=0)
    assert hits == ["overpass-api.de", "maps.mail.ru", "overpass.private.coffee"]
    assert len(json.loads(path.read_text())["features"]) == 5
    # Fresh and same locations: no new request.
    assert not osm.refresh(path, pts, client, now=1000.0 + 3600, pause=0)
    assert len(hits) == 3
    # New locations (one query each), or a week later: fetch again.
    hits.clear()
    two = [*pts, (50.06, -122.95)]
    assert osm.refresh(path, two, client, now=2000.0, pause=0)
    assert len(hits) == 6
    assert osm.refresh(path, two, client, now=2000.0 + 8 * 86400, pause=0)

    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    # Overpass down: the old file stays.
    dead = httpx.Client(transport=httpx.MockTransport(down))
    assert not osm.refresh(path, pts, dead, force=True, pause=0)
    assert path.exists()


def test_osm_refresh_retries_an_empty_file_sooner(tmp_path: Path) -> None:
    import httpx

    from snowwatch import osm

    def empty(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"elements": []})

    client = httpx.Client(transport=httpx.MockTransport(empty))
    path = tmp_path / "ski.geojson"
    pts = [(47.42, -121.42)]
    assert osm.refresh(path, pts, client, now=1000.0, pause=0)
    assert not osm.refresh(path, pts, client, now=1000.0 + 3600, pause=0)
    assert osm.refresh(path, pts, client, now=1000.0 + 7 * 3600, pause=0)


def test_api_serves_ski_map_and_glyphs(settings: Settings, monkeypatch: Any) -> None:
    from snowwatch import tiles

    client = TestClient(create_app(settings))
    assert client.get("/api/osm/ski.geojson").status_code == 503
    settings.osm_path.parent.mkdir(parents=True)
    settings.osm_path.write_text('{"type":"FeatureCollection","features":[]}')
    r = client.get("/api/osm/ski.geojson")
    assert r.status_code == 200 and r.json()["features"] == []

    monkeypatch.setattr(
        tiles, "glyphs", lambda cache, stack, rng: b"pbf" if stack == "Open Sans Semibold" else None
    )
    import snowwatch.api.app as app_mod

    monkeypatch.setattr(app_mod, "glyphs", tiles.glyphs)
    assert client.get("/api/glyphs/Open Sans Semibold/0-255.pbf").content == b"pbf"
    assert client.get("/api/glyphs/Comic Sans/0-255.pbf").status_code == 404


def test_glyph_names_are_checked(tmp_path: Path) -> None:
    import httpx

    from snowwatch.tiles import TileCache, glyphs

    def answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"font")

    cache = TileCache(tmp_path, "t", httpx.Client(transport=httpx.MockTransport(answer)))
    assert glyphs(cache, "Open Sans Semibold", "0-255") == b"font"
    assert (tmp_path / "glyphs" / "Open_Sans_Semibold" / "0-255.pbf").exists()
    assert glyphs(cache, "../../etc", "0-255") is None
    assert glyphs(cache, "Open Sans Semibold", "../x") is None


def test_full_cache_serves_but_stops_storing(tmp_path: Path) -> None:
    import httpx

    from snowwatch.tiles import TileCache

    tile = png((9, 9, 9), 64, 64)

    def answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tile, headers={"content-type": "image/png"})

    client = httpx.Client(transport=httpx.MockTransport(answer))
    cache = TileCache(tmp_path, "t", client, max_bytes=len(tile) + 10)
    assert cache.get("otm", 5, 1, 1) is not None
    assert cache.get("otm", 5, 1, 2) is not None  # served...
    assert cache.cached("otm", 5, 1, 1) and not cache.cached("otm", 5, 1, 2)  # ...not kept


def test_oversized_upstream_answers_are_refused(tmp_path: Path) -> None:
    import httpx

    from snowwatch.tiles import MAX_TILE_BYTES, TileCache

    def answer(req: httpx.Request) -> httpx.Response:
        body = b"x" * (MAX_TILE_BYTES + 1)
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})

    cache = TileCache(tmp_path, "t", httpx.Client(transport=httpx.MockTransport(answer)))
    assert cache.get("otm", 5, 1, 1) is None


def test_prune_removes_least_recently_used_beyond_the_cap(tmp_path: Path) -> None:
    import os

    from snowwatch.tiles import prune

    now = time.time()
    for i in range(10):
        p = tmp_path / "otm" / "5" / str(i) / "0"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x" * 100)
        os.utime(p, (now - 1000 + i, now - 1000 + i))  # tile 0 is the oldest
    assert prune(tmp_path, now=now, max_bytes=500) == 6  # down to 90% of the cap
    left = sorted(int(p.parent.name) for p in tmp_path.rglob("*") if p.is_file())
    assert left == [6, 7, 8, 9]
    assert not (tmp_path / "otm" / "5" / "0").exists()  # empty folders go too


def test_tile_misses_are_rate_limited(settings: Settings, monkeypatch: Any) -> None:
    from snowwatch.api import ratelimit
    from snowwatch.tiles import TileCache

    monkeypatch.setattr(ratelimit, "now", lambda: 1000.0)  # no refill during the test
    monkeypatch.setattr(TileCache, "cached", lambda self, layer, z, x, y: False)
    monkeypatch.setattr(TileCache, "get", lambda self, layer, z, x, y: (b"png", "image/png"))
    client = TestClient(create_app(settings))
    codes = [client.get(f"/api/tiles/otm/10/{i}/0.png").status_code for i in range(310)]
    assert codes.count(200) == 300 and codes[-1] == 429
