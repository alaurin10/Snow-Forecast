"""Sun position and sunshine on slopes, with no new dependency.

Sun position from NOAA's solar calculator (the simplified equations, good to a small
fraction of a degree, plenty for slopes). Sunshine on a slope: the direct beam on the
tilted surface plus the diffuse sky light it sees (isotropic sky), from Open-Meteo's
direct and diffuse radiation on the flat (W/m², the mean of the hour before each
timestamp). Snow and terrain shading are ignored, so every number is an estimate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from snowwatch.analysis.series import Hourly

ASPECTS = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
SLOPE_DEG = 35.0
MIN_SUN_DEG = 2.0  # below this the beam is too oblique (and too uncertain) to count


def sun_position(ts: float, lat: float, lon: float) -> tuple[float, float]:
    """(elevation, azimuth) in degrees for a Unix time; azimuth clockwise from north."""
    jd = ts / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(eps / 2)) ** 2
    l0r = math.radians(l0)
    eq_time = 4 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    minutes = (ts % 86400) / 60.0
    true_solar = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = true_solar / 4 - 180
    latr, har = math.radians(lat), math.radians(hour_angle)
    cos_zen = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(har)
    zen = math.acos(max(-1.0, min(1.0, cos_zen)))
    elevation = 90 - math.degrees(zen)
    sin_zen = math.sin(zen)
    if sin_zen < 1e-9:
        return elevation, 180.0
    cos_az = (math.sin(latr) * math.cos(zen) - math.sin(decl)) / (math.cos(latr) * sin_zen)
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    azimuth = (az + 180) % 360 if hour_angle > 0 else (540 - az) % 360
    return elevation, azimuth


def on_slope(
    direct_w: float | None,
    diffuse_w: float | None,
    elevation: float,
    azimuth: float,
    aspect: float,
    slope: float = SLOPE_DEG,
) -> float | None:
    """W/m² on a slope facing `aspect`, from direct and diffuse radiation on the flat."""
    if direct_w is None and diffuse_w is None:
        return None
    s = math.radians(slope)
    sky = (diffuse_w or 0.0) * (1 + math.cos(s)) / 2
    if elevation < MIN_SUN_DEG or not direct_w:
        return sky
    el = math.radians(elevation)
    beam = direct_w / math.sin(el)  # direct normal irradiance
    cos_inc = math.cos(s) * math.sin(el) + math.sin(s) * math.cos(el) * math.cos(
        math.radians(azimuth - aspect)
    )
    return sky + beam * max(0.0, cos_inc)


def slope_series(
    hours: Sequence[int], direct: Hourly, diffuse: Hourly, lat: float, lon: float, aspect: float
) -> Hourly:
    """W/m² on a 35° slope facing `aspect` for each hour. Open-Meteo's radiation is the
    mean of the hour before the timestamp, so the sun is placed at its middle."""
    out: Hourly = {}
    for h in hours:
        d, f = direct.get(h), diffuse.get(h)
        if d is None and f is None:
            out[h] = None
            continue
        el, az = sun_position(h - 1800, lat, lon)
        out[h] = on_slope(d, f, el, az, aspect)
    return out


def daily_kwh(series: Hourly, hours: Sequence[int]) -> float | None:
    """kWh/m² over the hours (each hour's mean W/m² for one hour)."""
    vals = [v for h in hours if (v := series.get(h)) is not None]
    return round(sum(vals) / 1000, 2) if vals else None
