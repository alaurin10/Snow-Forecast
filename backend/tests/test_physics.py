"""Milestone 3's physics (docs/OPEN-METEO-PLAN.md): wet-bulb snow level, precipitation
type, freezing rain, the column snow ratio, sun on slopes and ridge interpolation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from snowwatch.analysis import backcountry as bc
from snowwatch.analysis.build import _freezing_rain, _snow_level
from snowwatch.analysis.ridge import bracket, ridge_wind
from snowwatch.analysis.slr import column_period_ratio, hourly_slr, wind_cut
from snowwatch.analysis.snowlevel import (
    PhysicsConfig,
    model_flag_kind,
    precip_type,
    profile_kind,
    vote,
    warm_layer,
    wet_bulb_c,
    wet_bulb_zero_m,
)
from snowwatch.analysis.solar import on_slope, slope_series, sun_position
from snowwatch.config import SlrBand
from tests.helpers import config

PHYS = PhysicsConfig()
BANDS = [
    SlrBand(min_c=-0.556, ratio=8, label="Heavy & wet"),
    SlrBand(min_c=-3.333, ratio=11, label="Average"),
    SlrBand(min_c=-7.222, ratio=14, label="Light"),
    SlrBand(min_c=None, ratio=17, label="Dry & fluffy"),
]


# --- wet-bulb and the snow level ---------------------------------------------


@pytest.mark.parametrize(
    ("t", "rh", "wb"),
    [(20, 50, 13.7), (0, 100, 0.0), (5, 60, 1.8), (-5, 80, -6.5)],
)
def test_wet_bulb_matches_stull(t: float, rh: float, wb: float) -> None:
    assert wet_bulb_c(t, rh) == pytest.approx(wb, abs=0.35)


def test_wet_bulb_needs_both_inputs() -> None:
    assert wet_bulb_c(None, 50) is None
    assert wet_bulb_c(3, None) is None


def test_dry_air_puts_the_wet_bulb_zero_below_the_freezing_level() -> None:
    # +2 °C at the surface (1,000 m), 0 °C near 1,600 m: dry air cools falling snow.
    dry = [(1500.0, 0.6, 40.0), (3000.0, -9.0, 40.0)]
    moist = [(1500.0, 0.6, 100.0), (3000.0, -9.0, 100.0)]
    z_dry = wet_bulb_zero_m(1000, wet_bulb_c(2.0, 40), dry)
    z_moist = wet_bulb_zero_m(1000, wet_bulb_c(2.0, 100), moist)
    assert z_dry is not None and z_moist is not None
    assert z_dry < 1300 < z_moist


def test_no_humidity_aloft_means_no_wet_bulb_zero() -> None:
    assert wet_bulb_zero_m(1000, 1.0, [(1500.0, 0.5, None)]) is None


def test_snow_level_falls_back_to_the_freezing_level() -> None:
    cfg = config()
    md = {"gfs": {"temperature_2m": {0: 2.0}}}
    lean = {"gfs": {"geopotential_height_850hPa": {0: 1500.0}, "temperature_850hPa": {0: 0.0}}}
    level, how = _snow_level([0], md, lean, 1000, {0: 1500.0}, cfg)
    assert how[0] == "fl" and level[0] == pytest.approx(1500 - cfg.snow_level_offset_m)
    rich = {
        "gfs": {
            **lean["gfs"],
            "relative_humidity_850hPa": {0: 60.0},
            "geopotential_height_700hPa": {0: 3000.0},
            "temperature_700hPa": {0: -10.0},
            "relative_humidity_700hPa": {0: 60.0},
        }
    }
    md["gfs"]["relative_humidity_2m"] = {0: 60.0}
    level, how = _snow_level([0], md, rich, 1000, {0: 1500.0}, cfg)
    assert how[0] == "wb"
    assert level[0] is not None and level[0] < 1500 - cfg.snow_level_offset_m


def test_nbm_snow_level_counts() -> None:
    level, how = _snow_level(
        [0], {"nbm": {"snowfall_height": {0: 900.0}}}, {}, 500, {0: 2000.0}, config()
    )
    assert how[0] == "wb" and level[0] == 900


@pytest.mark.parametrize(("wb", "kind"), [(-1, "snow"), (0.5, "snow"), (1.2, "mix"), (2, "rain")])
def test_precip_type_from_wet_bulb(wb: float, kind: str) -> None:
    assert precip_type(wb, PHYS) == kind


def test_hourly_slr_uses_the_wet_bulb() -> None:
    # 2.5 °C air is too warm by temperature, but dry enough for snow by wet-bulb.
    assert hourly_slr(2.5, BANDS) is None
    assert hourly_slr(2.5, BANDS, wet_bulb_c=0.3) == 8
    assert hourly_slr(-2, BANDS, wet_bulb_c=2.5) is None


# --- freezing rain -----------------------------------------------------------

# An east-wind day at a pass: −2 °C at 900 m under a +4 °C layer near 1,500 m.
NOSE = [(1300.0, 1.0, 95.0), (1600.0, 4.0, 95.0), (3000.0, -8.0, 80.0)]


def test_warm_layer_over_cold_surface() -> None:
    got = warm_layer(900, -2.0, NOSE)
    assert got is not None
    t_max, cold_m = got
    assert t_max == 4.0
    assert 200 < cold_m < 400  # 0 °C crossed between 900 m (−2) and 1,300 m (+1)
    assert warm_layer(900, 1.0, NOSE) is None  # no cold surface
    assert warm_layer(900, -2.0, [(1500.0, -1.0, None)]) is None  # no warm layer


def test_profile_kind() -> None:
    assert profile_kind(900, -2.0, NOSE, PHYS) == "freezing_rain"
    # A deep cold layer refreezes the drops: sleet.
    deep = [(1900.0, -0.5, None), (2100.0, 4.0, None)]
    assert profile_kind(900, -6.0, deep, PHYS) == "sleet"
    # A barely warm layer only partly melts the snow.
    assert profile_kind(900, -2.0, [(1500.0, 2.5, None)], PHYS) == "sleet"
    assert profile_kind(900, -2.0, [(1500.0, 1.5, None)], PHYS) is None


def test_model_flags() -> None:
    assert model_flag_kind({"categorical_freezing_rain": {0: 1.0}}, 0, PHYS) == "freezing_rain"
    assert model_flag_kind({"precipitation_type": {0: 3}}, 0, PHYS) == "freezing_rain"
    assert model_flag_kind({"precipitation_type": {0: 8}}, 0, PHYS) == "sleet"
    assert model_flag_kind({"freezing_rain_probability": {0: 20}}, 0, PHYS) is None


def test_vote_needs_a_third_of_the_models() -> None:
    assert vote(["freezing_rain", None, None]) == "freezing_rain"
    assert vote(["freezing_rain", None, None, None]) is None
    assert vote(["sleet", "sleet", "freezing_rain"]) == "sleet"
    assert vote([]) is None


def test_freezing_rain_on_a_crafted_case() -> None:
    cfg = config()
    upper = {
        m: {
            "geopotential_height_850hPa": {0: 1300.0},
            "temperature_850hPa": {0: 1.0},
            "geopotential_height_800hPa": {0: 1600.0},
            "temperature_800hPa": {0: 4.0},
            "geopotential_height_700hPa": {0: 3000.0},
            "temperature_700hPa": {0: -8.0},
        }
        for m in ("gfs", "ecmwf", "gem")
    }
    md = {m: {"temperature_2m": {0: -2.0}} for m in upper}
    got = _freezing_rain([0], md, upper, 900, {0: 0.0}, {0: 2.0}, cfg)
    assert got == {0: "freezing_rain"}
    assert _freezing_rain([0], md, upper, 900, {0: 0.0}, {0: 0.0}, cfg) == {}  # dry
    warm = {m: {"temperature_2m": {0: 3.0}} for m in upper}
    assert _freezing_rain([0], warm, upper, 900, {0: 0.0}, {0: 2.0}, cfg) == {}


# --- column snow ratio --------------------------------------------------------


def test_wind_cut() -> None:
    assert wind_cut(10, 20, 60, 0.3) == 1.0
    assert wind_cut(40, 20, 60, 0.3) == pytest.approx(0.85)
    assert wind_cut(90, 20, 60, 0.3) == pytest.approx(0.7)


def test_column_ratio_takes_the_warmest_air() -> None:
    kw = {"wind_start": 20.0, "wind_full": 60.0, "cut": 0.3}
    swe = [1.0, 1.0, 0.0]
    # Cold at the surface but a −0.3 °C layer aloft: heavy, wet snow (8:1).
    assert column_period_ratio(swe, [-0.3, -0.3, 5.0], [10, 10, 10], BANDS, **kw) == 8
    assert column_period_ratio(swe, [-9.0, -9.0, None], [10, 10, 10], BANDS, **kw) == 17
    assert column_period_ratio(swe, [-9.0, -9.0, None], [60, 60, 0], BANDS, **kw) == 11.9
    assert column_period_ratio([0.0], [-9.0], [0.0], BANDS, **kw) is None


# --- sun ---------------------------------------------------------------------


def test_sun_position_at_known_times() -> None:
    # Summer solstice, solar noon at 47° N on the prime meridian: 90 − 47 + 23.44.
    noon = datetime(2026, 6, 21, 12, 2, tzinfo=UTC).timestamp()
    el, az = sun_position(noon, 47.0, 0.0)
    assert el == pytest.approx(66.44, abs=0.3)
    assert az == pytest.approx(180, abs=1.5)
    # Equinox sunrise on the equator: on the horizon, due east.
    rise = datetime(2026, 3, 20, 6, 7, tzinfo=UTC).timestamp()
    el, az = sun_position(rise, 0.0, 0.0)
    assert el == pytest.approx(0, abs=0.6)
    assert az == pytest.approx(90, abs=0.6)
    # Crystal Mountain, 21 Dec at 12:00 PST (20:00 UTC): low in the south.
    el, az = sun_position(datetime(2026, 12, 21, 20, tzinfo=UTC).timestamp(), 46.93, -121.5)
    assert el == pytest.approx(19.6, abs=0.5)
    assert az == pytest.approx(181, abs=3)


def test_south_slopes_get_more_winter_sun() -> None:
    el, az = 20.0, 180.0
    south = on_slope(300, 50, el, az, 180)
    north = on_slope(300, 50, el, az, 0)
    assert south is not None and north is not None
    assert south > 3 * north
    assert on_slope(None, None, el, az, 180) is None
    assert on_slope(0, 100, -5, 90, 90) == pytest.approx(100 * (1 + 0.819) / 2, abs=0.5)


def test_east_slopes_get_morning_sun() -> None:
    day = int(datetime(2026, 4, 15, tzinfo=UTC).timestamp())
    morning = day + 17 * 3600  # 10:00 PDT
    flat = {morning: 500.0}
    east = slope_series([morning], flat, {morning: 80.0}, 46.93, -121.5, 90)
    west = slope_series([morning], flat, {morning: 80.0}, 46.93, -121.5, 270)
    assert (east[morning] or 0) > (west[morning] or 0)


def test_sun_factor_and_cold_days() -> None:
    cfg = bc.BackcountryConfig()
    base = {
        "new_cm": 0.0,
        "storm_cm": 0.0,
        "wind_kmh": 0.0,
        "wind_from": None,
        "loading": [],
        "rain_mm": None,
        "rain_to_m": None,
        "fl_max_m": None,
        "thaw_h": 0,
        "temp_rise_c": None,
        "refreeze": None,
    }
    sunny = bc.DayWeather(**base, sun_kwh={"S": 7.0, "N": 1.0}, tmax_mid_c=3.0)  # type: ignore[arg-type]
    cold = bc.DayWeather(**base, sun_kwh={"S": 7.0}, tmax_mid_c=-12.0)  # type: ignore[arg-type]
    assert bc.factor_levels(sunny, cfg).sun == 2
    assert bc.factor_levels(cold, cfg).sun == 1
    assert bc.stress(bc.factor_levels(sunny, cfg)) == 2
    # Sun with a strong warm-up doesn't make a pair.
    assert bc.stress(bc.Levels(snow=0, wind=0, rain=0, warm=2, sun=2)) == 2


def test_corn_windows_after_a_refreeze() -> None:
    cfg = bc.BackcountryConfig()
    hours = [h * 3600 for h in range(24)]
    sun = {
        "E": {h: 600.0 if 6 * 3600 <= h < 12 * 3600 else 0.0 for h in hours},
        "S": {h: 500.0 if 9 * 3600 <= h < 16 * 3600 else 0.0 for h in hours},
        "W": {h: 0.0 for h in hours},
    }
    temp = dict.fromkeys(hours, 2.0)
    got = bc.corn_windows(hours, sun, temp, "Good", cfg)
    assert [(a, s // 3600) for a, s, _ in got] == [("E", 7), ("S", 10)]
    assert got[0][2] - got[0][1] == cfg.corn_window_h * 3600
    assert bc.corn_windows(hours, sun, temp, "None", cfg) == []


def test_rime_and_fog() -> None:
    cfg = bc.BackcountryConfig()
    hours = [0, 3600, 7200]
    lit = dict.fromkeys(hours, 1.0)
    sk = bc.sky(
        hours,
        {"low": {0: 90.0, 3600: 10.0, 7200: 10.0}},
        {0: 5000.0, 3600: 500.0, 7200: 20000.0},
        lit,
        rh_pct={0: 98.0, 3600: 99.0, 7200: 80.0},
        temp_c={0: -4.0, 3600: 2.0, 7200: -4.0},
        cfg=cfg,
    )
    assert sk.rime_h == 1  # hour 0 only: hour 3600 is above freezing
    assert sk.fog_h == 2  # low cloud at 0, poor visibility at 3600
    assert bc.sky(hours, {}, {}, lit).rime_h is None


# --- ridge wind --------------------------------------------------------------


def test_bracket_picks_the_levels_around_the_ridge() -> None:
    levels = [(1500.0, 10.0, 0.0), (2000.0, 20.0, 0.0), (2500.0, 30.0, 0.0), (None, 5.0, 0.0)]
    assert bracket(2200, levels) == (levels[1], levels[2])  # type: ignore[arg-type]
    assert bracket(1000, levels) == (levels[0], levels[1])  # type: ignore[arg-type]
    assert bracket(9000, levels) == (levels[1], levels[2])  # type: ignore[arg-type]
    assert bracket(9000, [(None, None, None)]) is None


def test_ridge_interpolates_between_bracketing_levels() -> None:
    model = {
        f"{v}_{p}hPa": {0: val}
        for p, z, spd in ((850, 1500, 10), (800, 2000, 20), (750, 2500, 40), (700, 3000, 50))
        for v, val in (("geopotential_height", z), ("wind_speed", spd), ("wind_direction", 270))
    }
    speed, _ = ridge_wind({"m": model}, 2250, [0])
    assert speed[0] == pytest.approx(30)  # between 800 and 750, not 850 and 700 (33.3)


def test_model_flags_need_a_cold_band() -> None:
    warm = {"precipitation_type": {0: 3}, "temperature_2m": {0: 1.7}}
    assert model_flag_kind(warm, 0, PHYS) is None


# --- the wet-bulb rain/snow split ---------------------------------------------


@pytest.mark.parametrize(
    ("wb", "share"), [(-3, 1.0), (0.5, 1.0), (1.25, 0.5), (2, 0.0), (None, None)]
)
def test_snow_fraction(wb: float | None, share: float | None) -> None:
    from snowwatch.analysis.snowlevel import snow_fraction

    assert snow_fraction(wb, PHYS) == share


def test_wb_split_resplits_by_the_bands_own_wet_bulb() -> None:
    from snowwatch.analysis.build import _wb_split

    # The model says all rain (its grid is lower), but the band's wet-bulb says snow.
    series = {
        "precipitation": {0: 2.0, 1: 2.0, 2: 2.0},
        "snowfall": {0: 0.0, 1: 0.0, 2: 0.7},
        "rain": {0: 2.0, 1: 2.0, 2: 1.0},
        "wet_bulb_temperature_2m": {0: -1.0, 1: 1.25},
    }
    got = _wb_split(series, 0.7, PHYS)
    assert got is not None
    snow, liq = got
    assert snow[0] == 2.0 and liq[0] == 0.0
    assert snow[1] == pytest.approx(1.0) and liq[1] == pytest.approx(1.0)
    assert snow[2] == pytest.approx(1.0) and liq[2] == 1.0  # no wet-bulb: the model's own
    # From temperature and humidity when the model has no wet-bulb field.
    computed = {
        **series,
        "wet_bulb_temperature_2m": {},
        "temperature_2m": {0: -2.0},
        "relative_humidity_2m": {0: 90.0},
    }
    assert (_wb_split(computed, 0.7, PHYS) or ({}, {}))[0][0] == 2.0
    assert _wb_split({"precipitation": {0: 1.0}}, 0.7, PHYS) is None  # lean data
