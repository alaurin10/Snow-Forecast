"""Recent satellite imagery: picking clear Sentinel-2 scenes, the index, the tile proxy."""

from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from snowwatch.api.app import create_app
from snowwatch.maps import sat
from snowwatch.settings import Settings
from snowwatch.tiles import S2_RENDER, TileCache, gibs_path, gibs_tile, s2_path, s2_tile
from tests.conftest import make_location

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


def crop(scl: int | np.ndarray, mask: int | np.ndarray = 255) -> np.ndarray:
    arrays = [x for x in (scl, mask) if isinstance(x, np.ndarray)]
    n = arrays[0].shape[0] if arrays else sat.AREA_PX
    a = np.zeros((2, n, n), np.uint8)
    a[0] = scl
    a[1] = mask
    return a


def npy(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, a)
    return buf.getvalue()


def jpeg(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), color).save(buf, "JPEG")
    return buf.getvalue()


def item(pid: str, tile: str, processed: str = "20261110T221403") -> str:
    return f"{pid}_{tile}_{processed}"


def feature(fid: str, when: str, bbox: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": fid,
        "bbox": bbox or [-121.5, 46.5, -120.5, 47.5],
        "properties": {"datetime": when, "platform": f"Sentinel-2{fid[2]}"},
    }


# ---- judging a pass -------------------------------------------------------------


def test_judge_counts_cloud_snow_and_missing_data() -> None:
    scl = np.full((64, 64), 4, np.uint8)  # vegetation
    scl[:16] = 9  # a quarter high cloud
    scl[16:24] = 11  # an eighth snow
    look = sat.judge(sat.merge_crops([crop(scl)]))
    assert look.clear == pytest.approx(0.75)
    assert look.snow == pytest.approx(0.125)
    assert look.nodata == 0
    # The mask, not only class 0, marks pixels without data.
    half = np.zeros((64, 64), np.uint8)
    half[:, :32] = 255
    look = sat.judge(sat.merge_crops([crop(5, half)]))
    assert look.nodata == pytest.approx(0.5) and look.clear == 1
    assert sat.judge(np.zeros((4, 4), np.uint8)) == sat.Look(clear=0, nodata=1, snow=0)


def test_merge_fills_one_tiles_gap_from_the_next() -> None:
    left = np.zeros((96, 96), np.uint8)
    left[:, :40] = 255
    merged = sat.merge_crops([crop(4, left), crop(11)])
    assert (merged[:, :40] == 4).all() and (merged[:, 40:] == 11).all()
    with pytest.raises(ValueError):
        sat.merge_crops([])


def test_passes_group_tiles_and_keep_the_newest_processing() -> None:
    a = "S2C_MSIL2A_20261110T182601_R127"
    b = "S2B_MSIL2A_20261105T182539_R127"
    feats = [
        feature(item(b, "T12TVL"), "2026-11-05T18:25:39Z"),
        feature(item(a, "T12TVL"), "2026-11-10T18:26:01Z"),
        feature(item(a, "T12TVK"), "2026-11-10T18:26:01Z"),
        feature(item(a, "T12TVK", "20261111T010101"), "2026-11-10T18:26:01Z"),  # reprocessed
        feature("not-a-sentinel-item", "2026-11-10T18:26:01Z"),
        {"id": item(b, "T12TVK"), "properties": {}},
    ]
    passes = sat.group_passes(feats)
    assert [p.id for p in passes] == [a, b]
    assert {i.id for i in passes[0].items} == {
        item(a, "T12TVL"),
        item(a, "T12TVK", "20261111T010101"),
    }
    assert passes[0].platform == "Sentinel-2C"
    assert sat.pass_id(item(a, "T12TVL")) == a


def test_crop_box_is_square_on_the_ground() -> None:
    w, s, e, n = sat.crop_box(60.0, -120.0)
    assert n - s == pytest.approx(8 / 111.32, rel=1e-3)
    assert e - w == pytest.approx(2 * (n - s), rel=1e-2)  # cos 60° = 0.5


def test_viirs_tile_check_tells_black_from_imagery() -> None:
    assert not sat.has_imagery(jpeg((0, 0, 0)))
    assert sat.has_imagery(jpeg((120, 130, 140)))
    assert not sat.has_imagery(b"not an image")
    assert sat.tile_xy(0, 0, 1) == (1, 1)


# ---- the refresh ----------------------------------------------------------------

CLEAR = "S2C_MSIL2A_20261110T182601_R127"
CLOUDY = "S2B_MSIL2A_20261108T182539_R084"
OLDER = "S2A_MSIL2A_20261101T182539_R127"
EDGE = "S2A_MSIL2A_20261030T182539_R127"


class Upstream:
    """Planetary Computer and GIBS, as far as the refresh uses them."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_search = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append(url)
        if url.startswith(sat.STAC_SEARCH):
            if self.fail_search:
                return httpx.Response(502)
            body = json.loads(req.content)
            assert body["collections"] == ["sentinel-2-l2a"] and len(body["bbox"]) == 4
            return httpx.Response(
                200,
                json={
                    "features": [
                        feature(item(CLEAR, "T10TET"), "2026-11-10T18:26:01Z"),
                        feature(item(CLOUDY, "T10TET"), "2026-11-08T18:25:39Z"),
                        feature(item(OLDER, "T10TET"), "2026-11-01T18:25:39Z"),
                        feature(item(EDGE, "T10TET"), "2026-10-30T18:25:39Z"),
                        feature(item(EDGE, "T10TFT"), "2026-10-30T18:25:39Z"),
                    ]
                },
            )
        if "/item/bbox/" in url:
            it = req.url.params["item"]
            assert req.url.params["assets"] == "SCL"
            if it.startswith(CLOUDY):
                return httpx.Response(200, content=npy(crop(9)))
            if it.startswith(EDGE):
                # Each tile of this pass sees half the square: together, all of it.
                m = np.zeros((96, 96), np.uint8)
                if "T10TET" in it:
                    m[:, :48] = 255
                else:
                    m[:, 48:] = 255
                return httpx.Response(200, content=npy(crop(11, m)))
            scl = np.full((96, 96), 11, np.uint8)
            # A band of cloud across the middle: an eighth of the 8 km square (rows
            # 32-63), still clear enough.
            scl[32:36] = 8
            return httpx.Response(200, content=npy(crop(scl)))
        if url.endswith(".xml") and sat.HLS in url:
            return httpx.Response(
                200,
                text="<Domains><DimensionDomain><Domain>2026-03-02/2026-11-04/P1D</Domain>"
                "</DimensionDomain></Domains>",
            )
        if sat.VIIRS in url:
            dark = "/2026-11-11/" in url
            return httpx.Response(200, content=jpeg((0, 0, 0) if dark else (90, 100, 110)))
        return httpx.Response(404)


def test_refresh_keeps_the_newest_clear_scenes_and_remembers_judged_passes(
    tmp_path: Path,
) -> None:
    up = Upstream()
    client = httpx.Client(transport=httpx.MockTransport(up))
    loc = make_location()
    res = sat.refresh(tmp_path, client, [loc], keep=3, now=NOW)
    assert res.errors == [] and res.locations == 1 and res.checked == 4
    index = sat.read_index(tmp_path / "index.json")
    assert index is not None
    assert index.viirs_date == "2026-11-10"  # today's mosaic is still black
    assert index.hls_date == "2026-11-04"
    spot = index.locations[0]
    assert (spot.id, spot.lat, spot.lon) == ("testhill", 47.0, -121.0)
    assert [s.id for s in spot.scenes] == [CLEAR, OLDER, EDGE]  # the cloudy one is out
    first = spot.scenes[0]
    assert (first.clear_pct, first.snow_pct, first.nodata_pct) == (88, 88, 0)
    assert first.hls is False and spot.scenes[1].hls is True  # HLS ends on 4 Nov
    assert len(spot.scenes[2].items) == 2  # the two half-squares make a whole
    assert sat.allowed_items(index) == {i.id for s in spot.scenes for i in s.items}

    # Stitched: the newest clear pass everywhere it saw the ground (less a cell's margin
    # round its cloud), and the band under its cloud from the newest pass that saw it.
    co = spot.composite
    assert co is not None
    assert [(x.id, x.share_pct) for x in co.layers] == [(CLEAR, 94), (EDGE, 6)]
    assert co.filled_pct == 100 and co.at_location == spot.scenes[0].time
    assert co.latest_pass == spot.scenes[0].time
    assert len(co.boundaries) == 2  # either side of the band
    assert len(co.labels) == 3  # each half of the newest pass, and the band
    w, _, e, _ = co.box
    assert all(
        round(lon, 4) in (round(w, 4), round(e, 4)) for line in co.boundaries for lon, _ in line
    )

    # Next time only the search, HLS's dates and VIIRS are asked for; passes aren't re-read.
    up.calls.clear()
    res = sat.refresh(tmp_path, client, [loc], keep=3, now=NOW)
    assert res.checked == 0 and not any("/item/bbox/" in c for c in up.calls)

    # A failed search keeps what was found, and says so.
    up.fail_search = True
    res = sat.refresh(tmp_path, client, [loc], keep=3, now=NOW)
    again = sat.read_index(tmp_path / "index.json")
    assert again is not None and len(res.errors) == 1
    assert [s.id for s in again.locations[0].scenes] == [CLEAR, OLDER, EDGE]
    assert again.locations[0].error


def test_refresh_stops_at_keep_and_drops_moved_locations(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(Upstream()))
    sat.refresh(tmp_path, client, [make_location()], keep=1, now=NOW)
    index = sat.read_index(tmp_path / "index.json")
    assert index is not None and [s.id for s in index.locations[0].scenes] == [CLEAR]
    moved = make_location(
        bands=[
            {"band": "base", "label": "Base", "lat": 48.0, "lon": -121.0, "elev_m": 1000},
            {"band": "mid", "label": "Mid", "lat": 48.0, "lon": -121.0, "elev_m": 1500},
            {"band": "summit", "label": "Top", "lat": 48.0, "lon": -121.0, "elev_m": 2000},
        ]
    )
    sat.refresh(tmp_path, client, [moved], keep=1, now=NOW)
    checked = json.loads((tmp_path / "checked.json").read_text())
    assert list(checked) == [f"testhill@48.000,-121.000#{sat.AREA_PX}"]


def test_refresh_survives_gibs_being_down(tmp_path: Path) -> None:
    up = Upstream()

    def answer(req: httpx.Request) -> httpx.Response:
        if "gibs" in str(req.url):
            return httpx.Response(503)
        return up(req)

    client = httpx.Client(transport=httpx.MockTransport(answer))
    res = sat.refresh(tmp_path, client, [make_location()], now=NOW)
    index = sat.read_index(tmp_path / "index.json")
    assert index is not None and index.viirs_date is None and index.hls_date is None
    assert len(res.errors) == 2 and index.locations[0].scenes
    assert not any(s.hls for s in index.locations[0].scenes)


# ---- the tile proxy ----------------------------------------------------------------

ITEM = item(CLEAR, "T10TET")


def test_s2_tiles_only_for_items_in_the_index(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, content=b"RIFFwebp", headers={"content-type": "image/webp"})

    cache = TileCache(tmp_path, "test", httpx.Client(transport=httpx.MockTransport(answer)))
    allowed = {ITEM}
    assert s2_tile(cache, "natural", ITEM, 12, 650, 1385, allowed) == b"RIFFwebp"
    assert s2_tile(cache, "natural", ITEM, 12, 650, 1385, allowed) == b"RIFFwebp"
    assert len(calls) == 1  # the second came from the cache
    assert "item=" + ITEM in calls[0] and "B04" in calls[0] and "@2x.webp" in calls[0]
    # The band files don't mark no data themselves: without this, off-swath is opaque black.
    assert "nodata=0" in calls[0]
    # Cached under the rendering version, so a new colour stretch is drawn afresh.
    assert (tmp_path / "s2" / f"r{S2_RENDER}" / "natural" / ITEM / "12" / "650" / "1385").exists()
    assert s2_tile(cache, "snow", ITEM, 12, 650, 1385, allowed) is not None
    assert "B11" in calls[1]
    for args in (
        ("natural", "S2C_MSIL2A_20261110T182601_R127_T10TEX_20261110T221403", 12, 650, 1385),
        ("infrared", ITEM, 12, 650, 1385),  # not a mode
        ("natural", ITEM, 7, 20, 40),  # too far out
        ("natural", ITEM, 15, 0, 0),  # too far in
        ("natural", ITEM, 12, 5000, 1385),  # not a tile
    ):
        assert s2_path(cache, *args, allowed) is None
        assert s2_tile(cache, *args, allowed) is None
    assert len(calls) == 2


def test_gibs_tiles_only_for_listed_layers_and_real_days(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "/9/" in str(req.url):
            return httpx.Response(400, text="bad zoom")
        return httpx.Response(200, content=b"jpg", headers={"content-type": "image/jpeg"})

    cache = TileCache(tmp_path, "test", httpx.Client(transport=httpx.MockTransport(answer)))
    today = date(2026, 11, 11)
    got = gibs_tile(cache, sat.VIIRS, "2026-11-10", 6, 11, 21, today)
    assert got == (b"jpg", "image/jpeg")
    assert calls[0].endswith(
        f"{sat.VIIRS}/default/2026-11-10/GoogleMapsCompatible_Level9/6/21/11.jpeg"
    )
    hls = gibs_tile(cache, sat.HLS, "2026-11-04", 12, 777, 1542, today)
    assert hls is not None and hls[1] == "image/png" and calls[1].endswith("/12/1542/777.png")
    assert gibs_tile(cache, sat.VIIRS, "2026-11-10", 9, 1, 1, today) is None  # upstream 400
    for layer, day, z in (
        ("MODIS_Terra_CorrectedReflectance_TrueColor", "2026-11-10", 6),
        (sat.VIIRS, "2026-11-13", 6),  # the future
        (sat.VIIRS, "2026-02-30", 6),  # not a day
        (sat.VIIRS, "../../etc", 6),
        (sat.VIIRS, "2026-11-10", 10),  # VIIRS stops at 9
    ):
        assert gibs_path(cache, layer, day, z, 1, 1, today) is None
    assert len(calls) == 3


def test_api_serves_the_index_and_proxies_tiles(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/sat").status_code == 503
    assert client.get(f"/api/tiles/s2/natural/{ITEM}/12/650/1385.webp").status_code == 404

    up = Upstream()
    sat.refresh(
        settings.sat_dir,
        httpx.Client(transport=httpx.MockTransport(up)),
        [make_location()],
        now=NOW,
    )
    r = client.get("/api/sat")
    assert r.status_code == 200
    body = r.json()
    assert body["viirs_date"] == "2026-11-10" and body["locations"][0]["scenes"][0]["id"] == CLEAR
    assert "Copernicus" in " ".join(body["attribution"])

    monkeypatch.setattr(TileCache, "through", lambda self, path, url, fix=False: b"tile")
    r = client.get(f"/api/tiles/s2/natural/{ITEM}/12/650/1385.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert client.get(f"/api/tiles/s2/natural/{ITEM[:-1]}X/12/650/1385.webp").status_code == 404
    r = client.get(f"/api/tiles/gibs/{sat.VIIRS}/2026-11-10/6/11/21")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/api/tiles/gibs/nope/2026-11-10/6/11/21").status_code == 404

    monkeypatch.setattr(TileCache, "through", lambda self, path, url, fix=False: None)
    assert client.get(f"/api/tiles/s2/snow/{ITEM}/12/650/1386.webp").status_code == 404
    assert client.get(f"/api/tiles/gibs/{sat.VIIRS}/2026-11-10/6/11/22").status_code == 404


def test_worker_looks_for_scenes_and_survives_failures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from snowwatch import cli
    from snowwatch.scheduler import Worker, build_scheduler
    from tests.helpers import config

    calls: list[dict[str, Any]] = []

    def refresh(sat_dir: Path, client: Any, locs: Any, **kw: Any) -> sat.SatResult:
        calls.append(kw)
        return sat.SatResult(locations=len(locs), errors=["one went wrong"])

    monkeypatch.setattr(sat, "refresh", refresh)
    w = Worker(settings, config())
    w.satellite()
    assert calls == [{"days": 30, "min_clear": 0.7, "max_nodata": 0.1, "keep": 3}]
    w.sat_lock.acquire()
    w.satellite()  # still running from last time: skip
    assert len(calls) == 1
    w.sat_lock.release()
    assert "satellite" in {j.id for j in build_scheduler(w).get_jobs()}

    def broken(*a: Any, **kw: Any) -> sat.SatResult:
        raise RuntimeError("Planetary Computer fell over")

    monkeypatch.setattr(sat, "refresh", broken)
    w.satellite()  # logged, not raised
    monkeypatch.setattr(sat, "refresh", refresh)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["map", "sat"]) == 0 and len(calls) == 2


# ---- stitching -----------------------------------------------------------------------

N = sat.AREA_PX
BOX = (-121.0, 47.0, -120.0, 48.0)


def grid(fill: int = sat.G_CLEAR) -> np.ndarray:
    return np.full((N, N), fill, np.uint8)


def pass_(day: int) -> sat.Pass:
    pid = f"S2A_MSIL2A_202611{day:02d}T190000_R013"
    return sat.Pass(
        pid,
        datetime(2026, 11, day, 19, tzinfo=UTC),
        "Sentinel-2A",
        [sat.SatItem(id=f"{pid}_T10TFT_202611{day:02d}T220000", bbox=[-122.0, 46.5, -119.5, 48.5])],
    )


def test_stitch_takes_each_cell_from_the_newest_pass_that_saw_it() -> None:
    # The newest pass's swath ends a third of the way across (a strip like Snoqualmie's
    # on 21 Oct); an older pass is clear everywhere.
    strip = grid()
    strip[:, N // 3 :] = sat.G_NODATA
    co = sat.stitch([(pass_(10), strip), (pass_(1), grid(sat.G_SNOW))], BOX)
    assert [x.id for x in co.layers] == [pass_(10).id, pass_(1).id]
    assert [x.share_pct for x in co.layers] == [33, 67]
    assert co.filled_pct == 100
    assert co.at_location == pass_(1).time  # the middle is past the strip
    # One dividing line, straight down at the strip's edge, and a date on each side.
    assert len(co.boundaries) == 1
    (lon0, lat0), (lon1, lat1) = co.boundaries[0]
    assert lon0 == lon1 == round(-121 + (N // 3) / N, 5) and {lat0, lat1} == {47.0, 48.0}
    assert sorted(lb.time.day for lb in co.labels) == [1, 10]
    # The newest pass's part, with a cell's margin, for the map to draw it over.
    assert co.layers[0].bbox[0] == -121.0 and co.layers[0].bbox[2] > -121 + 1 / 3


def test_stitch_cuts_round_cloud_and_skips_cloudy_passes() -> None:
    cloudy = grid(sat.G_CLOUD)
    holey = grid()
    holey[40:56, 40:56] = sat.G_CLOUD
    co = sat.stitch(
        [(pass_(11), cloudy), (pass_(10), holey), (pass_(1), grid())], BOX, pass_(11).time
    )
    assert [x.id for x in co.layers] == [pass_(10).id, pass_(1).id]
    # The older pass fills the hole and a cell's margin all round it: 18 x 18 cells.
    assert co.layers[1].share_pct == round(18 * 18 / N**2 * 100)
    assert co.at_location == pass_(1).time  # the middle was under the cloud
    assert co.latest_pass == pass_(11).time


def test_stitch_keeps_a_small_strip_at_the_location_but_not_scraps_elsewhere() -> None:
    near = grid(sat.G_NODATA)
    near[40:56, 44:52] = sat.G_CLEAR  # 128 cells, 1.4% of the area, 12% of the 8 km square
    far = grid(sat.G_NODATA)
    far[0:12, 0:12] = sat.G_CLEAR  # 144 cells, 1.6% of the area, far from the location
    co = sat.stitch([(pass_(12), far), (pass_(11), near), (pass_(1), grid())], BOX)
    assert [x.id for x in co.layers] == [pass_(11).id, pass_(1).id]
    assert co.at_location == pass_(11).time


def test_stitch_drops_specks_and_stops_at_its_limits() -> None:
    specks = grid(sat.G_NODATA)
    specks[::8, ::8] = sat.G_CLEAR  # single cells everywhere: noise, not ground
    co = sat.stitch([(pass_(12), specks), (pass_(1), grid())], BOX)
    assert [x.id for x in co.layers] == [pass_(1).id]
    # One column band each from nine passes: at most MAX_LAYERS of them are used.
    bands = []
    for i in range(9):
        g = grid(sat.G_NODATA)
        g[:, i * 10 : i * 10 + 10] = sat.G_CLEAR
        bands.append((pass_(20 - i), g))
    co = sat.stitch(bands, BOX)
    assert len(co.layers) == sat.MAX_LAYERS
    # Nothing clear at all: no layers, and nothing seen at the location.
    co = sat.stitch([(pass_(5), grid(sat.G_CLOUD))], BOX)
    assert co.layers == [] and co.at_location is None and co.filled_pct == 0


def test_chain_joins_segments_and_drops_straight_middles() -> None:
    segs = [((0, 0), (0, 1)), ((0, 1), (0, 2)), ((0, 2), (1, 2)), ((5, 5), (6, 5))]

    def same(line: list[tuple[int, int]]) -> list[tuple[int, int]]:
        return min(line, line[::-1])  # either direction

    lines = sorted((same(x) for x in sat.chain(segs)), key=len)
    assert lines == [[(5, 5), (6, 5)], [(0, 0), (0, 2), (1, 2)]]


# ---- cloud cut out of tiles ------------------------------------------------------------


def test_erode_shrinks_clear_ground_but_not_at_the_tile_edge() -> None:
    clear = np.ones((20, 20), bool)
    clear[8:12, 8:12] = False
    out = sat_erode(clear, 2)
    assert not out[6:14, 6:14].any() and out[:6].all() and out[14:].all()
    assert out[0, 0] and out[19, 19]  # the edge isn't eaten into
    assert (sat_erode(clear, 0) == clear).all()


def sat_erode(m: np.ndarray, r: int) -> np.ndarray:
    from snowwatch.tiles import erode

    return erode(m, r)


def webp(rgba: tuple[int, int, int, int], n: int = 512) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (n, n), rgba).save(buf, "WEBP", lossless=True)
    return buf.getvalue()


def mask_png(cloud: slice, n: int = 512) -> bytes:
    a = np.full((n, n, 2), 255, np.uint8)
    a[cloud, :, 0] = 0
    buf = io.BytesIO()
    Image.fromarray(a, "LA").save(buf, "PNG")
    return buf.getvalue()


def test_cut_clouds_makes_cloud_and_a_margin_transparent() -> None:
    from snowwatch.tiles import cut_clouds

    out = Image.open(
        io.BytesIO(cut_clouds(webp((50, 90, 60, 255)), mask_png(slice(0, 100)), 14, 5733))
    )
    alpha = np.asarray(out.convert("RGBA"))[..., 3]
    # 512 px tiles at zoom 14 here are ~3.2 m a pixel: an 80 m margin is 24 (the cap).
    assert (alpha[:124] == 0).all()
    assert (alpha[125:] == 255).all()


def test_clear_tiles_cut_cloud_once_and_are_cached(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if ".png" in str(req.url):
            return httpx.Response(
                200, content=mask_png(slice(0, 256)), headers={"content-type": "image/png"}
            )
        return httpx.Response(
            200, content=webp((10, 20, 30, 255)), headers={"content-type": "image/webp"}
        )

    from snowwatch.tiles import s2_clear_path, s2_clear_tile

    cache = TileCache(tmp_path, "test", httpx.Client(transport=httpx.MockTransport(answer)))
    allowed = {ITEM}
    data = s2_clear_tile(cache, "natural", ITEM, 13, 1333, 2866, allowed)
    assert data is not None
    alpha = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))[..., 3]
    assert (alpha[:256] == 0).all() and (alpha[-1] == 255).all()
    assert len(calls) == 2 and "SCL_b1" in calls[1].replace("%5F", "_")
    assert s2_clear_tile(cache, "natural", ITEM, 13, 1333, 2866, allowed) == data
    assert len(calls) == 2  # from the cache
    assert s2_clear_path(cache, "natural", "S2X_unknown", 13, 1, 1, allowed) is None
    assert s2_clear_tile(cache, "natural", ITEM, 7, 1, 1, allowed) is None


def test_api_serves_clear_tiles_for_stitched_items(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sat.refresh(
        settings.sat_dir,
        httpx.Client(transport=httpx.MockTransport(Upstream())),
        [make_location()],
        now=NOW,
    )
    client = TestClient(create_app(settings))
    edge_item = item(EDGE, "T10TFT")  # only in the stitched view, not a kept scene
    monkeypatch.setattr("snowwatch.api.app.s2_clear_tile", lambda *a: b"clear")
    r = client.get(f"/api/tiles/s2c/natural/{edge_item}/12/650/1385.webp?r=2")
    assert r.status_code == 200 and r.content == b"clear"
    assert client.get("/api/tiles/s2c/natural/nope/12/650/1385.webp").status_code == 404
    monkeypatch.setattr("snowwatch.api.app.s2_clear_tile", lambda *a: None)
    assert client.get(f"/api/tiles/s2c/natural/{edge_item}/12/650/1386.webp").status_code == 404


def test_small_patches_get_no_dividing_line() -> None:
    owner = np.zeros((N, N), np.int16)
    owner[:, N // 2 :] = 1  # two big halves: one line between them
    owner[10:14, 10:14] = 1  # a 16-cell island of the other pass: no box round it
    lines = sat.boundaries(sat.outlined(owner))
    assert lines == [[(0, N // 2), (N, N // 2)]] or lines == [[(N, N // 2), (0, N // 2)]]
