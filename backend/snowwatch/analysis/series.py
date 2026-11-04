"""Normalised hourly series and the small statistics helpers the analysis shares.

Every series is keyed by the hour's start as a Unix timestamp, so data from
different requests (and different models) lines up exactly. Local time only
matters when grouping hours into periods and days, which uses zoneinfo.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

Hourly = dict[int, float | None]


@dataclass
class PointData:
    """One point of an Open-Meteo response: hourly variables keyed by timestamp."""

    tz: str
    utc_offset_s: int
    hourly: dict[str, Hourly] = field(default_factory=dict)
    daily: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, var: str) -> Hourly:
        return self.hourly.get(var, {})


def _to_unix(times: Sequence[Any], tz: ZoneInfo) -> list[int]:
    """Accept Unix seconds (timeformat=unixtime) or local ISO strings (the prototype's)."""
    out = []
    for t in times:
        if isinstance(t, int | float):
            out.append(int(t))
        else:
            out.append(int(datetime.fromisoformat(str(t)).replace(tzinfo=tz).timestamp()))
    return out


def parse_point(resp: Mapping[str, Any]) -> PointData:
    tz_name = str(resp.get("timezone") or "UTC")
    tz = ZoneInfo(tz_name)
    data = PointData(tz=tz_name, utc_offset_s=int(resp.get("utc_offset_seconds") or 0))
    hourly = resp.get("hourly") or {}
    times = _to_unix(hourly.get("time", []), tz)
    for key, values in hourly.items():
        if key == "time":
            continue
        data.hourly[key] = dict(zip(times, values, strict=False))
    daily = resp.get("daily") or {}
    if daily:
        days = [str(d) for d in daily.get("time", [])]
        for key, values in daily.items():
            if key != "time":
                data.daily[key] = dict(zip(days, values, strict=False))
    return data


def parse_points(resp: Any) -> list[PointData]:
    """A multi-point response is a list; a single point is a dict."""
    return [parse_point(r) for r in resp] if isinstance(resp, list) else [parse_point(resp)]


def split_models(point: PointData, models: Iterable[str]) -> dict[str, dict[str, Hourly]]:
    """`snowfall_gfs_seamless` → {"gfs_seamless": {"snowfall": …}}. Empty models are dropped."""
    out: dict[str, dict[str, Hourly]] = {}
    for model in models:
        suffix = f"_{model}"
        series = {
            key[: -len(suffix)]: values
            for key, values in point.hourly.items()
            if key.endswith(suffix) and any(v is not None for v in values.values())
        }
        if series:
            out[model] = series
    return out


def ensemble_members(point: PointData, var: str = "snowfall") -> list[Hourly]:
    """Every member's series for one variable (the control run plus `_memberNN`)."""
    keys = sorted(k for k in point.hourly if k == var or k.startswith(f"{var}_member"))
    return [point.hourly[k] for k in keys if any(v is not None for v in point.hourly[k].values())]


def local(ts: int, tz: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def pct(values: Iterable[float | None], q: float) -> float | None:
    """Linear-interpolated percentile, as in the prototype's `pct`."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def median(values: Iterable[float | None]) -> float | None:
    return pct(values, 0.5)


def mean(values: Iterable[float | None]) -> float | None:
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def total(series: Hourly, hours: Sequence[int]) -> float | None:
    """Sum over the hours, or None if any hour is missing (a model that has ended)."""
    if not hours:
        return None
    acc = 0.0
    for h in hours:
        v = series.get(h)
        if v is None:
            return None
        acc += v
    return acc


def circular_mean(directions: Iterable[float | None]) -> float | None:
    """Mean wind direction in degrees, averaging unit vectors."""
    xs = ys = 0.0
    n = 0
    for d in directions:
        if d is None:
            continue
        r = math.radians(d)
        xs += math.sin(r)
        ys += math.cos(r)
        n += 1
    if n == 0 or (abs(xs) < 1e-9 and abs(ys) < 1e-9):
        return None
    return math.degrees(math.atan2(xs, ys)) % 360


def r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)
