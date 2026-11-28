"""Self-hosted ensembles (docs/OPEN-METEO-PLAN.md, milestone 1b).

The `openmeteo-ensembles` service (`docker/ensembles.sh`) downloads GEFS, ECMWF ENS and
GEPS runs into the volume it shares with the `openmeteo` server. `worker` and `api` see
that volume read-only at `OPEN_METEO_DATA_DIR` (/openmeteo), and read two things from it:

- each domain's `<folder>/static/meta.json`, written by the downloader with the run it
  holds (`last_run_initialisation_time`, `data_end_time`, Unix seconds): what the server
  will answer with
- `ensembles/status.json`, the downloader's own record: last run done per system, how
  long it took, its last error, and free disk
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from snowwatch.settings import Settings

STATUS_FILE = Path("ensembles") / "status.json"
DISK_LOG = Path("ensembles") / "disk.log"
LOW_DISK_GB = 10.0  # `openmeteo status` warns below this much free disk


@dataclass(frozen=True)
class Part:
    """One downloaded domain: a GEFS resolution, ECMWF ENS or GEPS."""

    key: str  # the downloader's name for it (docker/ensembles.sh)
    folder: str  # its folder in the volume
    label: str
    cycle_h: int  # hours between its runs


# By the `models` name the app asks /v1/ensemble for (config/forecast.yaml `ensembles`).
# GEFS is two downloads: the server joins 0.25° (to 240 h) and 0.5° (to 384 h).
SYSTEMS: dict[str, tuple[Part, ...]] = {
    "gfs_seamless": (
        Part("gefs025", "ncep_gefs025", "GEFS 0.25°", 6),
        Part("gefs05", "ncep_gefs05", "GEFS 0.5°", 6),
    ),
    "ecmwf_ifs025": (Part("ecmwf", "ecmwf_ifs025_ensemble", "ECMWF ENS", 6),),
    "gem_global": (Part("geps", "cmc_gem_geps", "GEPS", 12),),
}
PARTS = tuple(p for parts in SYSTEMS.values() for p in parts)


@dataclass(frozen=True)
class DomainRun:
    """The run a domain's folder holds, from its meta.json."""

    init: datetime  # the run's initialisation time
    data_end: datetime | None  # the last time step it has

    def age_h(self, now: datetime) -> float:
        return (now - self.init).total_seconds() / 3600

    def reach_h(self, now: datetime) -> float | None:
        """Hours ahead of `now` the data reaches."""
        return None if self.data_end is None else (self.data_end - now).total_seconds() / 3600


def _utc(ts: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def domain_run(data_dir: Path, folder: str) -> DomainRun | None:
    """The run in `<folder>/static/meta.json`, or None if there's none (yet)."""
    meta = _json(data_dir / folder / "static" / "meta.json")
    if not isinstance(meta, dict):
        return None
    init = _utc(meta.get("last_run_initialisation_time"))
    if init is None:
        return None
    return DomainRun(init=init, data_end=_utc(meta.get("data_end_time")))


def downloader_status(data_dir: Path) -> dict[str, Any] | None:
    """The downloader's `ensembles/status.json`, or None when it has never run."""
    data = _json(data_dir / STATUS_FILE)
    return data if isinstance(data, dict) else None


def free_gb(*paths: Path) -> float | None:
    """Free disk where the first existing path lives (the VM's disk, for Docker volumes)."""
    for p in paths:
        try:
            return shutil.disk_usage(p).free / 1024**3
        except OSError:
            continue
    return None


def _ago(when: datetime, now: datetime) -> str:
    minutes = (now - when).total_seconds() / 60
    return f"{minutes:.0f} min ago" if minutes < 120 else f"{minutes / 60:.1f} h ago"


def _gb(kb: Any) -> str:
    try:
        return f"{float(kb) / 1024**2:.1f} GB"
    except (TypeError, ValueError):
        return "?"


def status_lines(
    data_dir: Path,
    *,
    now: datetime | None = None,
    fallback_dir: Path | None = None,
    mode: str | None = None,
    sources: dict[str, tuple[bool, str | None, str]] | None = None,
) -> tuple[bool, list[str]]:
    """Lines for `snowwatch openmeteo status`: OPEN_METEO_ENSEMBLES and, in local mode,
    where each system's ensembles came from in the last run (`sources`: system ->
    (self-hosted, why not, since)); each downloaded system's run and age, the
    downloader's errors, and free disk. False only when disk is low (under LOW_DISK_GB):
    a stalled downloader costs nothing, as stale systems use the public API."""
    now = now or datetime.now(UTC)
    lines: list[str] = []
    if mode is not None:
        what = {
            "public": "public API (OPEN_METEO_ENSEMBLES=public)",
            "shadow": "public API, compared with the server each run (shadow)",
            "local": "the server for fresh systems, else the public API (local)",
        }
        lines.append(f"{'ensembles from':16s} {what.get(mode, mode)}")
        for system, (local, why, since) in (sources or {}).items():
            where = "self-hosted" if local else f"PUBLIC API ({why})"
            lines.append(f"  {label(system):14s} {where} since {since}")
    status = downloader_status(data_dir)
    if status is None:
        why = "not mounted" if not data_dir.is_dir() else "no ensembles/status.json"
        lines.append(
            f"{'ensembles':16s} not downloaded here ({why} at {data_dir}; the compose "
            "profile `ensembles` starts the downloader)"
        )
    else:
        checked = _utc_iso(status.get("updated"))
        when = f"last checked {_ago(checked, now)}" if checked else "never checked"
        lines.append(f"{'ensembles':16s} downloader {when}")
        systems = status.get("systems") or {}
        for part in PARTS:
            row = systems.get(part.key) or {}
            run = domain_run(data_dir, part.folder)
            if run is None and not row:
                continue
            bits = []
            if run is not None:
                stale = run.age_h(now) > 2 * part.cycle_h + 2
                bits.append(
                    f"run {run.init:%Y-%m-%d %H}z, {run.age_h(now):.1f} h old"
                    + (" (STALE)" if stale else "")
                )
                reach = run.reach_h(now)
                if reach is not None:
                    bits.append(f"reaches {reach:.0f} h ahead")
            else:
                bits.append("no run yet")
            if row.get("seconds") is not None:
                bits.append(f"took {row['seconds']} s")
            if row.get("size_kb") is not None:
                bits.append(_gb(row["size_kb"]))
            lines.append(f"  {part.label:14s} {', '.join(bits)}")
            if row.get("error"):
                retry = f" (retrying at {row['retry_at']})" if row.get("retry_at") else ""
                lines.append(f"  {'':14s} last error: {row['error']}{retry}")
    free = free_gb(data_dir, *([fallback_dir] if fallback_dir else []))
    ok = True
    if free is None:
        lines.append(f"{'disk':16s} unknown")
    elif free < LOW_DISK_GB:
        ok = False
        lines.append(
            f"{'disk':16s} LOW: {free:.1f} GB free (keep at least {LOW_DISK_GB:.0f}; the "
            "downloader stops under ENSEMBLES_MIN_FREE_GB, 5 by default)"
        )
    else:
        lines.append(f"{'disk':16s} {free:.1f} GB free")
    return ok, lines


def _utc_iso(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- Using them (milestone 1b, PR 2) ---------------------------------------------------

Mode = Literal["public", "shadow", "local"]
LABELS = {"gfs_seamless": "GEFS", "ecmwf_ifs025": "ECMWF ENS", "gem_global": "GEPS"}
# A system is fresh while its run is no older than two of its cycles (and a little).
FRESH_H = {"gfs_seamless": 14.0, "ecmwf_ifs025": 14.0, "gem_global": 26.0}
# ... and its answer reaches this far ahead. ECMWF's 06/18z runs stop at 144 h; the
# rolling file keeps the last 00/12z run's later hours, so a reach of 336 h also means a
# 00/12z run no older than ~24 h.
MIN_REACH_H = {"gfs_seamless": 360.0, "ecmwf_ifs025": 336.0, "gem_global": 360.0}


def label(system: str) -> str:
    return LABELS.get(system, system)


def stale_reason(data_dir: Path, system: str, now: datetime | None = None) -> str | None:
    """None when the server's copy of `system` is fresh enough to use, else why not."""
    now = now or datetime.now(UTC)
    parts = SYSTEMS.get(system)
    if not parts:
        return "not downloaded here"
    runs = [domain_run(data_dir, p.folder) for p in parts]
    if any(r is None for r in runs):
        return "no run downloaded"
    oldest = min(r.init for r in runs if r is not None)
    age = (now - oldest).total_seconds() / 3600
    limit = FRESH_H.get(system, 14.0)
    if age > limit:
        return f"its newest run ({oldest:%d %b %H}z) is {age:.0f} h old, more than {limit:.0f}"
    return None


def local_run(data_dir: Path, system: str) -> datetime | None:
    """The oldest of a system's downloaded runs (GEFS is two), as the server serves it."""
    runs = [domain_run(data_dir, p.folder) for p in SYSTEMS.get(system, ())]
    inits = [r.init for r in runs if r is not None]
    return min(inits) if len(inits) == len(runs) and inits else None


PUBLIC_DATA_URL = "https://openmeteo.s3.amazonaws.com/data"


def public_run(get_json: Any, system: str) -> datetime | None:
    """The newest run in the public data's folders for `system` (the oldest of its
    parts), from each folder's meta.json: what the public API serves, give or take its
    own update. `get_json(url)` fetches one (Fetcher.get_json, partially applied)."""
    inits = []
    for part in SYSTEMS.get(system, ()):
        try:
            meta = get_json(f"{PUBLIC_DATA_URL}/{part.folder}/static/meta.json")
        except Exception:  # unknown then: the comparison isn't counted
            return None
        init = _utc(meta.get("last_run_initialisation_time")) if isinstance(meta, dict) else None
        if init is None:
            return None
        inits.append(init)
    return min(inits) if inits else None


def _members(data: Any) -> dict[str, list[Any]]:
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict):
        return {}
    return {k: v for k, v in hourly.items() if k.startswith("snowfall") and isinstance(v, list)}


def _times(data: Any) -> list[float]:
    hourly = data.get("hourly") if isinstance(data, dict) else None
    times = hourly.get("time") if isinstance(hourly, dict) else None
    return [float(t) for t in times] if isinstance(times, list) else []


def _points(data: Any) -> list[Any]:
    """An answer's points: a list for several (base, mid, summit: milestone 4), else one."""
    return list(data) if isinstance(data, list) else [data]


def _mid(data: Any) -> Any:
    pts = _points(data)
    return pts[1] if len(pts) == 3 else (pts[0] if pts else None)


def members_with_data(data: Any) -> int:
    """Members with data; for several points, the fewest at any of them."""
    counts = [
        sum(any(v is not None for v in vals) for vals in _members(pt).values())
        for pt in _points(data)
    ]
    return min(counts, default=0)


def reach_h(data: Any, now: datetime) -> float | None:
    """How far ahead of `now` every member with data reaches (the shortest, at any
    point), in hours."""
    reaches = [_reach_point(pt, now) for pt in _points(data)]
    if any(r is None for r in reaches) or not reaches:
        return None
    return min(r for r in reaches if r is not None)


def _reach_point(data: Any, now: datetime) -> float | None:
    times = _times(data)
    lasts = []
    for vals in _members(data).values():
        last = next((i for i in range(len(vals) - 1, -1, -1) if vals[i] is not None), None)
        if last is not None and last < len(times):
            lasts.append(times[last])
    if not lasts:
        return None
    return (min(lasts) - now.timestamp()) / 3600


def response_problem(
    system: str, data: Any, expected_members: int, now: datetime | None = None
) -> str | None:
    """None when a self-hosted ensemble answer is usable, else why it counts as a failure:
    members missing, or not reaching as far ahead as expected."""
    now = now or datetime.now(UTC)
    n = members_with_data(data)
    if n < expected_members:
        return f"{n} of {expected_members} members"
    reach = reach_h(data, now)
    need = MIN_REACH_H.get(system, 336.0)
    if reach is None or reach < need:
        return f"reaches {0 if reach is None else reach:.0f} h ahead, not {need:.0f}"
    return None


@dataclass(frozen=True)
class Comparison:
    """A self-hosted ensemble answer against the public one (shadow mode)."""

    members_local: int
    members_public: int
    reach_local_h: float | None
    reach_public_h: float | None
    mean_diff_cm: float | None  # of member 16-day totals, over the hours both have
    max_diff_cm: float | None


def compare(local: Any, public: Any, now: datetime) -> Comparison:
    """Compared at mid (where both have it); counts and reach over every point."""
    a, b = _members(_mid(local)), _members(_mid(public))
    ta, tb = _times(_mid(local)), _times(_mid(public))
    common = sorted(set(ta) & set(tb))
    ia = {t: i for i, t in enumerate(ta)}
    ib = {t: i for i, t in enumerate(tb)}
    diffs = []
    for key in sorted(a.keys() & b.keys()):
        va, vb = a[key], b[key]
        sa = sum((va[ia[t]] or 0.0) for t in common if ia[t] < len(va))
        sb = sum((vb[ib[t]] or 0.0) for t in common if ib[t] < len(vb))
        diffs.append(abs(sa - sb))
    return Comparison(
        members_local=members_with_data(local),
        members_public=members_with_data(public),
        reach_local_h=reach_h(local, now),
        reach_public_h=reach_h(public, now),
        mean_diff_cm=round(sum(diffs) / len(diffs), 2) if diffs else None,
        max_diff_cm=round(max(diffs), 2) if diffs else None,
    )


def local_systems(
    settings: Settings, systems: Iterable[str], now: datetime | None = None
) -> list[str]:
    """The systems whose ensembles come from the server now (OPEN_METEO_ENSEMBLES=local,
    run fresh): free, so they cost nothing in the public budget."""
    if settings.ensemble_mode != "local":
        return []
    return [s for s in systems if stale_reason(settings.open_meteo_data_dir, s, now) is None]
