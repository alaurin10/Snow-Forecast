"""Snow-to-liquid ratio and precipitation type.

Open-Meteo's snowfall is snow water × 0.7 cm/mm (7:1) for every model. The
pipeline works in snow water and converts to depth two ways: `raw` (the 7:1
model snowfall) and `slr` (a ratio from the temperature while it snows).
"""

from __future__ import annotations

from collections.abc import Sequence

from snowwatch.analysis.series import median
from snowwatch.config import SlrBand

# A snowing hour: at least ~0.05 in of model snowfall (the prototype's threshold).
SNOWING_SWE_MM = 0.18
# Below this much water an hour has no precipitation type.
WET_MM = 0.1


def ratio_for(temp_c: float, bands: Sequence[SlrBand]) -> tuple[float, str]:
    for b in bands:
        if b.min_c is None or temp_c >= b.min_c:
            return b.ratio, b.label
    last = bands[-1]
    return last.ratio, last.label


def period_ratio(
    swe_mm: Sequence[float], temps_c: Sequence[float | None], bands: Sequence[SlrBand]
) -> tuple[float | None, str | None]:
    """Ratio and quality label from the median temperature during snowing hours."""
    snowing = [t for s, t in zip(swe_mm, temps_c, strict=False) if s >= SNOWING_SWE_MM]
    t = median(snowing)
    if t is None:
        return None, None
    return ratio_for(t, bands)


# Warmer than this the precipitation is rain, so an hour has no snow ratio.
SNOW_MAX_C = 1.0


def hourly_slr(
    temp_c: float | None,
    bands: Sequence[SlrBand],
    wet_bulb_c: float | None = None,
    rain_min_wb_c: float = 2.0,
) -> float | None:
    """The ratio snow would fall at this hour, or None when it is too warm for snow: by
    the wet-bulb temperature where there is one (rain from `rain_min_wb_c`), else by
    the temperature (`SNOW_MAX_C`)."""
    if temp_c is None:
        return None
    if wet_bulb_c is not None:
        if wet_bulb_c >= rain_min_wb_c:
            return None
    elif temp_c > SNOW_MAX_C:
        return None
    return ratio_for(temp_c, bands)[0]


def wind_cut(wind_kmh: float | None, start: float, full: float, cut: float) -> float:
    """The share of the ratio kept in strong wind: 1 up to `start`, falling linearly to
    1 − `cut` at `full` and beyond."""
    if wind_kmh is None or wind_kmh <= start or full <= start:
        return 1.0
    return 1.0 - cut * min(1.0, (wind_kmh - start) / (full - start))


def column_period_ratio(
    swe_mm: Sequence[float],
    column_c: Sequence[float | None],
    wind_kmh: Sequence[float | None],
    bands: Sequence[SlrBand],
    *,
    wind_start: float,
    wind_full: float,
    cut: float,
) -> float | None:
    """The column snow ratio for a period: the ratio band of the median, over snowing
    hours, of the warmest temperature between the surface and 500 hPa (snow takes the
    density of the warmest air it falls through), times the wind cut for the median
    surface wind while it snows. None without snow or without the column."""
    snowing = [i for i, s in enumerate(swe_mm) if s >= SNOWING_SWE_MM]
    t = median(column_c[i] for i in snowing)
    if t is None:
        return None
    w = median(wind_kmh[i] for i in snowing)
    return round(ratio_for(t, bands)[0] * wind_cut(w, wind_start, wind_full, cut), 1)


def slr_depth_cm(swe_mm: float, ratio: float) -> float:
    return swe_mm * ratio / 10


def ptype(snow_water_mm: float, liquid_mm: float) -> str:
    """snow / rain / mix / none from the share of water falling as snow."""
    total = snow_water_mm + liquid_mm
    if total < WET_MM:
        return "none"
    frac = snow_water_mm / total
    if frac >= 0.9:
        return "snow"
    if frac <= 0.1:
        return "rain"
    return "mix"
