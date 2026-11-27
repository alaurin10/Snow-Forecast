"""Snow level from the wet-bulb temperature, precipitation type, and freezing rain.

Falling snow melts where the air's wet-bulb temperature (what a wet surface cools to by
evaporation) is above 0 °C, not where the dry-bulb temperature is: in dry air snow
falls well below the freezing level. So with humidity at the pressure levels (a
self-hosted Open-Meteo server, docs/OPEN-METEO-PLAN.md milestone 3) each model's snow
level is the height where its wet-bulb profile crosses 0 °C, less a melting distance
(config `physics.snow_level_wb_offset_m`). Without it the snow level stays the freezing
level less `snow_level_offset_m`.

Freezing rain and sleet need a warm layer aloft (above 0 °C) over air below freezing
at the ground: snow melts in the warm layer, then refreezes on contact (freezing rain)
or, through a deep or very cold surface layer, into ice pellets (sleet). The models'
own flags vote too, where they have them.

Pure functions; the pressure levels are (geopotential height m, value) pairs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from snowwatch.analysis.freezing import freezing_level_m
from snowwatch.analysis.series import Hourly

Kind = str  # "freezing_rain" or "sleet"


class PhysicsConfig(BaseModel):
    """Milestone 3's thresholds (config `physics:`), to tune against the scorecard."""

    # Snow level: this far below the wet-bulb 0 °C height.
    snow_level_wb_offset_m: float = Field(150, ge=0, le=600)
    # Precipitation type from the surface wet-bulb: snow at or below the first, rain at or
    # above the second, a mix between.
    wb_snow_max_c: float = 0.5
    wb_rain_min_c: float = 2.0
    # Column snow ratio: the ratio for the warmest temperature between the surface and
    # 500 hPa, cut for strong wind at the surface (broken crystals pack densely): no cut
    # below the first speed, rising to `col_wind_cut` at the second.
    col_wind_start_kmh: float = 20
    col_wind_full_kmh: float = 60
    col_wind_cut: float = Field(0.3, ge=0, lt=1)
    # Freezing rain: a warm layer aloft at least this warm melts snow completely…
    frz_warm_c: float = 3.0
    # …while a cooler one (from `sleet_warm_c`) melts it partly, and a cold layer at the
    # ground deeper than `sleet_cold_m` refreezes the drops into ice pellets.
    sleet_warm_c: float = 2.0
    sleet_cold_m: float = 750
    # A model's own flag counts only while the band itself is at most this warm (the
    # model's flag is for its own ground, which can be lower and colder).
    flag_max_c: float = 0.5
    # A model's own freezing-rain / ice-pellet chance (NBM, %) that counts as its vote.
    frz_prob_pct: float = 50


def wet_bulb_c(temp_c: float | None, rh_pct: float | None) -> float | None:
    """Wet-bulb temperature from temperature and relative humidity (Stull 2011): within
    ~0.3 °C for 5–99 % humidity and −20 to 50 °C at sea-level pressure, close enough
    aloft for a snow level."""
    if temp_c is None or rh_pct is None:
        return None
    rh = min(100.0, max(1.0, rh_pct))
    t = temp_c
    return float(
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def levels_at(
    upper: Mapping[str, Hourly], h: int, levels: Sequence[int]
) -> list[tuple[float, float, float | None]]:
    """(height m, temperature °C, humidity % or None) at each pressure level that has a
    height and a temperature at hour `h`, lowest first."""
    out = []
    for p in levels:
        z = upper.get(f"geopotential_height_{p}hPa", {}).get(h)
        t = upper.get(f"temperature_{p}hPa", {}).get(h)
        if z is not None and t is not None:
            out.append((z, t, upper.get(f"relative_humidity_{p}hPa", {}).get(h)))
    return sorted(out)


def wet_bulb_zero_m(
    surface_m: float,
    surface_wb_c: float | None,
    levels: Sequence[tuple[float, float, float | None]],
) -> float | None:
    """The height (m above sea level) where the wet-bulb temperature crosses 0 °C, from
    the levels above the surface; None when the levels have no humidity."""
    above = [(z, t, rh) for z, t, rh in levels if z > surface_m]
    if not above or any(rh is None for _, _, rh in above):
        return None
    wbs = [(z, wet_bulb_c(t, rh)) for z, t, rh in above]
    return freezing_level_m(surface_m, surface_wb_c, wbs)


def precip_type(wb_c: float | None, cfg: PhysicsConfig) -> str | None:
    """snow / mix / rain from the surface wet-bulb; None without one."""
    if wb_c is None:
        return None
    if wb_c <= cfg.wb_snow_max_c:
        return "snow"
    if wb_c >= cfg.wb_rain_min_c:
        return "rain"
    return "mix"


def warm_layer(
    surface_m: float, surface_c: float | None, levels: Sequence[tuple[float, float, float | None]]
) -> tuple[float, float] | None:
    """With the surface at or below 0 °C: the warmest temperature above freezing aloft and
    the depth (m) of the sub-freezing air beneath it. None without such a layer."""
    if surface_c is None or surface_c > 0:
        return None
    above = [(z, t) for z, t, _ in levels if z > surface_m]
    warm = [(t, z) for z, t in above if t > 0]
    if not warm:
        return None
    t_max = max(t for t, _ in warm)
    # The cold layer's top: where the profile first rises through 0 °C.
    z_prev, t_prev = surface_m, surface_c
    top = surface_m
    for z, t in above:
        if t > 0:
            top = z_prev + (z - z_prev) * (0 - t_prev) / (t - t_prev) if t != t_prev else z
            break
        z_prev, t_prev = z, t
    return t_max, top - surface_m


def profile_kind(
    surface_m: float,
    surface_c: float | None,
    levels: Sequence[tuple[float, float, float | None]],
    cfg: PhysicsConfig,
) -> Kind | None:
    """What a warm layer aloft makes of falling snow: freezing rain, sleet, or nothing."""
    got = warm_layer(surface_m, surface_c, levels)
    if got is None:
        return None
    t_max, cold_m = got
    if t_max >= cfg.frz_warm_c and cold_m < cfg.sleet_cold_m:
        return "freezing_rain"
    if t_max >= cfg.sleet_warm_c:
        return "sleet"
    return None


# ECMWF's precipitation type (WMO code table 4.201).
_ECMWF_FZRA = (3, 12)  # freezing rain, freezing drizzle
_ECMWF_SLEET = (8,)  # ice pellets


def model_flag_kind(series: Mapping[str, Hourly], h: int, cfg: PhysicsConfig) -> Kind | None:
    """A model's own word on the hour: GFS and HRRR's freezing-rain flag, NBM's chances,
    ECMWF's precipitation type; only while the band's temperature (`temperature_2m`, at
    the band's elevation) is at most `flag_max_c`."""
    t2 = series.get("temperature_2m", {}).get(h)
    if t2 is not None and t2 > cfg.flag_max_c:
        return None
    cat = series.get("categorical_freezing_rain", {}).get(h)
    fzp = series.get("freezing_rain_probability", {}).get(h)
    ipp = series.get("ice_pellets_probability", {}).get(h)
    pt = series.get("precipitation_type", {}).get(h)
    if (cat or 0) >= 0.5 or (fzp or 0) >= cfg.frz_prob_pct or pt in _ECMWF_FZRA:
        return "freezing_rain"
    if (ipp or 0) >= cfg.frz_prob_pct or pt in _ECMWF_SLEET:
        return "sleet"
    return None


def vote(kinds: Sequence[Kind | None]) -> Kind | None:
    """The hour's kind when at least a third of the models (and at least one) say freezing
    rain or sleet; freezing rain wins a tie."""
    said = [k for k in kinds if k]
    if not said or len(said) * 3 < len(kinds):
        return None
    frz = said.count("freezing_rain")
    return "freezing_rain" if frz * 2 >= len(said) else "sleet"
