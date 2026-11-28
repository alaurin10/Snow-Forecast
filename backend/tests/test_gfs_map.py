"""Milestone 4B, the map's data: NOAA's GFS from 10 to 16 days (sources/gfs.py) in the
precipitation loop, the snow totals, the temperature and the forecast cloud cover."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snowwatch.maps import grib, totaldata, totals
from snowwatch.maps.geomet import Net
from snowwatch.maps.palette import RAIN_T, SNOW_T
from snowwatch.maps.region import box_region
from snowwatch.maps.render import LESS_CERTAIN_H, Renderer
from snowwatch.maps.sources import gfs, hrrr, nbm
from snowwatch.maps.sources.gfs import Gfs
from tests.test_forecast_maps import BANDS, FakeNbm, ModelsNet, near, rates, resp

FIXTURES = Path(__file__).parent / "fixtures" / "grib"
CSNOW = FIXTURES / "gfs_20261128t00z_f300_csnow.grib2"  # the 6 hours to 300 h, worldwide
IDX = FIXTURES / "gfs_20261128t00z_f300_excerpt.idx"
H = 3600
T0 = 1_800_000_000 - 1_800_000_000 % (6 * H)  # a synoptic hour
REGION = box_region(44, -125, 54, -110, 30)


class FakeGfs(Gfs):
    """GFS everywhere: `water` mm in each 6 hours, `share` of it snow, -1 °C at 2 m on
    its 500 m ground, 70% cloud. Nothing past `stop` hours (its last file)."""

    def __init__(
        self, run: int, region: Any, water: float = 3.6, share: float = 1.0, stop: int = 384
    ) -> None:
        super().__init__(Net.__new__(Net), run, region)
        self.water = water
        self.share = share
        self.stop = stop
        self.asked: list[tuple[int, str]] = []

    def _fields(self, fhour: int, patterns: list[str]) -> list[np.ndarray | None]:
        out: list[np.ndarray | None] = []
        shape = (self.region.height, self.region.width)
        for p in patterns:
            self.asked.append((fhour, p))
            var = p.split(":")[1]
            value = {
                "APCP": self.water,
                "CSNOW": self.share,
                "TMP": gfs.KELVIN - 1.0,
                "HGT": 500.0,
                "TCDC": 70.0,
            }[var]
            ok = 0 < fhour <= self.stop
            out.append(np.full(shape, value, np.float32) if ok else None)
        return out


# ---- The files ---------------------------------------------------------------------------


def test_file_names_and_messages() -> None:
    run = 1_795_824_000  # 2026-11-28 00 UTC
    assert gfs.file_url(run, 300) == (
        "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20261128/00/atmos/gfs.t00z.pgrb2.0p25.f300"
    )
    # Each pattern finds its message in a real index: the 6-hour sum and averages, not the
    # run's whole sum or the value at the hour.
    entries = grib.parse_idx(IDX.read_text())
    for pat, start in (
        (gfs.block("APCP", 300, "acc"), 423604769),
        (gfs.block("CSNOW", 300, "ave"), 426243454),
        (r":TCDC:entire atmosphere:294-300 hour ave fcst:", 443826446),
        (r":TMP:2 m above ground:300 hour fcst:", 412044520),
        (r":HGT:surface:300 hour fcst:", 403950398),
    ):
        hit = grib.find(entries, pat)
        assert hit is not None and hit.start == start, pat


def test_latest_run_needs_its_last_file() -> None:
    now = T0 + 13 * H

    class Bucket(Net):
        def __init__(self) -> None:
            self.asked: list[str] = []

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            self.asked.append(url)
            # The newest run (T0 + 12 h) isn't complete yet.
            return None if f"t{(T0 // H + 12) % 24:02d}z" in url else resp("x")

    b = Bucket()
    assert gfs.latest_run(b, now, (0, 6, 12, 18)) == T0 + 6 * H
    assert all(u.endswith(".f384.idx") for u in b.asked)
    assert gfs.latest_run(Bucket(), now, ()) is None


def test_a_real_message_on_the_region() -> None:
    raw = CSNOW.read_bytes()
    values, md = grib.decode(raw)
    lats, lons = (np.asarray(a, np.float64) for a in md.latlng())
    # A regular 0.25° grid from 90°N, longitudes 0–360: one row and column each.
    assert values.shape == (721, 1440) and lats.shape == (721,) and lons.shape == (1440,)
    got = gfs.on_region(raw, REGION)
    assert got is not None and got.shape == (REGION.height, REGION.width)
    assert got.dtype == np.float32
    assert float(got.min()) >= 0.0 and float(got.max()) <= 1.0
    # Each pixel is the bilinear mix of the four GFS points around it.
    lon, lat = gfs.region_lonlat(REGION)
    r, c = REGION.height // 2, REGION.width // 3
    fi, fj = (90 - lat[r]) / 0.25, (lon[c] % 360) / 0.25
    i, j = int(fi), int(fj)
    wi, wj = fi - i, fj - j
    want = (values[i, j] * (1 - wj) + values[i, j + 1] * wj) * (1 - wi) + (
        values[i + 1, j] * (1 - wj) + values[i + 1, j + 1] * wj
    ) * wi
    assert float(got[r, c]) == pytest.approx(float(want), abs=1e-5)
    assert gfs.on_region(None, REGION) is None
    assert gfs.on_region(b"GRIB nonsense", REGION) is None


def test_regrid_is_smooth_and_wraps_round_the_globe() -> None:
    # A field that rises 1 a degree east: bilinear gives each pixel's longitude exactly,
    # from either side of the 0°/360° seam.
    lats = np.arange(90, -90.1, -1.0)
    lons = np.arange(0, 360, 1.0)
    east = np.broadcast_to(lons, (lats.size, lons.size)).astype(np.float32)
    lon, _ = gfs.region_lonlat(REGION)
    got = gfs.regrid(east, lats, lons, REGION)
    assert np.allclose(got[0], lon % 360, atol=1e-3)
    seam = box_region(50, -1.5, 52, 1.5, 4)
    wrap = gfs.regrid(np.cos(np.radians(east)), lats, lons, seam)
    slon, _ = gfs.region_lonlat(seam)
    assert np.allclose(wrap[0], np.cos(np.radians(slon)), atol=2e-4)


# ---- One run ------------------------------------------------------------------------------


def test_times_are_six_hourly_to_384_hours() -> None:
    g = FakeGfs(T0, REGION)
    assert g.end() == T0 + 384 * H
    assert [t - T0 for t in g.times(T0 + 240 * H)] == [h * H for h in range(246, 385, 6)]
    assert g.times(g.end()) == []


def test_precipitation_snow_and_rain_from_the_share() -> None:
    g = FakeGfs(T0, REGION, water=6.0, share=1.0)
    got = g.precip(T0 + 300 * H)
    assert got is not None
    water, share, kinds = got
    assert np.allclose(water, 6.0) and np.allclose(share, 1.0) and (kinds == SNOW_T).all()
    assert (g.asked[0][0], g.asked[1][1]) == (300, gfs.block("CSNOW", 300, "ave"))
    wet = FakeGfs(T0, REGION, water=6.0, share=0.0).precip(T0 + 300 * H)
    assert wet is not None and (wet[2] == RAIN_T).all()
    assert g.precip(T0 + 303 * H) is None  # 3-hourly files have no 6-hour sums here
    assert g.precip(T0 + 390 * H) is None  # past the run
    assert FakeGfs(T0, REGION, stop=300).precip(T0 + 306 * H) is None


def test_snow_depth_from_water_share_and_temperature() -> None:
    g = FakeGfs(T0, REGION, water=6.0)
    # 6 mm a block, all snow, at -1 °C (11:1): 6.6 cm a block, four blocks a day.
    cm = g.snow_cm(T0 + 240 * H, T0 + 264 * H, BANDS)
    assert cm is not None and np.allclose(cm, 26.4)
    half = FakeGfs(T0, REGION, water=6.0, share=0.5).snow_cm(T0 + 240 * H, T0 + 252 * H, BANDS)
    assert half is not None and np.allclose(half, 6.6)
    assert FakeGfs(T0, REGION, stop=300).snow_cm(T0 + 240 * H, T0 + 384 * H, BANDS) is None


def test_temperature_ground_and_clouds() -> None:
    g = FakeGfs(T0, REGION)
    tc = g.temp_c(T0 + 300 * H)
    assert tc is not None and np.allclose(tc, -1.0)
    assert g.ground_m() is not None and g.ground_m() is not None
    assert sum(1 for _, p in g.asked if ":HGT:surface:" in p) == 1  # once per run
    cloud = g.cloud_pct(T0 + 300 * H)
    assert cloud is not None and np.allclose(cloud, 70.0)


# ---- The precipitation loop ------------------------------------------------------------


def test_the_loop_runs_on_to_16_days(tmp_path: Path, monkeypatch: Any) -> None:
    """GDPS (Canada) stops at 240 h and NBM (US) at 264 h: GFS carries both on, every 6 h,
    to 384 h, with NBM over it in the US while NBM lasts."""
    now = T0 + 4 * H + 600
    g = FakeGfs(T0, REGION)  # 0.6 mm/h; NBM 1 mm/h
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    monkeypatch.setattr(Renderer, "_gfs", lambda self, region: g)
    net = ModelsNet()
    ix = Renderer(tmp_path, net, now=lambda: now).forecast(REGION)
    six = [f for f in ix["frames"] if f["span_h"] == 6]
    assert [f["t"] - T0 for f in six] == [h * H for h in range(90, 385, 6)]
    by_h = {(f["t"] - T0) // H: f for f in six}
    assert by_h[240]["src"] == {"north": "gdps", "south": "nbm"}
    assert by_h[246]["src"] == {"north": "gfs", "south": "nbm"}
    assert by_h[264]["src"] == {"north": "gfs", "south": "nbm"}
    assert by_h[270]["src"] == {"north": "gfs", "south": "gfs"}
    assert by_h[384]["src"] == {"north": "gfs", "south": "gfs"}
    assert (by_h[264]["south"], by_h[270]["south"]) == ("nbm", "")
    # Canada GFS's 0.6 mm/h; the US NBM's 1 mm/h to 264 h, then GFS's too.
    v, k = rates(tmp_path / by_h[246]["file"])
    assert near(float(v[0, 5]), 0.6) and near(float(v[-1, 5]), 1.0) and (k == SNOW_T).all()
    v, _ = rates(tmp_path / by_h[300]["file"])
    assert near(float(v[0, 5]), 0.6) and near(float(v[-1, 5]), 0.6)
    assert by_h[300]["palette"] == "fine" and by_h[300]["ds"] == by_h[240]["ds"]
    # The second "Less certain" mark, 10 days from this hour, and GFS credited.
    assert ix["less_certain_from"] == now - now % H + LESS_CERTAIN_H * H
    assert any("GFS" in a for a in ix["attribution"])
    # Nothing new: nothing fetched or redrawn.
    asked = len(g.asked)
    again = Renderer(tmp_path, net, now=lambda: now).forecast(REGION)
    assert len(g.asked) == asked
    assert [f["file"] for f in again["frames"]] == [f["file"] for f in ix["frames"]]


def test_without_gfs_the_loop_stops_where_it_did(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    monkeypatch.setattr(gfs, "latest_run", lambda net, now, cycles: None)
    ix = Renderer(tmp_path, ModelsNet(), now=lambda: T0 + 4 * H + 600).forecast(REGION)
    assert max(f["t"] for f in ix["frames"]) == T0 + 240 * H
    assert not any("GFS" in a for a in ix["attribution"])


# ---- Snow totals ------------------------------------------------------------------------


def test_totals_and_steps_run_on_to_16_days(tmp_path: Path, monkeypatch: Any) -> None:
    now = T0 + 4 * H + 600
    t0 = T0 + 4 * H
    g = FakeGfs(T0, REGION, water=6.0)  # 6.6 cm a block at -1 °C
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: T0)
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    monkeypatch.setattr(Renderer, "_gfs", lambda self, region: g)
    out = tmp_path / "precip"
    net = ModelsNet()
    ix = Renderer(out, net, now=lambda: now, slr_bands=BANDS).snow_totals(REGION)
    wins = {t["window"]: t for t in ix["totals"]}
    assert list(wins) == [12, 24, 48, 72, 120, 168, 240, *totals.FAR_WINDOWS]
    # 14 days ends on the synoptic hour before; "to the end" where GFS's run stops.
    assert wins[336]["end"] == T0 + 336 * H and wins[336]["hours"] == 332
    assert wins[384]["end"] == T0 + 384 * H and wins[384]["hours"] == 380
    assert wins[384]["source"] == "hrdps+rdps+gdps+nbm+gfs" and wins[384]["runs"]["gfs"] == T0
    assert wins[240]["source"] == "hrdps+rdps+gdps+nbm"  # the 10-day total doesn't change
    # Past 10 days: the 10-day total plus GFS's snow from there, both sides of the border.
    work = out / ".work" / "totals"
    ten, fourteen, end = (np.load(work / f"{w}h.npy").astype(np.float32) for w in (240, 336, 384))
    assert np.allclose(fourteen - ten, 16 * 6.6, atol=0.5)
    assert np.allclose(end - ten, 24 * 6.6, atol=0.5)
    # Steps every 24 h on to 16 days, the far ones without snow by elevation.
    steps = ix["steps"]["steps"]
    far = [s for s in steps if s["end"] > T0 + 240 * H]
    assert [s["hours"] for s in far] == [h - 4 for h in totaldata.FAR_STEPS]
    step = totaldata.decode((out / far[-1]["data"]).read_bytes())
    assert step is not None
    assert any("GFS" in a for a in ix["attribution"])
    # Nothing new: nothing recomputed, the far totals kept without a grid by elevation.
    asked, cov = len(g.asked), len(net.coverages)
    again = Renderer(out, net, now=lambda: now, slr_bands=BANDS).snow_totals(REGION)
    assert (len(g.asked), len(net.coverages)) == (asked, cov)
    assert [t["file"] for t in again["totals"]] == [t["file"] for t in ix["totals"]]
    assert t0 == ix["steps"]["start"]


def test_totals_without_gfs_stop_at_10_days(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: T0)
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    monkeypatch.setattr(gfs, "latest_run", lambda net, now, cycles: None)
    r = Renderer(tmp_path / "precip", ModelsNet(), now=lambda: T0 + 4 * H + 600, slr_bands=BANDS)
    ix = r.snow_totals(REGION)
    assert [t["window"] for t in ix["totals"]][-1] == 240
    assert max(s["end"] for s in ix["steps"]["steps"]) <= T0 + 240 * H
