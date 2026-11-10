"""Flags: short "worth a look" notes for a location (see docs/ARCHITECTURE.md).

Pure: reads the finished snapshot (plus ensemble chances the builder works out),
returns `Flag`s with metric values. The browser words them in the viewer's units.
`avalanche_danger` is not here: the API adds it when serving, so it expires with
the avalanche forecast instead of living in a stored snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from snowwatch.doc import Flag, Snapshot

SEVERITY = {"warning": 0, "notice": 1, "info": 2}


class FlagConfig(BaseModel):
    powder_cm: float = 15  # 6 in, night before + day
    storm_cm: float = 30  # 12 in over 48 h
    storm_chance: float = 0.4  # or this share of ensemble members reach storm_cm
    storm_big_cm: float = 50  # makes it a warning
    outlier_factor: float = 2.0
    outlier_margin_cm: float = 15  # 6 in
    low_confidence_ratio: float = 3.0
    low_confidence_floor_cm: float = 2.5  # 1 in
    rain_on_snow_mm: float = 6  # 0.25 in of water
    wind_hold_kmh: float = 72  # 45 mph summit gusts in lift hours
    wind_loading_kmh: float = 40  # 25 mph ridge wind…
    wind_loading_snow_cm: float = 10  # …with 4 in of snow in 24 h
    warming_fl_m: float = 915  # 3,000 ft freezing-level rise in 24 h
    warming_temp_c: float = 8.3  # 15 °F
    refreeze_warm_day_c: float = 5  # a spring day warm enough to soften the snow


def flag_key(f: Flag) -> str:
    """Identity of a flag across runs, for `flag_log` (first raised / last seen)."""
    return f.date or f.period_key or f.model or f.detail or ""


def _date(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def compute_flags(
    snap: Snapshot, cfg: FlagConfig, storm_chances: Sequence[float | None] = ()
) -> list[Flag]:
    """storm_chances[j]: share of ensemble members with ≥ storm_cm in periods j..j+3 (mid)."""
    flags: list[Flag] = []
    resort = snap.location.kind == "resort"
    mid = snap.bands[1]
    periods = mid.periods[:10]  # the next 5 days

    for d in snap.days[:10]:
        new = (d.overnight_cm or 0) + (d.day_cm or 0)
        if new >= cfg.powder_cm and d.quality != "Heavy & wet":
            flags.append(
                Flag(type="powder_day", severity="notice", date=d.date, value=round(new, 1))
            )

    best: tuple[float, int] | None = None
    for j in range(max(0, len(mid.periods[:10]) - 3)):
        total = sum(p.snow_cm or 0 for p in mid.periods[j : j + 4])
        chance = storm_chances[j] if j < len(storm_chances) else None
        stormy = total >= cfg.storm_cm or (chance is not None and chance >= cfg.storm_chance)
        if stormy and (best is None or total > best[0]):
            best = (total, j)
    if best is not None:
        total, j = best
        chance = storm_chances[j] if j < len(storm_chances) else None
        flags.append(
            Flag(
                type="storm_incoming",
                severity="warning" if total >= cfg.storm_big_cm else "notice",
                date=mid.periods[j].date,
                period_key=mid.periods[j].key,
                value=round(total, 1),
                value2=None if chance is None else round(chance * 100),
            )
        )

    if len(snap.daily) >= 10 and snap.daily[9].pooled_cum is not None:
        p90 = snap.daily[9].pooled_cum.p90
        if p90 is not None:
            limit = max(cfg.outlier_factor * p90, p90 + cfg.outlier_margin_cm)
            over = [
                (v, m) for m, v in snap.daily[9].models_cum.items() if v is not None and v > limit
            ]
            if over:
                v, m = max(over)
                flags.append(
                    Flag(type="model_outlier", severity="info", model=m, value=v, value2=p90)
                )

    ens = mid.windows["next5"].ens
    if ens and ens.p10 is not None and ens.p50 is not None and ens.p90 is not None:
        spread = (ens.p90 - ens.p10) / max(ens.p50, cfg.low_confidence_floor_cm)
        if spread > cfg.low_confidence_ratio:
            flags.append(
                Flag(type="low_confidence", severity="info", value=ens.p10, value2=ens.p90)
            )

    bc = snap.backcountry
    on_snow = bc is not None and bc.warming.rain_on_snow_mm is not None
    if on_snow:
        wet = next((p for p in periods if (p.rain_mm or 0) >= cfg.rain_on_snow_mm), None)
        if wet is not None:
            flags.append(
                Flag(
                    type="rain_on_snow",
                    severity="notice",
                    date=wet.date,
                    period_key=wet.key,
                    value=wet.rain_mm,
                )
            )

    base_m, mid_m = snap.bands[0].elev_m, snap.bands[1].elev_m
    levels = [
        (t, v)
        for t, v in zip(mid.hourly.t[:72], mid.hourly.snow_level_m[:72], strict=False)
        if v is not None
    ]
    if levels:
        start = levels[0][1]
        if start >= base_m:
            low = next(((t, v) for t, v in levels if v < base_m), None)
            if low:
                flags.append(
                    Flag(
                        type="snow_level_crossing",
                        severity="notice",
                        detail="below_base",
                        date=_date(low[0]),
                        value=low[1],
                        value2=base_m,
                    )
                )
        if start <= mid_m:
            high = next(((t, v) for t, v in levels if v > mid_m), None)
            if high:
                flags.append(
                    Flag(
                        type="snow_level_crossing",
                        severity="notice",
                        detail="above_mid",
                        date=_date(high[0]),
                        value=high[1],
                        value2=mid_m,
                    )
                )

    if resort:
        windy = next((d for d in snap.days[:5] if (d.gust_max_kmh or 0) >= cfg.wind_hold_kmh), None)
        if windy is not None:
            flags.append(
                Flag(type="wind_hold", severity="notice", date=windy.date, value=windy.gust_max_kmh)
            )
        rated = [d for d in snap.days if d.score is not None]
        if rated:
            top = max(d.score or 0 for d in rated)
            if top >= 3:
                d = next(d for d in rated if d.score == top)
                flags.append(
                    Flag(
                        type="best_day",
                        severity="info",
                        date=d.date,
                        value=float(top),
                        detail=d.rating,
                    )
                )

    if snap.ridge is not None:
        top_h = snap.bands[2].hourly
        n = min(48, len(top_h.t), len(snap.ridge.kmh))
        for i in range(n):
            window = range(max(0, i - 23), i + 1)
            snow24 = sum(top_h.snow_cm[k] or 0 for k in window)
            wind = snap.ridge.kmh[i]
            if (
                wind is not None
                and wind >= cfg.wind_loading_kmh
                and snow24 >= cfg.wind_loading_snow_cm
            ):
                flags.append(
                    Flag(
                        type="wind_loading",
                        severity="notice",
                        date=_date(top_h.t[i]),
                        value=round(snow24, 1),
                        value2=wind,
                    )
                )
                break

    if bc is not None:
        w = bc.warming
        fl_hit = w.fl_rise_m is not None and w.fl_rise_m >= cfg.warming_fl_m
        t_hit = w.temp_rise_c is not None and w.temp_rise_c >= cfg.warming_temp_c
        if fl_hit or t_hit:
            flags.append(
                Flag(
                    type="rapid_warming",
                    severity="notice",
                    date=_date(w.fl_rise_at if fl_hit else w.temp_rise_at),
                    value=w.fl_rise_m,
                    value2=w.temp_rise_c,
                )
            )
        highs = {p.date: p.tmax_c for p in mid.periods if p.kind == "day"}
        for night in bc.refreeze:
            if night.band != "mid" or night.status != "Good":
                continue
            warm = highs.get(night.date)
            if warm is not None and warm >= cfg.refreeze_warm_day_c:
                flags.append(
                    Flag(
                        type="refreeze",
                        severity="info",
                        date=night.date,
                        value=night.low_c,
                        value2=warm,
                    )
                )
                break

    for a in snap.alerts[:3]:
        flags.append(
            Flag(
                type="nws_alert", severity="warning", detail=a.event or "Alert", date=_date(a.onset)
            )
        )

    def order(f: Flag) -> tuple[int, str]:
        return SEVERITY.get(f.severity, 3), f.date or "9999"

    return sorted(flags, key=order)


def avalanche_flag(level: int | None, date: str | None) -> Flag | None:
    """Added when served, from a current avalanche forecast (rating 4 or 5)."""
    if level is None or level < 4:
        return None
    return Flag(type="avalanche_danger", severity="warning", date=date, value=float(level))
