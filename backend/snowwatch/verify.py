"""The forecast scorecard: next-day forecasts against what the snow station measured.

For each day d with observations:
- observed new snow = max(0, depth at the start of d+1 − depth at the start of d);
  where a station has no depth sensor, snow water gain × ratio stands in;
- the forecast is the one from the last run issued before d began (local time),
  so every score is a 1-day lead.

Sources compared: the consensus (model snowfall at 7:1, `cons`, and the
temperature-based snow ratio, `cons_slr`; `headline` names the one the app shows),
the ensemble median and each model (both at 7:1). Stations sit at their own
elevation, which can differ from the mid band, so scores show bias as much as skill.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from snowwatch.config import ForecastConfig
from snowwatch.models import Location

BIG_DAY_CM = 7.62  # 3 in
MIN_DAYS = 7
PAIR_DAYS = 30
SCORE_DAYS = 365  # the scorecard covers the last year


class VerificationRow(BaseModel):
    source: str  # cons, cons_slr, ens_p50, or a model id
    n: int
    bias_cm: float | None  # mean forecast − observed
    mae_cm: float | None
    hits: int  # days of 3 in or more forecast and observed
    misses: int  # observed but not forecast
    false_alarms: int  # forecast but not observed


class VerificationPair(BaseModel):
    date: str
    observed_cm: float | None
    from_swe: bool  # observed from snow water (no depth sensor)
    cons_cm: float | None
    cons_slr_cm: float | None


class VerificationOut(BaseModel):
    location_id: str
    headline: str = "cons"  # the consensus source the app's snow totals use
    station: str | None
    station_name: str | None
    station_elev_m: float | None
    band_elev_m: float
    since: str | None
    n_days: int
    ready: bool
    needs_days: int
    rows: list[VerificationRow]
    pairs: list[VerificationPair]


def headline_source(cfg: ForecastConfig) -> str:
    """The `forecast_daily` consensus source that matches the snapshot's headline depth."""
    return "cons_slr" if cfg.depth_method == "slr" else "cons"


def _observed(
    conn: sqlite3.Connection, loc_id: str, station: str, swe_ratio: float
) -> dict[str, tuple[float, bool]]:
    rows = conn.execute(
        "SELECT date, depth_cm, swe_mm FROM obs_daily WHERE location_id = ? AND station = ? "
        "ORDER BY date",
        (loc_id, station),
    ).fetchall()
    by_date = {r["date"]: (r["depth_cm"], r["swe_mm"]) for r in rows}
    out: dict[str, tuple[float, bool]] = {}
    for d_str, (depth, swe) in by_date.items():
        nxt = (date.fromisoformat(d_str) + timedelta(days=1)).isoformat()
        if nxt not in by_date:
            continue
        depth2, swe2 = by_date[nxt]
        if depth is not None and depth2 is not None:
            out[d_str] = (max(0.0, depth2 - depth), False)
        elif swe is not None and swe2 is not None:
            out[d_str] = (max(0.0, swe2 - swe) * swe_ratio / 10, True)
    return out


def _forecasts(conn: sqlite3.Connection, loc_id: str, tz: ZoneInfo) -> dict[str, dict[str, float]]:
    """{date: {source: snow_cm}} from the last run issued before that date began."""
    rows = conn.execute(
        "SELECT run_id, issued_at, target_date, source, snow_cm FROM forecast_daily "
        "WHERE location_id = ? AND snow_cm IS NOT NULL AND target_date >= ? "
        "AND target_date <= date(issued_at, '+2 days')",
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
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        if best.get(r["target_date"]) == r["run_id"]:
            out[r["target_date"]][r["source"]] = r["snow_cm"]
    return out


def _order(source: str) -> tuple[int, str]:
    return {"cons": 0, "cons_slr": 1, "ens_p50": 2}.get(source, 3), source


def verification(
    conn: sqlite3.Connection,
    loc: Location,
    *,
    swe_ratio: float = 10.0,
    headline: str = "cons",
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
    days = sorted(d for d in observed if d in forecasts)

    per_source: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in days:
        o = observed[d][0]
        for source, f in forecasts[d].items():
            if source in ("ens_p10", "ens_p90"):
                continue
            per_source[source].append((f, o))
    rows = []
    for source in sorted(per_source, key=_order):
        pairs = per_source[source]
        n = len(pairs)
        rows.append(
            VerificationRow(
                source=source,
                n=n,
                bias_cm=round(sum(f - o for f, o in pairs) / n, 1) if n else None,
                mae_cm=round(sum(abs(f - o) for f, o in pairs) / n, 1) if n else None,
                hits=sum(1 for f, o in pairs if f >= BIG_DAY_CM and o >= BIG_DAY_CM),
                misses=sum(1 for f, o in pairs if f < BIG_DAY_CM and o >= BIG_DAY_CM),
                false_alarms=sum(1 for f, o in pairs if f >= BIG_DAY_CM and o < BIG_DAY_CM),
            )
        )
    recent = days[-PAIR_DAYS:]
    return VerificationOut(
        location_id=loc.id,
        headline=headline,
        station=station,
        station_name=meta["name"] if meta else None,
        station_elev_m=meta["elev_m"] if meta else None,
        band_elev_m=mid.elev_m,
        since=days[0] if days else None,
        n_days=len(days),
        ready=len(days) >= MIN_DAYS,
        needs_days=max(0, MIN_DAYS - len(days)),
        rows=rows,
        pairs=[
            VerificationPair(
                date=d,
                observed_cm=round(observed[d][0], 1),
                from_swe=observed[d][1],
                cons_cm=forecasts[d].get("cons"),
                cons_slr_cm=forecasts[d].get("cons_slr"),
            )
            for d in recent
        ],
    )
