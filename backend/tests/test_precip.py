"""The map's precipitation frames: colours, geometry, and a full render with a fake network."""

from __future__ import annotations

import io
import json
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
    parse_times,
    radar_recolor,
    rain_rate,
    region_for,
    snap,
    snow_rate,
    stitch,
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


def test_time_dimension() -> None:
    ts = parse_times("2026-11-06T19:00:00Z/2026-11-06T22:00:00Z/PT1H")
    assert len(ts) == 4 and ts[1] - ts[0] == 3600
    assert len(parse_times("2026-11-06T19:00:00Z, junk, 2026-11-06T18:00:00Z")) == 2


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
    """Answers like the real sources, with flat fields, and counts what was fetched."""

    def __init__(self, now: int) -> None:
        self.now = now
        self.images = 0
        self.grids = 0

    def json(self, url: str, params: dict[str, str] | None = None) -> Any:
        if "rainviewer" in url:
            past = [{"time": self.now - 600 * i, "path": f"/v2/radar/{i}"} for i in (2, 1, 0)]
            return {"host": "https://tiles.example", "radar": {"past": past}}
        return None

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        if params and params.get("request") == "GetCapabilities":
            if "radar" in params["layer"].lower():
                return None  # Environment Canada radar down: RainViewer stands in
            start = self.now - self.now % 3600
            text = (
                f'<Dimension name="time" default="x">{precip.ts_iso(start)}/'
                f"{precip.ts_iso(start + 12 * 3600)}/PT1H</Dimension>"
                '<Dimension name="reference_time" default="RUN1">x</Dimension>'
            )
            return type("R", (), {"text": text})()
        if "GetCoverage" in url:
            # GeoMet's numbers: HRDPS snows 0.6 mm an hour everywhere (its domain comes
            # from the picture below); RDPS, which fills in elsewhere, is dry.
            self.grids += 1
            import urllib.parse

            layer = urllib.parse.parse_qs(url.split("?", 1)[1])["coverageId"][0]
            value = 0.6 if layer == "HRDPS.CONTINENTAL.DIAG_SN_PT1H" else 0.0
            body = float_tiff(np.full((40, 60), value, np.float32), -126.0, 51.0, 0.25)
            return type("R", (), {"content": body, "headers": {"content-type": "image/tiff"}})()
        return None

    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None:
        self.images += 1
        if params:  # GeoMet: HRDPS's domain covers the top half
            assert params["layers"] == precip.DOMAIN_LAYER
            w, h = int(params["width"]), int(params["height"])
            out = np.zeros((h, w, 4), np.uint8)
            out[: h // 2] = (0, 0, 0, 255)
            return out
        tile = np.zeros((256, 256, 4), np.uint8)
        tile[...] = (0x00, 0x77, 0xAA, 255) if "tiles.example" in url else (0x73, 0xC4, 0x76, 255)
        return tile


def precip_rain_t() -> int:
    from snowwatch.maps.palette import RAIN_T

    return RAIN_T


def fake_hrrr(monkeypatch: Any, now: int) -> None:
    """HRRR reaches the first 6 hours, raining everywhere; no NBM run."""
    from snowwatch.maps.sources import hrrr, nbm

    init = now - now % 3600
    slots = {init + h * 3600: (init, h) for h in range(1, 7)}
    monkeypatch.setattr(hrrr, "slots", lambda net, now: slots)

    def fields(net: Any, run: int, f: int, region: Region, *dirs: Any) -> Any:
        shape = (region.height, region.width)
        return np.full(shape, 0.6, np.float32), np.full(shape, precip_rain_t(), np.uint8)

    monkeypatch.setattr(hrrr, "fields", fields)
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: None)


def test_render_writes_index_and_reuses_frames(tmp_path: Path, monkeypatch: Any) -> None:
    now = 1_800_000_000
    net = FakeNet(now)
    fake_hrrr(monkeypatch, now)
    region = Region(
        *[precip.merc_x(-125), precip.merc_y(42)], precip.merc_x(-115), precip.merc_y(50), 120, 100
    )
    out = tmp_path / "precip"
    index = Renderer(out, net, now=lambda: now).run(region)

    frames = index["frames"]
    past = [f for f in frames if f["past"]]
    future = [f for f in frames if not f["past"]]
    assert len(past) == 3 and index["now"] == now
    assert {f["kind"] for f in past} == {"radar"} and past[0]["src"]["north"] == "rainviewer"
    assert len(future) == 12 and {f["kind"] for f in future} == {"forecast"}
    assert {f["south"] for f in future} == {"hrrr", ""}  # HRRR to 6 h, nothing after…
    assert {f["src"]["south"] for f in future} == {"hrrr", "rdps"}  # …so RDPS fills in
    assert future[0]["src"] == {"north": "hrdps", "south": "hrrr"}
    assert index["version"] == 2 and "Radar: RainViewer" in index["attribution"]
    for f in frames:
        assert (out / f["file"]).exists()
    on_disk = json.loads((out / "index.json").read_text())
    assert on_disk["bounds"] == region.bounds

    # A forecast frame: HRDPS's snow well inside its domain, HRRR's rain well outside it,
    # and the same amount (0.6 mm/h) all the way across the join.
    first = np.asarray(Image.open(out / future[0]["file"]).convert("RGBA"))
    assert tuple(first[10, 10][:3]) == snow[1]
    assert tuple(first[90, 10][:3]) == rain[1]
    column = [tuple(px[:3]) for px in first[:, 10]]
    assert set(column) == {snow[1], rain[1]} and first[:, 10, 3].min() == 255
    # Beyond HRRR's reach, RDPS (dry here) fills in outside HRDPS's domain.
    late = np.asarray(Image.open(out / future[-1]["file"]).convert("RGBA"))
    assert tuple(late[10, 10][:3]) == snow[1] and late[90, 10, 3] == 0

    # Nothing changed: nothing fetched or redrawn.
    before = (net.images, net.grids)
    again = Renderer(out, net, now=lambda: now).run(region)
    assert (net.images, net.grids) == before
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
    """Many virtual machines report a basic CPU type; NumPy 2.4+ needs x86-64-v2 and
    fails to import there ("your machine doesn't support X86_V2"). Keep a build that doesn't."""
    simd = np.show_config(mode="dicts")["SIMD Extensions"]  # type: ignore[no-untyped-call]
    assert "X86_V2" not in simd.get("baseline", [])


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
                import urllib.parse

                q = urllib.parse.parse_qs(url.split("?", 1)[1])
                if not q["coverageId"][0].endswith("_SN"):
                    return None  # no temperatures: 10:1
                t = precip.iso_ts(q["TIME"][0])
                # 1 mm water an hour since the run began, over the whole box.
                grid = np.full((40, 60), float((t - (now - 6 * 3600)) / 3600), np.float32)
                body = float_tiff(grid, -126.0, 51.0, 0.25)
                return type("R", (), {"content": body, "headers": {"content-type": "image/tiff"}})()
            return None

    net = TotalsNet()
    g = wcs_grid(net, "HRDPS.CONTINENTAL_SN", precip.ts_iso(now), region)
    assert g is not None and g.dlon == 0.25 and g.lon0 == -126.0 and g.data.shape == (40, 60)

    r = Renderer(tmp_path, net, now=lambda: now + 600)
    totals = r._snow_totals(region, now + 600)
    assert [t.hours for t in totals] == [12, 24, 30]  # the run ends 30 h out
    assert [t.window for t in totals] == [12, 24, 48]
    assert all(t.start == now for t in totals)
    img = np.asarray(Image.open(tmp_path / totals[1].file).convert("RGBA"))
    # 24 mm of water ≈ 24 cm of snow: the 22.86 cm step.
    step = next(c for low, c in reversed(TOTAL) if low <= 24)
    assert tuple(img[25, 30][:3]) == hex_rgb(step)
