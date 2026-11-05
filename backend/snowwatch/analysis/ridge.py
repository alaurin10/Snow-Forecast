"""Free-air wind at ridge height, from the 850 and 700 hPa levels.

Surface (10 m) wind on a summit is shaped by terrain in the model grid; the free
air just above the ridges is what moves snow onto lee slopes. Each model's 850
and 700 hPa wind is interpolated to the summit elevation by geopotential height,
then the models are combined (median speed, mean direction).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from snowwatch.analysis.series import Hourly, circular_mean, median

LEVELS = (850, 700)


def interpolate(
    elev_m: float,
    lower: tuple[float | None, float | None, float | None],
    upper: tuple[float | None, float | None, float | None],
) -> tuple[float, float] | None:
    """Speed and direction at `elev_m` from two levels, each (height_m, speed, direction).

    Linear in height between the levels and clamped outside them. Direction is
    interpolated as a vector so 350° and 10° meet at 0°, not 180°.
    """
    z0, s0, d0 = lower
    z1, s1, d1 = upper
    have0 = None not in (z0, s0, d0)
    have1 = None not in (z1, s1, d1)
    if not have0 and not have1:
        return None
    if not have1:
        return float(s0), float(d0)  # type: ignore[arg-type]
    if not have0:
        return float(s1), float(d1)  # type: ignore[arg-type]
    assert z0 is not None and z1 is not None and s0 is not None and s1 is not None
    assert d0 is not None and d1 is not None
    f = 0.0 if z1 == z0 else (elev_m - z0) / (z1 - z0)
    f = min(1.0, max(0.0, f))
    if f in (0.0, 1.0):
        return (float(s0), float(d0)) if f == 0.0 else (float(s1), float(d1))
    speed = s0 + (s1 - s0) * f
    x = (1 - f) * math.sin(math.radians(d0)) + f * math.sin(math.radians(d1))
    y = (1 - f) * math.cos(math.radians(d0)) + f * math.cos(math.radians(d1))
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        direction = d0 if f < 0.5 else d1
    else:
        direction = math.degrees(math.atan2(x, y)) % 360
    return speed, direction


def ridge_wind(
    upper: Mapping[str, Mapping[str, Hourly]], elev_m: float, hours: Iterable[int]
) -> tuple[Hourly, Hourly]:
    """Consensus ridge-height wind speed (km/h) and direction (°) per hour."""
    speed: Hourly = {}
    direction: Hourly = {}
    for h in hours:
        speeds: list[float] = []
        dirs: list[float] = []
        for v in upper.values():
            levels = [
                (
                    v.get(f"geopotential_height_{p}hPa", {}).get(h),
                    v.get(f"wind_speed_{p}hPa", {}).get(h),
                    v.get(f"wind_direction_{p}hPa", {}).get(h),
                )
                for p in LEVELS
            ]
            got = interpolate(elev_m, levels[0], levels[1])
            if got is not None:
                speeds.append(got[0])
                dirs.append(got[1])
        speed[h] = median(speeds)
        direction[h] = circular_mean(dirs)
    return speed, direction
