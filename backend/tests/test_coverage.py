"""Filling radar's blind spots from the forecast (maps/coverage.py, render.fill_gaps)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snowwatch.analysis.backcountry import BackcountryConfig
from snowwatch.maps import coverage, dataframe, point
from snowwatch.maps.palette import NONE, RAIN_T, SNOW_T
from snowwatch.maps.render import FrameOut, Renderer, fill_gaps
from tests.test_maps import GeoMet, small_region


def test_quality_index_to_seen() -> None:
    q = np.array([0.0, 0.15, 0.325, 0.5, 1.0, np.nan], np.float32)
    seen = coverage.from_quality(q)
    assert seen[:5].tolist() == pytest.approx([0.0, 0.0, 0.5, 1.0, 1.0])
    assert np.isnan(seen[5])


def test_coverage_takes_mrms_where_it_reaches_and_canada_beyond() -> None:
    quality = np.full((20, 20), np.nan, np.float32)
    quality[10:] = 0.0  # MRMS's grid covers the south half: blind there
    quality[10:, 10:] = 1.0  # …except the south-east, which a radar sees
    mask = np.zeros((20, 20), np.float32)
    mask[:10, :10] = 1.0  # beyond MRMS, Canada's radars reach the north-west only
    seen = coverage.combine(quality, mask)
    assert seen is not None
    assert seen[2, 2] == pytest.approx(1.0, abs=0.01) and seen[2, 17] < 0.01
    assert seen[17, 2] < 0.01 and seen[17, 17] == pytest.approx(1.0, abs=0.01)
    # Softened across a few pixels, not a step.
    assert 0.05 < seen[2, 10] < 0.95
    assert coverage.combine(None, None) is None
    # Without Canada's mask, beyond MRMS counts as seen: no fill rather than a wrong one.
    only = coverage.combine(quality, None)
    assert only is not None and only[2, 17] == pytest.approx(1.0)


def test_fill_gaps_adds_the_forecast_where_radar_is_blind() -> None:
    radar = np.array([[0.0, 0.0, 2.0, 0.0, np.nan]], np.float32)
    kind = np.array([[NONE, NONE, RAIN_T, NONE, NONE]], np.uint8)
    rate = np.array([[1.0, 1.0, 0.5, 1.0, 1.0]], np.float32)
    snow = np.ones((1, 5), np.float32)
    mix = np.zeros((1, 5), np.float32)
    seen = np.array([[1.0, 0.0, 0.0, 0.5, 0.0]], np.float32)
    out, kinds, share = fill_gaps(radar, kind, (rate, snow, mix), seen)
    # Seen: radar as it is (dry). Blind: the forecast. An echo radar sees stays.
    # Half seen: half the forecast. No data from radar: the forecast.
    assert out.tolist()[0] == pytest.approx([0.0, 1.0, 2.0, 0.5, 1.0])
    assert share.tolist()[0] == pytest.approx([0.0, 1.0, 0.0, 1.0, 1.0])
    assert kinds.tolist()[0] == [NONE, SNOW_T, RAIN_T, SNOW_T, SNOW_T]


def test_frames_carry_the_filled_share_as_a_third_plane() -> None:
    amount = np.full((16, 16), 1.0, np.float32)
    kind = np.full((16, 16), SNOW_T, np.uint8)
    filled = np.zeros((16, 16), np.float32)
    filled[:, :8] = 1.0
    got = dataframe.decode(dataframe.encode(amount, kind, 1, filled))
    assert got is not None and got.filled is not None
    assert got.filled.shape == got.snow.shape
    assert got.filled[:, :2].min() == 255 and got.filled[:, 2:].max() == 0
    # Nothing filled: two planes, as before (and older files read as they did).
    plain = dataframe.decode(dataframe.encode(amount, kind, 1, np.zeros((16, 16))))
    assert plain is not None and plain.filled is None


class Blind(GeoMet):
    """GeoMet whose coverage says no radar reaches the west half of the box."""

    def image(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        assert params is not None
        if params["layers"] == coverage.UNCOVERED_LAYER:
            self.maps.append(params["layers"])
            h, w = int(params["height"]), int(params["width"])
            out = np.zeros((h, w, 4), np.uint8)
            out[:, : w // 2] = (181, 181, 181, 128)
            return out
        return super().image(url, params, tries)


def test_radar_frames_are_filled_where_no_radar_reaches(tmp_path: Path) -> None:
    latest = 1_800_000_000 - 1_800_000_000 % 360
    net = Blind(latest)  # radar: rain at 1.5 mm/h in the south, snow at 0.7 in the north
    region = small_region()
    r = Renderer(tmp_path, net, now=lambda: latest + 60)
    shape = (region.height, region.width)
    # The forecast: 6 mm/h of rain everywhere.
    forecast = []
    for i in range(3):
        t = latest - latest % 3600 + i * 3600
        name, data = r._save_precip(
            np.full(shape, 6.0, np.float32), np.full(shape, RAIN_T, np.uint8), f"f{t}", ds=2
        )
        forecast.append(
            FrameOut(t, False, name, f"f{t}", "", "forecast", 1, {}, "fine", data, 2, t - 1800)
        )
    r._commit(region, {"forecast"}, forecast)
    ix = r.radar(region)
    latest_frame = next(f for f in ix["frames"] if f["kind"] == "radar" and f["t"] == latest)
    got = dataframe.decode((tmp_path / latest_frame["data"]).read_bytes())
    assert got is not None and got.filled is not None
    rates = got.rates()
    row = shape[0] - 3
    # West (no radar): the forecast's 6 mm/h, 4.5 of it filled in over the 1.5 the fake
    # radar shows there. East: radar's own.
    assert rates[row, 2] == pytest.approx(6.0, rel=0.07)
    assert got.filled[row // 4, 0] == pytest.approx(0.75 * 255, abs=8)
    assert rates[row, -3] < 2.2 and got.filled[row // 4, -1] == 0
    # A tap says which is which.
    bc = BackcountryConfig()
    (south, west), (_north, east) = region.bounds
    lat = south + 0.1
    tap_w = point.probe(ix, tmp_path, tmp_path, lat, west + 0.2, latest, bc)
    tap_e = point.probe(ix, tmp_path, tmp_path, lat, east - 0.2, latest, bc)
    now_w = next(x for x in tap_w.rates if x.t == latest)
    now_e = next(x for x in tap_e.rates if x.t == latest)
    assert now_w.filled and now_w.type == "rain"
    assert not now_e.filled
    # The coverage is kept: the next run asks for it no more.
    asked = net.maps.count(coverage.UNCOVERED_LAYER)
    r.radar(region)
    assert net.maps.count(coverage.UNCOVERED_LAYER) == asked == 1
