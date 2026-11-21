"""Forecast clouds with their heights (maps/cloudheights.py), NBM's cloud layers
(sources/nbm.py) and the ground under the box (maps/ground.py)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from snowwatch.maps import cloudheights as ch
from snowwatch.maps import grib, ground
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import box_region
from snowwatch.maps.sources import nbm
from snowwatch.maps.sources.nbm import CloudLayer, Nbm

SHAPE = (8, 8)


def full(v: float) -> np.ndarray:
    return np.full(SHAPE, v, np.float32)


def layer(base: float, top: float, cover: float) -> CloudLayer:
    return CloudLayer(full(base), full(top), full(cover))


NONE = layer(7620, 13716, 0)


# ---- Heights from NBM's layers ------------------------------------------------------------


def test_the_lowest_layer_is_put_above_sea_level_and_one_just_above_joins_it() -> None:
    g = full(1000)
    # 500–1500 m above the ground, then one starting 200 m above its top.
    h = ch.from_layers([layer(500, 1500, 80), layer(1700, 3000, 50), NONE], full(30), g)
    assert h.known.all()
    assert np.allclose(h.base, 1500) and h.top is not None and np.allclose(h.top, 4000)
    assert np.allclose(h.low, 80)
    assert np.allclose(h.above, 30)  # only the high cloud is left above


def test_a_layer_well_above_counts_as_cloud_above() -> None:
    h = ch.from_layers([layer(300, 800, 60), layer(3000, 4000, 50), NONE], full(20), full(500))
    assert np.allclose(h.base, 800) and h.top is not None and np.allclose(h.top, 1300)
    # 50% and 20% together.
    assert np.allclose(h.above, 60)


def test_a_layer_too_high_for_any_terrain_is_only_cloud_above() -> None:
    h = ch.from_layers([layer(6000, 7000, 70), NONE, NONE], None, full(200))
    assert np.allclose(h.low, 0) and np.isnan(h.base).all()
    assert np.allclose(h.above, 70)


def test_clear_sky_and_thin_layers_have_no_low_cloud() -> None:
    h = ch.from_layers([NONE, NONE, NONE], full(0), full(800))
    assert np.allclose(h.low, 0) and np.allclose(h.above, 0) and np.isnan(h.base).all()
    thin = ch.from_layers([layer(500, 900, 3), NONE, NONE], None, full(800))
    assert np.allclose(thin.low, 0)


def test_a_top_nbm_left_out_is_taken_a_kilometre_above_the_base() -> None:
    h = ch.from_layers([layer(400, 13716, 90), NONE, NONE], None, full(100))
    assert h.top is not None and np.allclose(h.top, 1500)


def test_off_nbms_grid_the_heights_are_unknown() -> None:
    lay = layer(500, 1500, 80)
    lay.base[:, :4] = np.nan
    h = ch.from_layers([lay, NONE, NONE], None, full(0))
    assert not h.known[:, :4].any() and h.known[:, 4:].all()
    assert np.allclose(h.low[:, :4], 0)


def test_heights_from_the_base_alone() -> None:
    base = full(30.48)  # the ground in cloud
    base[:4] = 88888  # NBM's "no base": the cover is cloud above
    h = ch.from_base(base, full(70), full(2000))
    assert h.top is None
    assert np.allclose(h.base[4:], 2030.48) and np.allclose(h.low[4:], 70)
    assert np.isnan(h.base[:4]).all() and np.allclose(h.above[:4], 70)
    assert np.allclose(h.low[:4], 0) and np.allclose(h.above[4:], 0)


# ---- The numbers file ---------------------------------------------------------------------


def test_numbers_round_trip_at_a_quarter_size() -> None:
    shape = (40, 64)
    g = np.full(shape, 1200, np.float32)
    lay = CloudLayer(
        np.full(shape, 600, np.float32),
        np.full(shape, 1800, np.float32),
        np.full(shape, 75, np.float32),
    )
    lay.base[:, 32:] = 7620  # no cloud on the east side: its base is filled in from the west
    lay.cover[:, 32:] = 0
    blank = CloudLayer(*(np.full(shape, v, np.float32) for v in (7620, 13716, 0)))
    h = ch.from_layers([lay, blank, blank], np.full(shape, 21, np.float32), g)
    data = ch.encode(np.full(shape, 63, np.float32), h)
    assert data[:2] == b"\x1f\x8b"  # gzip
    d = ch.decode(data)
    assert d["ds"] == ch.DS and d["flags"] == ch.HAS_HEIGHTS | ch.HAS_TOPS
    cover = d["cover"]
    assert isinstance(cover, np.ndarray) and cover.shape == (10, 16)
    assert np.allclose(cover, 64)  # 2% steps
    assert np.allclose(d["known"], 1)
    assert np.allclose(d["low"][:, :8], 76) and np.allclose(d["low"][:, 8:], 0)
    assert np.allclose(d["base"], 1800)  # 600 m above 1,200 m ground, everywhere
    assert np.allclose(d["top"], 3000)
    assert np.allclose(d["above"], 20)  # 21% to the nearest 2% step


def test_numbers_without_heights_hold_only_the_cover() -> None:
    d = ch.decode(ch.encode(np.full((16, 16), 40, np.float32), None))
    assert d["flags"] == 0 and set(d) == {"flags", "ds", "cover"}
    no_tops = ch.decode(ch.encode(full(40), ch.from_base(full(100), full(40), full(500))))
    assert no_tops["flags"] == ch.HAS_HEIGHTS and "top" not in no_tops


def test_heights_above_the_scale_are_clipped() -> None:
    h = ch.from_layers([layer(5000, 12000, 90), NONE, NONE], None, full(800))
    d = ch.decode(ch.encode(full(90), h))
    assert np.allclose(d["base"], 5790) and np.allclose(d["top"], 255 * ch.STEP_M)


# ---- GRIB: the nth match and the level type -------------------------------------------------


def message(surface: int) -> bytes:
    """A GRIB2 stand-in: section 0, then a section 4 naming its first fixed surface."""
    sec4 = bytearray(34)
    sec4[0:4] = (34).to_bytes(4, "big")
    sec4[4] = 4
    sec4[22] = surface
    return b"GRIB" + bytes(12) + bytes(sec4) + b"7777"


def test_first_surface_reads_section_four() -> None:
    assert grib.first_surface(message(196)) == 196
    assert grib.first_surface(b"GRIB" + bytes(12)) is None


def test_find_takes_the_nth_of_identical_descriptions() -> None:
    idx = "\n".join(
        [
            "1:0:d=2026112112:CDCB:reserved:12 hour fcst:",
            "2:100:d=2026112112:TCDC:reserved:12 hour fcst:",
            "3:200:d=2026112112:CDCB:reserved:12 hour fcst:",
            "4:300:d=2026112112:CDCB:high cloud layer:12 hour fcst:",
        ]
    )
    entries = grib.parse_idx(idx)
    pat = r":CDCB:reserved:12 hour fcst:"
    first, second = grib.find(entries, pat), grib.find(entries, pat, 1)
    assert first is not None and first.start == 0
    assert second is not None and second.start == 200
    assert grib.find(entries, pat, 2) is None


# ---- NBM's cloud layers ---------------------------------------------------------------------


def test_nbm_cloud_layers_lowest_first_and_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    region = box_region(40, -120, 45, -110, 8)
    asked: list[tuple[list[str], list[int] | None]] = []
    # The file lists the second layer first; the third is missing its top.
    order = [196, 195, 197]

    def fetch(
        net: Any, url: str, patterns: list[str], cache_dir: Any = None, nth: Any = None
    ) -> list[bytes | None]:
        asked.append((patterns, nth))
        out: list[bytes | None] = []
        for i in range(9):
            surface = order[i // 3]
            out.append(None if (surface == 197 and i % 3 == 1) else message(surface))
        return [*out, message(234)]

    def on_region(raw: bytes | None, region: Any, grids: Any = None) -> np.ndarray | None:
        if raw is None:
            return None
        return np.full((region.height, region.width), float(grib.first_surface(raw) or 0))

    monkeypatch.setattr(grib, "fetch_messages", fetch)
    monkeypatch.setattr(grib, "on_region", on_region)
    fake = Nbm(Net.__new__(Net), 1_800_000_000, region)
    got = fake.cloud_layers(12)
    assert got is not None
    lays, high = got
    assert [float(lay.base[0, 0]) for lay in lays] == [195, 196]  # the third left out
    assert high is not None and float(high[0, 0]) == 234
    patterns, nth = asked[0]
    assert nth == [0, 0, 0, 1, 1, 1, 2, 2, 2, 0]
    assert patterns[0] == r":CDCB:reserved:12 hour fcst:"
    assert patterns[-1] == r":TCDC:high cloud layer:12 hour fcst:"
    # Past 36 h there are no layers, and nothing is asked for.
    assert fake.cloud_layers(nbm.CLOUD_LAYERS_TO_H + 3) is None and len(asked) == 1


# ---- The ground ---------------------------------------------------------------------------


def terrarium_png(metres: float) -> bytes:
    v = metres + 32768
    r, gb = divmod(v, 256)
    g, b = int(gb), round((gb - int(gb)) * 256)
    img = np.zeros((ground.TILE, ground.TILE, 3), np.uint8)
    img[...] = (int(r), g, b)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG")
    return buf.getvalue()


class TileClient:
    """Mapterhorn: 1,500 m tiles, except the sea (404) west of 125°W."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def get(self, url: str, timeout: float = 0) -> Any:
        self.calls += 1
        z, x, _ = (int(p) for p in [*url.rsplit("/", 3)[1:3], url.rsplit("/", 1)[1][:-5]])
        if self.fail and x == 5:
            return type("R", (), {"status_code": 503, "content": b""})()
        lon_west = x / 2**z * 360 - 180
        if lon_west < -125:
            return type("R", (), {"status_code": 404, "content": b""})()
        return type("R", (), {"status_code": 200, "content": terrarium_png(1500)})()


def test_ground_from_elevation_tiles_kept_on_disk(tmp_path: Path) -> None:
    region = box_region(44, -130, 50, -114, 40)
    client = TileClient()
    net = Net(client)  # type: ignore[arg-type]
    g = ground.ground(net, region, tmp_path)
    assert g is not None and g.shape == (region.height, region.width)
    assert g[:, -1].min() == pytest.approx(1500, abs=1)  # the east: land
    assert g[:, 0].max() == 0  # the far west: sea
    calls = client.calls
    assert ground.ground(net, region, tmp_path) is not None and client.calls == calls


def test_ground_with_a_tile_missing_is_tried_again(tmp_path: Path) -> None:
    region = box_region(44, -130, 50, -114, 40)
    net = Net(TileClient(fail=True))  # type: ignore[arg-type]
    assert ground.ground(net, region, tmp_path) is None
    assert not list(tmp_path.glob("ground-*.npy"))


def test_box_mean() -> None:
    a = np.zeros((5, 5), np.float32)
    a[2, 2] = 9
    m = ground._box_mean(a, 3)
    assert m[2, 2] == pytest.approx(1) and m[1, 1] == pytest.approx(1) and m[0, 0] == 0
