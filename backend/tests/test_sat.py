"""Recent satellite imagery: judging passes, stitching, drawing views, the index and API."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from snowwatch.api.app import create_app
from snowwatch.maps import sat, satrender
from snowwatch.settings import Settings
from snowwatch.tiles import TileCache, gibs_path, gibs_tile
from tests.conftest import make_location

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
N = sat.AREA_PX


def npy(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, a)
    return buf.getvalue()


def jpeg(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), color).save(buf, "JPEG")
    return buf.getvalue()


def image(mode: str, n: int, color: Any, fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (n, n), color).save(buf, fmt)
    return buf.getvalue()


def item(pid: str, tile: str, processed: str = "20261110T221403") -> str:
    return f"{pid}_{tile}_{processed}"


def feature(fid: str, when: str, bbox: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": fid,
        "bbox": bbox or [-121.5, 46.5, -120.5, 47.5],
        "properties": {"datetime": when, "platform": f"Sentinel-2{fid[2]}"},
    }


@pytest.fixture
def small(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small pictures and two zooms, so drawing views in tests is quick."""
    monkeypatch.setattr(satrender, "PX", 64)
    monkeypatch.setattr(satrender, "HALF", 32)
    monkeypatch.setattr(satrender, "ZOOMS", range(9, 11))


# ---- judging a pass -------------------------------------------------------------


def test_classify_reads_scl_and_catches_bright_cloud_it_missed() -> None:
    scl = np.array([[0, 4, 9, 11, 4, 11]])
    blue = np.array([[0, 1500, 6000, 9000, 4500, 9000]])
    swir = np.array([[0, 2500, 6000, 1800, 4000, 3600]])
    g = sat.classify(scl, blue, swir)
    # no data, ground, cloud (SCL), snow (bright but dark in SWIR), cloud SCL called
    # ground (bright in both), and "snow" bright in both: cloud.
    assert g.tolist() == [[0, 1, 2, 3, 2, 2]]
    assert sat.classify(scl).tolist() == [[0, 1, 2, 3, 1, 3]]  # SCL alone


def test_judge_and_merge() -> None:
    g = np.full((N, N), sat.G_CLEAR, np.uint8)
    g[: N // 4] = sat.G_CLOUD
    g[N // 4 : N // 2] = sat.G_SNOW
    look = sat.judge_grid(g)
    assert look.clear == pytest.approx(0.75) and look.snow == pytest.approx(0.25)
    assert look.nodata == 0
    half = g.copy()
    half[:, N // 2 :] = sat.G_NODATA
    assert sat.judge_grid(half).nodata == pytest.approx(0.5)
    assert sat.judge_grid(np.zeros((4, 4), np.uint8)) == sat.Look(clear=0, nodata=1, snow=0)
    other = np.full((N, N), sat.G_SNOW, np.uint8)
    merged = sat.merge_grids([half, other])
    assert (merged[:, N // 2 :] == sat.G_SNOW).all() and (
        merged[:, : N // 2] == half[:, : N // 2]
    ).all()
    with pytest.raises(ValueError):
        sat.merge_grids([])
    # With band values, the cells (first band) decide.
    a = np.stack([half, np.full((N, N), 7)]).astype(np.uint16)
    b = np.stack([other, np.full((N, N), 9)]).astype(np.uint16)
    m3 = sat.merge_grids([a, b])
    assert (m3[1, :, N // 2 :] == 9).all() and (m3[1, :, : N // 2] == 7).all()


def bands(cells: np.ndarray, blue: int, green: int = 1400, swir: int = 2200) -> np.ndarray:
    return np.stack(
        [cells, np.full(cells.shape, blue), np.full(cells.shape, green), np.full(cells.shape, swir)]
    ).astype(np.uint16)


def test_dehaze_marks_hazy_ground_but_not_snow_or_a_lone_pass() -> None:
    clear = np.full((N, N), sat.G_CLEAR, np.uint8)
    hazy = bands(clear, 1000 + 1300)  # blue 0.13 over ground another pass saw at 0.04
    crisp = bands(clear, 1000 + 400)
    snowy = bands(clear, 1000 + 7000, green=1000 + 7500, swir=1000 + 900)  # NDSI 0.8
    out = sat.dehaze([hazy, crisp, snowy])
    assert (out[0] == sat.G_HAZE).all()
    assert (out[1] == sat.G_CLEAR).all() and (out[2] == sat.G_CLEAR).all()
    # One pass alone can't be judged: left as it is.
    assert (sat.dehaze([hazy])[0] == sat.G_CLEAR).all()
    # New partial snow lifts blue too, but lowers SWIR: not haze.
    patchy = bands(clear, 1000 + 1300, swir=2200 - 400)
    assert (sat.dehaze([patchy, crisp])[0] == sat.G_CLEAR).all()
    assert sat.dehaze([]) == []


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


def test_the_area_is_square_on_the_ground() -> None:
    x0, y0, x1, y1 = sat.area_box(60.0, -120.0)
    assert x1 - x0 == pytest.approx(48_000, rel=1e-3)  # 24 km / cos 60°
    _, s, _, n = sat.box_lonlat((x0, y0, x1, y1))
    assert (n - s) * 111.32 == pytest.approx(24, rel=0.01)
    lat, lon = sat.unmerc(*sat.merc(47.4, -121.4))
    assert (lat, lon) == pytest.approx((47.4, -121.4))


def test_viirs_tile_check_tells_black_from_imagery() -> None:
    assert not sat.has_imagery(jpeg((0, 0, 0)))
    assert sat.has_imagery(jpeg((120, 130, 140)))
    assert not sat.has_imagery(b"not an image")
    assert sat.tile_xy(0, 0, 1) == (1, 1)


# ---- stitching -----------------------------------------------------------------------


def grid(fill: int = sat.G_CLEAR) -> np.ndarray:
    return np.full((N, N), fill, np.uint8)


def pass_(day: int, month: int = 11) -> sat.Pass:
    pid = f"S2A_MSIL2A_2026{month:02d}{day:02d}T190000_R013"
    return sat.Pass(
        pid,
        datetime(2026, month, day, 19, tzinfo=UTC),
        "Sentinel-2A",
        [
            sat.SatItem(
                id=f"{pid}_T10TFT_2026{month:02d}{day:02d}T220000", bbox=[-122, 46, -120, 48]
            )
        ],
    )


def test_stitch_takes_each_part_from_the_newest_pass_that_saw_it() -> None:
    # The newest pass's swath ends a third of the way across (like Snoqualmie's 21 Oct);
    # an older pass is clear everywhere.
    strip = grid()
    strip[:, N // 3 :] = sat.G_NODATA
    plan = sat.stitch([(pass_(10), strip), (pass_(1), grid(sat.G_SNOW))], latest=pass_(10).time)
    assert [p.id for p in plan.layers] == [pass_(10).id, pass_(1).id]
    assert plan.filled() == 1
    assert (plan.owner[:, : N // 3] == 0).all() and (plan.owner[:, N // 3 :] == 1).all()


def test_stitch_skips_mostly_cloudy_passes_and_fills_from_the_whole_scene() -> None:
    cloudy = grid(sat.G_CLOUD)
    cloudy[:4, :4] = sat.G_CLEAR  # a gap in the cloud: likely haze, not to be trusted
    holey = grid()
    holey[40:56, 40:56] = sat.G_CLOUD
    plan = sat.stitch([(pass_(11), cloudy), (pass_(10), holey)], fallback=[(pass_(1, 10), grid())])
    assert [p.id for p in plan.layers] == [pass_(10).id, pass_(1, 10).id]
    # The whole scene fills the hole, and a cell's margin round it.
    assert (plan.owner == 1).sum() == 18 * 18
    assert plan.filled() == 1


def test_stitch_keeps_a_small_strip_at_the_location_but_not_scraps_elsewhere() -> None:
    near = grid(sat.G_NODATA)
    near[38:58, 42:54] = sat.G_CLEAR  # 240 cells: 2.6% of the area, but at the location
    far = grid(sat.G_NODATA)
    far[0:12, 0:12] = sat.G_CLEAR  # 144 cells, 1.6% of the area, far from it
    plan = sat.stitch([(pass_(12), far), (pass_(11), near), (pass_(1), grid())])
    assert [p.id for p in plan.layers] == [pass_(11).id, pass_(1).id]
    assert plan.owner[N // 2, N // 2] == 0


def test_stitch_makes_compact_parts() -> None:
    # The newest pass saw a checkerboard of 4-cell blocks: on its own that's confetti.
    # Compacting gives its scraps to the older clear pass instead.
    board = grid(sat.G_NODATA)
    for r in range(0, N, 8):
        for c in range(0, N, 8):
            board[r : r + 4, c : c + 4] = sat.G_CLEAR
    board[:, : N // 2] = sat.G_CLEAR  # and a solid half
    plan = sat.stitch([(pass_(12), board), (pass_(1), grid())])
    assert (plan.owner[:, : N // 2 - 3] == 0).all()
    right = plan.owner[:, N // 2 + 3 :]
    assert (right == 1).mean() > 0.95  # the confetti side is the older pass, nearly all


def test_stitch_stops_at_its_layer_limit_and_handles_nothing_clear() -> None:
    bands = []
    for i in range(9):
        g = grid(sat.G_NODATA)
        g[:, i * 10 : i * 10 + 10] = sat.G_CLEAR
        bands.append((pass_(20 - i), g))
    assert len(sat.stitch(bands).layers) == sat.MAX_LAYERS
    plan = sat.stitch([(pass_(5), grid(sat.G_CLOUD))])
    assert plan.layers == [] and plan.filled() == 0


def test_rings_and_polygons() -> None:
    m = np.zeros((6, 6), bool)
    m[1:5, 1:5] = True
    m[2:4, 2:4] = False  # a hole
    rings = sat.rings(m)
    areas = sorted(sat.signed_area(r) for r in rings)
    assert areas == [-4, 16]
    polys = sat.polygons(m, min_hole=1)
    assert len(polys) == 1 and len(polys[0]) == 2  # outer ring and its hole
    # Cells touching only at a corner are two regions, not one figure-of-eight.
    d = np.zeros((4, 4), bool)
    d[0, 0] = d[1, 1] = True
    assert len(sat.rings(d)) == 2 and len(sat.polygons(d)) == 2


def test_lines_only_where_two_parts_meet() -> None:
    owner = np.full((N, N), -1, np.int16)
    owner[:, : N // 2] = 0
    owner[:, N // 2 :] = 1
    owner[: N // 4, :] = -1  # a cloudy band with no pass: no line along it
    lines = sat.boundaries(owner)
    assert len(lines) == 1
    xs = {x for x, _ in lines[0]}
    ys = {y for _, y in lines[0]}
    assert xs == {N // 2} and min(ys) == N // 4 and max(ys) == N


def test_composite_out_dates_parts_and_draws_lines(tmp_path: Path) -> None:
    strip = grid()
    strip[:, N // 2 :] = sat.G_NODATA
    plan = sat.stitch([(pass_(10), strip), (pass_(1), grid())], latest=pass_(11).time)
    box = sat.area_box(47.0, -121.0)
    co = sat.composite_out(plan, "0123456789abcdef", box)
    assert [(x.id, x.share_pct) for x in co.layers] == [(pass_(10).id, 50), (pass_(1).id, 50)]
    assert [p.time.day for p in co.parts] == [10, 1]
    assert co.at_location == pass_(1).time  # the middle cell is just east of the strip
    assert co.latest_pass == pass_(11).time and co.filled_pct == 100
    assert len(co.lines) == 1
    lon_mid = (sat.box_lonlat(box)[0] + sat.box_lonlat(box)[2]) / 2
    assert all(abs(lon - lon_mid) < 1e-3 for lon, _ in co.lines[0])
    w, s, e, n = sat.box_lonlat(box)
    for ring in co.parts[0].polygons[0]:
        assert all(w - 1e-5 <= lon <= e + 1e-5 and s - 1e-5 <= lat <= n + 1e-5 for lon, lat in ring)


# ---- drawing views -----------------------------------------------------------------


def test_choose_prefers_the_part_then_fills_gaps_from_the_newest() -> None:
    owner = np.full((N, N), 1, np.int16)
    owner[:, : N // 2] = 0
    size = 64
    ok0 = np.ones((size, size), bool)
    ok0[:8, :8] = False  # a cloud gap in the newest pass's part
    ok1 = np.ones((size, size), bool)
    choice = satrender.choose(owner, [ok0, ok1])
    assert (choice[20:, :28] == 0).all() and (choice[:, 36:] == 1).all()
    assert (choice[:8, :8] == 1).all()  # filled from the other pass
    none = [np.zeros((size, size), bool)] * 2
    assert satrender.choose(owner, none).max() == -1
    # Cloud in every pass: each pass's own picture of it, its part's pass first.
    seen = [np.ones((size, size), bool)] * 2
    filled = satrender.choose(owner, none, seen)
    assert (filled[:, :28] == 0).all() and (filled[:, 36:] == 1).all()


def test_gaps_are_filled_from_the_pass_nearest_in_time() -> None:
    owner = np.full((N, N), 2, np.int16)  # all the oldest pass's part
    size = 32
    gap = np.ones((size, size), bool)
    gap[:8, :8] = False
    full = np.ones((size, size), bool)
    choice = satrender.choose(owner, [full, full, gap])
    # Pass 1 is nearer in time to pass 2 than the newest (0) is.
    assert (choice[:8, :8] == 1).all() and (choice[8:, 8:] == 2).all()


def test_grow_and_upsample() -> None:
    m = np.zeros((9, 9), bool)
    m[4, 4] = True
    assert satrender.grow(m, 2).sum() == 25 and satrender.grow(m, 0).sum() == 1
    assert satrender.upsample2(m).shape == (18, 18) and satrender.upsample2(m).sum() == 4


def test_cut_puts_the_picture_in_the_right_tiles(tmp_path: Path) -> None:
    r = satrender.Renderer(tmp_path, httpx.Client())
    box = sat.area_box(47.424, -121.418)
    px = 240
    a = np.zeros((px, px, 4), np.uint8)
    a[..., :3] = (200, 30, 30)
    a[..., 3] = 255
    a[px // 2 - 5 : px // 2 + 5, px // 2 - 5 : px // 2 + 5, :3] = (30, 30, 200)  # the middle
    count = r.cut(a, box, tmp_path / "out")
    assert count == len(list((tmp_path / "out").rglob("*.webp"))) > 0
    # The middle pixel is in the zoom-13 tile under the location, and blue.
    z = 13
    lat, lon = sat.unmerc((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    tx, ty = sat.tile_xy(lat, lon, z)
    tile = np.asarray(
        Image.open(tmp_path / "out" / str(z) / str(tx) / f"{ty}.webp").convert("RGBA")
    )
    half = satrender.WORLD / 2
    span = satrender.WORLD / 2**z
    mx, my = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    u = int((mx + half - tx * span) / span * 512)
    v = int((half - my - ty * span) / span * 512)
    assert tile[v, u, 2] > 150 and tile[v, u, 0] < 90
    # Tiles round the picture are partly transparent; none beyond it are written.
    assert all((tmp_path / "out" / str(zz)).exists() for zz in satrender.ZOOMS)


def test_view_names_change_with_what_they_show() -> None:
    box = sat.area_box(47.0, -121.0)
    a = satrender.view_id("scene", box, ["x"])
    assert a == satrender.view_id("scene", box, ["x"]) and re.fullmatch(r"[0-9a-f]{16}", a)
    assert a != satrender.view_id("scene", box, ["y"])
    assert a != satrender.view_id("stitched", box, ["x"])


# ---- the refresh, end to end (small pictures) -----------------------------------------

NEWEST = "S2C_MSIL2A_20261110T182601_R127"  # its swath covers the west half
CLOUDY = "S2B_MSIL2A_20261108T182539_R084"
FULL = "S2A_MSIL2A_20261101T182539_R127"  # clear everywhere: a whole scene
COLORS = {NEWEST: (200, 40, 40), FULL: (40, 40, 200), CLOUDY: (240, 240, 240)}


class Upstream:
    """Planetary Computer and GIBS, as far as the refresh uses them."""

    def __init__(self, lat: float = 47.0, lon: float = -121.0) -> None:
        self.calls: list[str] = []
        self.fail_search = False
        box = sat.area_box(lat, lon)
        self.mid_x = (box[0] + box[2]) / 2

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
                        feature(item(NEWEST, "T10TET"), "2026-11-10T18:26:01Z"),
                        feature(item(CLOUDY, "T10TET"), "2026-11-08T18:25:39Z"),
                        feature(item(FULL, "T10TET"), "2026-11-01T18:25:39Z"),
                    ]
                },
            )
        if "/item/bbox/" in url:
            it = req.url.params["item"]
            pid = sat.pass_id(it)
            x0 = float(url.split("/item/bbox/")[1].split(",")[0])
            if url.split("?")[0].endswith(".npy"):  # the grid
                assert req.url.params.get_list("assets") == ["SCL", "B02", "B03", "B11"]
                a = np.zeros((5, N, N), np.uint16)
                a[4] = 255
                a[1], a[2], a[3] = 1500, 1600, 2000
                if pid == CLOUDY:
                    a[0] = 9
                elif pid == FULL:
                    a[0] = 11
                else:
                    a[0, :, : N // 2] = 4  # the east half has no data
                return httpx.Response(200, content=npy(a))
            size = int(re.search(r"/(\d+)x\d+\.", url).group(1))  # type: ignore[union-attr]
            east = x0 >= self.mid_x - 1  # a quarter in the east half of the area
            if url.split("?")[0].endswith(".png"):  # the cloud mask
                v = 0 if pid == CLOUDY else 255
                return httpx.Response(200, content=image("LA", size, (v, 255), "PNG"))
            alpha = 0 if (pid == NEWEST and east) else 255
            return httpx.Response(200, content=image("RGBA", size, (*COLORS[pid], alpha), "WEBP"))
        if sat.VIIRS in url:
            dark = "/2026-11-11/" in url
            return httpx.Response(200, content=jpeg((0, 0, 0) if dark else (90, 100, 110)))
        return httpx.Response(404)


def tile_colors(view_dir: Path) -> set[str]:
    """Which of the passes' colours a view's tiles show."""
    seen = set()
    for f in view_dir.rglob("*.webp"):
        a = np.asarray(Image.open(f).convert("RGBA")).reshape(-1, 4)
        a = a[a[:, 3] > 200]
        if (a[:, 0] > 150).any():
            seen.add("red")
        if (a[:, 2] > 150).any():
            seen.add("blue")
    return seen


def test_refresh_chooses_and_draws_views(tmp_path: Path, small: None) -> None:
    up = Upstream()
    client = httpx.Client(transport=httpx.MockTransport(up))
    res = sat.refresh(tmp_path, client, [make_location()], now=NOW)
    assert res.errors == [] and res.locations == 1 and res.checked == 3 and res.fetched > 0
    index = sat.read_index(tmp_path / "index.json")
    assert index is not None and index.viirs_date == "2026-11-10"  # today's is still black
    spot = index.locations[0]
    assert (spot.id, spot.lat, spot.lon) == ("testhill", 47.0, -121.0)
    assert spot.box == pytest.approx(sat.box_lonlat(sat.area_box(47.0, -121.0)))
    # Whole scenes: only the pass that covers the whole area (the newest covers half).
    assert [s.id for s in spot.scenes] == [FULL]
    assert (spot.scenes[0].clear_pct, spot.scenes[0].snow_pct) == (100, 100)
    # Stitched: the newest half, then the whole scene; the cloudy pass isn't used.
    co = spot.composite
    assert co is not None
    assert [x.id for x in co.layers] == [NEWEST, FULL] and co.filled_pct == 100
    assert co.latest_pass == datetime(2026, 11, 10, 18, 26, 1, tzinfo=UTC)
    assert len(co.parts) == 2 and len(co.lines) == 1
    views = tmp_path / "views"
    assert (views / co.view / "done").exists() and (views / spot.scenes[0].view / "done").exists()
    assert tile_colors(views / co.view / "natural") == {"red", "blue"}
    assert tile_colors(views / spot.scenes[0].view / "snow") == {"blue"}
    assert {d.name for d in views.iterdir()} == {co.view, spot.scenes[0].view}

    # Next time nothing is fetched: passes, pictures and views are all kept.
    up.calls.clear()
    res = sat.refresh(tmp_path, client, [make_location()], now=NOW)
    assert res.checked == 0 and res.fetched == 0
    assert not any("/item/bbox/" in c for c in up.calls)

    # A failed search keeps what was found, and says so.
    up.fail_search = True
    res = sat.refresh(tmp_path, client, [make_location()], now=NOW)
    again = sat.read_index(tmp_path / "index.json")
    assert again is not None and len(res.errors) == 1 and again.locations[0].error
    assert again.locations[0].composite == co and [s.id for s in again.locations[0].scenes] == [
        FULL
    ]
    assert (views / co.view / "done").exists()  # its views are kept too


def test_refresh_forgets_moved_locations(tmp_path: Path, small: None) -> None:
    client = httpx.Client(transport=httpx.MockTransport(Upstream()))
    sat.refresh(tmp_path, client, [make_location()], now=NOW)
    moved = make_location(
        bands=[
            {"band": "base", "label": "Base", "lat": 48.0, "lon": -121.0, "elev_m": 1000},
            {"band": "mid", "label": "Mid", "lat": 48.0, "lon": -121.0, "elev_m": 1500},
            {"band": "summit", "label": "Top", "lat": 48.0, "lon": -121.0, "elev_m": 2000},
        ]
    )
    sat.refresh(
        tmp_path, httpx.Client(transport=httpx.MockTransport(Upstream(48.0))), [moved], now=NOW
    )
    checked = json.loads((tmp_path / "checked.json").read_text())
    assert list(checked) == [sat._spot_key("testhill", 48.0, -121.0)]
    assert len(list((tmp_path / "crops").iterdir())) == 1  # the old spot's pictures went


def test_refresh_survives_gibs_being_down(tmp_path: Path, small: None) -> None:
    up = Upstream()

    def answer(req: httpx.Request) -> httpx.Response:
        if "gibs" in str(req.url):
            return httpx.Response(503)
        return up(req)

    res = sat.refresh(
        tmp_path, httpx.Client(transport=httpx.MockTransport(answer)), [make_location()], now=NOW
    )
    index = sat.read_index(tmp_path / "index.json")
    assert index is not None and index.viirs_date is None
    assert res.errors == ["VIIRS: no day with imagery in the last four"]
    assert index.locations[0].composite is not None


# ---- serving --------------------------------------------------------------------------


def test_gibs_tiles_only_for_listed_layers_and_real_days(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "/9/" in str(req.url):
            return httpx.Response(400, text="bad zoom")
        return httpx.Response(200, content=b"jpg", headers={"content-type": "image/jpeg"})

    cache = TileCache(tmp_path, "test", httpx.Client(transport=httpx.MockTransport(answer)))
    today = date(2026, 11, 11)
    assert gibs_tile(cache, sat.VIIRS, "2026-11-10", 6, 11, 21, today) == (b"jpg", "image/jpeg")
    assert calls[0].endswith(
        f"{sat.VIIRS}/default/2026-11-10/GoogleMapsCompatible_Level9/6/21/11.jpeg"
    )
    assert gibs_tile(cache, sat.VIIRS_SNOW, "2026-11-10", 6, 11, 21, today) is not None
    assert gibs_tile(cache, sat.VIIRS, "2026-11-10", 9, 1, 1, today) is None  # upstream 400
    for layer, day, z in (
        ("HLS_S30_Nadir_BRDF_Adjusted_Reflectance", "2026-11-04", 6),  # not offered now
        (sat.VIIRS, "2026-11-13", 6),  # the future
        (sat.VIIRS, "2026-02-30", 6),  # not a day
        (sat.VIIRS, "../../etc", 6),
        (sat.VIIRS, "2026-11-10", 10),  # VIIRS stops at 9
    ):
        assert gibs_path(cache, layer, day, z, 1, 1, today) is None
    assert len(calls) == 3


def test_api_serves_the_index_compressed_and_the_drawn_tiles(
    settings: Settings, small: None
) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/sat").status_code == 503
    sat.refresh(
        settings.sat_dir,
        httpx.Client(transport=httpx.MockTransport(Upstream())),
        [make_location()],
        now=NOW,
    )
    r = client.get("/api/sat", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    body = r.json()
    assert body["viirs_date"] == "2026-11-10" and body["zooms"] == [9, 10]
    assert "Copernicus" in " ".join(body["attribution"])
    view = body["locations"][0]["composite"]["view"]
    tile = next((settings.sat_dir / "views" / view / "natural").rglob("*.webp"))
    z, x, y = tile.parent.parent.name, tile.parent.name, tile.stem
    r = client.get(f"/api/sat/tiles/{view}/natural/{z}/{x}/{y}.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers["cache-control"]
    for bad in (
        f"/api/sat/tiles/{view}/natural/{z}/{x}/{int(y) + 99}.webp",  # not drawn
        f"/api/sat/tiles/{view}/infrared/{z}/{x}/{y}.webp",
        f"/api/sat/tiles/notahexname/natural/{z}/{x}/{y}.webp",
        f"/api/sat/tiles/{view}/natural/3/99/0.webp",  # not a tile
    ):
        assert client.get(bad).status_code == 404
    r = client.get(f"/api/tiles/gibs/{sat.VIIRS}/2026-11-10/6/99/99")
    assert r.status_code in (200, 404)  # proxied (upstream not reachable in tests)
    assert client.get("/api/tiles/gibs/nope/2026-11-10/6/11/21").status_code == 404


def test_worker_looks_for_imagery_and_survives_failures(
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
    assert calls == [
        {"days": 30, "scene_days": 60, "min_clear": 0.85, "max_nodata": 0.03, "keep": 3}
    ]
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
