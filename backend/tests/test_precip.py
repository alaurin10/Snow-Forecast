"""The map's precipitation frames: colours, geometry, and a full render with a fake network."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from snowwatch import precip
from snowwatch.api.app import create_app
from snowwatch.precip import (
    MIX,
    PALETTE,
    RAIN,
    SNOW,
    Region,
    Renderer,
    encode,
    hex_rgb,
    hrrr_recolor,
    parse_times,
    radar_recolor,
    rain_rate,
    region_for,
    snap,
    snow_rate,
    stitch,
    wpc_layer,
    wpc_ts,
)
from snowwatch.settings import Settings

rain = [hex_rgb(c) for _, c in RAIN]
snow = [hex_rgb(c) for _, c in SNOW]
mix = [hex_rgb(c) for _, c in MIX]


def test_reflectivity_to_rates() -> None:
    assert round(rain_rate(30), 1) == 2.7
    assert round(snow_rate(30), 2) == 2.36


def test_radar_colours_become_ours() -> None:
    assert radar_recolor(0x88, 0xDD, 0xEE) == rain[0]  # 15 dBZ rain
    assert radar_recolor(0x00, 0x77, 0xAA) == rain[2]  # 25 dBZ: ~1.3 mm/h
    assert radar_recolor(0xFF, 0x44, 0x00) == rain[5]  # 45 dBZ
    assert radar_recolor(0x85, 0xC5, 0xFF) == snow[1]  # 19 dBZ snow
    assert radar_recolor(0x00, 0x3F, 0xFF) == snow[4]
    assert radar_recolor(0xC7, 0xFF, 0xFF) is None  # 0 dBZ snow: too light to show


def test_hrrr_colour_families() -> None:
    assert hrrr_recolor(*hex_rgb("#d6efd0")) == rain[0]
    assert hrrr_recolor(*hex_rgb("#00441b")) == rain[2]
    assert hrrr_recolor(*hex_rgb("#ffe81a")) == rain[3]
    assert hrrr_recolor(*hex_rgb("#ffa000")) == rain[5]
    assert hrrr_recolor(*hex_rgb("#81c0d5")) == snow[0]
    assert hrrr_recolor(*hex_rgb("#003f7f")) == snow[4]
    assert hrrr_recolor(*hex_rgb("#dedded")) == mix[0]
    assert hrrr_recolor(*hex_rgb("#fc8767")) == mix[1]
    assert hrrr_recolor(128, 128, 128) is None


def test_time_dimension() -> None:
    ts = parse_times("2026-11-06T19:00:00Z/2026-11-06T22:00:00Z/PT1H")
    assert len(ts) == 4 and ts[1] - ts[0] == 3600
    assert len(parse_times("2026-11-06T19:00:00Z, junk, 2026-11-06T18:00:00Z")) == 2


def test_wpc_blocks() -> None:
    base = wpc_ts("2026-11-06 18:00:00")
    assert wpc_layer(base + 3600, base) == 13
    assert wpc_layer(base + 6 * 3600, base) == 13
    assert wpc_layer(base + 7 * 3600, base) == 14
    assert wpc_layer(base, base) is None


def test_region_covers_locations_with_room() -> None:
    r = region_for([(46.9, -121.5), (51.1, -115.8)])
    (south, west), (north, east) = r.bounds
    assert south < 46.9 - 4 and north > 51.1 + 5
    assert west < -121.5 - 9 and east > -115.8 + 7
    assert r.width == precip.WIDTH and 500 < r.height <= 1800
    one = region_for([(47.0, -121.0)])
    assert one.bounds[1][0] - one.bounds[0][0] >= 11.9


def test_palette_png_round_trip() -> None:
    r = Region(0, 0, 1, 1, 4, 2)
    img = np.zeros((2, 4, 4), np.uint8)
    img[0, 0] = (*snow[2], 255)
    img[1, 3] = (rain[4][0] + 3, rain[4][1], rain[4][2], 255)  # near enough: snaps
    data = encode(snap(img, r))
    back = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))
    assert tuple(back[0, 0]) == (*snow[2], 255)
    assert tuple(back[1, 3]) == (*rain[4], 255)
    assert back[0, 1, 3] == 0
    assert len(PALETTE) <= 256


# ---- A whole render, offline -------------------------------------------------------


def png(color: tuple[int, int, int] | None, w: int, h: int) -> bytes:
    im = Image.new("RGBA", (w, h), (*color, 255) if color else (0, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class FakeNet(precip.Net):
    """Answers like the real sources, with flat colours, and counts image requests."""

    def __init__(self, now: int) -> None:
        self.now = now
        self.images = 0

    def json(self, url: str, params: dict[str, str] | None = None) -> Any:
        if "rainviewer" in url:
            past = [{"time": self.now - 600 * i, "path": f"/v2/radar/{i}"} for i in (2, 1, 0)]
            return {"host": "https://tiles.example", "radar": {"past": past}}
        if "refp_" in url:
            minute = int(url.rsplit("_", 1)[1].split(".")[0])
            if minute > 6 * 60:
                return None
            init = self.now - self.now % 3600
            valid = init + minute * 60
            return {
                "model_init_utc": precip.ts_iso(init),
                "model_forecast_utc": precip.ts_iso(valid),
            }
        if url.endswith("/13/query"):
            start = precip.ts_iso(self.now - self.now % 3600).replace("T", " ").rstrip("Z")
            return {"features": [{"attributes": {"start_time": start, "issue_time": "x"}}]}
        if "/query" in url:
            ring = [[-125, 40], [-115, 40], [-115, 45], [-125, 45], [-125, 40]]
            props = {"qpf": 0.3}
            return {
                "features": [
                    {"properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}
                ]
            }
        return None

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        if params and params.get("request") == "GetCapabilities":
            start = self.now - self.now % 3600
            text = (
                f'<Dimension name="time" default="x">{precip.ts_iso(start)}/'
                f"{precip.ts_iso(start + 12 * 3600)}/PT1H</Dimension>"
                '<Dimension name="reference_time" default="RUN1">x</Dimension>'
            )
            return type("R", (), {"text": text})()
        return None

    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None:
        self.images += 1
        if params:  # GeoMet: domain covers the top half; snow everywhere it covers
            w, h = int(params["width"]), int(params["height"])
            out = np.zeros((h, w, 4), np.uint8)
            color = (0, 0, 0) if params["layers"] == precip.DOMAIN_LAYER else snow[1]
            if "SN_PT1H" in params["layers"] or params["layers"] == precip.DOMAIN_LAYER:
                out[: h // 2] = (*color, 255)
            return out
        tile = np.zeros((256, 256, 4), np.uint8)
        tile[...] = (0x00, 0x77, 0xAA, 255) if "tiles.example" in url else (0x73, 0xC4, 0x76, 255)
        return tile


def test_render_writes_index_and_reuses_frames(tmp_path: Path) -> None:
    now = 1_800_000_000
    net = FakeNet(now)
    region = Region(
        *[precip.merc_x(-125), precip.merc_y(42)], precip.merc_x(-115), precip.merc_y(50), 120, 100
    )
    out = tmp_path / "precip"
    index = Renderer(out, net, now=lambda: now).run(region)

    frames = index["frames"]
    past = [f for f in frames if f["past"]]
    future = [f for f in frames if not f["past"]]
    assert len(past) == 3 and index["now"] == now
    assert len(future) == 12
    assert {f["south"] for f in future} >= {"hrrr", "wpc"}  # HRRR to 6 h, WPC after
    for f in frames:
        assert (out / f["file"]).exists()
    on_disk = json.loads((out / "index.json").read_text())
    assert on_disk["bounds"] == region.bounds

    # A forecast frame: snow from HRDPS on top, HRRR rain below, cut out under the domain.
    first = np.asarray(Image.open(out / future[0]["file"]).convert("RGBA"))
    assert tuple(first[10, 10][:3]) == snow[1]
    assert tuple(first[90, 10][:3]) == rain[1]

    # Nothing changed: nothing redrawn.
    before = net.images
    again = Renderer(out, net, now=lambda: now).run(region)
    assert net.images == before
    assert [f["file"] for f in again["frames"]] == [f["file"] for f in frames]


def test_stitch_samples_tiles_onto_the_region() -> None:
    net = FakeNet(0)
    region = Region(
        precip.merc_x(-125), precip.merc_y(42), precip.merc_x(-115), precip.merc_y(50), 50, 40
    )
    img = stitch(net, "https://tiles.example/{z}/{x}/{y}.png", region)
    assert img is not None and img.shape == (40, 50, 4)
    assert tuple(img[20, 25]) == (0x00, 0x77, 0xAA, 255)


def test_api_serves_index_and_frames(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/precip").status_code == 503
    d = settings.precip_dir
    d.mkdir(parents=True)
    (d / "index.json").write_text('{"frames": []}')
    (d / "f123-0123456789ab.png").write_bytes(png((1, 2, 3), 2, 2))
    r = client.get("/api/precip")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    r = client.get("/api/precip/f123-0123456789ab.png")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    (d / "t24-0123456789ab.png").write_bytes(png((1, 2, 3), 2, 2))
    assert client.get("/api/precip/t24-0123456789ab.png").status_code == 200
    assert client.get("/api/precip/index.json.tmp").status_code == 404
    assert client.get("/api/precip/..%2Fsnowwatch.db").status_code == 404


def test_numpy_runs_on_plain_x86_64() -> None:
    """The mini PC's Docker VM reports a basic CPU type; NumPy 2.4+ needs x86-64-v2 and
    fails to import there ("your machine doesn't support X86_V2"). Keep a build that doesn't."""
    simd = np.show_config(mode="dicts")["SIMD Extensions"]  # type: ignore[no-untyped-call]
    assert "X86_V2" not in simd.get("baseline", [])


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


# ---- Snowfall totals ---------------------------------------------------------------


def float_tiff(values: np.ndarray, lon0: float, lat0: float, d: float) -> bytes:
    from PIL import TiffImagePlugin

    im = Image.fromarray(values.astype(np.float32), "F")
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[33922] = (0.0, 0.0, 0.0, lon0, lat0, 0.0)
    info[33550] = (d, d, 0.0)
    buf = io.BytesIO()
    im.save(buf, "TIFF", tiffinfo=info)
    return buf.getvalue()


def test_snow_totals_subtract_running_totals(tmp_path: Path) -> None:
    from snowwatch.precip import TOTAL, wcs_grid

    now = 1_800_000_000 - 1_800_000_000 % 3600
    region = Region(
        precip.merc_x(-125), precip.merc_y(42), precip.merc_x(-115), precip.merc_y(50), 60, 50
    )

    class TotalsNet(precip.Net):
        def __init__(self) -> None:
            pass

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            if params and params.get("request") == "GetCapabilities":
                text = (
                    f'<Dimension name="time" default="x">{precip.ts_iso(now - 3600)}/'
                    f"{precip.ts_iso(now + 30 * 3600)}/PT1H</Dimension>"
                    '<Dimension name="reference_time" default="RUN7">x</Dimension>'
                )
                return type("R", (), {"text": text})()
            if "GetCoverage" in url:
                t = precip.iso_ts(url.split("TIME=")[1].replace("%3A", ":"))
                # 1 mm water an hour since the run began, over the whole box.
                grid = np.full((40, 60), float((t - (now - 6 * 3600)) / 3600), np.float32)
                body = float_tiff(grid, -126.0, 51.0, 0.25)
                return type("R", (), {"content": body, "headers": {"content-type": "image/tiff"}})()
            return None

    net = TotalsNet()
    g = wcs_grid(net, "X", precip.ts_iso(now), region)
    assert g is not None and g.dlon == 0.25 and g.lon0 == -126.0 and g.data.shape == (40, 60)

    r = Renderer(tmp_path, net, now=lambda: now + 600)
    totals = r._snow_totals(region, now + 600)
    assert [t.hours for t in totals] == [12, 24, 30]  # the run ends 30 h out
    assert all(t.start == now for t in totals)
    img = np.asarray(Image.open(tmp_path / totals[1].file).convert("RGBA"))
    # 24 mm of water ≈ 24 cm of snow: the 22.86 cm step.
    step = next(c for low, c in reversed(TOTAL) if low <= 24)
    assert tuple(img[25, 30][:3]) == hex_rgb(step)
