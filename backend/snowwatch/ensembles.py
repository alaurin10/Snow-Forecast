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
from typing import Any

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
    data_dir: Path, *, now: datetime | None = None, fallback_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Lines for `snowwatch openmeteo status`: each downloaded system's run and age, the
    downloader's errors, and free disk. False only when disk is low (under LOW_DISK_GB):
    a stalled downloader costs nothing yet, as the app keeps using public ensembles."""
    now = now or datetime.now(UTC)
    lines: list[str] = []
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
