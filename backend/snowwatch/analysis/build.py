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
from snowwatch.analysis.clouds import cloud_layers
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
    median,
    r,
    split_models,
    total,
)
from snowwatch.analysis.skiday import DayFacts, rate
from snowwatch.analysis.slr import (
    SNOWING_SWE_MM,
    WET_MM,
    column_period_ratio,
    hourly_slr,
    period_ratio,
    ptype,
    ratio_for,
)
from snowwatch.analysis.snowlevel import (
    PhysicsConfig,
    levels_at,
    model_flag_kind,
    precip_type,
    profile_kind,
    snow_fraction,
    vote,
    warm_layer,
    wet_bulb_c,
    wet_bulb_zero_m,
)
from snowwatch.analysis.solar import ASPECTS, daily_kwh, slope_series
from snowwatch.config import ForecastConfig, SlrBand
from snowwatch.doc import (
    Alert,
    BackcountryOut,
    BandOut,
    CloudsOut,
    CornDay,
    CornWindow,
    DailyEns,
    DailyRow,
    DayOut,
    ElevationOut,
    EnsStats,
    HourlyOut,
    LocationMeta,
    OutlookDay,
    OutlookLevels,
    OutlookSteps,
    PeriodOut,
    Reason,
    RefreezeNight,
    RidgeOut,
    RoseOut,
    SkyDay,
    Snapshot,
    Snotel,
    SnowpackOut,
    StormOut,
    SunDay,
    WarmingOut,
    WindowOut,
)
from snowwatch.models import Location
from snowwatch.sources.openmeteo import CLOUD_DAYS, CLOUD_LEVELS

WINDOWS = {"next5": (0, 10), "d6_10": (10, 20), "d11_16": (20, 32)}
# Where the forecast becomes less certain, in hours from now (milestone 4B): the chart
# and the map mark both (Snapshot.less_certain_from). Days 11–16 also get no ski-day
# rating: it reads lift-hour gusts, low cloud and visibility, meaningless that far out.
LESS_CERTAIN_H = (120, 240)
RATED_DAYS = 10


@dataclass
class ForecastInputs:
    blend: list[PointData]  # base, mid, summit
    multi: list[PointData]  # base, mid, summit
    upper: PointData | None = None
    clouds: PointData | None = None  # one model's cloud cover at each pressure level
    ensembles: dict[str, PointData] = field(default_factory=dict)  # at mid
    # Each system at base, mid and summit, when it was asked for all three (milestone 4).
    ensemble_bands: dict[str, list[PointData]] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    snotel: Snotel | None = None
    warnings: list[str] = field(default_factory=list)
    station: PointData | None = None  # each model at the snow station (scorecard only)


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
        # "column" uses period ratios like "slr"; the builder hands it the column ones.
        return cls(cfg.snowfall_cm_per_mm, cfg.depth_method != "raw", cfg.slr_bands)

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
    """One model's freezing level: its own where it has one, else found from its pressure
    levels with `model_vars`' 2 m temperature at `elev_m` as the bottom of the column."""
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
    ratios: list[tuple[float | None, str | None]]  # the headline's (depth_method)
    model_sums: list[dict[str, float | None]]
    # Milestone 3. The temperature-based ratios (the same as `ratios` unless the headline
    # is the column ratio), the column ratios, the wet-bulb line, and freezing rain or
    # sleet per hour.
    temp_ratios: list[tuple[float | None, str | None]] = field(default_factory=list)
    col_ratios: list[float | None] = field(default_factory=list)
    wb: Hourly = field(default_factory=dict)
    frz: dict[int, str | None] = field(default_factory=dict)
    # The mid band's snow water with every model's precipitation split into snow and rain
    # by its wet-bulb at the band, scored as `cons_wb`; and with the models' own split,
    # scored as `cons_model` while the headline uses the wet-bulb split
    # (`physics.snow_split`). Empty without wet-bulb data.
    wb_sw: Hourly = field(default_factory=dict)
    model_sw: Hourly = field(default_factory=dict)


CLOUD_PAST_H = 3  # the map's satellite pictures reach this far back


def _clouds(
    loc: Location, inputs: ForecastInputs, cfg: ForecastConfig, now_h: int
) -> CloudsOut | None:
    """The cloud layers above the location from 3 h ago to 10 days ahead, for the map."""
    model = cfg.cloud_model(loc.country)
    if inputs.clouds is None or not model:
        return None
    return cloud_layers(
        inputs.clouds,
        model,
        CLOUD_LEVELS,
        start=now_h - CLOUD_PAST_H * 3600,
        hours=CLOUD_PAST_H + CLOUD_DAYS * 24,
    )


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

    # The hours: as far as the blend or any global model reaches (milestone 4B: 16 days),
    # so a shorter blend (an older cache, a lean fallback) doesn't cut the forecast.
    temps_mid = inputs.blend[1].get("temperature_2m")
    reach = {h for h, v in temps_mid.items() if v is not None}
    for series in split_models(inputs.multi[1], cfg.models.global_).values():
        reach.update(h for h, v in series.get("temperature_2m", {}).items() if v is not None)
    all_hours = sorted(h for h in reach if h >= now_h)
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
    # Bands with ensembles of their own (every system asked at all three bands): their
    # members, unscaled. Other bands scale mid's (`_scaled_ens_mean`, as before).
    own_pools = _band_pools(inputs, systems, k)
    own_members = {
        i: [ens.member_totals(pool, p.hours) for p in periods] for i, pool in own_pools.items()
    }

    # The freezing level is one height for the whole location, found once at the lowest
    # band and shared by every band. Found at each band, it depended on the band: a model
    # without a freezing level of its own (ECMWF, GEM) started its column at the band's
    # 2 m temperature, and at a band above the 0 °C level that ignored the free air below
    # and extrapolated down from the band, so the summit read hundreds of metres lower
    # than the base for the same model and hour.
    low = min(range(len(loc.bands)), key=lambda j: loc.bands[j].elev_m)
    low_md = split_models(inputs.multi[low], [*global_models, *short_models])
    low_m = loc.bands[low].elev_m
    fl_g = {
        m: f
        for m in global_models
        if m in low_md and (f := _freezing(low_md[m], upper.get(m), low_m))
    }
    fl_s = {
        m: f
        for m in short_models
        if m in low_md and (f := _freezing(low_md[m], upper.get(m), low_m))
    }
    fl = consensus_line(
        all_hours, fl_g, fl_s, short_until, inputs.blend[low].get("freezing_level_height")
    )
    # The snow level: from each model's wet-bulb profile where it has humidity aloft
    # (milestone 3), the freezing level less the fixed offset otherwise. Shared by every
    # band, like the freezing level.
    snow_level, sl_how = _snow_level(all_hours, low_md, upper, low_m, fl[0], cfg)

    phys = cfg.physics
    work: dict[int, _BandWork] = {}
    for i in (1, 0, 2):  # mid first: the other bands scale from it
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
        # Each model's precipitation split into snow and rain by its own wet-bulb at this
        # band: some models split at their grid's elevation, so a base below the grid got
        # the summit's share of snow (ECMWF at Crystal, 27 Nov 2026).
        band_m = loc.bands[i].elev_m
        wb_g, wb_liq_g = _wb_split_group(g, k, phys, upper, band_m)
        wb_s, wb_liq_s = _wb_split_group(s, k, phys, upper, band_m)
        blend_series = {
            "precipitation": blend.get("precipitation"),
            "wet_bulb_temperature_2m": blend.get("wet_bulb_temperature_2m"),
            "temperature_2m": blend.get("temperature_2m"),
            "relative_humidity_2m": blend.get("relative_humidity_2m"),
            "snowfall": blend.get("snowfall"),
            "rain": blend_liq,
        }
        wb_blend = _wb_split(blend_series, k, phys)
        resplit = any(m in wb_g or m in wb_s for m in md) or wb_blend is not None
        wb_g, wb_liq_g = {**sw_g, **wb_g}, {**liq_g, **wb_liq_g}
        wb_s, wb_liq_s = {**sw_s, **wb_s}, {**liq_s, **wb_liq_s}
        wb_blend_sw, wb_blend_liq = wb_blend or (blend_sw, blend_liq)
        own_g, own_s, own_blend_sw = sw_g, sw_s, blend_sw
        if resplit and phys.snow_split == "wetbulb":
            sw_g, liq_g, sw_s, liq_s = wb_g, wb_liq_g, wb_s, wb_liq_s
            blend_sw, blend_liq = wb_blend_sw, wb_blend_liq

        temp = consensus_line(
            all_hours,
            _var(g, "temperature_2m"),
            _var(s, "temperature_2m"),
            short_until,
            blend.get("temperature_2m"),
        )
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
        wb = consensus_line(
            all_hours,
            _var(g, "wet_bulb_temperature_2m"),
            _var(s, "wet_bulb_temperature_2m"),
            short_until,
            blend.get("wet_bulb_temperature_2m"),
        )[0]
        col_t = _column_max(all_hours, md, upper, loc.bands[i].elev_m)
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
        col_ratios: list[float | None] = []
        sums: list[dict[str, float | None]] = []
        for j, p in enumerate(periods):
            early = j < cfg.blend_periods
            if i == 1:
                e_mean = mid_ens_mean[j]
            elif i in own_members:
                e_mean = mean(own_members[i][j]) if own_members[i][j] else None
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
            swe_p = [hourly_sw.get(h) or 0.0 for h in p.hours]
            ratio, label = period_ratio(swe_p, [temp[0].get(h) for h in p.hours], cfg.slr_bands)
            # Wet snow: melting on the way down (the wet-bulb at or above
            # `wet_snow_wb_c` while it snows) makes it heavy and wet whatever its ratio.
            wb_snowing = median(
                wb.get(h) for h, sw in zip(p.hours, swe_p, strict=True) if sw >= SNOWING_SWE_MM
            )
            if ratio is not None and wb_snowing is not None and wb_snowing >= phys.wet_snow_wb_c:
                label = cfg.slr_bands[0].label
            ratios.append((ratio, label))
            col_ratios.append(
                column_period_ratio(
                    swe_p,
                    [col_t.get(h) for h in p.hours],
                    [wind[0].get(h) for h in p.hours],
                    cfg.slr_bands,
                    wind_start=cfg.physics.col_wind_start_kmh,
                    wind_full=cfg.physics.col_wind_full_kmh,
                    cut=cfg.physics.col_wind_cut,
                )
            )
        head = ratios
        if cfg.depth_method == "column":
            head = [
                (col, label) if col is not None else (ratio, label)
                for (ratio, label), col in zip(ratios, col_ratios, strict=True)
            ]
        frz = _freezing_rain(all_hours, md, upper, loc.bands[i].elev_m, hourly_sw, hourly_liq, cfg)
        wb_sw: Hourly = {}
        model_sw: Hourly = {}
        if i == 1 and resplit:
            # Both splits are scored whichever leads: the other one is made as the band
            # loop makes the headline.
            if phys.snow_split == "wetbulb":
                wb_sw = hourly_sw
                model_sw = _consensus_hourly(
                    periods, own_g, own_s, own_blend_sw, water_all, short_until, mid_ens_mean, cfg
                )
            else:
                wb_sw = _consensus_hourly(
                    periods, wb_g, wb_s, wb_blend_sw, water_all, short_until, mid_ens_mean, cfg
                )
        work[i] = _BandWork(
            sw_c,
            liq_c,
            hourly_sw,
            hourly_liq,
            temp,
            fl,
            wind,
            gust,
            cloud,
            wdir,
            head,
            sums,
            temp_ratios=ratios,
            col_ratios=col_ratios,
            wb=wb,
            frz=frz,
            wb_sw=wb_sw,
            model_sw=model_sw,
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
            snow_level,
            sl_how,
            own_members.get(i),
            own_pools.get(i),
        )
        for i in range(3)
    ]

    daily, records = _daily(
        loc, inputs, cfg, tz, now_h, systems, work[1], periods, depth, snow_level
    )
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
        loc,
        inputs,
        cfg,
        tz,
        now_h,
        all_hours,
        periods,
        work,
        ridge_kmh,
        ridge_dir,
        depth,
        snow_level,
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
        less_certain_from=[_iso(now_h + h * 3600, tz) for h in LESS_CERTAIN_H],
        bands=bands_out,
        daily=daily,
        sun=_sun(inputs.blend[1], tz),
        alerts=inputs.alerts,
        snotel=inputs.snotel,
        ridge=ridge,
        backcountry=backcountry,
        days=days,
        warnings=warnings,
        clouds=_clouds(loc, inputs, cfg, now_h),
        snowpack=_snowpack(loc, inputs, cfg, tz, now_h),
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


def _wb_split(
    series: Mapping[str, Hourly],
    k: float,
    phys: PhysicsConfig,
    upper: Mapping[str, Hourly] | None = None,
    elev_m: float | None = None,
) -> tuple[Hourly, Hourly] | None:
    """(snow water, liquid) per hour: the precipitation split by the wet-bulb at the band
    (snow at or below `wb_snow_max_c`, rain from `wb_rain_min_c`, a linear share
    between). An hour without a wet-bulb keeps the model's own split, and so does the
    snow share of an hour with a warm layer aloft (`upper`, at least `sleet_warm_c`
    above the band): snow melted on the way down isn't snow at the band whatever its
    wet-bulb. None when the series has no wet-bulb at all (the public API's lean data).

    Checked against last winter's SNOTEL snow-water gains at Crystal, Snoqualmie and
    Rainy Pass (`scripts/backtest_split.py`, docs/OPEN-METEO-PLAN.md milestone 3c)."""
    wb = dict(series.get("wet_bulb_temperature_2m") or {})
    t2, rh = series.get("temperature_2m", {}), series.get("relative_humidity_2m", {})
    for h in t2:
        if wb.get(h) is None:
            wb[h] = wet_bulb_c(t2.get(h), rh.get(h))
    precip = series.get("precipitation", {})
    if not precip or not any(v is not None for v in wb.values()):
        return None
    own_sw, own_liq = series.get("snowfall", {}), series.get("rain", {})
    snow: Hourly = {}
    liq: Hourly = {}
    for h, p in precip.items():
        f = snow_fraction(wb.get(h), phys)
        if p is None or f is None:
            sv = own_sw.get(h)
            snow[h] = None if sv is None else sv / k
            liq[h] = own_liq.get(h)
            continue
        sw = p * f
        if f > 0 and upper and elev_m is not None:
            levels = levels_at(upper, h, LEVELS)
            warm = warm_layer(elev_m, t2.get(h), levels) if levels else None
            if warm is not None and warm[0] >= phys.sleet_warm_c:
                own = own_sw.get(h)
                sw = min(sw, own / k if own is not None else sw)
        snow[h], liq[h] = sw, p - sw
    return snow, liq


def _wb_split_group(
    group: Mapping[str, Mapping[str, Hourly]],
    k: float,
    phys: PhysicsConfig,
    upper: Mapping[str, Mapping[str, Hourly]] | None = None,
    elev_m: float | None = None,
) -> tuple[dict[str, Hourly], dict[str, Hourly]]:
    """`_wb_split` for each model that has a wet-bulb: (snow water, liquid) by model."""
    sw: dict[str, Hourly] = {}
    liq: dict[str, Hourly] = {}
    for m, v in group.items():
        got = _wb_split(v, k, phys, (upper or {}).get(m), elev_m)
        if got is not None:
            sw[m], liq[m] = got
    return sw, liq


def _consensus_hourly(
    periods: Sequence[Period],
    sw_g: Mapping[str, Hourly],
    sw_s: Mapping[str, Hourly],
    blend_sw: Hourly,
    water_all: Sequence[Hourly],
    short_until: int,
    ens_means: Sequence[float | None],
    cfg: ForecastConfig,
) -> Hourly:
    """The consensus snow water hour by hour, made as the band loop makes it, for an
    alternative set of model series (the wet-bulb split, scored as `cons_wb`)."""
    out: Hourly = {}
    for j, p in enumerate(periods):
        c = period_consensus(
            p.hours,
            sw_g,
            short_range=sw_s,
            blend=blend_sw,
            early=j < cfg.blend_periods,
            ens_mean=ens_means[j],
            min_models=cfg.consensus_min_models,
        )
        support = support_counts(p.hours, water_all)
        shape = {h: shape_value(h, sw_g, sw_s, short_until, blend_sw) for h in p.hours}
        out.update(scale_to_total(p.hours, shape, c.value, support))
    return out


def _snow_level(
    hours: Sequence[int],
    md: Mapping[str, Mapping[str, Hourly]],
    upper: Mapping[str, Mapping[str, Hourly]],
    surface_m: float,
    fl: Hourly,
    cfg: ForecastConfig,
) -> tuple[Hourly, dict[int, str | None]]:
    """The snow level per hour and how it was found ("wb" or "fl"). Each model with
    humidity at its pressure levels gives its wet-bulb 0 °C height less the melting
    distance, and NBM its own snow level; the median of those, else the freezing level
    less `snow_level_offset_m`."""
    wb_off = cfg.physics.snow_level_wb_offset_m
    level: Hourly = {}
    how: dict[int, str | None] = {}
    for h in hours:
        vals: list[float] = []
        for m, v in md.items():
            u = upper.get(m)
            if u:
                wb_s = v.get("wet_bulb_temperature_2m", {}).get(h)
                if wb_s is None:
                    wb_s = wet_bulb_c(
                        v.get("temperature_2m", {}).get(h), v.get("relative_humidity_2m", {}).get(h)
                    )
                z = wet_bulb_zero_m(surface_m, wb_s, levels_at(u, h, LEVELS))
                if z is not None:
                    vals.append(max(0.0, z - wb_off))
            own = v.get("snowfall_height", {}).get(h)
            if own is not None:
                vals.append(max(0.0, own))
        if vals:
            level[h], how[h] = median(vals), "wb"
        elif (f := fl.get(h)) is not None:
            level[h], how[h] = max(0.0, f - cfg.snow_level_offset_m), "fl"
        else:
            level[h], how[h] = None, None
    return level, how


def _column_max(
    hours: Sequence[int],
    md: Mapping[str, Mapping[str, Hourly]],
    upper: Mapping[str, Mapping[str, Hourly]],
    elev_m: float,
) -> Hourly:
    """The warmest temperature between the band (its 2 m temperature) and 500 hPa, the
    median over the models with pressure levels above the band."""
    out: Hourly = {}
    for h in hours:
        vals = []
        for m, u in upper.items():
            t2 = md.get(m, {}).get("temperature_2m", {}).get(h)
            above = [t for z, t, _ in levels_at(u, h, LEVELS) if z > elev_m]
            if t2 is not None and above:
                vals.append(max(t2, *above))
        out[h] = median(vals)
    return out


def _freezing_rain(
    hours: Sequence[int],
    md: Mapping[str, Mapping[str, Hourly]],
    upper: Mapping[str, Mapping[str, Hourly]],
    elev_m: float,
    sw: Hourly,
    liq: Hourly,
    cfg: ForecastConfig,
) -> dict[int, str | None]:
    """Freezing rain or sleet in each wet hour at a band: each model votes from its
    profile (a warm layer aloft over sub-freezing air at the band) and its own flags."""
    out: dict[int, str | None] = {}
    phys = cfg.physics
    for h in hours:
        if (sw.get(h) or 0.0) + (liq.get(h) or 0.0) < WET_MM:
            continue
        kinds: list[str | None] = []
        for m, v in md.items():
            said = model_flag_kind(v, h, phys)
            u = upper.get(m)
            levels = levels_at(u, h, LEVELS) if u else []
            t2 = v.get("temperature_2m", {}).get(h)
            if said is None and levels and t2 is not None:
                said = profile_kind(elev_m, t2, levels, phys)
            if said is not None or levels:
                kinds.append(said)
        got = vote(kinds)
        if got:
            out[h] = got
    return out


def _snowpack(
    loc: Location, inputs: ForecastInputs, cfg: ForecastConfig, tz: ZoneInfo, now_h: int
) -> SnowpackOut | None:
    """The models' snow on the ground at mid: the blend at the start of each local day
    from 3 days back, and each model now. None without `snow_depth` (milestone 3)."""
    blend = inputs.blend[1].get("snow_depth")
    if not any(v is not None for v in blend.values()):
        return None
    md = split_models(inputs.multi[1], cfg.models_for(loc.country))
    models = {
        m: None if (d := v["snow_depth"].get(now_h)) is None else r(d * 100)
        for m, v in md.items()
        if "snow_depth" in v
    }
    starts = sorted(h for h in blend if local(h, tz).hour == 0)
    now = blend.get(now_h)
    return SnowpackOut(
        elev_m=loc.band("mid").elev_m,
        dates=[local(h, tz).date().isoformat() for h in starts],
        depth_cm=[None if (v := blend.get(h)) is None else r(v * 100) for h in starts],
        now_cm=None if now is None else r(now * 100),
        models=models,
    )


def _sun_on_slopes(blend: PointData, lat: float, lon: float) -> dict[str, Hourly]:
    """W/m² on 35° slopes facing N, E, S and W, hour by hour; empty without radiation."""
    direct, diffuse = blend.get("direct_radiation"), blend.get("diffuse_radiation")
    if not any(v is not None for v in direct.values()):
        return {}
    hours = sorted(set(direct) | set(diffuse))
    return {a: slope_series(hours, direct, diffuse, lat, lon, az) for a, az in ASPECTS.items()}


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
    snow_level: Hourly,
) -> BackcountryOut:
    """Facts for touring (see docs/ARCHITECTURE.md). No safety judgement."""
    bcfg = cfg.backcountry
    top_band, mid_band = loc.band("summit"), loc.band("mid")
    sun_top = _sun_on_slopes(inputs.blend[2], top_band.lat, top_band.lon)
    sun_mid = _sun_on_slopes(inputs.blend[1], mid_band.lat, mid_band.lon)
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
    # Without a station (every spot), the models' snow on the ground at mid says whether
    # there is snow for rain to fall on (milestone 3's snow depth).
    model_m = inputs.blend[1].get("snow_depth").get(now_h)
    model_snow = (
        on_ground is None and model_m is not None and model_m * 100 >= bcfg.model_snow_min_cm
    )
    on_snow = (on_ground or 0) > 0 or recent >= 1.0 or model_snow
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
            f = bc.refreeze(
                p.hours, w.temp[0], w.cloud, bcfg, inputs.blend[i].get("relative_humidity_2m")
            )
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
            rh_pct=blend_top.get("relative_humidity_2m"),
            temp_c=_first(top.temp[0], blend_top.get("temperature_2m")),
            cfg=bcfg,
        )
        sky.append(
            SkyDay(
                date=p.date.isoformat(),
                cloud_low=sk.cloud_low,
                cloud_mid=sk.cloud_mid,
                cloud_high=sk.cloud_high,
                vis_min_m=sk.vis_min_m,
                rime_h=sk.rime_h,
                fog_h=sk.fog_h,
            )
        )

    # Spring corn: the next three days after a refreeze at mid, when sunny aspects soften.
    corn: list[CornDay] = []
    if sun_mid:
        mid_temp = _first(mid.temp[0], inputs.blend[1].get("temperature_2m"))
        for p in [p for p in periods if p.kind == "day"][:3]:
            night = sorted(
                {
                    *_local_hours(p.date - timedelta(days=1), cfg.night_start_hour, 24, tz),
                    *_local_hours(p.date, 0, cfg.day_start_hour, tz),
                }
            )
            frozen = bc.refreeze(
                night, mid_temp, mid.cloud, bcfg, inputs.blend[1].get("relative_humidity_2m")
            )
            day_hours = _local_hours(p.date, 0, 24, tz)
            got = bc.corn_windows(day_hours, sun_mid, mid_temp, frozen.status, bcfg)
            if got:
                corn.append(
                    CornDay(
                        date=p.date.isoformat(),
                        refreeze=frozen.status,
                        windows=[
                            CornWindow(aspect=a, start=_iso(start, tz), end=_iso(end, tz))
                            for a, start, end in got
                        ],
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
        snow_level=snow_level,
        sun=sun_top,
    )
    steps = OutlookSteps(
        snow_cm=list(bcfg.outlook_snow_cm),
        storm_cm=list(bcfg.outlook_storm_cm),
        wind_kmh=list(bcfg.outlook_wind_kmh),
        rain_mm=list(bcfg.outlook_rain_mm),
        rise_c=list(bcfg.outlook_rise_c),
        thaw_h=list(bcfg.outlook_thaw_h),
        sun_kwh=list(bcfg.outlook_sun_kwh),
    )
    return BackcountryOut(
        rose=roses,
        warming=warming,
        refreeze=refreeze,
        sky=sky,
        storm=storm,
        outlook=outlook,
        outlook_steps=steps,
        corn=corn,
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
    snow_level: Hourly,
    sun: Mapping[str, Hourly],
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
    # The snow level where the forecast has one (wet-bulb or freezing level), the blend's
    # freezing level less the offset behind it.
    snow_level = _first(
        snow_level,
        {h: None if v is None else max(0.0, v - cfg.snow_level_offset_m) for h, v in fl.items()},
    )
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
        frozen = [
            bc.refreeze(
                night, temps[i], clouds[i], bcfg, inputs.blend[i].get("relative_humidity_2m")
            )
            for i in range(3)
        ]
        fallen = sum(mid_all.get(h) or 0.0 for h in mid_all if h <= hours[-1])
        sun_kwh = {a: daily_kwh(series, hours) for a, series in sun.items()} if sun else None
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
            sun_kwh=sun_kwh,
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
                rh_pct=blend_top.get("relative_humidity_2m"),
                temp_c=temps[2],
                cfg=bcfg,
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
                        rime_h=sk.rime_h,
                        fog_h=sk.fog_h,
                    ),
                    sun_kwh=sun_kwh,
                    levels=OutlookLevels(
                        snow=levels.snow,
                        wind=levels.wind,
                        rain=levels.rain,
                        warm=levels.warm,
                        sun=levels.sun,
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
        fog_h = bc.sky(
            lift,
            {"low": blend_mid.get("cloud_cover_low")},
            blend_mid.get("visibility"),
            dict.fromkeys(lift, 1.0),
            rh_pct=blend_mid.get("relative_humidity_2m"),
            temp_c=mid.temp[0],
            cfg=cfg.backcountry,
        ).fog_h
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
            fog_h=fog_h,
            tmax_c=max(temps) if temps else po.tmax_c,
        )
        rated = (p.date - local(now_h, tz).date()).days < RATED_DAYS
        rating = rate(facts, scfg) if loc.kind == "resort" and rated else None
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


def _band_pools(
    inputs: ForecastInputs, systems: Mapping[str, Sequence[Hourly]], k: float
) -> dict[int, list[Hourly]]:
    """Base's and summit's own pooled ensemble members (snow water), for bands every
    system in use was asked at; a band missing any system scales mid's instead, so the
    pool always holds the same systems as mid's."""
    out: dict[int, list[Hourly]] = {}
    if not systems:
        return out
    for i in (0, 2):
        band: dict[str, list[Hourly]] = {}
        for s in systems:
            pts = inputs.ensemble_bands.get(s)
            if not pts or len(pts) <= i:
                break
            got = [_swe(m, k) for m in ensemble_members(pts[i])]
            if not got:
                break
            band[s] = got
        else:
            out[i] = ens.pooled(band)
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
    snow_level: Hourly,
    sl_how: Mapping[int, str | None],
    own_members: Sequence[Sequence[float]] | None = None,
    own_pool: Sequence[Hourly] | None = None,
) -> BandOut:
    """own_members, own_pool: this band's own ensemble (period totals, pooled members),
    when every system was asked at every band; else mid's are scaled to it."""
    band = loc.bands[i]
    phys = cfg.physics
    k = cfg.snowfall_cm_per_mm
    min_m = cfg.ensemble_min_members
    pop = blend.get("precipitation_probability")
    cape = blend.get("cape")

    period_ratio_of: dict[int, float | None] = {}
    out_periods: list[PeriodOut] = []
    for j, p in enumerate(periods):
        c, lq = w.sw[j], w.liq[j]
        ratio, label = w.ratios[j]
        for h in p.hours:
            period_ratio_of[h] = ratio
        cm_per_mm = depth.factor(ratio)  # this period's headline
        raw = None if c.value is None else c.value * k
        slr = _depth(c.value, w.temp_ratios[j][0] if w.temp_ratios else ratio, k)
        temps = [v for h in p.hours if (v := w.temp[0].get(h)) is not None]
        sls = [v for h in p.hours if (v := snow_level.get(h)) is not None]
        wbs = [v for h in p.hours if (v := w.wb.get(h)) is not None]
        hows = [how for h in p.hours if (how := sl_how.get(h)) is not None]
        frz = [kind for h in p.hours if (kind := w.frz.get(h))]
        capes = [v for h in p.hours if (v := cape.get(h)) is not None]
        winds = [v for h in p.hours if (v := w.wind[0].get(h)) is not None]
        gusts = [v for h in p.hours if (v := w.gust.get(h)) is not None]
        clouds = [v for h in p.hours if (v := w.cloud.get(h)) is not None]
        pops = [v for h in p.hours if (v := pop.get(h)) is not None]
        e: EnsStats | None
        if i == 1:
            e = _ens_stats(period_members[j], cm_per_mm, min_m)
        elif own_members is not None:
            e = _ens_stats(own_members[j], cm_per_mm, min_m)
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
                snow_level_min_m=r(min(sls), 0) if sls else None,
                wind_max_kmh=r(max(winds), 0) if winds else None,
                gust_max_kmh=r(max(gusts), 0) if gusts else None,
                cloud_mean=r(sum(clouds) / len(clouds), 0) if clouds else None,
                pop_max=max(pops) if pops else None,
                cape_max=r(max(capes), 0) if capes else None,
                showery=bool(capes)
                and max(capes) >= phys.showery_cape
                and (c.value or 0.0) >= SNOWING_SWE_MM,
                slr_col=w.col_ratios[j] if w.col_ratios else None,
                wetbulb_min_c=r(min(wbs)) if wbs else None,
                wetbulb_max_c=r(max(wbs)) if wbs else None,
                snow_level_how=max(set(hows), key=hows.count) if hows else None,
                frz="freezing_rain" if "freezing_rain" in frz else ("sleet" if frz else None),
                frz_h=len(frz),
            )
        )

    members = ens.pooled(systems)
    windows = {
        name: _window(w, mid, periods, a, b, i, k, min_m, depth, members, own_pool)
        for name, (a, b) in WINDOWS.items()
    }

    def hourly_depth(h: int) -> float | None:
        return depth.cm(w.hourly_sw.get(h), period_ratio_of.get(h))

    hours = list(shown)
    have_wb = any(w.wb.get(h) is not None for h in hours)

    def hour_type(h: int) -> str:
        sw, lq = w.hourly_sw.get(h) or 0.0, w.hourly_liq.get(h) or 0.0
        if have_wb and sw + lq >= WET_MM and (got := precip_type(w.wb.get(h), phys)):
            return got
        return ptype(sw, lq)

    hourly = HourlyOut(
        t=[_iso(h, tz) for h in hours],
        snow_cm=[r(hourly_depth(h), 2) for h in hours],
        swe_mm=[r(w.hourly_sw.get(h), 2) for h in hours],
        water_mm=[r(_sum2(w.hourly_sw.get(h), w.hourly_liq.get(h)), 2) for h in hours],
        rain_mm=[r(w.hourly_liq.get(h), 2) for h in hours],
        ptype=[hour_type(h) for h in hours],
        temp_c=[r(w.temp[0].get(h)) for h in hours],
        temp_lo=[r(w.temp[1].get(h)) for h in hours],
        temp_hi=[r(w.temp[2].get(h)) for h in hours],
        fl_m=[r(w.fl[0].get(h), -1) for h in hours],
        fl_lo=[r(w.fl[1].get(h), -1) for h in hours],
        fl_hi=[r(w.fl[2].get(h), -1) for h in hours],
        snow_level_m=[r(snow_level.get(h), -1) for h in hours],
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
        slr=[
            hourly_slr(w.temp[0].get(h), cfg.slr_bands, w.wb.get(h), phys.wb_rain_min_c)
            for h in hours
        ],
        wetbulb_c=[r(w.wb.get(h)) for h in hours] if have_wb else [],
        snow_level_how=[sl_how.get(h) for h in hours],
        frz=[w.frz.get(h) for h in hours] if have_wb or w.frz else [],
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
    own: Sequence[Hourly] | None = None,
) -> WindowOut:
    """members: mid's pooled ensemble; own: this band's, if it was asked for (then its
    totals use this band's own snow ratios, unscaled)."""
    ps = list(periods[a:b])
    if not ps:
        return WindowOut(
            snow_cm=None, snow_cm_raw=None, snow_cm_slr=None, ens=None, ens_raw=None, ens_slr=None
        )
    raw, slr, headline = _window_totals(w, a, b, k, depth)
    # Mid's members use mid's snow ratios; a band's own members, its own.
    at = w if own is not None and i != 1 else mid
    pool = own if own is not None and i != 1 else members
    ratios = [rt for rt, _ in at.ratios[a:b]]
    raw_m = sorted(_member_depths(pool, ps, [k] * len(ps)))
    slr_m = sorted(_member_depths(pool, ps, [rt / 10 if rt else k for rt in ratios]))
    head_m = slr_m if depth.slr else raw_m
    if i == 1 or own is not None:
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
    temp_ratios = [rt for rt, _ in (w.temp_ratios or w.ratios)[a:b]]
    if all(v is None for v in sw):
        return None, None, None
    pairs = list(zip(sw, ratios, strict=True))
    raw = sum(v or 0.0 for v in sw) * k
    slr = sum(_depth(v, rt, k) or 0.0 for v, rt in zip(sw, temp_ratios, strict=True))
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
    snow_level: Hourly,
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
    temp_ratios = mid.temp_ratios or mid.ratios
    ratio_at = {
        h: ratio for p, (ratio, _) in zip(periods, temp_ratios, strict=True) for h in p.hours
    }
    # Each hour's column ratio; an hour of a period with nothing snowing needs none.
    col_at: dict[int, float | None] = {}
    for p, col, (ratio, _) in zip(
        periods, mid.col_ratios or [None] * len(periods), temp_ratios, strict=True
    ):
        if col is not None or ratio is None:
            col_at.update(dict.fromkeys(p.hours, col))

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
        sls = [v for h in hs if (v := snow_level.get(h)) is not None]
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
                snow_level_min_m=r(min(sls), 0) if sls else None,
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
            # And with the column snow ratio (milestone 3), once every hour of the day has
            # one (or nothing snowing to need one), for the scorecard to compare.
            if mid.col_ratios and all(h in col_at for h in hs):
                col = sum(_depth(mid.hourly_sw[h], col_at[h], k) or 0.0 for h in hs)
                records.append(DailyRecord(d, "cons_col", r(col), r(swe + liq)))
            # And with the precipitation split by wet-bulb at the band (`cons_wb`): the
            # same depth conversion as cons_slr, so only the split differs.
            if mid.wb_sw and all(mid.wb_sw.get(h) is not None for h in hs):
                wbs = sum(_depth(mid.wb_sw[h], ratio_at[h], k) or 0.0 for h in hs)
                records.append(DailyRecord(d, "cons_wb", r(wbs), r(swe + liq)))
            # And with the models' own split while the headline uses the wet-bulb's.
            if mid.model_sw and all(mid.model_sw.get(h) is not None for h in hs):
                own = sum(_depth(mid.model_sw[h], ratio_at[h], k) or 0.0 for h in hs)
                records.append(DailyRecord(d, "cons_model", r(own), r(swe + liq)))
    if inputs.station is not None:
        records += _station_records(inputs.station, models, days, day_hours, cfg)
    return rows, records


def _station_records(
    point: PointData,
    models: Sequence[str],
    days: Sequence[str],
    day_hours: Sequence[Sequence[int]],
    cfg: ForecastConfig,
) -> list[DailyRecord]:
    """The consensus at the snow station (`stn_cons`): per calendar day, the median of
    the models' snowfall (Open-Meteo's 7:1, like `cons`) and of their precipitation, once
    at least `consensus_min_models` models cover the whole day. The station response
    shares the bands' timezone, so the same hours make the same days."""
    md = split_models(point, models)
    out = []
    for d, hs in zip(days, day_hours, strict=True):
        snow = [t for v in md.values() if (t := total(v.get("snowfall", {}), hs)) is not None]
        water = [t for v in md.values() if (t := total(v.get("precipitation", {}), hs)) is not None]
        if len(snow) < cfg.consensus_min_models or len(water) < cfg.consensus_min_models:
            continue
        out.append(DailyRecord(d, "stn_cons", r(median(snow)), r(median(water))))
    return out


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
