"""The backcountry layer: facts for planning a tour, never a verdict on safety.

Pure functions over hourly series keyed by Unix hour (see `series.py`). The
snapshot builder decides which bands and hours to pass in.

The day-by-day outlook (`day_weather`, `factor_levels`, `stress`) is the one place
this layer grades anything: how hard each day's weather pushes on the snowpack (new
snow, drifting, rain, warming), on rule-of-thumb thresholds from the config. It says
what the weather is doing, not what the snowpack will do with it: it knows nothing of
buried weak layers, and it is never a danger rating.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, field_validator

from snowwatch.analysis.series import Hourly

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
Steps = tuple[float, float, float]


class BackcountryConfig(BaseModel):
    refreeze_good_c: float = -3.0
    refreeze_partial_c: float = 0.0
    refreeze_clear_cloud_pct: float = 30.0
    refreeze_clear_frac: float = 0.5
    rose_min_snow_cm: float = 2.0
    rose_min_wind_kmh: float = 15.0
    # The day-by-day outlook. Each factor has three steps: the values where its level
    # becomes 1 (some), 2 (strong) and 3 (very strong).
    outlook_days: int = 7
    outlook_snow_cm: Steps = (10.0, 25.0, 40.0)  # new snow in the day (summit)
    outlook_storm_cm: Steps = (30.0, 50.0, 80.0)  # new snow over 72 h
    outlook_wind_kmh: Steps = (25.0, 40.0, 60.0)  # ridge wind, the day's strongest 6 h
    outlook_wind_thin_cm: float = 15.0  # less snow than this in 72 h: drifting stays at 1
    outlook_rain_mm: Steps = (1.0, 6.0, 20.0)  # rain onto snow at mid
    outlook_rise_c: Steps = (5.0, 8.0, 12.0)  # warming within 24 h at mid
    outlook_thaw_h: tuple[float, float] = (3.0, 8.0)  # hours above freezing at the summit

    @field_validator(
        "outlook_snow_cm",
        "outlook_storm_cm",
        "outlook_wind_kmh",
        "outlook_rain_mm",
        "outlook_rise_c",
        "outlook_thaw_h",
    )
    @classmethod
    def _rising(cls, v: tuple[float, ...]) -> tuple[float, ...]:
        if list(v) != sorted(set(v)):
            raise ValueError("outlook steps must rise")
        return v


def sector_of(direction: float) -> int:
    """0 = N … 7 = NW, each sector 45° wide and centred on its name."""
    return int(((direction % 360) + 22.5) // 45) % 8


@dataclass(frozen=True)
class Rose:
    sectors: list[float]  # share of the loading per sector (sums to 1), wind blowing from
    snow_cm: float
    mean_kmh: float | None  # snow-weighted wind speed
    wind_from: str | None  # e.g. "SW" or "SW–W"
    loading: list[str]  # lee aspects, e.g. ["NE", "E"]
    label: str


def loading_rose(
    hours: Sequence[int],
    snow_cm: Hourly,
    speed_kmh: Hourly,
    direction: Hourly,
    cfg: BackcountryConfig,
) -> Rose:
    """Where wind would drift new snow: snowfall × wind speed per wind sector.

    The loaded aspects are the lee of the leading sector, plus its neighbour when
    that neighbour carries at least 60% as much.
    """
    weights = [0.0] * 8
    snow = 0.0
    speed_w = 0.0
    for h in hours:
        s, v, d = snow_cm.get(h), speed_kmh.get(h), direction.get(h)
        if s is None or s <= 0:
            continue
        snow += s
        if v is None or d is None:
            continue
        weights[sector_of(d)] += s * v
        speed_w += s * v
    total = sum(weights)
    shares = [w / total if total > 0 else 0.0 for w in weights]
    mean_kmh = speed_w / snow if snow > 0 and total > 0 else None
    if snow < cfg.rose_min_snow_cm or total <= 0:
        return Rose(shares, round(snow, 1), mean_kmh, None, [], "Little new snow to move")
    if mean_kmh is not None and mean_kmh < cfg.rose_min_wind_kmh:
        return Rose(shares, round(snow, 1), mean_kmh, None, [], "Light wind: little drifting")
    wind_from, lee = lead_sectors(shares)
    label = f"{wind_from} wind, loading {'–'.join(lee)} aspects"
    return Rose(shares, round(snow, 1), mean_kmh, wind_from, lee, label)


def lead_sectors(shares: Sequence[float]) -> tuple[str, list[str]]:
    """The leading wind sector (with its neighbour when that carries at least 60% as
    much), as "SW" or "SW–W", and the lee aspects opposite."""
    lead = max(range(8), key=lambda i: shares[i])
    group = [lead]
    left, right = (lead - 1) % 8, (lead + 1) % 8
    side = left if shares[left] >= shares[right] else right
    if shares[side] >= 0.6 * shares[lead]:
        group = sorted([lead, side], key=lambda i: (i - lead + 1) % 8)
    return "–".join(SECTORS[i] for i in group), [SECTORS[(i + 4) % 8] for i in group]


@dataclass(frozen=True)
class Rise:
    amount: float | None
    end: int | None  # the hour the rise is reached


def max_rise(series: Hourly, hours: Sequence[int], window_h: int = 24) -> Rise:
    """The largest increase over any `window_h` span that starts and ends within `hours`."""
    best: Rise = Rise(None, None)
    have = set(hours)
    for h in hours:
        later = h + window_h * 3600
        if later not in have:
            continue
        a, b = series.get(h), series.get(later)
        if a is None or b is None:
            continue
        if best.amount is None or b - a > best.amount:
            best = Rise(b - a, later)
    return best


def total_over(series: Hourly, hours: Sequence[int]) -> float | None:
    vals = [v for h in hours if (v := series.get(h)) is not None]
    return sum(vals) if vals else None


@dataclass(frozen=True)
class Refreeze:
    status: str  # "Good", "Partial", "None" or "Unknown"
    low_c: float | None
    clear_frac: float | None


def refreeze(
    hours: Sequence[int], temp_c: Hourly, cloud_pct: Hourly, cfg: BackcountryConfig
) -> Refreeze:
    """How well the surface refreezes overnight: the low and how much of the night is clear."""
    temps = [v for h in hours if (v := temp_c.get(h)) is not None]
    clouds = [v for h in hours if (v := cloud_pct.get(h)) is not None]
    if not temps:
        return Refreeze("Unknown", None, None)
    low = min(temps)
    clear = (
        sum(1 for c in clouds if c < cfg.refreeze_clear_cloud_pct) / len(clouds) if clouds else None
    )
    if low <= cfg.refreeze_good_c and (clear is None or clear >= cfg.refreeze_clear_frac):
        status = "Good"
    elif low <= cfg.refreeze_partial_c:
        status = "Partial"
    else:
        status = "None"
    return Refreeze(status, round(low, 1), None if clear is None else round(clear, 2))


@dataclass(frozen=True)
class Sky:
    cloud_low: float | None
    cloud_mid: float | None
    cloud_high: float | None
    vis_min_m: float | None


def sky(
    hours: Sequence[int],
    layers: Mapping[str, Hourly],
    visibility_m: Hourly,
    is_day: Hourly,
) -> Sky:
    """Mean cloud per layer and the lowest visibility during daylight hours."""
    lit = [h for h in hours if is_day.get(h)] or list(hours)

    def avg(series: Hourly) -> float | None:
        vals = [v for h in lit if (v := series.get(h)) is not None]
        return round(sum(vals) / len(vals)) if vals else None

    vis = [v for h in lit if (v := visibility_m.get(h)) is not None]
    return Sky(
        avg(layers.get("low", {})),
        avg(layers.get("mid", {})),
        avg(layers.get("high", {})),
        min(vis) if vis else None,
    )


# --- The day-by-day outlook ---------------------------------------------------


@dataclass(frozen=True)
class DayWeather:
    """One day's weather as the snowpack feels it."""

    new_cm: float | None  # summit snowfall in the day
    storm_cm: float | None  # summit snowfall over the 72 h to the end of the day
    wind_kmh: float | None  # ridge wind: the mean of the day's strongest 6 h
    wind_from: str | None  # where that wind comes from, e.g. "SW" or "SW–W"
    loading: list[str]  # the lee aspects, while there is snow to move
    rain_mm: float | None  # rain at mid; None with no snow for it to fall on
    rain_to_m: float | None  # the highest snow level while it rains
    fl_max_m: float | None
    thaw_h: int  # hours above freezing at the summit
    temp_rise_c: float | None  # the biggest 24 h warming that ends in the day (mid)
    refreeze: str | None  # the night before, at the summit: Good, Partial, None


@dataclass(frozen=True)
class Levels:
    """How hard each factor pushes, 0 (nothing) to 3 (very strong)."""

    snow: int
    wind: int
    rain: int
    warm: int


def level(value: float | None, steps: Sequence[float]) -> int:
    """How many of the rising `steps` the value has reached."""
    return 0 if value is None else sum(1 for s in steps if value >= s)


def strongest(values: Sequence[float], n: int = 6) -> float | None:
    """The mean of the `n` highest values: a sustained wind, not one gusty hour."""
    top = sorted(values, reverse=True)[:n]
    return sum(top) / len(top) if top else None


def wind_sectors(
    hours: Sequence[int], speed_kmh: Hourly, direction: Hourly, min_kmh: float
) -> tuple[str | None, list[str]]:
    """Where the day's drifting wind comes from, and the lee aspects: each hour at or
    above `min_kmh` counts by its speed."""
    weights = [0.0] * 8
    for h in hours:
        v, d = speed_kmh.get(h), direction.get(h)
        if v is not None and d is not None and v >= min_kmh:
            weights[sector_of(d)] += v
    total = sum(weights)
    if total <= 0:
        return None, []
    return lead_sectors([w / total for w in weights])


def day_weather(
    hours: Sequence[int],
    *,
    snow_cm: Hourly,
    speed_kmh: Hourly,
    direction: Hourly,
    rain_mm: Hourly,
    snow_level_m: Hourly,
    fl_m: Hourly,
    temp_top_c: Hourly,
    temp_mid_c: Hourly,
    refreeze_status: str | None,
    on_snow: bool,
    cfg: BackcountryConfig,
) -> DayWeather:
    """A day's facts from hourly series. `snow_cm`, the wind and `temp_top_c` are the
    summit's; rain, the snow level, the freezing level and `temp_mid_c` are mid's. The
    series must reach 72 h (snow) and 24 h (mid temperature) back from the day."""
    new = [v for h in hours if (v := snow_cm.get(h)) is not None]
    back = range(hours[-1] - 71 * 3600, hours[-1] + 3600, 3600) if hours else range(0)
    storm = [v for h in back if (v := snow_cm.get(h)) is not None]
    storm_cm = sum(storm) if storm else None
    winds = [v for h in hours if (v := speed_kmh.get(h)) is not None]
    wind_from, lee = wind_sectors(hours, speed_kmh, direction, cfg.rose_min_wind_kmh)
    movable = (storm_cm or 0.0) >= cfg.rose_min_snow_cm
    wet = [h for h in hours if (rain_mm.get(h) or 0.0) >= 0.1]
    rain = [v for h in hours if (v := rain_mm.get(h)) is not None]
    reach = [v for h in wet if (v := snow_level_m.get(h)) is not None]
    fls = [v for h in hours if (v := fl_m.get(h)) is not None]
    rises = [
        b - a
        for h in hours
        if (b := temp_mid_c.get(h)) is not None and (a := temp_mid_c.get(h - 24 * 3600)) is not None
    ]
    return DayWeather(
        new_cm=sum(new) if new else None,
        storm_cm=storm_cm,
        wind_kmh=strongest(winds),
        wind_from=wind_from,
        loading=lee if movable else [],
        rain_mm=(sum(rain) if rain else None) if on_snow else None,
        rain_to_m=max(reach) if reach and on_snow else None,
        fl_max_m=max(fls) if fls else None,
        thaw_h=sum(1 for h in hours if (temp_top_c.get(h) or 0.0) > 0.0),
        temp_rise_c=max(rises) if rises else None,
        refreeze=refreeze_status,
    )


def factor_levels(d: DayWeather, cfg: BackcountryConfig) -> Levels:
    """Each factor's level for the day.

    Snow: the day's new snow or the 72 h total, whichever grades higher, so the day
    after a big storm still counts. Wind: the sustained ridge wind, while there is
    recent snow to move (a thin supply holds it at 1). Rain: rain onto snow. Warming:
    a sharp 24 h rise, or a thaw at the summit: after a good refreeze a long thaw is
    the ordinary melt-freeze day and stays at 1, after no refreeze it counts one more.
    """
    snow = max(level(d.new_cm, cfg.outlook_snow_cm), level(d.storm_cm, cfg.outlook_storm_cm))
    supply = d.storm_cm or 0.0
    wind = level(d.wind_kmh, cfg.outlook_wind_kmh)
    if supply < cfg.rose_min_snow_cm:
        wind = 0
    elif supply < cfg.outlook_wind_thin_cm:
        wind = min(wind, 1)
    rain = level(d.rain_mm, cfg.outlook_rain_mm)
    thaw = level(float(d.thaw_h), cfg.outlook_thaw_h)
    if d.refreeze == "Good":
        thaw = min(thaw, 1)
    elif thaw and d.refreeze == "None":
        thaw += 1
    warm = min(3, max(level(d.temp_rise_c, cfg.outlook_rise_c), thaw))
    return Levels(snow=snow, wind=wind, rain=rain, warm=warm)


def stress(levels: Levels) -> int:
    """The day's weather stress, 0 to 3: its strongest factor, one more when two or
    more are strong together (snow with wind, rain with warming)."""
    all_ = (levels.snow, levels.wind, levels.rain, levels.warm)
    top = max(all_)
    if sum(1 for v in all_ if v >= 2) >= 2:
        top += 1
    return min(3, top)


def tendency(before: int | None, now: int) -> str | None:
    """Rising, steady or easing against the day before."""
    if before is None:
        return None
    return "rising" if now > before else "easing" if now < before else "steady"
