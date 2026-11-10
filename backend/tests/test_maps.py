"""The map package: the West box, ECCC radar typing, the index v2 merge, and GRIB helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from snowwatch.maps import grib
from snowwatch.maps.geomet import Net, ts_iso
from snowwatch.maps.palette import (
    MIX,
    MIX_T,
    RAIN,
    RAIN_T,
    SNOW,
    SNOW_T,
    decode_indices,
    encode,
    hex_rgb,
    kinds_of,
    snap,
)
from snowwatch.maps.region import WEST, box_region, region_for, spread
from snowwatch.maps.render import RETIRE_S, FrameOut, Renderer, TotalOut
from snowwatch.maps.sources import radar_eccc as rx

FIXTURES = Path(__file__).parent / "fixtures" / "grib"
CSNOW = FIXTURES / "hrrr_20261110t14z_f01_csnow.grib2"
IDX = FIXTURES / "hrrr_20261110t14z_f01_excerpt.idx"

rain = [hex_rgb(c) for _, c in RAIN]
snow = [hex_rgb(c) for _, c in SNOW]
mix = [hex_rgb(c) for _, c in MIX]


# ---- The region --------------------------------------------------------------------


def test_fixed_west_box() -> None:
    r = region_for([(50.1, -122.9), (39.6, -106.0)], WEST, 1700)
    (south, west), (north, east) = r.bounds
    assert (south, west, north, east) == (31.0, -134.0, 57.0, -102.0)
    assert r.width == 1700 and 1900 < r.height < 2000  # about 1.5 km a pixel


def test_box_widens_for_a_location_outside() -> None:
    r = region_for([(61.2, -149.9)], WEST, 1700)  # Anchorage
    (south, west), (north, east) = r.bounds
    assert north >= 62.2 and west <= -150.9 and south == 31.0 and east == -102.0
    assert r.height <= 2400


def test_spread_fills_gaps_nearby_only() -> None:
    a = np.zeros((1, 9), np.uint8)
    a[0, 0] = 2
    out = spread(a, 3)
    assert out[0, :4].tolist() == [2, 2, 2, 2] and out[0, 5:].tolist() == [0, 0, 0, 0]
    b = np.full((3, 3), -1, np.int32)
    b[1, 1] = 7
    assert (spread(b, 2, empty=-1) == 7).all()


def test_palette_indices_carry_the_type() -> None:
    img = np.zeros((1, 4, 4), np.uint8)
    img[0, 0] = (*snow[3], 255)
    img[0, 1] = (*mix[1], 255)
    img[0, 2] = (*rain[5], 255)
    idx = decode_indices(encode(snap(img)))
    assert idx is not None
    assert kinds_of(idx)[0].tolist() == [SNOW_T, MIX_T, RAIN_T, 0]
    assert decode_indices(b"not a png") is None


# ---- ECCC radar typing ---------------------------------------------------------------


def rgba(h: int, w: int, color: tuple[int, int, int] | None = None) -> np.ndarray:
    out = np.zeros((h, w, 4), np.uint8)
    if color:
        out[...] = (*color, 255)
    return out


def test_type_picture_classified_by_legend_colour() -> None:
    img = rgba(1, 6)
    for i, c in enumerate(["#7fe0ec", "#c46dd3", "#9bfe9b", "#fe1e0d", "#ffc107", "#123456"]):
        img[0, i] = (*hex_rgb(c), 255)
    codes = rx.classify_types(img)
    assert codes is not None
    # snow, mixed, rain, freezing rain → mix, hail → rain, not a legend colour → none
    assert codes[0].tolist() == [SNOW_T, MIX_T, RAIN_T, MIX_T, RAIN_T, 0]
    assert rx.classify_types(None) is None


def test_compose_types_each_echo() -> None:
    h, w = 1, 40
    rain_pic = rgba(h, w, rain[1])  # 0.5 mm/h everywhere…
    rain_pic[0, 2] = (*rain[3], 255)  # …2.5 mm/h here
    snow_pic = rgba(h, w, snow[2])
    types = np.zeros((h, w), np.uint8)
    types[0, 0] = SNOW_T
    types[0, 1:3] = MIX_T
    types[0, 3] = RAIN_T
    # 4…11: untyped but near the rain pixel; 30+: far from any typed pixel.
    fallback = np.zeros((h, w), np.uint8)
    fallback[0, 30:35] = SNOW_T
    out = rx.compose(rain_pic, snow_pic, types, fallback)
    assert out is not None
    assert tuple(out[0, 0, :3]) == snow[2]
    assert tuple(out[0, 1, :3]) == mix[0]  # mixed at 0.5 mm/h: light
    assert tuple(out[0, 2, :3]) == mix[1]  # mixed at 2.5 mm/h: heavy
    assert tuple(out[0, 3, :3]) == rain[1]
    assert tuple(out[0, 6, :3]) == rain[1]  # nearest radar type within reach
    assert tuple(out[0, 32, :3]) == snow[2]  # the forecast's type
    assert tuple(out[0, 38, :3]) == rain[1]  # nothing else known: rain
    assert out[0, :, 3].min() == 255


def test_compose_without_pictures() -> None:
    assert rx.compose(None, None, None) is None
    only_snow = rx.compose(None, rgba(1, 2, snow[0]), np.full((1, 2), SNOW_T, np.uint8))
    assert only_snow is not None and tuple(only_snow[0, 0, :3]) == snow[0]


def test_radar_times_sit_on_the_clock() -> None:
    latest = 1_800_000_000 - 1_800_000_000 % 360  # a 6-minute scan
    scans = list(range(latest - 4 * 3600, latest + 1, 360))
    picked = rx.radar_times(scans)
    assert picked[-1] == latest and picked[0] >= latest - 3 * 3600
    old = [t for t in picked if t < latest - 30 * 60]
    assert old and all(t % 720 == 0 for t in old)
    assert [t for t in scans if t >= latest - 30 * 60] == [t for t in picked if t not in old]
    assert rx.radar_times([]) == []


def test_type_time_takes_the_scan_or_one_before() -> None:
    assert rx.type_time(1000, [400, 640, 1000]) == 1000
    assert rx.type_time(1000, [400, 640]) == 640
    assert rx.type_time(1000, [100]) is None


# ---- A radar render with a fake GeoMet -------------------------------------------------


class GeoMet(Net):
    """Answers the radar layers' capabilities and draws flat pictures for each layer."""

    def __init__(self, latest: int, *, up: bool = True) -> None:
        self.latest = latest
        self.up = up
        self.maps: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        if not self.up or not params or params.get("request") != "GetCapabilities":
            return None
        layer = params["layer"]
        t = self.latest
        if layer == rx.RRAI:
            text = f'<Dimension name="time" default="x">{ts_iso(t - 3 * 3600)}/{ts_iso(t)}/PT6M<'
        elif layer == rx.TYPE:
            start, end = ts_iso(t - 3 * 3600), ts_iso(t - 360)
            text = f'<Dimension name="time" default="x">{start}/{end}/PT6M<'
        elif layer == rx.NOW_RAIN:
            ref = t - 360
            text = (
                f'<Dimension name="time" default="x">{ts_iso(ref)}/{ts_iso(ref + 72 * 60)}/PT6M<'
                f'<Dimension name="reference_time" default="{ts_iso(ref)}">x<'
            )
        else:
            return None
        return type("R", (), {"text": text})()

    def json(self, url: str, params: dict[str, str] | None = None) -> Any:
        return None

    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None:
        assert params is not None
        self.maps.append(params["layers"])
        h, w = int(params["height"]), int(params["width"])
        layer = params["layers"]
        if layer in (rx.RRAI, rx.NOW_RAIN):
            return rgba(h, w, rain[2])
        if layer in (rx.RSNO, rx.NOW_SNOW):
            return rgba(h, w, snow[1])
        if layer == rx.TYPE:  # snow in the top half, rain below
            out = rgba(h, w, hex_rgb("#9bfe9b"))
            out[: h // 2] = (*hex_rgb("#7fe0ec"), 255)
            return out
        return None


def small_region() -> Any:
    return box_region(45, -125, 50, -115, 40)


def test_radar_render_types_frames_and_adds_a_nowcast(tmp_path: Path) -> None:
    latest = 1_800_000_000 - 1_800_000_000 % 360
    net = GeoMet(latest)
    region = small_region()
    ix = Renderer(tmp_path, net, now=lambda: latest + 60).radar(region)
    radar = [f for f in ix["frames"] if f["kind"] == "radar"]
    nowcast = [f for f in ix["frames"] if f["kind"] == "nowcast"]
    assert ix["now"] == latest == radar[-1]["t"]
    assert all(f["past"] and f["span_h"] == 0 for f in radar)
    assert radar[0]["src"] == {"north": "radar-eccc", "south": "radar-eccc"}
    # Every 12 minutes from the nowcast's start, after the latest scan, to 72 minutes.
    assert [f["t"] - (latest - 360) for f in nowcast] == [720, 1440, 2160, 2880, 3600, 4320]
    assert all(not f["past"] for f in nowcast) and nowcast[0]["file"].startswith("n")

    from PIL import Image

    img = np.asarray(Image.open(tmp_path / radar[-1]["file"]).convert("RGBA"))
    assert tuple(img[2, 20, :3]) == snow[1]  # typed snow: the snow-rate colour
    assert tuple(img[-2, 20, :3]) == rain[2]  # typed rain: the rain-rate colour

    # Nothing new: nothing redrawn.
    before = len(net.maps)
    again = Renderer(tmp_path, net, now=lambda: latest + 60).radar(region)
    assert len(net.maps) == before
    assert [f["file"] for f in again["frames"]] == [f["file"] for f in ix["frames"]]


def test_rainviewer_stands_in_when_geomet_radar_is_down(tmp_path: Path) -> None:
    class Down(GeoMet):
        def json(self, url: str, params: dict[str, str] | None = None) -> Any:
            return {"host": "https://rv.example", "radar": {"past": [{"time": 5, "path": "/p"}]}}

        def image(
            self, url: str, params: dict[str, str] | None = None, tries: int = 3
        ) -> np.ndarray | None:
            return rgba(256, 256, (0x00, 0x77, 0xAA))  # RainViewer's 25 dBZ rain

    ix = Renderer(tmp_path, Down(0, up=False)).radar(small_region())
    assert [f["src"]["north"] for f in ix["frames"]] == ["rainviewer"]


# ---- The index: each job replaces only its own part -----------------------------------


def frame(t: int, kind: str, file: str, region_key: str) -> FrameOut:
    return FrameOut(t, kind == "radar", file, f"{kind}|{t}|{region_key}", "", kind, 1, {})


def test_parts_merge_and_old_files_linger(tmp_path: Path) -> None:
    region = small_region()
    r = Renderer(tmp_path, Net(httpx.Client()), now=lambda: 2000)
    for name in ("r1-aaaaaaaaaaaa.png", "f2-bbbbbbbbbbbb.png", "f3-cccccccccccc.png"):
        (tmp_path / name).write_bytes(b"x")
    r._commit(region, {"radar"}, [frame(1000, "radar", "r1-aaaaaaaaaaaa.png", region.key)])
    ix = r._commit(
        region,
        {"forecast"},
        [
            frame(900, "forecast", "f2-bbbbbbbbbbbb.png", region.key),  # over: before "now"
            frame(4600, "forecast", "f3-cccccccccccc.png", region.key),
        ],
    )
    assert [(f["kind"], f["t"]) for f in ix["frames"]] == [("radar", 1000), ("forecast", 4600)]
    ix = r._commit(region, set(), None, [TotalOut(24, 0, 1, "t24-dddddddddddd.png", "k")])
    assert len(ix["frames"]) == 2 and ix["totals"][0]["source"] == "hrdps"

    # A file that left the index stays a while, then goes.
    old = time.time() - RETIRE_S - 60
    os.utime(tmp_path / "f2-bbbbbbbbbbbb.png", (old, old))
    r._commit(region, {"forecast"}, [])
    assert (tmp_path / "f2-bbbbbbbbbbbb.png").exists() is False
    assert (tmp_path / "f3-cccccccccccc.png").exists()  # just left: kept for now
    os.utime(tmp_path / "f3-cccccccccccc.png", (old, old))
    r._commit(region, {"forecast"}, [])
    assert not (tmp_path / "f3-cccccccccccc.png").exists()
    assert (tmp_path / "r1-aaaaaaaaaaaa.png").exists()


def test_a_new_region_drops_the_other_parts(tmp_path: Path) -> None:
    a, b = small_region(), box_region(40, -120, 45, -110, 40)
    r = Renderer(tmp_path, Net(httpx.Client()), now=lambda: 0)
    r._commit(a, {"forecast"}, [frame(4600, "forecast", "f1-aaaaaaaaaaaa.png", a.key)])
    ix = r._commit(b, {"radar"}, [frame(1000, "radar", "r1-aaaaaaaaaaaa.png", b.key)])
    assert [f["kind"] for f in ix["frames"]] == ["radar"] and ix["region"] == b.key


def test_reads_an_index_written_before_v2(tmp_path: Path) -> None:
    region = small_region()
    v1 = {
        "region": region.key,  # not in v1, but lets the frames count as this region's
        "frames": [
            {"t": 1, "past": True, "file": "r1.png", "key": "k1", "south": ""},
            {"t": 9, "past": False, "file": "f9.png", "key": "k9", "south": "hrrr"},
        ],
    }
    (tmp_path / "index.json").write_text(json.dumps(v1))
    r = Renderer(tmp_path, Net(httpx.Client()))
    frames = r._frames_of(r._read(), region)
    assert [f.kind for f in frames] == ["radar", "forecast"]
    (tmp_path / "index.json").write_text("not json")
    assert r._read() == {}


def test_forecast_keeps_its_frames_when_geomet_is_silent(tmp_path: Path) -> None:
    region = small_region()
    r = Renderer(tmp_path, GeoMet(0, up=False), now=lambda: 0)
    (tmp_path / "f9-aaaaaaaaaaaa.png").write_bytes(b"x")
    r._commit(region, {"forecast"}, [frame(9000, "forecast", "f9-aaaaaaaaaaaa.png", region.key)])
    assert len(r.forecast(region)["frames"]) == 1
    assert r.snow_totals(region)["frames"]  # no totals either: index untouched


# ---- GRIB ---------------------------------------------------------------------------


def test_parse_idx_and_find() -> None:
    entries = grib.parse_idx(IDX.read_text() + "junk line\n")
    csnow = grib.find(entries, r":CSNOW:surface:")
    assert csnow is not None and csnow.start == 57974213 and csnow.end == 57979935
    assert csnow.line == ":CSNOW:surface:1 hour fcst:"
    assert entries[-1].end is None
    assert grib.find(entries, r":ASNOW:") is None


class Files(Net):
    """A web server with one GRIB file and its index, answering range requests."""

    def __init__(self, body: bytes, idx: str) -> None:
        self.body, self.idx = body, idx

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        return type("R", (), {"text": self.idx})() if url.endswith(".idx") else None

    def range(self, url: str, start: int, end: int | None, tries: int = 3) -> bytes | None:
        return self.body[start : None if end is None else end + 1]


def test_fetch_message_by_byte_range() -> None:
    msg = CSNOW.read_bytes()
    body = b"\0" * 100 + msg + b"\0" * 50
    idx = "1:0:d=2026111014:XX:surface:anl:\n2:100:d=2026111014:CSNOW:surface:1 hour fcst:\n"
    idx += f"3:{100 + len(msg)}:d=2026111014:CRAIN:surface:1 hour fcst:\n"
    net = Files(body, idx)
    assert grib.fetch_message(net, "https://x/f.grib2", r":CSNOW:") == msg
    assert grib.fetch_message(net, "https://x/f.grib2", r":ASNOW:") is None
    assert grib.fetch_message(net, "https://x/f.grib2", r":XX:") is None  # not GRIB bytes


def test_net_range_accepts_only_partial_content() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/ok":
            assert req.headers["Range"] == "bytes=10-19"
            return httpx.Response(206, content=b"0123456789")
        if req.url.path == "/whole":
            return httpx.Response(200, content=b"x" * 1000)
        return httpx.Response(404)

    net = Net(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert net.range("https://h/ok", 10, 19) == b"0123456789"
    assert net.range("https://h/whole", 10, 19) is None
    assert net.range("https://h/missing", 0, None) is None


def test_decode_and_resample_real_hrrr(tmp_path: Path) -> None:
    values, md = grib.decode(CSNOW.read_bytes())
    assert values.shape == (1059, 1799) and values.dtype == np.float32
    assert md.var_abbrev == "CSNOW" and set(np.unique(values)) <= {0.0, 1.0}
    region = box_region(44, -124, 50, -114, 300)
    imap = grib.index_map(md, region, tmp_path)
    assert imap.shape == (region.height, region.width) and (imap >= 0).all()
    # Each pixel's source cell is the grid point under it (HRRR is 3 km; a pixel ~2.6 km).
    lat, lon = md.latlng()
    lons, lats = region.lonlats()
    for i, j in [(5, 5), (region.height // 2, 150), (region.height - 3, 290)]:
        k = imap[i, j]
        assert abs(lat[k] - lats[i]) < 0.04 and abs(lon[k] - lons[j]) < 0.05
    assert list(tmp_path.glob("*.npy"))  # cached…
    assert (grib.index_map(md, region, tmp_path) == imap).all()  # …and read back
    out = grib.resample(values, imap)
    assert out.shape == imap.shape and np.isfinite(out).all()
    # Off the HRRR grid (mid-Pacific): no source cells.
    far = grib.index_map(md, box_region(10, -170, 15, -160, 20))
    assert (far == -1).all() and np.isnan(grib.resample(values, far)).all()


def test_config_has_the_map_box() -> None:
    from snowwatch.config import MapConfig
    from tests.helpers import config

    assert config().map.region == WEST and config().map.width == 1700
    with pytest.raises(ValueError):
        MapConfig(region=(50, -100, 40, -120))


# ---- The worker's three map jobs ----------------------------------------------------


def test_worker_runs_map_parts_and_survives_failures(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from snowwatch import cli
    from snowwatch.scheduler import Worker, build_scheduler
    from tests.helpers import config

    calls: list[tuple[str, int]] = []

    def radar(self: Renderer, region: Any) -> dict[str, Any]:
        calls.append(("radar", region.width))
        return {"frames": [{"kind": "radar"}], "totals": []}

    def broken(self: Renderer, region: Any) -> dict[str, Any]:
        raise RuntimeError("GeoMet fell over")

    monkeypatch.setattr(Renderer, "radar", radar)
    monkeypatch.setattr(Renderer, "forecast", broken)
    monkeypatch.setattr(Renderer, "snow_totals", lambda self, region: {})
    w = Worker(settings, config())
    w.precip()  # the forecast's failure is logged, not raised
    assert calls == [("radar", 1700)]
    w.map_locks["radar"].acquire()
    w.radar()  # still running from last time: skip
    assert len(calls) == 1
    w.map_locks["radar"].release()

    ids = {j.id for j in build_scheduler(w).get_jobs()}
    assert {"radar", "forecast_frames", "totals_fields"} <= ids and "precip" not in ids

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["map", "radar"]) == 0 and len(calls) == 2
    assert cli.main(["precip"]) == 0 and len(calls) == 3
