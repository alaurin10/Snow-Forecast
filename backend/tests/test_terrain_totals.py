"""Milestone 8 of the map: snow totals by elevation and the terrain-adjusted tiles."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from snowwatch.analysis.backcountry import BackcountryConfig
from snowwatch.api.app import create_app
from snowwatch.config import SlrBand
from snowwatch.maps import bins, point, terrain_totals, tiles_render, totals
from snowwatch.maps.geomet import ts_iso
from snowwatch.maps.palette import TOTAL, hex_rgb
from snowwatch.maps.region import box_region, merc_x, merc_y
from snowwatch.maps.render import Renderer
from snowwatch.maps.sources import nbm, rdps_gdps
from snowwatch.settings import Settings
from tests.test_forecast_maps import BANDS, T0, FakeNbm, H, ModelsNet

DEFAULT_BANDS = [
    SlrBand(min_c=-0.556, ratio=8, label="Heavy & wet"),
    SlrBand(min_c=-3.333, ratio=11, label="Average"),
    SlrBand(min_c=-7.222, ratio=14, label="Light"),
    SlrBand(min_c=None, ratio=17, label="Dry & fluffy"),
]
K = len(bins.ELEVS)


def band(z: float) -> int:
    return round(z / bins.BIN_M)


# ---- The arithmetic -----------------------------------------------------------------


def test_half_averages_blocks_and_ignores_nan() -> None:
    a = np.arange(30, dtype=np.float32).reshape(5, 6)
    a[0, 0] = np.nan
    h = bins.half(a)
    assert h.shape == (3, 3)
    assert h[0, 0] == pytest.approx((1 + 6 + 7) / 3)  # NaN left out
    assert h[0, 1] == pytest.approx((2 + 3 + 8 + 9) / 4)
    assert h[2, 0] == pytest.approx((24 + 25) / 2)  # the odd last row repeats
    all_nan = np.full((2, 2), np.nan)
    assert np.isnan(bins.half(all_nan)).all()
    assert bins.shape_for(box_region(40, -120, 45, -110, 5)) == (
        -(-box_region(40, -120, 45, -110, 5).height // 2),
        3,
    )


def test_phase_crosses_the_snow_level() -> None:
    assert bins.phase(np.array([-400.0, -150, 0, 75, 150, 900])).tolist() == [
        0,
        0,
        0.5,
        0.75,
        1,
        1,
    ]


def test_lift_raises_only_wet_ratios_well_above_the_snow_level() -> None:
    lift = bins.Lift(DEFAULT_BANDS)
    assert lift.from_m == pytest.approx(239, abs=1) and lift.to_m == pytest.approx(667, abs=1)
    r = np.array([5.0, 8, 14], np.float32)
    assert lift(r, np.full(3, 100.0)).tolist() == [5, 8, 14]  # near the snow level: as is
    assert lift(r, np.full(3, 1500.0)).tolist() == [11, 11, 14]  # high up: at least 11:1
    mid = (lift.from_m + lift.to_m) / 2
    assert lift(r, np.full(3, mid)).tolist() == pytest.approx([8, 9.5, 14])  # half way
    # Too few bands with a lower bound: nothing raised.
    flat = bins.Lift([SlrBand(min_c=None, ratio=12, label="x")])
    assert flat(r, np.full(3, 3000.0)) is r


def test_model_ratio_fills_what_the_model_lacks() -> None:
    r = bins.model_ratio(np.array([[0.0, np.nan, 7.0, 99.0]]), (1, 4))
    assert r.tolist() == [[10, 10, 7, 30]]
    assert bins.model_ratio(None, (1, 2)).tolist() == [[10, 10]]
    assert bins.model_ratio(12.0, (1, 2)).tolist() == [[12, 12]]


def test_add_period_puts_snow_above_the_snow_level() -> None:
    acc = np.zeros((1, 2, K), np.float32)
    water = np.array([[10.0, 10.0]], np.float32)
    level = np.array([[1000.0, np.nan]], np.float32)  # the second cell: no snow level
    own = np.array([[3.0, 4.0]], np.float32)
    ratio = np.array([[14.0, 14.0]], np.float32)
    bins.add_period(acc, water, level, ratio, own, bins.Lift(DEFAULT_BANDS))
    cell = acc[0, 0]
    assert cell[: band(750) + 1].tolist() == [0] * (band(750) + 1)  # 150 m+ below: rain
    assert cell[band(1000)] == pytest.approx(7)  # at the snow level: half of 14 cm
    assert cell[band(1250)] == pytest.approx(14)  # above: 10 mm at 14:1
    assert cell[-1] == pytest.approx(14)
    assert (acc[0, 1] == 4).all()  # no snow level: the model's own snow in every band
    # The model's own snow needs more water than it reports (NBM's blends): the water is
    # raised to match, so high ground never gets less than the model gives the cell.
    more = np.zeros((1, 2, K), np.float32)
    lots = np.array([[30.0, 4.0]], np.float32)  # 30 cm needs 21.4 mm at 14:1
    bins.add_period(more, water, level, ratio, lots, bins.Lift(DEFAULT_BANDS))
    assert more[0, 0, -1] == pytest.approx(30) and more[0, 0, band(1000)] == pytest.approx(15)
    # A block only partly inside the window counts in proportion.
    part = np.zeros((1, 2, K), np.float32)
    bins.add_period(part, water, level, ratio, own, bins.Lift(DEFAULT_BANDS), share=0.5)
    assert np.allclose(part, acc / 2)


def test_join_crosses_the_border_band_by_band() -> None:
    n = np.full((3, 1, K), 10.0, np.float32)
    s = np.full((3, 1, K), 20.0, np.float32)
    w = np.array([[0.0], [0.5], [1.0]], np.float32)
    out = bins.join(n, s, w)
    assert out[:, 0, 4].tolist() == [10, 15, 20]
    assert bins.join(None, s, w) is s and bins.join(n, None, w) is n
    with pytest.raises(ValueError):
        bins.join(None, None, w)


def test_sample_is_bilinear_in_space_and_linear_in_elevation() -> None:
    r, c, k = np.meshgrid(np.arange(3), np.arange(4), np.arange(K), indexing="ij")
    grid = (r * 100 + c * 10 + k).astype(np.float16)
    got = bins.sample(
        grid,
        np.array([0.5, 2.0, -3.0, 1.0]),
        np.array([0.5, 3.0, 0.0, 1.0]),
        np.array([125.0, 250.0, 0.0, 99999.0]),
    )
    assert got.tolist() == pytest.approx([55.5, 231, 0, 110 + K - 1])
    assert bins.sample(grid, np.array([0.0]), np.array([0.0]), np.array([np.nan]))[0] == 0


def test_cell_coords_follow_the_pictures() -> None:
    region = box_region(44, -125, 54, -110, 40)
    (south, west), (north, east) = region.bounds
    # The middle of the picture's top-left 2 × 2 block is the band grid's first cell.
    x = merc_x(west) + 1 / region.width * (merc_x(east) - merc_x(west)) * 1
    y = merc_y(north) - 1 / region.height * (merc_y(north) - merc_y(south))
    rows, cols = bins.cell_coords(
        region.bounds, region.width, region.height, np.array([x]), np.array([y])
    )
    assert rows[0] == pytest.approx(0) and cols[0] == pytest.approx(0)


# ---- The walks ------------------------------------------------------------------------


def chain_of(net: ModelsNet) -> list[rdps_gdps.Run]:
    return [
        r
        for r in (
            rdps_gdps.run_of(net, m, m.accum)
            for m in (rdps_gdps.HRDPS, rdps_gdps.RDPS, rdps_gdps.GDPS)
        )
        if r is not None
    ]


def test_north_bins_match_the_plain_totals_above_the_snow_level() -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet(snow_level=500.0)
    chain = chain_of(net)
    t0 = T0 + 4 * H
    ends = [t0 + 12 * H, T0 + 72 * H, T0 + 168 * H]
    plain = totals.north_totals(net, region, t0, ends, chain, BANDS)
    levels = terrain_totals.SnowLevels(
        net,
        region,
        terrain_totals.level_runs(net),
        None,
        np.ones((region.height, region.width), np.float32),
    )
    got: dict[int, np.ndarray] = {}
    used = terrain_totals.north_bins(
        net, region, t0, ends, chain, BANDS, levels, lambda e, a: got.__setitem__(e, a.copy())
    )
    assert set(got) == set(ends) and used == plain.runs
    assert {"hrdps", "rdps", "gdps"} <= levels.used
    for end in ends:
        cell = got[end][3, 3]
        assert cell[: band(250) + 1].tolist() == [0, 0]  # below the mix band: rain
        assert cell[band(500)] == pytest.approx(plain.cm[end][6, 6] / 2, rel=0.02)
    # Above the snow level (500 m) the water is all snow, and HRDPS's and RDPS's 11:1
    # isn't raised: the plain total.
    for end in ends[:2]:
        assert got[end][3, 3, band(1000)] == pytest.approx(plain.cm[end][6, 6], rel=0.02)
    # GDPS has no temperature (10:1 for its 84 h), raised on the way up to 11:1.
    lift = bins.Lift(BANDS)
    for z in (1000, 2000):
        r = float(lift(np.array([10.0]), np.array([z - 500.0]))[0])
        want = 80 * 1.1 + 84 * r / 10
        assert got[ends[2]][3, 3, band(z)] == pytest.approx(want, rel=0.02)


def test_north_bins_without_a_snow_level_use_the_models_own_snow() -> None:
    region = box_region(44, -125, 54, -110, 30)

    class NoLevel(ModelsNet):
        def value(self, cov: str, t: int) -> float | None:
            return None if cov.endswith("SnowLevelHeight") else super().value(cov, t)

    net = NoLevel()
    chain = chain_of(net)
    t0 = T0 + 4 * H
    ends = [t0 + 24 * H]
    plain = totals.north_totals(net, region, t0, ends, chain, BANDS)
    levels = terrain_totals.SnowLevels(net, region, terrain_totals.level_runs(net), None, None)
    got: dict[int, np.ndarray] = {}
    terrain_totals.north_bins(
        net, region, t0, ends, chain, BANDS, levels, lambda e, a: got.__setitem__(e, a.copy())
    )
    assert np.allclose(got[ends[0]][3, 3], plain.cm[ends[0]][6, 6], rtol=0.02)
    assert levels.used == set()


def test_snow_levels_fall_back_to_nbm_beyond_geomet() -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet(snow_level=800.0)
    runs = terrain_totals.level_runs(net)
    levels = terrain_totals.SnowLevels(net, region, runs, FakeNbm(T0, region, 1200.0), None)
    # No HRDPS domain: HRDPS-WEonG is skipped; RDPS-WEonG has 24 h.
    assert np.allclose(levels.at(T0 + 24 * H), 800) and levels.used == {"rdps"}
    # Past GDPS-WEonG's last time (240 h here) only NBM has one.
    assert np.allclose(levels.at(T0 + 252 * H), 1200) and "nbm" in levels.used
    assert levels.at(T0 + 300 * H) is None  # nothing at all
    assert terrain_totals.nbm_has(47) and not terrain_totals.nbm_has(49)
    assert terrain_totals.nbm_has(51) and not terrain_totals.nbm_has(195)
    assert terrain_totals.nbm_has(198) and not terrain_totals.nbm_has(0)


def test_south_bins_from_nbm() -> None:
    region = box_region(40, -120, 45, -110, 8)
    t0 = T0 + 4 * H
    ends = [t0 + 12 * H, T0 + 72 * H, T0 + 300 * H]
    got: dict[int, np.ndarray] = {}
    fake = FakeNbm(T0, region, 500.0)
    ok = terrain_totals.south_bins(
        fake, t0, ends, DEFAULT_BANDS, lambda e, a: got.__setitem__(e, a.copy())
    )
    assert ok and set(got) == set(ends[:2])  # NBM stops before the third
    plain = totals.south_totals(FakeNbm(T0, region), t0, ends)
    for end in ends[:2]:
        cell = got[end][0, 0]
        # 1 mm an hour at NBM's 10:1 is NBM's own 1 cm an hour just above the mix band;
        # higher up 10:1 is raised to 11:1.
        assert cell[band(750)] == pytest.approx(plain[end][0, 0], rel=0.01)
        assert cell[-1] == pytest.approx(plain[end][0, 0] * 1.1, rel=0.01)
        assert cell[band(250)] == 0
    assert ("SNOWLR" in {v for _, v in fake.fields}) and (6, "SNOWLVL") in fake.fields
    assert not terrain_totals.south_bins(None, t0, ends, DEFAULT_BANDS, lambda e, a: None)
    late = FakeNbm(t0 + H, region)
    assert not terrain_totals.south_bins(late, t0, ends, DEFAULT_BANDS, lambda e, a: None)


# ---- In the totals job --------------------------------------------------------------


def test_totals_job_writes_grids_by_elevation(tmp_path: Path, monkeypatch: Any) -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet(snow_level=500.0)
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: T0)
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region, 500.0))
    now = T0 + 4 * H + 600
    r = Renderer(tmp_path / "precip", net, now=lambda: now, slr_bands=DEFAULT_BANDS)
    ix = r.snow_totals(region)
    day = next(t for t in ix["totals"] if t["window"] == 24)
    tid = day["tiles_id"]
    assert day["tiles"] == f"/api/snowtiles/{tid}/{{z}}/{{x}}/{{y}}.png"
    work = tmp_path / "precip" / ".work" / "totals"
    grid = np.load(work / f"bins-{tid}.npy")
    assert grid.dtype == np.float16 and grid.shape == (*bins.shape_for(region), K)
    meta = json.loads((work / f"bins-{tid}.json").read_text())
    assert meta == {"bounds": region.bounds, "width": region.width, "height": region.height}
    plain = np.load(work / "24h.npy")
    # In Canada (top) and the US (bottom), high up: the plain total (24 mm at 11:1; NBM's
    # 1 cm an hour raised to 11:1); low down: rain.
    assert float(grid[0, 3, band(1500)]) == pytest.approx(float(plain[0, 6]), rel=0.02)
    assert float(grid[-1, 3, band(1500)]) == pytest.approx(26.4, rel=0.02)
    assert float(grid[0, 3, 0]) == 0 and float(grid[-1, 3, 0]) == 0
    assert not (work / ".parts").exists() or not any((work / ".parts").iterdir())
    # Nothing new: nothing recomputed, the same grids.
    before = len(net.coverages)
    again = Renderer(tmp_path / "precip", net, now=lambda: now, slr_bands=DEFAULT_BANDS)
    ix2 = again.snow_totals(region)
    assert len(net.coverages) == before
    assert [t["tiles_id"] for t in ix2["totals"]] == [t["tiles_id"] for t in ix["totals"]]


def test_totals_keep_working_when_the_grids_by_elevation_fail(
    tmp_path: Path, monkeypatch: Any
) -> None:
    region = box_region(44, -125, 54, -110, 30)
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: T0)
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("no")

    monkeypatch.setattr(terrain_totals, "south_bins", boom)
    r = Renderer(tmp_path / "precip", ModelsNet(), now=lambda: T0 + 4 * H, slr_bands=BANDS)
    ix = r.snow_totals(region)
    assert ix["totals"] and all(t["tiles"] is None for t in ix["totals"])


def test_old_grids_by_elevation_are_dropped(tmp_path: Path) -> None:
    r = Renderer(tmp_path / "precip", ModelsNet())
    r.totals_dir.mkdir(parents=True)
    tiles = r.totals_dir.parent / "snowtiles"
    for tid in ("a" * 16, "b" * 16):
        (r.totals_dir / f"bins-{tid}.npy").write_bytes(b"x")
        (r.totals_dir / f"bins-{tid}.json").write_bytes(b"{}")
        (tiles / tid / "8").mkdir(parents=True)
    import os

    old = 0
    os.utime(r.totals_dir / f"bins-{'b' * 16}.npy", (old, old))
    os.utime(r.totals_dir / f"bins-{'b' * 16}.json", (old, old))
    r._prune_bins({"a" * 16})
    assert (r.totals_dir / f"bins-{'a' * 16}.npy").exists() and (tiles / ("a" * 16)).exists()
    assert not (r.totals_dir / f"bins-{'b' * 16}.npy").exists()
    assert not (tiles / ("b" * 16)).exists()


# ---- Tiles ----------------------------------------------------------------------------


def terrarium_png(elev: np.ndarray) -> bytes:
    v = elev.astype(np.float64) + 32768
    r = np.floor(v / 256)
    g = np.floor(v - r * 256)
    b = np.round((v - r * 256 - g) * 256).clip(0, 255)
    im = Image.fromarray(np.stack([r, g, b], -1).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", lossless=True)
    return buf.getvalue()


def test_terrarium_decodes() -> None:
    elev = np.array([[0.0, 1234.5], [-50.0, 4400.0]], np.float32)
    got = tiles_render.terrarium(terrarium_png(elev))
    assert got is not None and np.allclose(got, elev, atol=0.01)
    assert tiles_render.terrarium(b"nope") is None


class FakeCache:
    """A TileCache that answers elevation tiles from a function of (z, x, y)."""

    def __init__(self, root: Path, answer: Any) -> None:
        self.root = root
        self.answer = answer
        self.asked: list[str] = []

    def through_status(self, path: Path, url: str, fix_edges: bool = False) -> Any:
        self.asked.append(url)
        return self.answer(url)


def write_grid(totals_dir: Path, region: Any, tid: str, high_cm: float = 30.0) -> None:
    """A grid with no snow below 1,000 m and `high_cm` from 1,250 m up, everywhere."""
    grid = np.zeros((*bins.shape_for(region), K), np.float32)
    grid[..., band(1250) :] = high_cm
    totals_dir.mkdir(parents=True, exist_ok=True)
    bins.save(totals_dir / f"bins-{tid}.npy", grid)
    meta = {"bounds": region.bounds, "width": region.width, "height": region.height}
    (totals_dir / f"bins-{tid}.json").write_text(json.dumps(meta))


def tile_of(lat: float, lon: float, z: int) -> tuple[int, int]:
    import math

    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def test_tiles_paint_snow_on_the_high_ground(tmp_path: Path) -> None:
    region = box_region(44, -125, 54, -110, 60)
    tid = "0123456789abcdef"
    write_grid(tmp_path / "totals", region, tid)
    # The tile's left half is a valley at 500 m, its right half a ridge at 2,000 m.
    elev = np.full((512, 512), 500.0, np.float32)
    elev[:, 256:] = 2000.0
    dem = terrarium_png(elev)
    cache = FakeCache(tmp_path / "tiles", lambda url: (dem, 200))
    x, y = tile_of(49, -118, 9)
    data = tiles_render.tile(
        tmp_path / "totals",
        tmp_path / "snowtiles",
        cache,
        tid,
        9,
        x,
        y,  # type: ignore[arg-type]
    )
    assert data is not None
    im = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))
    assert im.shape == (512, 512, 4)
    assert (im[:, :200, 3] == 0).all()  # valley: no snow, clear
    colour = [c for low, c in TOTAL if low <= 30][-1]
    assert tuple(im[100, 400, :3]) == hex_rgb(colour) and im[100, 400, 3] == 255
    # Drawn once: the second ask comes from disk.
    again = tiles_render.tile(
        tmp_path / "totals",
        tmp_path / "snowtiles",
        cache,
        tid,
        9,
        x,
        y,  # type: ignore[arg-type]
    )
    assert again == data and len(cache.asked) == 1
    assert "tiles.mapterhorn.com/9/" in cache.asked[0]


def test_tiles_outside_the_box_sea_and_failures(tmp_path: Path) -> None:
    region = box_region(44, -125, 54, -110, 60)
    tid = "0123456789abcdef"
    write_grid(tmp_path / "totals", region, tid)
    calls: list[str] = []

    def answer(url: str) -> Any:
        calls.append(url)
        return (None, 404) if "/8/" in url else (None, 0)

    cache = FakeCache(tmp_path / "tiles", answer)
    td, st = tmp_path / "totals", tmp_path / "snowtiles"
    # Far from the box: clear, without asking for elevation.
    x, y = tile_of(20, -60, 7)
    far = tiles_render.tile(td, st, cache, tid, 7, x, y)  # type: ignore[arg-type]
    assert far is not None and calls == []
    assert (np.asarray(Image.open(io.BytesIO(far)).convert("RGBA"))[..., 3] == 0).all()
    # Over the sea (Mapterhorn has no tile): sea level, so no snow here.
    x, y = tile_of(49, -118, 8)
    sea = tiles_render.tile(td, st, cache, tid, 8, x, y)  # type: ignore[arg-type]
    assert sea is not None
    # Mapterhorn not answering: no tile, and nothing kept.
    x, y = tile_of(49, -118, 9)
    with pytest.raises(tiles_render.Unavailable):
        tiles_render.tile(td, st, cache, tid, 9, x, y)  # type: ignore[arg-type]
    assert not (st / tid / "9").exists()
    # Unknown grid, bad id, zoom out of range, off the world.
    assert tiles_render.tile(td, st, cache, "f" * 16, 9, x, y) is None  # type: ignore[arg-type]
    assert tiles_render.tile(td, st, cache, "../etc", 9, x, y) is None  # type: ignore[arg-type]
    assert tiles_render.tile(td, st, cache, tid, 12, x, y) is None  # type: ignore[arg-type]
    assert tiles_render.tile(td, st, cache, tid, 9, 600, y) is None  # type: ignore[arg-type]


def test_snow_tile_api(settings: Settings, monkeypatch: Any) -> None:
    region = box_region(44, -125, 54, -110, 60)
    tid = "0123456789abcdef"
    write_grid(settings.map_work_dir / "totals", region, tid)
    monkeypatch.setattr(
        tiles_render, "elevation", lambda cache, z, x, y: np.full((512, 512), 2000, np.float32)
    )
    client = TestClient(create_app(settings))
    x, y = tile_of(49, -118, 9)
    r = client.get(f"/api/snowtiles/{tid}/9/{x}/{y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]
    assert client.get(f"/api/snowtiles/{'f' * 16}/9/{x}/{y}.png").status_code == 404
    assert client.get(f"/api/snowtiles/{tid}/13/{x}/{y}.png").status_code == 404

    def down(cache: Any, z: int, x: int, y: int) -> np.ndarray:
        raise tiles_render.Unavailable

    monkeypatch.setattr(tiles_render, "elevation", down)
    r = client.get(f"/api/snowtiles/{tid}/9/{x + 1}/{y}.png")
    assert r.status_code == 503 and r.headers["cache-control"] == "no-store"


# ---- Tap for numbers ------------------------------------------------------------------


def test_point_gives_snow_by_elevation(tmp_path: Path) -> None:
    region = box_region(44, -125, 54, -110, 60)
    tid = "0123456789abcdef"
    totals_dir = tmp_path / "totals"
    write_grid(totals_dir, region, tid, high_cm=30)
    np.save(totals_dir / "24h.npy", np.full((region.height, region.width), 12, np.float16))
    index = {
        "bounds": region.bounds,
        "width": region.width,
        "height": region.height,
        "frames": [],
        "totals": [
            {
                "window": 24,
                "hours": 24,
                "start": T0,
                "end": T0 + 24 * H,
                "file": "t24-0123456789ab.png",
                "source": "hrdps",
                "tiles_id": tid,
            },
            {"window": 48, "hours": 48, "start": T0, "end": T0 + 48 * H, "file": "x"},
        ],
    }
    p = point.probe(index, tmp_path, totals_dir, 49.0, -118.0, T0, BackcountryConfig())
    assert p.elevations == [int(z) for z in bins.ELEVS]
    day = p.totals[0]
    assert day.cm == 12 and day.by_elevation is not None and len(day.by_elevation) == K
    assert day.by_elevation[band(1000)] == 0 and day.by_elevation[band(1500)] == 30
    assert p.totals[1].by_elevation is None  # no grid for that window
    # A grid gone from disk: no numbers, no error.
    (totals_dir / f"bins-{tid}.npy").unlink()
    again = point.probe(index, tmp_path, totals_dir, 49.0, -118.0, T0, BackcountryConfig())
    assert again.totals[0].by_elevation is None and again.elevations == []
    assert ts_iso(T0)  # (keeps the import honest)
