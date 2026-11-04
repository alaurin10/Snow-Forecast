from __future__ import annotations

import pytest

from snowwatch.analysis.freezing import freezing_level_m

# (geopotential height m, temperature °C) at 850, 700, 600, 500 hPa
WARM_LOW = [(1500, 4.0), (3000, -6.0), (4200, -14.0), (5600, -25.0)]


def test_interpolates_the_zero_crossing() -> None:
    # Between 1500 m (+4) and 3000 m (-6): 1500 + 1500 * 4/10 = 2100 m.
    assert freezing_level_m(1000, 6.0, WARM_LOW) == pytest.approx(2100)


def test_surface_layer_counts() -> None:
    # Surface 1800 m at +1 °C and 3000 m at -6 °C: 1800 + 1200/7 ≈ 1971 m.
    levels = [(1500, 4.0), (3000, -6.0)]
    assert freezing_level_m(1800, 1.0, levels) == pytest.approx(1800 + 1200 / 7)


def test_column_below_freezing_extrapolates_down() -> None:
    levels = [(1500, -8.0), (3000, -15.0)]
    assert freezing_level_m(1000, -3.25, levels) == pytest.approx(500)


def test_never_below_sea_level() -> None:
    assert freezing_level_m(200, -20.0, []) == 0.0


def test_warm_column_extrapolates_up() -> None:
    assert freezing_level_m(1000, 20.0, [(5600, 3.25)]) == pytest.approx(6100)


def test_missing_data() -> None:
    assert freezing_level_m(1000, None, [(None, None)]) is None
