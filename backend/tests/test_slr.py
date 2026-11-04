from __future__ import annotations

import pytest

from snowwatch.analysis.slr import period_ratio, ptype, ratio_for, slr_depth_cm
from snowwatch.config import ForecastConfig


@pytest.mark.parametrize(
    "temp_c,ratio,label",
    [
        (0.5, 8, "Heavy & wet"),
        (-0.556, 8, "Heavy & wet"),
        (-0.6, 11, "Average"),
        (-3.333, 11, "Average"),
        (-3.4, 14, "Light"),
        (-7.222, 14, "Light"),
        (-7.3, 17, "Dry & fluffy"),
        (-25, 17, "Dry & fluffy"),
    ],
)
def test_ratio_bands(cfg: ForecastConfig, temp_c: float, ratio: int, label: str) -> None:
    assert ratio_for(temp_c, cfg.slr_bands) == (ratio, label)


def test_period_ratio_uses_snowing_hours_only(cfg: ForecastConfig) -> None:
    swe = [0.0, 2.0, 2.0, 2.0, 0.05]
    temps = [5.0, -8.0, -9.0, -10.0, 3.0]
    assert period_ratio(swe, temps, cfg.slr_bands) == (17, "Dry & fluffy")
    assert period_ratio([0.0, 0.1], [-5.0, -5.0], cfg.slr_bands) == (None, None)


def test_depth() -> None:
    assert slr_depth_cm(10, 15) == 15.0  # 10 mm water at 15:1 is 15 cm


@pytest.mark.parametrize(
    "snow,liquid,expected",
    [
        (0.0, 0.05, "none"),
        (1.0, 0.0, "snow"),
        (0.9, 0.1, "snow"),
        (0.0, 1.0, "rain"),
        (0.5, 0.5, "mix"),
    ],
)
def test_ptype(snow: float, liquid: float, expected: str) -> None:
    assert ptype(snow, liquid) == expected
