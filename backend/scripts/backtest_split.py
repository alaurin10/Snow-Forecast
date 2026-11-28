"""Backtest the rain/snow split against SNOTEL (docs/OPEN-METEO-PLAN.md milestone 3c).

For each SNOTEL station, the self-hosted Open-Meteo server's archive (the start of each
model run, stitched) is asked for every global model's hours at the station's own spot
and elevation over a past season. Each precipitation day is then scored two ways:

- **snow share**: the forecast's snow water ÷ its precipitation, against the station's
  snow-water gain ÷ its gauge catch (0–1). This isolates the split from the models'
  precipitation amounts.
- **snow water**: the forecast's snow water against the snow-water gain (mm).

Days count when the gauge caught at least 5 mm and three or more models cover them; the
forecast is the median of the models. Methods: the models' own split, and the app's
wet-bulb split (`analysis/build._wb_split`, with its warm-layer guard) at several
thresholds. Gauges catch less than falls in windy snow and rain soaking into the
snowpack adds snow water, so the observed share leans high: read the results as which
method is closer, not as exact.

Run on a machine with the server (OPEN_METEO_URL) and the public SNOTEL API:

    uv run python scripts/backtest_split.py --stations 642:WA:SNTL 672:WA:SNTL 711:WA:SNTL \\
        --begin 2025-11-15 --end 2026-04-15

Responses are kept in --cache (default /tmp/backtest-split), so re-runs are instant.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from snowwatch.analysis.build import _wb_split
from snowwatch.analysis.snowlevel import PhysicsConfig
from snowwatch.capture import station_positions
from snowwatch.http import Fetcher
from snowwatch.settings import get_settings
from snowwatch.sources import snotel
from snowwatch.sources.base import fetch

MODELS = ["gfs_seamless", "ecmwf_ifs025", "gem_seamless", "icon_seamless"]
LEVELS = (850, 800, 750, 700, 650, 600)
HOURLY = [
    "precipitation",
    "snowfall",
    "rain",
    "temperature_2m",
    "relative_humidity_2m",
    "wet_bulb_temperature_2m",
    *[f"{v}_{p}hPa" for p in LEVELS for v in ("temperature", "geopotential_height")],
]
THRESHOLDS = [(0.5, 2.0), (0.0, 2.0), (0.0, 1.5), (0.5, 1.5), (0.0, 1.0), (-0.5, 1.0)]
PST = timezone(timedelta(hours=-8))  # SNOTEL days are local standard time (Pacific)
K = 0.7  # Open-Meteo's cm of snow per mm of water


def cached(path: Path, get: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text())
    data = get()
    path.write_text(json.dumps(data))
    return data


def observed(blob: Any, triplet: str) -> dict[str, tuple[float, float]]:
    """{day: (snow-water gain, gauge catch)} in mm."""
    s = snotel.parse_snotel(triplet, blob, [])
    by = {r.date: r for r in s.daily}
    out = {}
    for d, r in by.items():
        nxt = by.get((date.fromisoformat(d) + timedelta(days=1)).isoformat())
        if nxt and None not in (r.swe_mm, nxt.swe_mm, r.precip_mm, nxt.precip_mm):
            out[d] = (nxt.swe_mm - r.swe_mm, nxt.precip_mm - r.precip_mm)  # type: ignore[operator]
    return out


def methods() -> Iterator[tuple[str, PhysicsConfig | None]]:
    yield "models' own split", None
    for lo, hi in THRESHOLDS:
        yield f"wet-bulb {lo:+.1f}..{hi:+.1f} °C", PhysicsConfig(wb_snow_max_c=lo, wb_rain_min_c=hi)


def model_days(
    data: Any, elev_m: float, phys: PhysicsConfig | None
) -> dict[str, tuple[float, float]]:
    """{day: (snow water, precipitation)} for one model's hours."""
    h = data["hourly"]
    times = h["time"]
    series = {k: dict(zip(times, v, strict=False)) for k, v in h.items() if k != "time"}
    upper = {k: v for k, v in series.items() if "hPa" in k}
    if phys is None:
        snow = {t: None if v is None else v / K for t, v in series["snowfall"].items()}
    else:
        got = _wb_split(series, K, phys, upper, elev_m)
        snow = (
            got[0]
            if got
            else {t: None if v is None else v / K for t, v in series["snowfall"].items()}
        )
    days: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for t in times:
        p = series["precipitation"].get(t)
        if p is None:
            continue
        d = datetime.fromtimestamp(t - 3600, PST).date().isoformat()  # the hour ending at t
        days[d][0] += snow.get(t) or 0.0
        days[d][1] += p
        days[d][2] += 1
    return {d: (sw, p) for d, (sw, p, n) in days.items() if n == 24}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--stations", nargs="+", required=True, help="SNOTEL triplets, e.g. 642:WA:SNTL"
    )
    ap.add_argument("--begin", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    ap.add_argument("--server", default=None, help="Open-Meteo server (default OPEN_METEO_URL)")
    ap.add_argument("--cache", type=Path, default=Path("/tmp/backtest-split"))
    args = ap.parse_args()
    server = (args.server or get_settings().open_meteo_url).rstrip("/")
    if not server:
        raise SystemExit("set OPEN_METEO_URL or pass --server")
    args.cache.mkdir(parents=True, exist_ok=True)

    with Fetcher(user_agent="snowwatch-backtest", tries=3, timeout_s=300) as f:
        states = sorted({t.split(":")[1] for t in args.stations})
        pos: dict[str, tuple[float, float, float]] = {}
        for st in states:
            blob = cached(
                args.cache / f"stations_{st}.json",
                lambda st=st: fetch(f, snotel.stations_request(st)),
            )
            pos |= station_positions(blob)
        data: dict[str, dict[str, Any]] = {}
        obs: dict[str, dict[str, tuple[float, float]]] = {}
        for trip in args.stations:
            lat, lon, elev = pos[trip]
            key = trip.replace(":", "_")
            obs[trip] = observed(
                cached(
                    args.cache / f"{key}_snotel_{args.begin}_{args.end}.json",
                    lambda trip=trip: fetch(f, snotel.daily_request(trip, args.begin, args.end)),
                ),
                trip,
            )
            data[trip] = {}
            for m in MODELS:
                params = {
                    "latitude": f"{lat}",
                    "longitude": f"{lon}",
                    "elevation": f"{elev:.0f}",
                    "models": m,
                    "hourly": ",".join(HOURLY),
                    "timeformat": "unixtime",
                    "start_date": args.begin.isoformat(),
                    "end_date": args.end.isoformat(),
                }
                data[trip][m] = cached(
                    args.cache / f"{key}_{m}_{args.begin}_{args.end}.json",
                    lambda params=params: f.get_json(
                        f"{server}/v1/forecast", params, source="backtest"
                    ),
                )

    print(
        f"Rain/snow split against SNOTEL, {args.begin} to {args.end} ({datetime.now(UTC):%Y-%m-%d})"
    )
    print(
        f"{'method':26} {'days':>4} {'share bias':>10} {'share MAE':>9} "
        f"{'SWE bias':>9} {'SWE MAE':>8}"
    )
    for name, phys in methods():
        share_err: list[float] = []
        swe_err: list[float] = []
        for trip in args.stations:
            elev = pos[trip][2]
            per_model = {m: model_days(d, elev, phys) for m, d in data[trip].items()}
            for day, (gain, catch) in obs[trip].items():
                vals = [pm[day] for pm in per_model.values() if day in pm]
                if catch < 5 or len(vals) < 3:
                    continue
                snow = statistics.median(v[0] for v in vals)
                precip = statistics.median(v[1] for v in vals)
                if precip < 2:
                    continue
                share_err.append(snow / precip - min(1.0, max(0.0, gain / catch)))
                swe_err.append(snow - max(0.0, gain))
        if share_err:
            print(
                f"{name:26} {len(share_err):4d} {statistics.mean(share_err):+10.3f} "
                f"{statistics.mean(abs(e) for e in share_err):9.3f} "
                f"{statistics.mean(swe_err):+8.1f}mm "
                f"{statistics.mean(abs(e) for e in swe_err):6.1f}mm"
            )


if __name__ == "__main__":
    main()
