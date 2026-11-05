"""The backcountry layer: facts for planning a tour, never a verdict on safety.

Pure functions over hourly series keyed by Unix hour (see `series.py`). The
snapshot builder decides which bands and hours to pass in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from snowwatch.analysis.series import Hourly

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class BackcountryConfig(BaseModel):
    refreeze_good_c: float = -3.0
    refreeze_partial_c: float = 0.0
    refreeze_clear_cloud_pct: float = 30.0
    refreeze_clear_frac: float = 0.5
    rose_min_snow_cm: float = 2.0
    rose_min_wind_kmh: float = 15.0


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
    lead = max(range(8), key=lambda i: shares[i])
    group = [lead]
    left, right = (lead - 1) % 8, (lead + 1) % 8
    side = left if shares[left] >= shares[right] else right
    if shares[side] >= 0.6 * shares[lead]:
        group = sorted([lead, side], key=lambda i: (i - lead + 1) % 8)
    wind_from = "–".join(SECTORS[i] for i in group)
    lee = [SECTORS[(i + 4) % 8] for i in group]
    label = f"{wind_from} wind, loading {'–'.join(lee)} aspects"
    return Rose(shares, round(snow, 1), mean_kmh, wind_from, lee, label)


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
