"""Turn one location's upstream responses into its snapshot document.

Pure: no I/O. The pipeline fetches (or loads cached / fixture) responses into
`ForecastInputs`, and this module does all the analysis.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
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
from snowwatch.analysis.slr import hourly_slr, period_ratio, ptype
from snowwatch.config import ForecastConfig
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
        )
        for i in range(3)
    ]

    daily, records = _daily(loc, inputs, cfg, tz, now_h, systems, work[1], periods)
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
        loc, inputs, cfg, tz, now_h, all_hours, periods, work, ridge_kmh, ridge_dir
    )
    days = _days(loc, inputs, cfg, tz, now_h, periods, work, bands_out)
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
    # Chance that 48 h (4 periods) bring a storm's worth of snow, from the members.
    chances: list[float | None] = []
    for j in range(max(0, min(10, len(periods)) - 3)):
        hours = [h for p in periods[j : j + 4] for h in p.hours]
        totals = ens.member_totals(members, hours)
        chances.append(
            sum(1 for t in totals if t * k >= cfg.flags.storm_cm) / len(totals)
            if len(totals) >= cfg.ensemble_min_members
            else None
        )
    snap.flags = compute_flags(snap, cfg.flags, chances)
    return snap, records


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
) -> BackcountryOut:
    """Facts for touring (section 4.6 of the plan). No safety judgement."""
    k = cfg.snowfall_cm_per_mm
    bcfg = cfg.backcountry
    top, mid = work[2], work[1]
    blend_top = inputs.blend[2]
    past_snow = blend_top.get("snowfall")
    past72 = _past(past_snow, now_h, 72)
    next48 = list(all_hours[:48])
    # Ridge wind where the free-air data has it, the summit's own wind otherwise.
    speed = _first(ridge_kmh, _first(top.wind[0], blend_top.get("wind_speed_10m")))
    direction = _first(ridge_dir, _first(top.wdir, blend_top.get("wind_direction_10m")))
    future_snow = {h: None if v is None else v * k for h, v in top.hourly_sw.items()}

    roses = []
    for name, hours, snow in (("past72", past72, past_snow), ("next48", next48, future_snow)):
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
    mid_past = inputs.blend[1].get("snowfall")
    recent = sum(mid_past.get(h) or 0.0 for h in _past(mid_past, now_h, 72))
    depth = inputs.snotel.depth_cm if inputs.snotel else None
    on_snow = (depth or 0) > 0 or recent >= 1.0
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
    return BackcountryOut(rose=roses, warming=warming, refreeze=refreeze, sky=sky, storm=storm)


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
) -> list[DayOut]:
    """One row per day period: the Plan-a-day facts, and the rating for resorts."""
    scfg = cfg.skiday
    mid, top = work[1], work[2]
    mid_periods = {p.key: p for p in bands_out[1].periods}
    top_periods = {p.key: p for p in bands_out[2].periods}
    blend_mid = inputs.blend[1]
    past_snow = blend_mid.get("snowfall")
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
            # high-res model's snowfall from the evening before until now.
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
    if swe is None:
        return None
    return swe * ratio / 10 if ratio else swe * k


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
) -> BandOut:
    band = loc.bands[i]
    k = cfg.snowfall_cm_per_mm
    min_m = cfg.ensemble_min_members
    offset = cfg.snow_level_offset_m
    headline_slr = cfg.depth_method == "slr"
    pop = blend.get("precipitation_probability")

    period_ratio_of: dict[int, float | None] = {}
    out_periods: list[PeriodOut] = []
    for j, p in enumerate(periods):
        c, lq = w.sw[j], w.liq[j]
        ratio, label = w.ratios[j]
        for h in p.hours:
            period_ratio_of[h] = ratio
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
            e = _ens_stats(period_members[j], k, min_m)
        else:
            mid_c = mid.sw[j].value
            e = None
            if mid_c and c.value is not None:
                e = _ens_stats(period_members[j], k * c.value / mid_c, min_m, estimated=True)
        out_periods.append(
            PeriodOut(
                key=p.key,
                date=p.date.isoformat(),
                kind=p.kind,
                label=p.label,
                start=_iso(p.hours[0], tz),
                hours=len(p.hours),
                snow_cm=r(slr if headline_slr else raw),
                snow_cm_raw=r(raw),
                snow_cm_slr=r(slr),
                swe_mm=r(c.value),
                water_mm=r(None if c.value is None else c.value + (lq.value or 0.0)),
                rain_mm=r(lq.value),
                basis=c.basis,
                nmodels=c.nmodels,
                models={m: r(None if v is None else v * k) for m, v in c.models.items()},
                blend_cm=r(None if c.blend is None else c.blend * k),
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
        name: _window(w, mid, periods, a, b, i, k, min_m, headline_slr, members)
        for name, (a, b) in WINDOWS.items()
    }

    def hourly_depth(h: int) -> float | None:
        sw = w.hourly_sw.get(h)
        return _depth(sw, period_ratio_of.get(h) if headline_slr else None, k)

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
    past = [h for h in blend.get("snowfall") if now_h - 24 * 3600 <= h < now_h]
    last24 = sum(blend.get("snowfall").get(h) or 0.0 for h in past) if past else None
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
    headline_slr: bool,
    members: Sequence[Hourly],
) -> WindowOut:
    ps = list(periods[a:b])
    if not ps:
        return WindowOut(snow_cm=None, snow_cm_raw=None, snow_cm_slr=None, ens=None, ens_slr=None)
    sw = [c.value for c in w.sw[a:b]]
    ratios = [rt for rt, _ in w.ratios[a:b]]
    have = [v for v in sw if v is not None]
    raw = sum(have) * k if have else None
    slr = sum(_depth(v, rt, k) or 0.0 for v, rt in zip(sw, ratios, strict=True)) if have else None
    headline = slr if headline_slr else raw

    # Ensemble members are fetched at mid. Their per-period totals use this
    # band's snow ratios so the ratio-adjusted spread matches the consensus.
    covering = [m for m in members if all(total(m, p.hours) is not None for p in ps)]
    per_member = [[total(m, p.hours) or 0.0 for p in ps] for m in covering]
    raw_m = sorted(sum(v) * k for v in per_member)
    slr_m = sorted(
        sum(_depth(v, rt, k) or 0.0 for v, rt in zip(vals, ratios, strict=True))
        for vals in per_member
    )
    if i == 1:
        return WindowOut(
            snow_cm=r(headline),
            snow_cm_raw=r(raw),
            snow_cm_slr=r(slr),
            ens=_ens_stats(raw_m, 1.0, min_m),
            ens_slr=_ens_stats(slr_m, 1.0, min_m),
            members_cm=[round(v, 1) for v in raw_m],
            members_cm_slr=[round(v, 1) for v in slr_m],
        )
    mid_have = [c.value for c in mid.sw[a:b] if c.value is not None]
    mid_raw = sum(mid_have) * k
    scale = raw / mid_raw if raw is not None and mid_raw > 0 else None
    return WindowOut(
        snow_cm=r(headline),
        snow_cm_raw=r(raw),
        snow_cm_slr=r(slr),
        ens=None if scale is None else _ens_stats(raw_m, scale, min_m, estimated=True),
        ens_slr=None if scale is None else _ens_stats(slr_m, scale, min_m, estimated=True),
        scale=None if scale is None else round(scale, 3),
    )


def _daily(
    loc: Location,
    inputs: ForecastInputs,
    cfg: ForecastConfig,
    tz: ZoneInfo,
    now_h: int,
    systems: Mapping[str, Sequence[Hourly]],
    mid: _BandWork,
    periods: Sequence[Period],
) -> tuple[list[DailyRow], list[DailyRecord]]:
    """15–16 days of per-model totals and ensemble running totals at mid."""
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
    running = ens.running_totals(systems, day_hours, min_members=cfg.ensemble_min_members)
    members = ens.pooled(systems)
    offset = cfg.snow_level_offset_m

    # Consensus per date from the periods (day + night of that date).
    cons_by_date: dict[str, list[tuple[float | None, float | None, float | None]]] = defaultdict(
        list
    )
    for p, c, lq, (ratio, _) in zip(periods, mid.sw, mid.liq, mid.ratios, strict=True):
        cons_by_date[p.date.isoformat()].append((c.value, lq.value, ratio))

    rows: list[DailyRow] = []
    records: list[DailyRecord] = []
    cum: dict[str, float | None] = dict.fromkeys(sw, 0.0)
    for d, hs, run in zip(days, day_hours, running, strict=True):
        day_models: dict[str, float | None] = {}
        for m, series in sw.items():
            v = total(series, hs)
            day_models[m] = None if v is None else v * k
            prev = cum[m]
            cum[m] = None if v is None or prev is None else prev + v * k
            if v is not None:
                wv = total(water.get(m, {}), hs)
                records.append(DailyRecord(d, m, r(v * k), r(wv)))
        fls = [v for h in hs if (v := mid.fl[0].get(h)) is not None]
        day_ens = ens.stats(ens.member_totals(members, hs), cfg.ensemble_min_members)
        rows.append(
            DailyRow(
                date=d,
                hours=len(hs),
                models={m: r(v) for m, v in day_models.items()},
                models_cum={m: r(v) for m, v in cum.items()},
                ens_cum={s: _daily_ens(st, k) for s, st in run.systems.items()},
                pooled_cum=_daily_ens(run.pooled, k),
                pooled_tail=run.tail,
                ens_day=_daily_ens(day_ens, k),
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
        parts = cons_by_date.get(d)
        if parts and all(sv is not None for sv, _, _ in parts):
            swe = sum(sv or 0.0 for sv, _, _ in parts)
            liq = sum(lv or 0.0 for _, lv, _ in parts)
            records.append(DailyRecord(d, "cons", r(swe * k), r(swe + liq)))
            # The same snow with the temperature-based snow-to-liquid ratio, so the
            # scorecard can compare the two depth methods.
            slr = sum(_depth(sv, rt, k) or 0.0 for sv, _, rt in parts)
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
