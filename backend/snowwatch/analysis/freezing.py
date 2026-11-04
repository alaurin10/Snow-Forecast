"""Freezing level from a vertical temperature profile.

Only GFS, ICON and HRRR provide `freezing_level_height` on Open-Meteo. For the
other models it is found from pressure-level temperatures: the 0 °C crossing,
interpolated against geopotential height. When the whole column is below
freezing it is extrapolated down from the surface with a standard lapse rate.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

LAPSE_C_PER_M = 0.0065
LEVELS = (850, 700, 600, 500)


def freezing_level_m(
    surface_m: float, surface_c: float | None, levels: Sequence[tuple[float | None, float | None]]
) -> float | None:
    """levels: (geopotential height m, temperature °C) per pressure level, any order.

    Returns metres above sea level, never below 0.
    """
    profile = sorted((h, t) for h, t in levels if h is not None and t is not None and h > surface_m)
    if surface_c is not None:
        profile.insert(0, (surface_m, surface_c))
    if not profile:
        return None
    h0, t0 = profile[0]
    if t0 <= 0:
        # Below freezing at the bottom: the 0 °C level is lower still.
        return max(0.0, h0 + t0 / LAPSE_C_PER_M)
    for (h1, t1), (h2, t2) in itertools.pairwise(profile):
        if t1 > 0 >= t2:
            return h1 + (h2 - h1) * t1 / (t1 - t2)
    # Above freezing at every level: extrapolate up from the top.
    h_top, t_top = profile[-1]
    return h_top + t_top / LAPSE_C_PER_M
