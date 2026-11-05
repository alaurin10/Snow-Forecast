"""Ski-day rating for resorts: Powder, Great, Good, Fair or Poor, with the reasons.

A day starts from how much new snow there is (the night before plus the day),
then steps down for rain, wind that holds lifts, flat light and deep cold. The
rating never applies to backcountry locations: the app doesn't judge tours.
Thresholds come from `config/forecast.yaml` (`skiday:`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

RATINGS = {5: "Powder", 4: "Great", 3: "Good", 2: "Fair", 1: "Poor"}
HEAVY = "Heavy & wet"


class SkiDayConfig(BaseModel):
    lift_start_hour: int = 9
    lift_end_hour: int = 16  # exclusive: lifts close at 16:00
    powder_cm: float = 15
    great_cm: float = 8
    good_cm: float = 3
    clear_cloud_low_pct: float = 50
    dry_water_mm: float = 0.5
    rain_fair_mm: float = 1
    rain_poor_mm: float = 5
    gust_hold_kmh: float = 70
    gust_closed_kmh: float = 90
    flat_light_vis_m: float = 1000
    flat_light_cloud_low_pct: float = 80
    very_cold_c: float = -18


@dataclass(frozen=True)
class DayFacts:
    """What the rating looks at for one day. None means no data."""

    new_cm: float | None  # overnight + day, mid band
    quality: str | None  # snow-to-liquid label of the day's snow
    water_mm: float | None  # all precipitation during the day period, mid
    rain_mm: float | None  # rain during lift hours, mid
    gust_max_kmh: float | None  # summit, lift hours
    cloud_low: float | None  # mean %, mid, lift hours
    vis_min_m: float | None  # mid, lift hours
    tmax_c: float | None  # mid, lift hours


@dataclass(frozen=True)
class Reason:
    code: str  # new_snow, heavy_wet, clear, grey, rain, gusts, flat_light, very_cold
    value: float | None = None


@dataclass
class Rating:
    score: int
    rating: str
    reasons: list[Reason] = field(default_factory=list)


def rate(f: DayFacts, cfg: SkiDayConfig) -> Rating:
    new = f.new_cm or 0.0
    lead: list[Reason] = []
    if new >= cfg.powder_cm:
        if f.quality == HEAVY:
            base = 4
            lead = [Reason("new_snow", new), Reason("heavy_wet")]
        else:
            base = 5
            lead = [Reason("new_snow", new)]
    elif new >= cfg.great_cm:
        base, lead = 4, [Reason("new_snow", new)]
    elif new >= cfg.good_cm:
        base, lead = 3, [Reason("new_snow", new)]
    else:
        dry = (f.water_mm or 0.0) < cfg.dry_water_mm
        clear = f.cloud_low is not None and f.cloud_low < cfg.clear_cloud_low_pct
        if dry and clear:
            base, lead = 3, [Reason("clear")]
        else:
            base, lead = 2, [Reason("grey")]

    # Each penalty: (steps, reason). Rain caps instead of stepping down.
    cap = 5
    penalties: list[tuple[int, Reason]] = []
    rain = f.rain_mm or 0.0
    if rain >= cfg.rain_poor_mm:
        cap = 1
        penalties.append((4, Reason("rain", rain)))
    elif rain >= cfg.rain_fair_mm:
        cap = 2
        penalties.append((3, Reason("rain", rain)))
    gust = f.gust_max_kmh
    if gust is not None and gust >= cfg.gust_closed_kmh:
        penalties.append((2, Reason("gusts", gust)))
    elif gust is not None and gust >= cfg.gust_hold_kmh:
        penalties.append((1, Reason("gusts", gust)))
    low_vis = f.vis_min_m is not None and f.vis_min_m < cfg.flat_light_vis_m
    low_cloud = f.cloud_low is not None and f.cloud_low >= cfg.flat_light_cloud_low_pct
    if low_vis or low_cloud:
        penalties.append((1, Reason("flat_light")))
    if f.tmax_c is not None and f.tmax_c < cfg.very_cold_c:
        penalties.append((1, Reason("very_cold", f.tmax_c)))

    steps = sum(s for s, rs in penalties if rs.code != "rain")
    score = max(1, min(base - steps, cap))
    # The reasons that decided it. When something pulled the day down (or the day
    # had no snow to speak of), that leads; otherwise the snow does.
    penalties.sort(key=lambda p: -p[0])
    downs = [rs for _, rs in penalties]
    reasons = downs + lead if downs and (score < base or base <= 2) else lead + downs
    return Rating(score, RATINGS[score], reasons[:3])
