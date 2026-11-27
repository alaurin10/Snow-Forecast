"""The forecast scorecard: next-day forecasts against what the snow station measured.

Two checks, each day d (local time, midnight to midnight):

- **Snow depth**: observed new snow = max(0, depth at the start of d+1 − depth at the
  start of d); where a station has no depth sensor, snow water gain × ratio stands in.
  A depth sensor measures snow that has settled for up to a day, so beside the app's
  own sources the consensus is also scored as settled snow (its snow water × a settled
  ratio, `cons_settled`). Days the depth can't measure are left out of this check:
  no snowpack at the start (`bare`: snow falling on warm, bare ground melts or doesn't
  register) or above freezing all day at the station (`warm`).
- **Precipitation**: the station's gauge catch (the rise in its season total) against
  the forecast's total water, snow and rain alike. It works on bare ground and in rain,
  and it doesn't depend on the snow ratio, so it says whether the models had the
  amount right. Gauges catch less than falls in wind-driven snow.

Both checks also score the consensus at the station itself (`stn_cons`, and as settled
snow `stn_settled`): the models asked for the station's own spot and elevation, so a
station below or beside the mid band is compared with a forecast for where it is. The
bands are unchanged; this forecast is only for the scorecard.

The forecast is the one from the last run issued before d began, so every score is a
1-day lead. Sources: the consensus (model snowfall at 7:1, `cons`; the temperature-based
snow ratio, `cons_slr`; the column snow ratio, `cons_col`, with a self-hosted server's
pressure levels; settled, `cons_settled`; `headline` names the one the app shows),
the ensemble median and each model. Stations sit at their own elevation, which can differ
from the mid band, so scores show bias as much as skill.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from snowwatch.config import ForecastConfig
from snowwatch.models import Location

BIG_DAY_CM = 7.62  # 3 in
BIG_WATER_MM = 12.7  # 0.5 in
BARE_CM = 5.0  # less than 2 in on the ground: no snowpack for the depth to build on
GAUGE_FAULT_MM = -5.0  # a bigger drop in the season total is a reset or a fault
MIN_DAYS = 7
PAIR_DAYS = 30
SCORE_DAYS = 365  # the scorecard covers the last year
NOT_SCORED = ("ens_p10", "ens_p90")

Skip = Literal["bare", "warm"]


class VerificationRow(BaseModel):
    source: str  # cons, cons_slr, cons_col, cons_settled, stn_settled, ens_p50, or a model id
    n: int
    bias_cm: float | None  # mean forecast − observed
    mae_cm: float | None
    hits: int  # days of 3 in or more forecast and observed
    misses: int  # observed but not forecast
    false_alarms: int  # forecast but not observed


class WaterRow(BaseModel):
    """A source's precipitation forecasts against the station's gauge."""

    source: str  # cons, stn_cons, or a model id
    n: int
    bias_mm: float | None  # mean forecast − observed
    mae_mm: float | None
    hits: int  # days of 0.5 in (12.7 mm) or more forecast and observed
    misses: int
    false_alarms: int


class VerificationPair(BaseModel):
    date: str
    observed_cm: float | None
    from_swe: bool  # observed from snow water (no depth sensor)
    skip: Skip | None = None  # why the depth check leaves this day out
    cons_cm: float | None
    cons_slr_cm: float | None
    cons_col_cm: float | None = None  # the column snow ratio (milestone 3)
    cons_settled_cm: float | None = None
    observed_water_mm: float | None = None  # the gauge's catch
    cons_water_mm: float | None = None  # the consensus's water, snow and rain
    stn_settled_cm: float | None = None  # the consensus at the station, settled
    stn_water_mm: float | None = None  # …and its water


class VerificationOut(BaseModel):
    location_id: str
    headline: str = "cons"  # the consensus source the app's snow totals use
    station: str | None
    station_name: str | None
    station_elev_m: float | None
    band_elev_m: float
    since: str | None
    n_days: int  # days the snow depth was scored
    n_water_days: int = 0  # days the precipitation was scored
    skipped_bare: int = 0  # days left out of the depth check: no snowpack
    skipped_warm: int = 0  # …above freezing all day
    settled_ratio: float = 8  # the snow-to-water ratio for `cons_settled`
    ready: bool
    needs_days: int
    rows: list[VerificationRow]
    water_rows: list[WaterRow] = []
    pairs: list[VerificationPair]


def headline_source(cfg: ForecastConfig) -> str:
    """The `forecast_daily` consensus source that matches the snapshot's headline depth."""
    return {"slr": "cons_slr", "column": "cons_col"}.get(cfg.depth_method, "cons")


@dataclass(frozen=True)
class _Obs:
    snow_cm: float | None
    from_swe: bool
    water_mm: float | None
    skip: Skip | None


def _observed(
    conn: sqlite3.Connection, loc_id: str, station: str, swe_ratio: float
) -> dict[str, _Obs]:
    rows = conn.execute(
        "SELECT date, depth_cm, swe_mm, precip_mm, tmin_c FROM obs_daily "
        "WHERE location_id = ? AND station = ? ORDER BY date",
        (loc_id, station),
    ).fetchall()
    by_date = {r["date"]: r for r in rows}
    out: dict[str, _Obs] = {}
    for d_str, r in by_date.items():
        nxt = by_date.get((date.fromisoformat(d_str) + timedelta(days=1)).isoformat())
        if nxt is None:
            continue
        snow: float | None = None
        from_swe = False
        on_ground: float | None = None
        if r["depth_cm"] is not None and nxt["depth_cm"] is not None:
            snow, on_ground = max(0.0, nxt["depth_cm"] - r["depth_cm"]), r["depth_cm"]
        elif r["swe_mm"] is not None and nxt["swe_mm"] is not None:
            snow = max(0.0, nxt["swe_mm"] - r["swe_mm"]) * swe_ratio / 10
            on_ground, from_swe = r["swe_mm"] * swe_ratio / 10, True
        water: float | None = None
        if r["precip_mm"] is not None and nxt["precip_mm"] is not None:
            gain = nxt["precip_mm"] - r["precip_mm"]
            water = None if gain < GAUGE_FAULT_MM else max(0.0, gain)
        skip: Skip | None = None
        if snow is not None:
            if on_ground is not None and on_ground < BARE_CM:
                skip = "bare"
            elif r["tmin_c"] is not None and r["tmin_c"] > 0:
                skip = "warm"
        if snow is not None or water is not None:
            out[d_str] = _Obs(snow, from_swe, water, skip)
    return out


Forecast = tuple[float | None, float | None]  # snow cm, water mm


def _forecasts(
    conn: sqlite3.Connection, loc_id: str, tz: ZoneInfo
) -> dict[str, dict[str, Forecast]]:
    """{date: {source: (snow_cm, water_mm)}} from the last run issued before that date began."""
    rows = conn.execute(
        "SELECT run_id, issued_at, target_date, source, snow_cm, water_mm FROM forecast_daily "
        "WHERE location_id = ? AND (snow_cm IS NOT NULL OR water_mm IS NOT NULL) "
        "AND target_date >= ? AND target_date <= date(issued_at, '+2 days')",
        (loc_id, (date.today() - timedelta(days=SCORE_DAYS)).isoformat()),
    ).fetchall()
    best: dict[str, int] = {}
    for r in rows:
        d = date.fromisoformat(r["target_date"])
        start = datetime(d.year, d.month, d.day, tzinfo=tz)
        issued = datetime.fromisoformat(r["issued_at"])
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=UTC)
        if issued < start and r["run_id"] > best.get(r["target_date"], -1):
            best[r["target_date"]] = r["run_id"]
    out: dict[str, dict[str, Forecast]] = defaultdict(dict)
    for r in rows:
        if best.get(r["target_date"]) == r["run_id"]:
            out[r["target_date"]][r["source"]] = (r["snow_cm"], r["water_mm"])
    return out


ORDER = ("cons", "cons_slr", "cons_col", "cons_settled", "stn_settled", "stn_cons", "ens_p50")


def _order(source: str) -> tuple[int, str]:
    return ORDER.index(source) if source in ORDER else len(ORDER), source


def _score(
    pairs: Iterable[tuple[float, float]], big: float
) -> tuple[int, float | None, float | None, int, int, int]:
    """n, bias, mean absolute error, hits, misses, false alarms."""
    ps = list(pairs)
    n = len(ps)
    return (
        n,
        round(sum(f - o for f, o in ps) / n, 1) if n else None,
        round(sum(abs(f - o) for f, o in ps) / n, 1) if n else None,
        sum(1 for f, o in ps if f >= big and o >= big),
        sum(1 for f, o in ps if f < big and o >= big),
        sum(1 for f, o in ps if f >= big and o < big),
    )


def verification(
    conn: sqlite3.Connection,
    loc: Location,
    *,
    swe_ratio: float = 10.0,
    headline: str = "cons",
    snowfall_cm_per_mm: float = 0.7,
    settled_ratio: float = 8.0,
) -> VerificationOut:
    tz = ZoneInfo(loc.tz or "UTC")
    mid = loc.band("mid")
    station = loc.snotel
    meta = (
        conn.execute(
            "SELECT name, elev_m FROM snotel_stations WHERE triplet = ?", (station,)
        ).fetchone()
        if station
        else None
    )
    observed = _observed(conn, loc.id, station, swe_ratio) if station else {}
    forecasts = _forecasts(conn, loc.id, tz)
    # The consensus as settled snow: its snow water (7:1 snowfall ÷ 0.7) × the ratio.
    for fc in forecasts.values():
        for src, settled in (("cons", "cons_settled"), ("stn_cons", "stn_settled")):
            if (got := fc.get(src)) and got[0] is not None:
                fc[settled] = (round(got[0] / snowfall_cm_per_mm * settled_ratio / 10, 1), None)
    days = sorted(d for d in observed if d in forecasts)
    depth_days = [d for d in days if observed[d].snow_cm is not None and observed[d].skip is None]
    water_days = [d for d in days if observed[d].water_mm is not None]

    snow_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in depth_days:
        snow = observed[d].snow_cm
        assert snow is not None
        for source, (f, _) in forecasts[d].items():
            # The station's 7:1 snow is scored settled, as stn_settled.
            if f is not None and source not in (*NOT_SCORED, "stn_cons"):
                snow_pairs[source].append((f, snow))
    water_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in water_days:
        caught = observed[d].water_mm
        assert caught is not None
        for source, (_, w) in forecasts[d].items():
            # cons_slr's and cons_col's water is the consensus's: scored once, as cons.
            if w is not None and source not in (*NOT_SCORED, "cons_slr", "cons_col"):
                water_pairs[source].append((w, caught))

    rows = []
    for source in sorted(snow_pairs, key=_order):
        n, bias, mae, hits, misses, fa = _score(snow_pairs[source], BIG_DAY_CM)
        rows.append(
            VerificationRow(
                source=source,
                n=n,
                bias_cm=bias,
                mae_cm=mae,
                hits=hits,
                misses=misses,
                false_alarms=fa,
            )
        )
    water_rows = []
    for source in sorted(water_pairs, key=_order):
        n, bias, mae, hits, misses, fa = _score(water_pairs[source], BIG_WATER_MM)
        water_rows.append(
            WaterRow(
                source=source,
                n=n,
                bias_mm=bias,
                mae_mm=mae,
                hits=hits,
                misses=misses,
                false_alarms=fa,
            )
        )

    scored = max(len(depth_days), len(water_days))
    recent = days[-PAIR_DAYS:]

    def r1(v: float | None) -> float | None:
        return None if v is None else round(v, 1)

    def pair(d: str) -> VerificationPair:
        o, fc = observed[d], forecasts[d]
        return VerificationPair(
            date=d,
            observed_cm=r1(o.snow_cm),
            from_swe=o.from_swe,
            skip=o.skip,
            cons_cm=fc.get("cons", (None, None))[0],
            cons_slr_cm=fc.get("cons_slr", (None, None))[0],
            cons_col_cm=fc.get("cons_col", (None, None))[0],
            cons_settled_cm=fc.get("cons_settled", (None, None))[0],
            observed_water_mm=r1(o.water_mm),
            cons_water_mm=fc.get("cons", (None, None))[1],
            stn_settled_cm=fc.get("stn_settled", (None, None))[0],
            stn_water_mm=fc.get("stn_cons", (None, None))[1],
        )

    return VerificationOut(
        location_id=loc.id,
        headline=headline,
        station=station,
        station_name=meta["name"] if meta else None,
        station_elev_m=meta["elev_m"] if meta else None,
        band_elev_m=mid.elev_m,
        since=days[0] if days else None,
        n_days=len(depth_days),
        n_water_days=len(water_days),
        skipped_bare=sum(1 for d in days if observed[d].skip == "bare"),
        skipped_warm=sum(1 for d in days if observed[d].skip == "warm"),
        settled_ratio=settled_ratio,
        ready=scored >= MIN_DAYS,
        needs_days=max(0, MIN_DAYS - scored),
        rows=rows,
        water_rows=water_rows,
        pairs=[pair(d) for d in recent],
    )
