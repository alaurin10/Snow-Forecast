"""Turn one location's upstream responses into its snapshot document.

Pure: no I/O. The pipeline fetches (or loads cached / fixture) responses into
`ForecastInputs`, and this module does all the analysis.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from snowwatch.analysis import backcountry as bc
from snowwatch.analysis import ensemble as ens
from snowwatch.analysis.consensus import PeriodConsensus, period_consensus
from snowwatch.analysis.flags import compute_flags
from snowwatch.analysis.freezing import LEVELS, freezing_level_m
from snowwatch.analysis.hourly import consensus_line, scale_to_total, shape_value, support_counts
from snowwatch.analysis.periods import Period, build_periods
from snowwatch.analysis.ridge import ridge_wind
from snowwatch.analysis.series import (
    Hourly,
    PointData,
    circular_mean,
    ensemble_members,
    local,
    mean,
    r,
    split_models,
    total,
)
from snowwatch.analysis.skiday import DayFacts, rate
from snowwatch.analysis.slr import hourly_slr, period_ratio, ptype, ratio_for
from snowwatch.config import ForecastConfig, SlrBand
from snowwatch.doc import (
    Alert,
    BackcountryOut,
    BandOut,
    DailyEns,
    DailyRow,
    DayOut,
    ElevationOut,
    EnsStats,
    HourlyOut,
    LocationMeta,
    OutlookDay,
    OutlookLevels,
    PeriodOut,
    Reason,
    RefreezeNight,
    RidgeOut,
    RoseOut,
    SkyDay,
    Snapshot,
    Snotel,
    StormOut,
    SunDay,
    WarmingOut,
    WindowOut,
)
from snowwatch.models import Location

WINDOWS = {"next5": (0, 10), "d6_10": (10, 20)}


@dataclass
class ForecastInputs:
    blend: list[PointData]  # base, mid, summit
    multi: list[PointData]  # base, mid, summit
    upper: PointData | None = None
    ensembles: dict[str, PointData] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    snotel: Snotel | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyRecord:
    """One row of `forecast_daily` (mid band) for trend and verification."""

    target_date: str
    source: str
    snow_cm: float | None
    water_mm: float | None


@dataclass(frozen=True)
class Depth:
    """Snow water (mm) to the headline snow depth (cm), per `depth_method`.

    "slr": the temperature-based snow-to-liquid ratio. Forecast periods use their own
    ratio (from the temperature while it snows); an hour outside every period (past
    hours, days past the last period) uses the ratio for its own temperature.
    "raw": Open-Meteo's fixed 7:1. With nothing snowing there is no ratio, and both
    use 7:1. Every depth the snapshot surfaces goes through this, so totals, ranges,
    model bars, flags and ratings all agree.
    """

    k: float  # Open-Meteo's cm of snow per mm of water (0.7)
    slr: bool
    bands: Sequence[SlrBand]

    @classmethod
    def of(cls, cfg: ForecastConfig) -> Depth:
        return cls(cfg.snowfall_cm_per_mm, cfg.depth_method == "slr", cfg.slr_bands)

    def factor(self, ratio: float | None) -> float:
        """cm of snow per mm of water, for a period with this snow ratio."""
        return ratio / 10 if self.slr and ratio else self.k

    def cm(self, swe: float | None, ratio: float | None) -> float | None:
        return None if swe is None else swe * self.factor(ratio)

    def hour_factor(self, temp_c: float | None) -> float:
        """cm per mm for an hour outside the periods, from its own temperature."""
        return self.factor(None if temp_c is None else ratio_for(temp_c, self.bands)[0])

    def from_snowfall(self, snowfall_cm: Hourly, temps: Hourly) -> Hourly:
        """Open-Meteo's snowfall (7:1) as headline depth, hour by hour."""
        return {
            h: None if v is None else v / self.k * self.hour_factor(temps.get(h))
            for h, v in snowfall_cm.items()
        }


def _period_factors(
    periods: Sequence[Period], ratios: Sequence[tuple[float | None, str | None]], depth: Depth
) -> dict[int, float]:
    """Each forecast hour's cm per mm: its period's."""
    return {
        h: depth.factor(ratio)
        for p, (ratio, _) in zip(periods, ratios, strict=True)
        for h in p.hours
    }


def _swe(snowfall_cm: Hourly, cm_per_mm: float) -> Hourly:
    return {h: None if v is None else v / cm_per_mm for h, v in snowfall_cm.items()}


def _add(a: Hourly, b: Hourly) -> Hourly:
    out: Hourly = {}
    for h in set(a) | set(b):
        x, y = a.get(h), b.get(h)
        out[h] = None if x is None and y is None else (x or 0.0) + (y or 0.0)
    return out


def _var(group: Mapping[str, Mapping[str, Hourly]], name: str) -> dict[str, Hourly]:
    return {m: v[name] for m, v in group.items() if name in v}


def _freezing(
    model_vars: Mapping[str, Hourly], upper: Mapping[str, Hourly] | None, elev_m: float
) -> Hourly:
    native = model_vars.get("freezing_level_height")
    if native and any(v is not None for v in native.values()):
        return dict(native)
    if not upper:
        return {}
    t2 = model_vars.get("temperature_2m", {})
    out: Hourly = {}
    for h, t in t2.items():
        levels = [
            (
                upper.get(f"geopotential_height_{p}hPa", {}).get(h),
                upper.get(f"temperature_{p}hPa", {}).get(h),
            )
            for p in LEVELS
        ]
        out[h] = freezing_level_m(elev_m, t, levels)
    return out


def _ens_stats(
    values: Sequence[float], k: float, min_members: int, *, estimated: bool = False
) -> EnsStats | None:
    s = ens.stats(values, min_members)
    if s is None:
        return None
    s = s.scaled(k)
    return EnsStats(
        p10=r(s.p10), p50=r(s.p50), p90=r(s.p90), mean=r(s.mean), n=s.n, estimated=estimated
    )


def _daily_ens(s: ens.Stats | None, k: float) -> DailyEns | None:
    if s is None:
        return None
    s = s.scaled(k)
    return DailyEns(p10=r(s.p10), p50=r(s.p50), p90=r(s.p90), n=s.n)


def _iso(ts: int, tz: ZoneInfo) -> str:
    return local(ts, tz).isoformat(timespec="minutes")


@dataclass
class _BandWork:
    """Intermediate per-band results."""

    sw: list[PeriodConsensus]
    liq: list[PeriodConsensus]
    hourly_sw: dict[int, float | None]
    hourly_liq: dict[int, float | None]
    temp: tuple[dict[int, float | None], dict[int, float | None], dict[int, float | None]]
    fl: tuple[dict[int, float | None], dict[int, float | None], dict[int, float | None]]
    wind: tuple[dict[int, float | None], dict[int, float | None], dict[int, float | None]]
    gust: dict[int, float | None]
    cloud: dict[int, float | None]
    wdir: dict[int, float | None]
    ratios: list[tuple[float | None, str | None]]
    model_sums: list[dict[str, float | None]]


def build_snapshot(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    now: datetime,
    *,
    run_id: int | None = None,
) -> tuple[Snapshot, list[DailyRecord]]:
    tz_name = loc.tz or inputs.blend[1].tz
    tz = ZoneInfo(tz_name)
    warnings = list(inputs.warnings)
    now_h = int(now.timestamp()) // 3600 * 3600
    today = local(now_h, tz).date()
    offset = local(now_h, tz).utcoffset()
    if offset is not None and int(offset.total_seconds()) != inputs.blend[1].utc_offset_s:
        warnings.append(
            f"timezone data disagrees with Open-Meteo for {tz_name}: "
            f"{int(offset.total_seconds())} s vs {inputs.blend[1].utc_offset_s} s"
        )
    k = cfg.snowfall_cm_per_mm
    depth = Depth.of(cfg)
    global_models = list(cfg.models.global_)
    short_models = cfg.short_range_for(loc.country)
    short_until = now_h + cfg.short_range_hours * 3600

    temps_mid = inputs.blend[1].get("temperature_2m")
    all_hours = sorted(h for h, v in temps_mid.items() if h >= now_h and v is not None)
    periods = build_periods(
        all_hours,
        tz,
        today,
        n=cfg.periods,
        min_hours=cfg.min_period_hours,
        day_start=cfg.day_start_hour,
        night_start=cfg.night_start_hour,
    )
    shown = all_hours[: cfg.hourly_hours]

    systems = {s: [_swe(m, k) for m in ensemble_members(pt)] for s, pt in inputs.ensembles.items()}
    systems = {s: m for s, m in systems.items() if m}
    members = ens.pooled(systems)
    upper = split_models(inputs.upper, cfg.upper_air_models(loc.country)) if inputs.upper else {}

    period_members = [ens.member_totals(members, p.hours) for p in periods]
    mid_ens_mean = [mean(t) if t else None for t in period_members]

    work: dict[int, _BandWork] = {}
    for i in (1, 0, 2):  # mid first: the other bands scale from it
        band = loc.bands[i]
        md = split_models(inputs.multi[i], [*global_models, *short_models])
        g = {m: md[m] for m in global_models if m in md}
        s = {m: md[m] for m in short_models if m in md}
        sw_g = {m: _swe(v, k) for m, v in _var(g, "snowfall").items()}
        sw_s = {m: _swe(v, k) for m, v in _var(s, "snowfall").items()}
        liq_g, liq_s = _var(g, "rain"), _var(s, "rain")
        blend = inputs.blend[i]
        blend_sw = _swe(blend.get("snowfall"), k)
        blend_liq = _add(blend.get("rain"), blend.get("showers"))
        water_all = [*_var(g, "precipitation").values(), *_var(s, "precipitation").values()]

        temp = consensus_line(
            all_hours,
            _var(g, "temperature_2m"),
            _var(s, "temperature_2m"),
            short_until,
            blend.get("temperature_2m"),
        )
        fl_g = {m: _freezing(v, upper.get(m), band.elev_m) for m, v in g.items()}
        fl_s = {m: _freezing(v, upper.get(m), band.elev_m) for m, v in s.items()}
        fl_g = {m: v for m, v in fl_g.items() if v}
        fl_s = {m: v for m, v in fl_s.items() if v}
        fl = consensus_line(all_hours, fl_g, fl_s, short_until, blend.get("freezing_level_height"))
        wind = consensus_line(
            all_hours,
            _var(g, "wind_speed_10m"),
            _var(s, "wind_speed_10m"),
            short_until,
            blend.get("wind_speed_10m"),
        )
        gust = consensus_line(
            all_hours,
            _var(g, "wind_gusts_10m"),
            _var(s, "wind_gusts_10m"),
            short_until,
            blend.get("wind_gusts_10m"),
        )[0]
        cloud = consensus_line(
            all_hours,
            _var(g, "cloud_cover"),
            _var(s, "cloud_cover"),
            short_until,
            blend.get("cloud_cover"),
        )[0]
        dirs = [*_var(g, "wind_direction_10m").values(), *_var(s, "wind_direction_10m").values()]
        wdir = {
            h: circular_mean(d.get(h) for d in dirs)
            if dirs
            else blend.get("wind_direction_10m").get(h)
            for h in all_hours
        }

        sw_c: list[PeriodConsensus] = []
        liq_c: list[PeriodConsensus] = []
        hourly_sw: dict[int, float | None] = {}
        hourly_liq: dict[int, float | None] = {}
        ratios: list[tuple[float | None, str | None]] = []
        sums: list[dict[str, float | None]] = []
        for j, p in enumerate(periods):
            early = j < cfg.blend_periods
            if i == 1:
                e_mean = mid_ens_mean[j]
            else:
                e_mean = _scaled_ens_mean(
                    mid_ens_mean[j], sw_g, work[1].model_sums[j] if 1 in work else {}, p.hours
                )
            c = period_consensus(
                p.hours,
                sw_g,
                short_range=sw_s,
                blend=blend_sw,
                early=early,
                ens_mean=e_mean,
                min_models=cfg.consensus_min_models,
            )
            lq = period_consensus(
                p.hours,
                liq_g,
                short_range=liq_s,
                blend=blend_liq,
                early=early,
                min_models=cfg.consensus_min_models,
            )
            sw_c.append(c)
            liq_c.append(lq)
            sums.append({m: total(v, p.hours) for m, v in sw_g.items()})
            support = support_counts(p.hours, water_all)
            shape = {h: shape_value(h, sw_g, sw_s, short_until, blend_sw) for h in p.hours}
            hourly_sw.update(scale_to_total(p.hours, shape, c.value, support))
            shape_l = {h: shape_value(h, liq_g, liq_s, short_until, blend_liq) for h in p.hours}
            hourly_liq.update(scale_to_total(p.hours, shape_l, lq.value, support))
            ratios.append(
                period_ratio(
                    [hourly_sw.get(h) or 0.0 for h in p.hours],
                    [temp[0].get(h) for h in p.hours],
                    cfg.slr_bands,
                )
            )
        work[i] = _BandWork(
            sw_c, liq_c, hourly_sw, hourly_liq, temp, fl, wind, gust, cloud, wdir, ratios, sums
        )

    bands_out = [
        _band_out(
            loc,
            i,
            work[i],
            work[1],
            periods,
            period_members,
            shown,
            inputs.blend[i],
            cfg,
            tz,
            now_h,
            systems,
            depth,
        )
        for i in range(3)
    ]

    daily, records = _daily(loc, inputs, cfg, tz, now_h, systems, work[1], periods, depth)
    ridge_kmh, ridge_dir = ridge_wind(
        upper,
        loc.bands[2].elev_m,
        [*range(now_h - 72 * 3600, now_h, 3600), *all_hours],
    )
    have_ridge = any(v is not None for v in ridge_kmh.values())
    ridge = (
        RidgeOut(
            level_m=loc.bands[2].elev_m,
            kmh=[r(ridge_kmh.get(h), 0) for h in shown],
            dir=[r(ridge_dir.get(h), 0) for h in shown],
        )
        if have_ridge
        else None
    )
    backcountry = _backcountry(
        loc, inputs, cfg, tz, now_h, all_hours, periods, work, ridge_kmh, ridge_dir, depth
    )
    days = _days(loc, inputs, cfg, tz, now_h, periods, work, bands_out, depth)
    switch = next(
        (p for p, c in zip(periods, work[1].sw, strict=True) if c.basis == "ensemble"), None
    )
    snap = Snapshot(
        location=LocationMeta(
            id=loc.id,
            name=loc.name,
            kind=loc.kind,
            region=loc.region,
            country=loc.country,
            tz=tz_name,
            lat=loc.band("mid").lat,
            lon=loc.band("mid").lon,
            links=loc.links,
            webcams=loc.webcams,
        ),
        run_id=run_id,
        generated_at=now.isoformat(timespec="seconds"),
        now=_iso(now_h, tz),
        depth_method=cfg.depth_method,
        models=[*global_models, *short_models],
        ensembles={s: len(m) for s, m in systems.items()},
        basis_switch=_iso(switch.hours[0], tz) if switch else None,
        bands=bands_out,
        daily=daily,
        sun=_sun(inputs.blend[1], tz),
        alerts=inputs.alerts,
        snotel=inputs.snotel,
        ridge=ridge,
        backcountry=backcountry,
        days=days,
        warnings=warnings,
    )
    # Chance that 48 h (4 periods) bring a storm's worth of snow, from the members,
    # each period's snow water at its headline ratio.
    chances: list[float | None] = []
    for j in range(max(0, min(10, len(periods)) - 3)):
        ps = periods[j : j + 4]
        factors = [depth.factor(ratio) for ratio, _ in work[1].ratios[j : j + 4]]
        totals = _member_depths(members, ps, factors)
        chances.append(
            sum(1 for t in totals if t >= cfg.flags.storm_cm) / len(totals)
            if len(totals) >= cfg.ensemble_min_members
            else None
        )
    snap.flags = compute_flags(snap, cfg.flags, chances)
    return snap, records


def _member_depths(
    members: Sequence[Hourly], periods: Sequence[Period], factors: Sequence[float]
) -> list[float]:
    """Each member's depth over the periods (period snow water × its cm per mm), for
    the members that cover every hour."""
    out = []
    for m in members:
        sums = [total(m, p.hours) for p in periods]
        if all(v is not None for v in sums):
            out.append(sum((v or 0.0) * f for v, f in zip(sums, factors, strict=True)))
    return out


def _past(series: Hourly, now_h: int, hours: int) -> list[int]:
    return [h for h in series if now_h - hours * 3600 <= h < now_h]


def _first(a: Hourly, b: Hourly) -> Hourly:
    """`a` where it has a value, otherwise `b`."""
    return {h: a.get(h) if a.get(h) is not None else b.get(h) for h in set(a) | set(b)}


def _backcountry(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    all_hours: Sequence[int],
    periods: Sequence[Period],
    work: Mapping[int, _BandWork],
    ridge_kmh: Hourly,
    ridge_dir: Hourly,
    depth: Depth,
) -> BackcountryOut:
    """Facts for touring (see docs/ARCHITECTURE.md). No safety judgement."""
    bcfg = cfg.backcountry
    top, mid = work[2], work[1]
    blend_top = inputs.blend[2]
    past_snow = depth.from_snowfall(blend_top.get("snowfall"), blend_top.get("temperature_2m"))
    past72 = _past(past_snow, now_h, 72)
    next48 = list(all_hours[:48])
    # Ridge wind where the free-air data has it, the summit's own wind otherwise.
    speed = _first(ridge_kmh, _first(top.wind[0], blend_top.get("wind_speed_10m")))
    direction = _first(ridge_dir, _first(top.wdir, blend_top.get("wind_direction_10m")))
    top_factor = _period_factors(periods, top.ratios, depth)
    future_snow = {
        h: None if v is None else v * top_factor.get(h, depth.k) for h, v in top.hourly_sw.items()
    }

    # The first two are the Backcountry tab's; the rest feed the map's wind-effect layer.
    windows = (
        ("past72", past72, past_snow),
        ("next48", next48, future_snow),
        ("past48", _past(past_snow, now_h, 48), past_snow),
        ("next24", list(all_hours[:24]), future_snow),
        ("next72", list(all_hours[:72]), future_snow),
    )
    roses = []
    for name, hours, snow in windows:
        rose = bc.loading_rose(hours, snow, speed, direction, bcfg)
        roses.append(
            RoseOut(
                window=name,
                sectors=[round(x, 3) for x in rose.sectors],
                snow_cm=rose.snow_cm,
                mean_kmh=r(rose.mean_kmh, 0),
                wind_from=rose.wind_from,
                loading=rose.loading,
                label=rose.label,
            )
        )

    next72 = list(all_hours[:72])
    fl_rise = bc.max_rise(mid.fl[0], next72)
    t_rise = bc.max_rise(mid.temp[0], next72)
    mid_past = depth.from_snowfall(
        inputs.blend[1].get("snowfall"), inputs.blend[1].get("temperature_2m")
    )
    recent = sum(mid_past.get(h) or 0.0 for h in _past(mid_past, now_h, 72))
    on_ground = inputs.snotel.depth_cm if inputs.snotel else None
    on_snow = (on_ground or 0) > 0 or recent >= 1.0
    rain48 = bc.total_over(mid.hourly_liq, next48)
    warming = WarmingOut(
        fl_rise_m=r(fl_rise.amount, -1),
        fl_rise_at=_iso(fl_rise.end, tz) if fl_rise.end else None,
        temp_rise_c=r(t_rise.amount),
        temp_rise_at=_iso(t_rise.end, tz) if t_rise.end else None,
        rain_on_snow_mm=r(rain48) if on_snow else None,
    )

    nights = [p for p in periods if p.kind == "night"][:3]
    refreeze = []
    for i in range(3):
        w = work[i]
        for p in nights:
            f = bc.refreeze(p.hours, w.temp[0], w.cloud, bcfg)
            refreeze.append(
                RefreezeNight(
                    date=p.date.isoformat(),
                    band=loc.bands[i].band,
                    status=f.status,
                    low_c=f.low_c,
                    clear_frac=f.clear_frac,
                )
            )

    sky = []
    for p in [p for p in periods if p.kind == "day"][:3]:
        sk = bc.sky(
            p.hours,
            {
                "low": blend_top.get("cloud_cover_low"),
                "mid": blend_top.get("cloud_cover_mid"),
                "high": blend_top.get("cloud_cover_high"),
            },
            blend_top.get("visibility"),
            blend_top.get("is_day"),
        )
        sky.append(
            SkyDay(
                date=p.date.isoformat(),
                cloud_low=sk.cloud_low,
                cloud_mid=sk.cloud_mid,
                cloud_high=sk.cloud_high,
                vis_min_m=sk.vis_min_m,
            )
        )

    storm = StormOut(
        past72_cm=r(sum(past_snow.get(h) or 0.0 for h in past72)) if past72 else None,
        next48_cm=r(bc.total_over(future_snow, next48)),
    )
    outlook = _outlook(
        loc,
        inputs,
        cfg,
        tz,
        now_h,
        work,
        snow=_first(future_snow, past_snow),
        mid_snow=mid_past,
        speed=speed,
        direction=direction,
        on_snow=on_snow,
        depth=depth,
        periods=periods,
    )
    return BackcountryOut(
        rose=roses, warming=warming, refreeze=refreeze, sky=sky, storm=storm, outlook=outlook
    )


def _outlook(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    work: Mapping[int, _BandWork],
    *,
    snow: Hourly,
    mid_snow: Hourly,
    speed: Hourly,
    direction: Hourly,
    on_snow: bool,
    depth: Depth,
    periods: Sequence[Period],
) -> list[OutlookDay]:
    """Avalanche weather for today and the days after it (see `analysis/backcountry.py`).

    Each day is a whole calendar day: the forecast where there is one, the
    high-resolution model's last three days behind it, so today counts the snow that
    has already fallen and has a day before to rise or ease against.
    """
    bcfg = cfg.backcountry
    mid = work[1]
    blend_top, blend_mid = inputs.blend[2], inputs.blend[1]
    temps = [_first(work[i].temp[0], inputs.blend[i].get("temperature_2m")) for i in range(3)]
    clouds = [_first(work[i].cloud, inputs.blend[i].get("cloud_cover")) for i in range(3)]
    rain = _first(mid.hourly_liq, _add(blend_mid.get("rain"), blend_mid.get("showers")))
    fl = _first(mid.fl[0], blend_mid.get("freezing_level_height"))
    snow_level = {
        h: None if v is None else max(0.0, v - cfg.snow_level_offset_m) for h, v in fl.items()
    }
    mid_factor = _period_factors(periods, mid.ratios, depth)
    mid_all = _first(
        {
            h: None if v is None else v * mid_factor.get(h, depth.k)
            for h, v in mid.hourly_sw.items()
        },
        mid_snow,
    )
    today = local(now_h, tz).date()
    out: list[OutlookDay] = []
    before: int | None = None
    for offset in range(-1, bcfg.outlook_days):
        day = today + timedelta(days=offset)
        hours = sorted(set(_local_hours(day, 0, 24, tz)))
        if sum(1 for h in hours if temps[2].get(h) is not None) < 12:
            continue  # yesterday may be missing; the far end of the forecast stops mid-day
        night = sorted(
            {
                *_local_hours(day - timedelta(days=1), cfg.night_start_hour, 24, tz),
                *_local_hours(day, 0, cfg.day_start_hour, tz),
            }
        )
        frozen = [bc.refreeze(night, temps[i], clouds[i], bcfg) for i in range(3)]
        fallen = sum(mid_all.get(h) or 0.0 for h in mid_all if h <= hours[-1])
        facts = bc.day_weather(
            hours,
            snow_cm=snow,
            speed_kmh=speed,
            direction=direction,
            rain_mm=rain,
            snow_level_m=snow_level,
            fl_m=fl,
            temp_top_c=temps[2],
            temp_mid_c=temps[1],
            refreeze_status=None if frozen[2].status == "Unknown" else frozen[2].status,
            on_snow=on_snow or fallen >= 1.0,
            cfg=bcfg,
        )
        levels = bc.factor_levels(facts, bcfg)
        score = bc.stress(levels)
        if offset >= 0:
            sk = bc.sky(
                hours,
                {
                    "low": blend_top.get("cloud_cover_low"),
                    "mid": blend_top.get("cloud_cover_mid"),
                    "high": blend_top.get("cloud_cover_high"),
                },
                blend_top.get("visibility"),
                blend_top.get("is_day"),
            )
            out.append(
                OutlookDay(
                    date=day.isoformat(),
                    new_cm=r(facts.new_cm),
                    storm_cm=r(facts.storm_cm),
                    wind_kmh=r(facts.wind_kmh, 0),
                    wind_from=facts.wind_from,
                    loading=facts.loading,
                    rain_mm=r(facts.rain_mm),
                    rain_to_m=r(facts.rain_to_m, -1),
                    fl_max_m=r(facts.fl_max_m, -1),
                    thaw_h=facts.thaw_h,
                    temp_rise_c=r(facts.temp_rise_c),
                    refreeze=[
                        RefreezeNight(
                            date=(day - timedelta(days=1)).isoformat(),
                            band=loc.bands[i].band,
                            status=f.status,
                            low_c=f.low_c,
                            clear_frac=f.clear_frac,
                        )
                        for i, f in enumerate(frozen)
                    ],
                    sky=SkyDay(
                        date=day.isoformat(),
                        cloud_low=sk.cloud_low,
                        cloud_mid=sk.cloud_mid,
                        cloud_high=sk.cloud_high,
                        vis_min_m=sk.vis_min_m,
                    ),
                    levels=OutlookLevels(
                        snow=levels.snow, wind=levels.wind, rain=levels.rain, warm=levels.warm
                    ),
                    stress=score,
                    trend=bc.tendency(before, score),
                )
            )
        before = score
    return out


def _local_hours(day: date, start: int, end: int, tz: ZoneInfo) -> list[int]:
    """Unix hours from `start`:00 to `end`:00 (exclusive) local time on `day`."""
    out = []
    for hour in range(start, end):
        t = datetime(day.year, day.month, day.day, hour, tzinfo=tz)
        out.append(int(t.timestamp()))
    return out


def _days(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    periods: Sequence[Period],
    work: Mapping[int, _BandWork],
    bands_out: Sequence[BandOut],
    depth: Depth,
) -> list[DayOut]:
    """One row per day period: the Plan-a-day facts, and the rating for resorts."""
    scfg = cfg.skiday
    mid, top = work[1], work[2]
    mid_periods = {p.key: p for p in bands_out[1].periods}
    top_periods = {p.key: p for p in bands_out[2].periods}
    blend_mid = inputs.blend[1]
    past_snow = depth.from_snowfall(blend_mid.get("snowfall"), blend_mid.get("temperature_2m"))
    out: list[DayOut] = []
    for j, p in enumerate(periods):
        if p.kind != "day":
            continue
        po = mid_periods[p.key]
        prev = periods[j - 1] if j > 0 else None
        if prev is not None and prev.kind == "night":
            night = mid_periods[prev.key]
            overnight = night.snow_cm
            night_quality, night_cm = night.quality, night.snow_cm or 0.0
        else:
            # The night before is already past (today, morning or later): use the
            # high-res model's snowfall from the evening before until now, at the
            # headline ratio.
            day_start = _local_hours(p.date, cfg.day_start_hour, cfg.day_start_hour + 1, tz)[0]
            before = range(day_start - 12 * 3600, min(now_h, p.hours[0]), 3600)
            got = [v for h in before if (v := past_snow.get(h)) is not None]
            overnight = r(sum(got)) if got else None
            night_quality, night_cm = None, 0.0
        lift = [
            h
            for h in _local_hours(p.date, scfg.lift_start_hour, scfg.lift_end_hour, tz)
            if h in p.hours
        ] or list(p.hours)
        gusts = [v for h in lift if (v := top.gust.get(h)) is not None]
        temps = [v for h in lift if (v := mid.temp[0].get(h)) is not None]
        rain = [v for h in lift if (v := mid.hourly_liq.get(h)) is not None]
        clouds = [v for h in lift if (v := blend_mid.get("cloud_cover_low").get(h)) is not None]
        vis = [v for h in lift if (v := blend_mid.get("visibility").get(h)) is not None]
        codes = [v for h in lift if (v := blend_mid.get("weather_code").get(h)) is not None]
        day_cm = po.snow_cm
        quality = po.quality if (day_cm or 0.0) >= night_cm else night_quality or po.quality
        top_p = top_periods.get(p.key)
        facts = DayFacts(
            new_cm=None
            if overnight is None and day_cm is None
            else (overnight or 0) + (day_cm or 0),
            quality=quality,
            water_mm=po.water_mm,
            rain_mm=sum(rain) if rain else None,
            gust_max_kmh=max(gusts) if gusts else (top_p.gust_max_kmh if top_p else None),
            cloud_low=sum(clouds) / len(clouds) if clouds else None,
            vis_min_m=min(vis) if vis else None,
            tmax_c=max(temps) if temps else po.tmax_c,
        )
        rating = rate(facts, scfg) if loc.kind == "resort" else None
        out.append(
            DayOut(
                date=p.date.isoformat(),
                label=p.label,
                overnight_cm=r(overnight),
                day_cm=day_cm,
                quality=quality,
                rating=rating.rating if rating else None,
                score=rating.score if rating else None,
                reasons=[Reason(code=x.code, value=r(x.value)) for x in rating.reasons]
                if rating
                else [],
                gust_max_kmh=r(facts.gust_max_kmh, 0),
                rain_mm=r(facts.rain_mm),
                tmax_c=r(facts.tmax_c),
                tmin_c=r(min(temps)) if temps else po.tmin_c,
                cloud_low=r(facts.cloud_low, 0),
                vis_min_m=facts.vis_min_m,
                wcode=max(codes) if codes else None,
            )
        )
    return out


def _scaled_ens_mean(
    mid_mean: float | None,
    band_sw: Mapping[str, Hourly],
    mid_sums: Mapping[str, float | None],
    hours: Sequence[int],
) -> float | None:
    """The mid-band ensemble mean, scaled by how this band's models compare with mid's."""
    if mid_mean is None:
        return None
    band_tot = mid_tot = 0.0
    for m, mid_v in mid_sums.items():
        band_v = total(band_sw[m], hours) if m in band_sw else None
        if mid_v is not None and band_v is not None:
            band_tot += band_v
            mid_tot += mid_v
    return mid_mean * band_tot / mid_tot if mid_tot > 0 else mid_mean


def _depth(swe: float | None, ratio: float | None, k: float) -> float | None:
    """Temperature-based depth (whatever the headline): computed exactly as `Depth.cm`."""
    if swe is None:
        return None
    return swe * (ratio / 10 if ratio else k)


def _band_out(
    loc: Location,
    i: int,
    w: _BandWork,
    mid: _BandWork,
    periods: Sequence[Period],
    period_members: Sequence[Sequence[float]],
    shown: Sequence[int],
    blend: PointData,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    systems: Mapping[str, Sequence[Hourly]],
    depth: Depth,
) -> BandOut:
    band = loc.bands[i]
    k = cfg.snowfall_cm_per_mm
    min_m = cfg.ensemble_min_members
    offset = cfg.snow_level_offset_m
    pop = blend.get("precipitation_probability")

    period_ratio_of: dict[int, float | None] = {}
    out_periods: list[PeriodOut] = []
    for j, p in enumerate(periods):
        c, lq = w.sw[j], w.liq[j]
        ratio, label = w.ratios[j]
        for h in p.hours:
            period_ratio_of[h] = ratio
        cm_per_mm = depth.factor(ratio)  # this period's headline
        raw = None if c.value is None else c.value * k
        slr = _depth(c.value, ratio, k)
        temps = [v for h in p.hours if (v := w.temp[0].get(h)) is not None]
        fls = [v for h in p.hours if (v := w.fl[0].get(h)) is not None]
        winds = [v for h in p.hours if (v := w.wind[0].get(h)) is not None]
        gusts = [v for h in p.hours if (v := w.gust.get(h)) is not None]
        clouds = [v for h in p.hours if (v := w.cloud.get(h)) is not None]
        pops = [v for h in p.hours if (v := pop.get(h)) is not None]
        e: EnsStats | None
        if i == 1:
            e = _ens_stats(period_members[j], cm_per_mm, min_m)
        else:
            mid_c = mid.sw[j].value
            e = None
            if mid_c and c.value is not None:
                e = _ens_stats(
                    period_members[j], cm_per_mm * c.value / mid_c, min_m, estimated=True
                )
        out_periods.append(
            PeriodOut(
                key=p.key,
                date=p.date.isoformat(),
                kind=p.kind,
                label=p.label,
                start=_iso(p.hours[0], tz),
                hours=len(p.hours),
                snow_cm=r(depth.cm(c.value, ratio)),
                snow_cm_raw=r(raw),
                snow_cm_slr=r(slr),
                swe_mm=r(c.value),
                water_mm=r(None if c.value is None else c.value + (lq.value or 0.0)),
                rain_mm=r(lq.value),
                basis=c.basis,
                nmodels=c.nmodels,
                models={m: r(depth.cm(v, ratio)) for m, v in c.models.items()},
                blend_cm=r(depth.cm(c.blend, ratio)),
                ens=e,
                ptype=ptype(c.value or 0.0, lq.value or 0.0),
                slr=ratio,
                quality=label,
                tmin_c=r(min(temps)) if temps else None,
                tmax_c=r(max(temps)) if temps else None,
                snow_level_min_m=r(max(0.0, min(fls) - offset), 0) if fls else None,
                wind_max_kmh=r(max(winds), 0) if winds else None,
                gust_max_kmh=r(max(gusts), 0) if gusts else None,
                cloud_mean=r(sum(clouds) / len(clouds), 0) if clouds else None,
                pop_max=max(pops) if pops else None,
            )
        )

    members = ens.pooled(systems)
    windows = {
        name: _window(w, mid, periods, a, b, i, k, min_m, depth, members)
        for name, (a, b) in WINDOWS.items()
    }

    def hourly_depth(h: int) -> float | None:
        return depth.cm(w.hourly_sw.get(h), period_ratio_of.get(h))

    hours = list(shown)
    hourly = HourlyOut(
        t=[_iso(h, tz) for h in hours],
        snow_cm=[r(hourly_depth(h), 2) for h in hours],
        swe_mm=[r(w.hourly_sw.get(h), 2) for h in hours],
        water_mm=[r(_sum2(w.hourly_sw.get(h), w.hourly_liq.get(h)), 2) for h in hours],
        rain_mm=[r(w.hourly_liq.get(h), 2) for h in hours],
        ptype=[ptype(w.hourly_sw.get(h) or 0.0, w.hourly_liq.get(h) or 0.0) for h in hours],
        temp_c=[r(w.temp[0].get(h)) for h in hours],
        temp_lo=[r(w.temp[1].get(h)) for h in hours],
        temp_hi=[r(w.temp[2].get(h)) for h in hours],
        fl_m=[r(w.fl[0].get(h), -1) for h in hours],
        fl_lo=[r(w.fl[1].get(h), -1) for h in hours],
        fl_hi=[r(w.fl[2].get(h), -1) for h in hours],
        snow_level_m=[
            None if (f := w.fl[0].get(h)) is None else r(max(0.0, f - offset), -1) for h in hours
        ],
        wind_kmh=[r(w.wind[0].get(h), 0) for h in hours],
        wind_hi=[r(w.wind[2].get(h), 0) for h in hours],
        gust_kmh=[r(w.gust.get(h), 0) for h in hours],
        wdir=[r(w.wdir.get(h), 0) for h in hours],
        cloud=[r(w.cloud.get(h), 0) for h in hours],
        cloud_low=[blend.get("cloud_cover_low").get(h) for h in hours],
        cloud_mid=[blend.get("cloud_cover_mid").get(h) for h in hours],
        cloud_high=[blend.get("cloud_cover_high").get(h) for h in hours],
        pop=[pop.get(h) for h in hours],
        visibility_m=[blend.get("visibility").get(h) for h in hours],
        is_day=[blend.get("is_day").get(h) for h in hours],
        wcode=[blend.get("weather_code").get(h) for h in hours],
        slr=[hourly_slr(w.temp[0].get(h), cfg.slr_bands) for h in hours],
    )

    first24 = hours[:24]
    temps24 = [v for h in first24 if (v := w.temp[0].get(h)) is not None]
    past_snow = depth.from_snowfall(blend.get("snowfall"), blend.get("temperature_2m"))
    past = _past(past_snow, now_h, 24)
    last24 = sum(past_snow.get(h) or 0.0 for h in past) if past else None
    stats = ElevationOut(
        temp_now_c=r(w.temp[0].get(now_h)),
        tmin24_c=r(min(temps24)) if temps24 else None,
        tmax24_c=r(max(temps24)) if temps24 else None,
        last24_cm=r(last24),
        next24_cm=r(sum(hourly_depth(h) or 0.0 for h in first24)),
        next5_cm=windows["next5"].snow_cm,
        d6_10_cm=windows["d6_10"].snow_cm,
    )
    return BandOut(
        band=band.band,
        label=band.label,
        elev_m=band.elev_m,
        periods=out_periods,
        windows=windows,
        hourly=hourly,
        stats=stats,
    )


def _sum2(a: float | None, b: float | None) -> float | None:
    return None if a is None and b is None else (a or 0.0) + (b or 0.0)


def _window(
    w: _BandWork,
    mid: _BandWork,
    periods: Sequence[Period],
    a: int,
    b: int,
    i: int,
    k: float,
    min_m: int,
    depth: Depth,
    members: Sequence[Hourly],
) -> WindowOut:
    ps = list(periods[a:b])
    if not ps:
        return WindowOut(
            snow_cm=None, snow_cm_raw=None, snow_cm_slr=None, ens=None, ens_raw=None, ens_slr=None
        )
    raw, slr, headline = _window_totals(w, a, b, k, depth)
    # Ensemble members are fetched at mid, so their totals use mid's snow ratios.
    ratios = [rt for rt, _ in mid.ratios[a:b]]
    raw_m = sorted(_member_depths(members, ps, [k] * len(ps)))
    slr_m = sorted(_member_depths(members, ps, [rt / 10 if rt else k for rt in ratios]))
    head_m = slr_m if depth.slr else raw_m
    if i == 1:
        return WindowOut(
            snow_cm=r(headline),
            snow_cm_raw=r(raw),
            snow_cm_slr=r(slr),
            ens=_ens_stats(head_m, 1.0, min_m),
            ens_raw=_ens_stats(raw_m, 1.0, min_m),
            ens_slr=_ens_stats(slr_m, 1.0, min_m),
            members_cm=[round(v, 1) for v in head_m],
            members_cm_raw=[round(v, 1) for v in raw_m],
        )
    # Other bands scale the mid members by how this band's total compares with mid's,
    # per depth method (`scale` is the headline's, for the browser's exceedance curve).
    mid_tot = _window_totals(mid, a, b, k, depth)

    def ratio(band: float | None, at_mid: float | None) -> float | None:
        return band / at_mid if band is not None and at_mid else None

    def scaled(values: Sequence[float], s: float | None) -> EnsStats | None:
        return None if s is None else _ens_stats(values, s, min_m, estimated=True)

    scale = ratio(headline, mid_tot[2])
    return WindowOut(
        snow_cm=r(headline),
        snow_cm_raw=r(raw),
        snow_cm_slr=r(slr),
        ens=scaled(head_m, scale),
        ens_raw=scaled(raw_m, ratio(raw, mid_tot[0])),
        ens_slr=scaled(slr_m, ratio(slr, mid_tot[1])),
        scale=None if scale is None else round(scale, 3),
    )


def _window_totals(
    w: _BandWork, a: int, b: int, k: float, depth: Depth
) -> tuple[float | None, float | None, float | None]:
    """A window's depth three ways: model snowfall (7:1), temperature-based, headline.
    The headline is the sum of the periods' headline depths, as the bars show them."""
    sw = [c.value for c in w.sw[a:b]]
    ratios = [rt for rt, _ in w.ratios[a:b]]
    if all(v is None for v in sw):
        return None, None, None
    pairs = list(zip(sw, ratios, strict=True))
    raw = sum(v or 0.0 for v in sw) * k
    slr = sum(_depth(v, rt, k) or 0.0 for v, rt in pairs)
    return raw, slr, sum(depth.cm(v, rt) or 0.0 for v, rt in pairs)


def _daily(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    systems: Mapping[str, Sequence[Hourly]],
    mid: _BandWork,
    periods: Sequence[Period],
    depth: Depth,
) -> tuple[list[DailyRow], list[DailyRecord]]:
    """15–16 days of per-model totals and ensemble running totals at mid.

    The rows (Model agreement) are in headline depth; the records keep each source's
    own depth for the scorecard: models and the ensemble at 7:1, the consensus both ways.
    """
    k = cfg.snowfall_cm_per_mm
    models = cfg.models_for(loc.country)
    md = split_models(inputs.multi[1], models)
    sw = {m: _swe(v["snowfall"], k) for m, v in md.items() if "snowfall" in v}
    water = {m: v["precipitation"] for m, v in md.items() if "precipitation" in v}
    hours = sorted({h for s in sw.values() for h in s if h >= now_h})
    by_day: dict[str, list[int]] = defaultdict(list)
    for h in hours:
        by_day[local(h, tz).date().isoformat()].append(h)
    days = sorted(by_day)[:16]
    day_hours = [by_day[d] for d in days]
    offset = cfg.snow_level_offset_m

    # Headline cm per mm for every hour: its period's, or past the last period its own
    # temperature's. Ensemble members are converted hour by hour before any totals.
    in_period = _period_factors(periods, mid.ratios, depth)

    def factor(h: int) -> float:
        f = in_period.get(h)
        return f if f is not None else depth.hour_factor(mid.temp[0].get(h))

    def in_depth(series: Hourly) -> Hourly:
        return {h: None if v is None else v * factor(h) for h, v in series.items()}

    depth_systems = {s: [in_depth(m) for m in ms] for s, ms in systems.items()}
    running = ens.running_totals(depth_systems, day_hours, min_members=cfg.ensemble_min_members)
    members = ens.pooled(systems)
    depth_members = ens.pooled(depth_systems)

    # The consensus per calendar day, from its hourly series: the same midnight-to-
    # midnight hours as the models above and the station's observations, so the
    # scorecard compares like with like. Each hour takes its period's snow ratio.
    ratio_at = {
        h: ratio for p, (ratio, _) in zip(periods, mid.ratios, strict=True) for h in p.hours
    }

    rows: list[DailyRow] = []
    records: list[DailyRecord] = []
    cum: dict[str, float | None] = dict.fromkeys(sw, 0.0)
    for d, hs, run in zip(days, day_hours, running, strict=True):
        day_models: dict[str, float | None] = {}
        for m, series in sw.items():
            v = total(series, hs)
            d_cm = None if v is None else sum((series[h] or 0.0) * factor(h) for h in hs)
            day_models[m] = d_cm
            prev = cum[m]
            cum[m] = None if d_cm is None or prev is None else prev + d_cm
            if v is not None:
                wv = total(water.get(m, {}), hs)
                records.append(DailyRecord(d, m, r(v * k), r(wv)))
        fls = [v for h in hs if (v := mid.fl[0].get(h)) is not None]
        day_ens = ens.stats(ens.member_totals(members, hs), cfg.ensemble_min_members)
        day_ens_depth = ens.stats(ens.member_totals(depth_members, hs), cfg.ensemble_min_members)
        rows.append(
            DailyRow(
                date=d,
                hours=len(hs),
                models={m: r(v) for m, v in day_models.items()},
                models_cum={m: r(v) for m, v in cum.items()},
                ens_cum={s: _daily_ens(st, 1.0) for s, st in run.systems.items()},
                pooled_cum=_daily_ens(run.pooled, 1.0),
                pooled_tail=run.tail,
                ens_day=_daily_ens(day_ens_depth, 1.0),
                snow_level_min_m=r(max(0.0, min(fls) - offset), 0) if fls else None,
            )
        )
        if day_ens is not None:
            for name, val in (
                ("ens_p10", day_ens.p10),
                ("ens_p50", day_ens.p50),
                ("ens_p90", day_ens.p90),
            ):
                records.append(DailyRecord(d, name, r(None if val is None else val * k), None))
        cons = [mid.hourly_sw.get(h) for h in hs]
        if hs and all(v is not None for v in cons) and all(h in ratio_at for h in hs):
            swe = sum(v or 0.0 for v in cons)
            liq = sum(mid.hourly_liq.get(h) or 0.0 for h in hs)
            records.append(DailyRecord(d, "cons", r(swe * k), r(swe + liq)))
            # The same snow with the temperature-based snow-to-liquid ratio, so the
            # scorecard can compare the two depth methods.
            slr = sum(_depth(mid.hourly_sw[h], ratio_at[h], k) or 0.0 for h in hs)
            records.append(DailyRecord(d, "cons_slr", r(slr), r(swe + liq)))
    return rows, records


def _sun(blend_mid: PointData, tz: ZoneInfo) -> list[SunDay]:
    rise = blend_mid.daily.get("sunrise", {})
    sets = blend_mid.daily.get("sunset", {})
    light = blend_mid.daily.get("daylight_duration", {})
    out = []
    for key in sorted(rise, key=lambda x: int(x) if x.isdigit() else x):
        day = local(int(key), tz).date().isoformat() if key.isdigit() else key[:10]
        sr, ss = rise.get(key), sets.get(key)
        out.append(
            SunDay(
                date=day,
                sunrise=_iso(int(sr), tz) if isinstance(sr, int | float) else sr,
                sunset=_iso(int(ss), tz) if isinstance(ss, int | float) else ss,
                daylight_s=light.get(key),
            )
        )
    return out
