"""The snow total as numbers for the map (maps/totaldata.py)."""

from __future__ import annotations

import numpy as np
import pytest

from snowwatch.maps import bins, totaldata, totals


def test_codes_round_trip_within_a_step() -> None:
    cm = np.array([0.0, 0.1, 0.2, 2.54, 30.0, 400.0, 5000.0, np.nan], np.float32)
    codes = totaldata.cm_codes(cm)
    assert codes[0] == codes[1] == codes[-1] == 0
    back = totaldata.code_cm(codes)
    assert back[2:6] == pytest.approx(cm[2:6], rel=0.02)
    assert back[6] == pytest.approx(totaldata.CM_MAX, rel=0.02)  # capped


def test_a_step_keeps_the_area_total_and_every_other_band() -> None:
    area = np.full((40, 60), 12.0, np.float32)
    grid = np.zeros((20, 30, len(bins.ELEVS)), np.float32)
    grid[..., :] = bins.ELEVS / 100  # 0 cm at sea level, 45 cm at 4,500 m
    step = totaldata.decode(totaldata.encode(totaldata.area_plane(area), grid))
    assert step is not None
    assert step.area.shape == (20, 30) and step.band_m == 500
    assert step.bands.shape == (10, 10, 15)
    assert float(totaldata.code_cm(step.area[5, 5])) == pytest.approx(12, rel=0.02)
    want = np.arange(0, 4501, 500) / 100
    got = totaldata.code_cm(step.bands[:, 3, 3])
    assert got[1:] == pytest.approx(want[1:], rel=0.02) and got[0] == 0
    # No snow by elevation: the area alone.
    plain = totaldata.decode(totaldata.encode(totaldata.area_plane(area), None))
    assert plain is not None and plain.bands.shape[0] == 0
    assert totaldata.decode(b"nope") is None


def test_the_steps_include_every_window() -> None:
    assert set(totals.WINDOWS) <= set(totaldata.STEP_WINDOWS)
