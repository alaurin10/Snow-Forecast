from __future__ import annotations

import pytest

from snowwatch.analysis.ridge import interpolate, ridge_wind


def test_halfway_between_levels() -> None:
    speed, direction = interpolate(2250, (1500, 20, 200), (3000, 40, 240)) or (0, 0)
    assert speed == pytest.approx(30)
    assert direction == pytest.approx(220, abs=0.5)


def test_clamped_outside_the_levels() -> None:
    assert interpolate(1000, (1500, 20, 200), (3000, 40, 240)) == (20, 200)
    assert interpolate(4000, (1500, 20, 200), (3000, 40, 240)) == (40, 240)


def test_direction_wraps_through_north() -> None:
    _, direction = interpolate(2250, (1500, 20, 350), (3000, 20, 10)) or (0, 0)
    assert min(direction, 360 - direction) == pytest.approx(0, abs=0.5)


def test_one_level_missing_uses_the_other() -> None:
    assert interpolate(2000, (None, None, None), (3000, 40, 240)) == (40, 240)
    assert interpolate(2000, (None, None, None), (None, 10, None)) is None


def test_models_combine_by_median_and_mean_direction() -> None:
    h = 0

    def model(speed: float, direction: float) -> dict[str, dict[int, float | None]]:
        return {
            "geopotential_height_850hPa": {h: 1500},
            "geopotential_height_700hPa": {h: 3000},
            "wind_speed_850hPa": {h: speed},
            "wind_speed_700hPa": {h: speed},
            "wind_direction_850hPa": {h: direction},
            "wind_direction_700hPa": {h: direction},
        }

    upper = {"a": model(20, 350), "b": model(30, 10), "c": model(100, 0)}
    speed, direction = ridge_wind(upper, 2000, [h])
    assert speed[h] == 30
    assert min(direction[h] or 0, 360 - (direction[h] or 0)) == pytest.approx(0, abs=0.5)
