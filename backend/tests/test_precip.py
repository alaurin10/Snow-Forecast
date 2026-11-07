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
    assert client.get("/api/precip/index.json.tmp").status_code == 404
    assert client.get("/api/precip/..%2Fsnowwatch.db").status_code == 404
