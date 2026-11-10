"""Radar from Environment Canada's North American composite (MSC GeoMet), typed, plus a
72-minute nowcast.

The composite includes the US NEXRAD radars, at 1 km every 6 minutes, 16.9–67.2°N.
For each time we ask GeoMet for three pictures over the whole region:

  RADAR_1KM_RRAI           rate if it's rain (mm/h), drawn on our RAIN ramp by our SLD
  RADAR_1KM_RSNO           rate if it's snow (cm/h ≈ mm of water/h), on our SNOW ramp
  Radar_1km_SfcPrecipType  the type (12 classes), in GeoMet's own style

and combine them: snow pixels take the snow colour, rain pixels the rain colour, mixed
and freezing pixels the MIX ramp by the rain rate. The type product leaves the lightest
echoes unclassified, so an echo without a type takes the nearest type within a few
kilometres, then the forecast's type for that hour, else rain.

The nowcast (`…PrecipRate-Extrapolation`) moves the latest echoes forward with no growth
or decay, and is typed by the latest observed type picture.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from snowwatch.maps.geomet import Net, capabilities_dims, geomet_map, parse_times, sld, ts_iso
from snowwatch.maps.palette import (
    MIX,
    MIX_T,
    NONE,
    RAIN,
    RAIN_T,
    RGB,
    SNOW,
    SNOW_T,
    hex_rgb,
    rgb_mask,
)
from snowwatch.maps.region import Region, spread

log = logging.getLogger("snowwatch.precip")

RRAI = "RADAR_1KM_RRAI"
RSNO = "RADAR_1KM_RSNO"
TYPE = "Radar_1km_SfcPrecipType"
NOW_RAIN = "Radar_1km_RainPrecipRate-Extrapolation"
NOW_SNOW = "Radar_1km_SnowPrecipRate-Extrapolation"

MIN = 60
HISTORY_S = 3 * 3600  # how far back the radar loop goes
EVERY_S = 12 * MIN  # one frame every 12 minutes…
RECENT_S = 30 * MIN  # …and every 6 minutes for the last half hour
NOWCAST_S = 72 * MIN
NOWCAST_EVERY_S = 12 * MIN
TYPE_LAG_S = 12 * MIN  # the type picture may trail the rate pictures by a scan or two
FILL_PX = 8  # an untyped echo takes a type from this many pixels away (~12 km)

# GeoMet's default style for Radar_1km_SfcPrecipType: the published legend's colours
# and, where they differ by a step, the colours its pictures actually use (Nov 2026).
TYPE_COLORS: list[tuple[str, int]] = [
    ("#7fdfeb", SNOW_T),  # light snow (value 110)
    ("#7fe0ec", SNOW_T),
    ("#47a4f0", SNOW_T),  # moderate snow (120)
    ("#47a5f1", SNOW_T),
    ("#0000e0", SNOW_T),  # heavy snow
    ("#e0bde6", MIX_T),  # light mixed rain/snow (210)
    ("#e1bee7", MIX_T),
    ("#c36dd2", MIX_T),  # moderate mixed (220)
    ("#c46dd3", MIX_T),
    ("#9b27af", MIX_T),  # heavy mixed
    ("#9afd9a", RAIN_T),  # light rain
    ("#9bfe9b", RAIN_T),
    ("#00cb00", RAIN_T),  # moderate rain
    ("#00cc00", RAIN_T),
    ("#008000", RAIN_T),  # heavy rain
    ("#fec007", RAIN_T),  # hail/rain
    ("#ffc107", RAIN_T),
    ("#fecbc8", MIX_T),  # light freezing rain
    ("#ffccc9", MIX_T),
    ("#fe1e0d", MIX_T),  # moderate/heavy freezing rain
]
_TYPE_RGB = np.array([hex_rgb(c) for c, _ in TYPE_COLORS], np.int32)
_TYPE_CODE = np.array([k for _, k in TYPE_COLORS], np.uint8)
_TYPE_TOLERANCE = 3 * 24**2  # squared RGB distance: a legend colour, give or take

# A rain colour (our RAIN ramp) to the MIX colour for the same rate.
_MIX_FOR_RAIN: list[tuple[RGB, RGB]] = [
    (hex_rgb(c), hex_rgb(MIX[-1][1] if low >= MIX[-1][0] else MIX[0][1])) for low, c in RAIN
]


def classify_types(img: np.ndarray | None) -> np.ndarray | None:
    """GeoMet's type picture to codes (none, snow, mix, rain) by nearest legend colour."""
    if img is None:
        return None
    out = np.zeros(img.shape[:2], np.uint8)
    solid = img[..., 3] > 0
    if not solid.any():
        return out
    px = img[solid][:, :3].astype(np.int32)
    keys, inverse = np.unique(px, axis=0, return_inverse=True)
    d = ((keys[:, None, :] - _TYPE_RGB[None, :, :]) ** 2).sum(-1)
    best = d.argmin(1)
    codes = np.where(d[np.arange(len(keys)), best] <= _TYPE_TOLERANCE, _TYPE_CODE[best], NONE)
    out[solid] = codes.astype(np.uint8)[inverse.reshape(-1)]
    return out


def fill_types(
    types: np.ndarray | None, echo: np.ndarray, fallback: np.ndarray | None
) -> np.ndarray:
    """A type for every echo: radar's, a nearby radar type, the forecast's, else rain."""
    out = np.zeros(echo.shape, np.uint8) if types is None else spread(types, FILL_PX)
    gap = echo & (out == NONE)
    if fallback is not None and fallback.shape == out.shape:
        out[gap] = fallback[gap]
        gap &= out == NONE
    out[gap] = RAIN_T
    return out


def compose(
    rain: np.ndarray | None,
    snow: np.ndarray | None,
    types: np.ndarray | None,
    fallback: np.ndarray | None = None,
) -> np.ndarray | None:
    """One typed picture from the rain-rate and snow-rate pictures and the type codes."""
    if rain is None and snow is None:
        return None
    shape = (rain if rain is not None else snow).shape  # type: ignore[union-attr]
    blank = np.zeros(shape, np.uint8)
    rain = blank if rain is None else rain
    snow = blank if snow is None else snow
    rain_on, snow_on = rain[..., 3] > 0, snow[..., 3] > 0
    kind = fill_types(types, rain_on | snow_on, fallback)
    out = np.zeros(shape, np.uint8)
    is_snow, is_rain, is_mix = kind == SNOW_T, kind == RAIN_T, kind == MIX_T
    out[is_snow & snow_on] = snow[is_snow & snow_on]
    out[is_rain & rain_on] = rain[is_rain & rain_on]
    # Mixed: the MIX colour for the rain rate; light where only the snow picture has echo.
    out[is_mix & snow_on & ~rain_on] = (*hex_rgb(MIX[0][1]), 255)
    for rain_rgb, mix_rgb in _MIX_FOR_RAIN:
        out[is_mix & rgb_mask(rain, rain_rgb)] = (*mix_rgb, 255)
    return out


# ---- Which times ------------------------------------------------------------------


def radar_times(times: list[int]) -> list[int]:
    """The last 3 h every 12 minutes (on the clock, so frames keep their names from one
    run to the next), and every scan of the last half hour."""
    if not times:
        return []
    latest = times[-1]
    return [
        t for t in times if t >= latest - HISTORY_S and (t >= latest - RECENT_S or t % EVERY_S == 0)
    ]


def type_time(t: int, type_times: list[int]) -> int | None:
    """The type picture for time t: the same scan, or the newest one before it."""
    best = [s for s in type_times if t - TYPE_LAG_S <= s <= t]
    return best[-1] if best else None


@dataclass
class Plan:
    """What GeoMet has now: radar times, type times, and the nowcast's run and times."""

    radar: list[int]
    types: list[int]
    nowcast_ref: str
    nowcast: list[int]


def plan(net: Net) -> Plan | None:
    """Ask GeoMet which times exist. None if its radar isn't answering."""
    rates = parse_times(capabilities_dims(net, RRAI).get("time", ""))
    if not rates:
        return None
    types = parse_times(capabilities_dims(net, TYPE).get("time", ""))
    dims = capabilities_dims(net, NOW_RAIN)
    ref = dims.get("reference_time.default", "")
    future = parse_times(dims.get("time", ""))
    start = future[0] if future else 0
    latest = rates[-1]
    nowcast = [
        t
        for t in future
        if t > latest and t <= start + NOWCAST_S and (t - start) % NOWCAST_EVERY_S == 0
    ]
    return Plan(radar_times(rates), types, ref, nowcast)


# ---- Drawing ----------------------------------------------------------------------


Job = tuple[str, str | None, str | None]  # layer, SLD (None: GeoMet's style), time


def _pictures(
    net: Net, jobs: list[Job], region: Region, extra: dict[str, str] | None = None
) -> list[np.ndarray | None]:
    """GetMaps two at a time (GeoMet throttles harder than that)."""
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(lambda j: geomet_map(net, j[0], j[1], region, j[2], extra), jobs))


def draw_radar(
    net: Net, t: int, type_t: int | None, region: Region, fallback: np.ndarray | None
) -> np.ndarray | None:
    """One observed frame. None if GeoMet sent neither rate picture."""
    jobs: list[Job] = [
        (RRAI, sld(RRAI, RAIN), ts_iso(t)),
        (RSNO, sld(RSNO, SNOW), ts_iso(t)),
    ]
    if type_t is not None:
        jobs.append((TYPE, None, ts_iso(type_t)))
    pics = _pictures(net, jobs, region)
    rain, snow = pics[0], pics[1]
    if rain is None or snow is None:
        return None  # half a picture would show the wrong type: skip this scan
    types = classify_types(pics[2]) if type_t is not None else None
    return compose(rain, snow, types, fallback)


def type_codes(net: Net, type_t: int | None, region: Region) -> np.ndarray | None:
    """The type codes at one time (for typing the nowcast)."""
    if type_t is None:
        return None
    return classify_types(geomet_map(net, TYPE, None, region, ts_iso(type_t)))


def draw_nowcast(
    net: Net,
    t: int,
    ref: str,
    types: np.ndarray | None,
    region: Region,
    fallback: np.ndarray | None,
) -> np.ndarray | None:
    """One nowcast frame from the extrapolated rain and snow rates."""
    rain, snow = _pictures(
        net,
        [(NOW_RAIN, sld(NOW_RAIN, RAIN), ts_iso(t)), (NOW_SNOW, sld(NOW_SNOW, SNOW), ts_iso(t))],
        region,
        {"dim_reference_time": ref} if ref else None,
    )
    if rain is None or snow is None:
        return None
    return compose(rain, snow, types, fallback)
