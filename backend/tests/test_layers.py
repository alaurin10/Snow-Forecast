"""Milestone 7 of the map: snow level, wind, snow on the ground, observed snowfall and
clouds as layers, and tap-for-numbers."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import urllib.parse
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from snowwatch.analysis.backcountry import BackcountryConfig
from snowwatch.api.app import create_app
from snowwatch.maps import layers, point
from snowwatch.maps.geomet import Grid, Net, iso_ts, ts_iso
from snowwatch.maps.palette import (
    DEPTH,
    PALETTE,
    SNOWLEVEL,
    TOTAL,
    WIND,
    index_ramp,
    paint_ramp,
    paint_typed,
    snap,
)
from snowwatch.maps.palette import SNOW_T as PSNOW
from snowwatch.maps.region import box_region
from snowwatch.maps.render import Renderer
from snowwatch.maps.sources import gibs, nohrsc, snodas
from snowwatch.settings import Settings
from tests.test_forecast_maps import FakeNbm, float_tiff, resp

H = 3600
T0 = 1_800_000_000 - 1_800_000_000 % (6 * H)
NOW = T0 + 4 * H + 600
REGION = box_region(44, -125, 54, -110, 30)


# ---- Painting -------------------------------------------------------------------------


@pytest.mark.parametrize("ramp", [SNOWLEVEL, WIND, DEPTH, TOTAL])
def test_index_ramp_matches_painting_then_snapping(ramp: list[tuple[float, str]]) -> None:
    lows = [low for low, _ in ramp]
    values = np.array([[lows[0] - 1, np.nan, *lows, lows[-1] * 3]], np.float32)
    # The same colours (TOTAL shares some with the precipitation ramps, so compare
    # colours rather than indices).
    pal = np.array(PALETTE)
    assert (pal[index_ramp(values, ramp)] == pal[snap(paint_ramp(values, ramp))]).all()
    assert index_ramp(values, ramp)[0, 0] == 0 and index_ramp(values, ramp)[0, 1] == 0


# ---- Sources ----------------------------------------------------------------------------


def snodas_tar(mm: np.ndarray, lon0: float, lat0: float, d: float, day: str = "20261111") -> bytes:
    rows, cols = mm.shape
    hdr = (
        "Description: Modeled snow layer thickness, total of snow layers\n"
        "Data units: Meters / 1000.000000\n"
        f"Number of columns: {cols}\nNumber of rows: {rows}\n"
        f"Minimum x-axis coordinate: {lon0}\nMaximum y-axis coordinate: {lat0}\n"
        f"X-axis resolution: {d}\nY-axis resolution: {d}\nNo data value: -9999\n"
    )
    stem = f"us_ssmv11036tS__T0001TTNATS{day}05HP001"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, body in (
            (f"{stem}.txt.gz", gzip.compress(hdr.encode())),
            (f"{stem}.dat.gz", gzip.compress(mm.astype(">i2").tobytes())),
            ("us_ssmv11034tS__T0001TTNATS2026111105HP001.dat.gz", gzip.compress(b"other")),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def test_snodas_reads_depth_from_the_days_tar() -> None:
    mm = np.array([[100, -9999], [2500, 0]], np.int16)
    g = snodas.depth_grid(snodas_tar(mm, -125.0, 50.0, 0.5))
    assert g is not None and g.lon0 == -125.0 and g.lat0 == 50.0 and g.dlon == 0.5
    assert g.data.tolist() == mm.tolist()
    assert snodas.depth_grid(b"not a tar") is None
    bad = io.BytesIO()
    with tarfile.open(fileobj=bad, mode="w"):
        pass
    assert snodas.depth_grid(bad.getvalue()) is None  # no depth files in it
    assert snodas.day_ts("20261111") == iso_ts("2026-11-11T06:00:00Z")


class Listing(Net):
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        self.asked.append(url)
        for k, v in self.pages.items():
            if url.endswith(k):
                return resp(v)
        return None


def test_snodas_newest_day_looks_back_a_month() -> None:
    now = iso_ts("2026-12-01T03:00:00Z")
    net = Listing({"2026/11_Nov/": "SNODAS_20261129.tar SNODAS_20261130.tar"})
    assert snodas.latest(net, now) == "20261130"
    assert net.asked[0].endswith("2026/12_Dec/")
    assert snodas.latest(Listing({}), now) is None


def test_nohrsc_newest_file_per_window_in_inches() -> None:
    now = iso_ts("2026-11-12T03:00:00Z")
    page = " ".join(
        f"sfav2_CONUS_{h}h_{s}.tif"
        for h in (6, 24, 48, 72)
        for s in ("2026111100", "2026111112", "2026111200")
    )
    names = nohrsc.latest(Listing({"202611/": page}), now)
    assert names == {h: f"sfav2_CONUS_{h}h_2026111200.tif" for h in (24, 48, 72)}
    assert nohrsc.end_ts(names[24]) == iso_ts("2026-11-12T00:00:00Z")
    with pytest.raises(ValueError):
        nohrsc.end_ts("something.tif")
    tif = float_tiff(np.full((4, 4), 2.0, np.float32), -126.0, 55.0, 0.04)
    net = Listing({names[24]: ""})
    net.pages = {}

    class Files(Net):
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            self.urls.append(url)
            return resp(content=tif, ctype="image/tiff")

    files = Files()
    g = nohrsc.fetch(files, names[24])
    assert g is not None and float(g.data[0, 0]) == 2.0 and g.lon0 == -126.0
    assert files.urls == [f"{nohrsc.BASE}/202611/{names[24]}"]


def test_gibs_picks_one_image_each_half_hour() -> None:
    now = iso_ts("2026-11-12T02:17:00Z")
    have = [iso_ts(f"2026-11-12T{h}:00Z") for h in ("00:00", "00:20", "01:10", "01:30", "02:00")]
    have += [iso_ts("2026-11-11T23:30:00Z")]
    got = [ts_iso(t) for t in gibs.pick(have, now)]
    # 23:00 has nothing within 10 minutes; 00:30 takes 00:20; 01:00 nothing (01:10 is after).
    assert got == [
        "2026-11-11T23:30:00Z",
        "2026-11-12T00:00:00Z",
        "2026-11-12T00:20:00Z",
        "2026-11-12T01:30:00Z",
        "2026-11-12T02:00:00Z",
    ]
    domain = (
        "<Domains><DimensionDomain><Domain>2026-11-12T00:00:00Z/2026-11-12T00:30:00Z/PT10M,"
        "2026-11-12T01:30:00Z</Domain></DimensionDomain></Domains>"
    )
    times = gibs.times(Listing({".xml": domain}), now - 3 * H, now)
    assert len(times) == 5 and times[-1] == iso_ts("2026-11-12T01:30:00Z")
    assert gibs.times(Listing({}), now - H, now) == []
    assert "/2026-11-12T02:00:00Z/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png" in gibs.template(
        iso_ts("2026-11-12T02:00:00Z")
    )


# ---- The layers job ---------------------------------------------------------------------

# GeoMet's values per layer: HRDPS reports snow to the ground (-2) over its domain.
VALUES = {
    "HRDPS-WEonG_2.5km_SnowLevelHeight": -2.0,
    "RDPS-WEonG_10km_SnowLevelHeight": 1500.0,
    "HRDPS-WEonG_2.5km_WindGust": 10.0,  # m/s
    "RDPS-WEonG_10km_WindGust": 12.0,
    "RDPS_10km_WindSpeed_700mb": 20.0,
    "RDPS_10km_WindDir_700mb": 225.0,
    "CaLDAS-NSRPS_2.5km_SnowDepth": 0.5,  # m
}


class LayersNet(Net):
    """GeoMet for the layers: HRDPS-WEonG to 48 h, RDPS to 84 h, CaLDAS one analysis.
    HRDPS's domain is the top half of the box."""

    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.missing = missing
        self.coverages: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        if params and params.get("request") == "GetCapabilities":
            layer = params["layer"]
            if layer in self.missing:
                return None
            if layer.startswith("CaLDAS"):
                t = ts_iso(T0)
                text = (
                    f'<Dimension name="time" default="{t}">{t}/{t}/PT0H</Dimension>'
                    f'<Dimension name="reference_time" default="{t}">x</Dimension>'
                )
                return resp(text)
            end = 48 if layer.startswith("HRDPS") else 84
            text = (
                f'<Dimension name="time" default="x">{ts_iso(T0 + H)}/'
                f"{ts_iso(T0 + end * H)}/PT1H</Dimension>"
                f'<Dimension name="reference_time" default="{ts_iso(T0)}">x</Dimension>'
            )
            return resp(text)
        if "GetCoverage" in url:
            q = urllib.parse.parse_qs(url.split("?", 1)[1])
            cov = q["coverageId"][0]
            self.coverages.append(cov)
            body = float_tiff(np.full((40, 60), VALUES[cov], np.float32), -136.0, 58.0, 0.5)
            return resp(content=body, ctype="image/tiff")
        return None

    def image(self, url: str, params: Any = None, tries: int = 3) -> np.ndarray | None:
        h, w = int(params["height"]), int(params["width"])
        out = np.zeros((h, w, 4), np.uint8)
        out[: h // 2] = (0, 0, 0, 255)
        return out


class FieldNbm(FakeNbm):
    def field(self, fhour: int, var: str, level: str) -> np.ndarray | None:
        value = {"SNOWLVL": 800.0, "GUST": 8.0}[var]
        return np.full((self.region.height, self.region.width), value, np.float32)


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """SNODAS, NOHRSC and GIBS answering, counting their downloads."""
    calls = {"snodas": 0, "nohrsc": 0, "clouds": 0}
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FieldNbm(T0, region))
    monkeypatch.setattr(snodas, "latest", lambda net, now: "20261111")

    def tar(net: Net, day: str) -> bytes:
        calls["snodas"] += 1
        # 30 cm everywhere south of 49°N.
        return snodas_tar(np.full((20, 40), 300, np.int16), -130.0, 49.0, 0.5)

    monkeypatch.setattr(snodas, "fetch", tar)
    monkeypatch.setattr(nohrsc, "latest", lambda net, now: {24: "sfav2_CONUS_24h_2026111200.tif"})

    def grid(net: Net, name: str) -> Grid:
        calls["nohrsc"] += 1
        return Grid(np.full((100, 100), 2.0, np.float32), -126.0, 49.0, 0.2, 0.2)

    monkeypatch.setattr(nohrsc, "fetch", grid)
    monkeypatch.setattr(gibs, "times", lambda net, a, b: [NOW - NOW % 1800 - 1800])

    def stitch(net: Any, template: str, region: Any, z: int = 6) -> np.ndarray:
        calls["clouds"] += 1
        return np.full((region.height, region.width, 4), 200, np.uint8)

    monkeypatch.setattr(layers, "stitch", stitch)
    return calls


def probe_at(folder: Path, file: str, row: int, col: int) -> np.ndarray:
    arr = np.load(folder / "probe" / f"{file}.npy")
    return np.atleast_1d(arr[..., row // 4, col // 4]).astype(np.float32)


def test_layers_are_drawn_blended_and_kept_as_numbers(
    tmp_path: Path, sources: dict[str, int]
) -> None:
    net = LayersNet()
    out = tmp_path / "precip"
    ix = Renderer(out, net, now=lambda: NOW).layers(REGION)
    lay = ix["layers"]
    assert set(lay) == {"snowlevel", "gust", "ridge", "depth", "snowfall", "clouds"}
    sl = lay["snowlevel"]["frames"]
    # Every 3 hours from the next one to the end of RDPS's run.
    assert [f["t"] - T0 for f in sl] == [h * H for h in range(6, 85, 3)]
    assert sl[0]["src"] == {"south": "nbm", "north": "hrdps"}
    assert sl[-1]["src"] == {"south": "nbm", "north": "rdps"}  # beyond HRDPS's 48 h
    assert sl[0]["runs"]["nbm"] == T0
    top, bottom = 0, REGION.height - 1
    # North: HRDPS's "snow to the ground" is 0 m; south: NBM's 800 m.
    assert probe_at(out, sl[0]["file"], top, 5)[0] == 0
    assert probe_at(out, sl[0]["file"], bottom, 5)[0] == 800
    # Beyond 48 h, RDPS's 1500 m in the north.
    assert probe_at(out, sl[-1]["file"], top, 5)[0] == 1500
    g = lay["gust"]["frames"][0]
    assert probe_at(out, g["file"], top, 5)[0] == pytest.approx(36, abs=0.1)
    assert probe_at(out, g["file"], bottom, 5)[0] == pytest.approx(28.8, abs=0.1)
    w = lay["ridge"]["frames"][0]
    assert probe_at(out, w["file"], 10, 5).tolist() == pytest.approx([72, 225], abs=0.1)
    d = lay["depth"]["frames"][0]
    assert d["src"] == {"south": "snodas", "north": "caldas"} and d["kind"] == "observed"
    assert probe_at(out, d["file"], top, 5)[0] == 50  # CaLDAS 0.5 m
    assert probe_at(out, d["file"], bottom, 5)[0] == 30  # SNODAS 300 mm
    o = lay["snowfall"]["frames"][0]
    assert o["hours"] == 24 and o["t"] == iso_ts("2026-11-12T00:00:00Z")
    assert probe_at(out, o["file"], bottom, 5)[0] == pytest.approx(5.08, abs=0.01)
    c = lay["clouds"]["frames"][0]
    assert c["file"].endswith(".webp") and (out / c["file"]).exists()
    assert any("SNODAS" in a for a in ix["attribution"])
    assert any("GOES-West" in a for a in ix["attribution"])

    # Nothing new: nothing fetched or redrawn.
    before = (len(net.coverages), dict(sources))
    again = Renderer(out, net, now=lambda: NOW).layers(REGION)
    assert (len(net.coverages), sources) == before
    assert again["layers"] == ix["layers"]


def test_a_layer_whose_source_fails_keeps_its_pictures(
    tmp_path: Path, sources: dict[str, int]
) -> None:
    out = tmp_path / "precip"
    first = Renderer(out, LayersNet(), now=lambda: NOW).layers(REGION)
    # GeoMet stops listing the snow level and the 700 hPa wind.
    gone = ("HRDPS-WEonG_2.5km_SnowLevelHeight", "RDPS-WEonG_10km_SnowLevelHeight")
    net = LayersNet(missing=(*gone, layers.RIDGE_SPEED))
    later = Renderer(out, net, now=lambda: NOW).layers(REGION)
    assert later["layers"]["snowlevel"] == first["layers"]["snowlevel"]
    assert later["layers"]["ridge"] == first["layers"]["ridge"]


def test_other_jobs_leave_the_layers_alone(tmp_path: Path, sources: dict[str, int]) -> None:
    out = tmp_path / "precip"
    r = Renderer(out, LayersNet(), now=lambda: NOW)
    ix = r.layers(REGION)
    after = r._commit(REGION, {"radar"}, [])
    assert after["layers"] == ix["layers"]
    for f in ix["layers"]["snowlevel"]["frames"]:
        assert (out / f["file"]).exists()


# ---- Tap for numbers --------------------------------------------------------------------


def point_index(tmp_path: Path) -> tuple[dict[str, Any], Path, Path]:
    """A small index: three frames (radar rain, two hours of forecast snow), a 24 h total,
    one ridge-wind frame and one snow-level frame."""
    region = box_region(44, -125, 54, -110, 40)
    out = tmp_path / "precip"
    totals_dir = tmp_path / "maps" / "totals"
    r = Renderer(out, Net.__new__(Net), now=lambda: NOW)
    shape = (region.height, region.width)

    def typed(rate: float, kind: int) -> str:
        return r._save(
            paint_typed(np.full(shape, rate, np.float32), np.full(shape, kind, np.uint8)),
            region,
            "f1",
        )

    rain = typed(3.0, 3)
    snow1 = typed(1.5, PSNOW)
    snow2 = typed(0.7, PSNOW)
    ridge = r._save_ramp(
        np.full(shape, 50.0), WIND, "w1", np.stack([np.full(shape, 50.0), np.full(shape, 260.0)])
    )
    level = r._save_ramp(np.full(shape, 1234.0), SNOWLEVEL, "sl1")
    totals_dir.mkdir(parents=True)
    np.save(totals_dir / "24h.npy", np.full(shape, 12.0, np.float16))
    top = NOW - NOW % H
    frame = {"past": False, "south": "", "key": "k", "src": {}}
    index = {
        "bounds": region.bounds,
        "width": region.width,
        "height": region.height,
        "generated": "2026-11-12T00:00:00Z",
        "frames": [
            {**frame, "t": top - 600, "file": rain, "kind": "radar", "span_h": 0, "past": True},
            {**frame, "t": top + H, "file": snow1, "kind": "forecast", "span_h": 1},
            {**frame, "t": top + 2 * H, "file": snow2, "kind": "forecast", "span_h": 1},
            {**frame, "t": top + 3 * H, "file": "f9-000000000000.png", "kind": "forecast"},
        ],
        "totals": [
            {"hours": 24, "window": 24, "start": top, "end": top + 24 * H, "file": "t", "key": "k"}
        ],
        "layers": {
            "ridge": {"frames": [{"t": top + 3 * H, "file": ridge}]},
            "snowlevel": {"frames": [{"t": top + 3 * H, "file": level}]},
        },
    }
    return index, out, totals_dir


def test_point_reads_every_layer_at_a_spot(tmp_path: Path) -> None:
    index, out, totals_dir = point_index(tmp_path)
    p = point.probe(index, out, totals_dir, 49.0, -118.0, NOW, BackcountryConfig())
    assert p.inside
    assert [(x.kind, x.type, x.low, x.high) for x in p.rates] == [
        ("radar", "rain", 2.5, 5.0),
        ("forecast", "snow", 1.0, 2.0),
        ("forecast", "snow", 0.5, 1.0),
    ]  # the frame without a probe is left out
    assert [(x.window, x.cm) for x in p.totals] == [(24, 12.0)]
    assert [(x.value) for x in p.snow_level] == [1230.0]
    assert [(x.kmh, x.dir) for x in p.ridge] == [(50.0, 260.0)]
    rose = {x.window: x for x in p.roses}
    # The 24 h total is 12 cm, from the west (260°): it loads east-facing slopes.
    assert rose["next24"].snow_cm == 12.0 and rose["next24"].wind_from == "W"
    assert rose["next24"].loading == ["E"] and rose["next24"].mean_kmh == 50
    # No 72 h total: the bands' own estimate (1.5 + 0.75 cm).
    assert rose["next72"].snow_cm == pytest.approx(2.2, abs=0.1)
    # Outside the box: nothing.
    far = point.probe(index, out, totals_dir, 20.0, -150.0, NOW, BackcountryConfig())
    assert not far.inside and far.rates == [] and far.roses == []
    assert point.pixel({}, 49, -118) is None


def test_point_api(tmp_path: Path, settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/map/point?lat=49&lon=-118").status_code == 503
    assert client.get("/api/map/point?lat=95&lon=-118").status_code == 422
    index, out, totals_dir = point_index(tmp_path / "x")
    settings.precip_dir.parent.mkdir(parents=True, exist_ok=True)
    out.rename(settings.precip_dir)
    settings.map_work_dir.mkdir(parents=True, exist_ok=True)
    totals_dir.rename(settings.map_work_dir / "totals")
    (settings.precip_dir / "index.json").write_text(json.dumps(index))
    r = client.get("/api/map/point?lat=49&lon=-118")
    assert r.status_code == 200
    body = r.json()
    assert body["inside"] and body["totals"][0]["cm"] == 12.0 and len(body["rates"]) == 3
    assert body["min_snow_cm"] == 2.0
    # Layer pictures are served like frames, WebP included.
    (settings.precip_dir / "c123-0123456789ab.webp").write_bytes(b"RIFF")
    got = client.get("/api/precip/c123-0123456789ab.webp")
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp"
    assert client.get("/api/precip/sl12-0123456789ab.png").status_code == 404  # not on disk
    assert client.get("/api/precip/abc12-0123456789ab.png").status_code == 404  # bad name


def test_snow_reaching_the_ground_takes_the_level_around_it() -> None:
    # A narrow range of coded cells (-1, -2) inside a 1,800 m snow level, and a wide cold
    # area (the right half) that's coded everywhere.
    v = np.full((20, 40), 1800.0, np.float32)
    v[8:12, 5:9] = -2.0
    v[9, 6] = -1.0
    v[:, 20:] = -2.0
    out = layers.fill_codes(v, 6, 0.0)
    assert (out[8:12, 5:9] == 1800).all()  # the range takes its surroundings' level
    assert (out[:, 20:26] == 1800).all()  # the cold area's edge, within reach
    assert (out[:, 27:] == 0).all()  # beyond reach: snow to the valleys
    assert (layers.fill_codes(np.full((3, 3), -2.0), 6, 0.0) == 0).all()
