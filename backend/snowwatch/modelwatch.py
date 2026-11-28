"""Refresh when new model data lands (docs/OPEN-METEO-PLAN.md, milestone 4).

Every model folder in the public Open-Meteo data (which the self-hosted server reads)
has a `static/meta.json` with its latest run: `last_run_initialisation_time` and
`last_run_availability_time` (Unix seconds). HRRR and NBM update hourly, the others
every 6 h. The worker reads them every few minutes (`Worker.watch_models`), keeps them
in `model_runs` (the Status page, each snapshot's `model_runs`, and the spot cache's
expiry read it), and with `schedule.refresh: data` the `Planner` here turns a newer run
into a forecast run for the locations that use that model, a few minutes later so the
server has the new data at hand. A location runs at most once per `min_gap` and at least
once per `max_gap` whatever the models do.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger("snowwatch.modelwatch")

DATA_URL = "https://openmeteo.s3.amazonaws.com/data"

# The app's model names (config/forecast.yaml) and the folders that feed each one, the
# first being the one whose run labels it ("GFS 18z"). `checks.MODEL_FOLDERS` lists the
# same folders. (GFS seamless also blends HRRR in the US, where HRRR is its own model in
# the set already; leaving it out here keeps Canadian locations off HRRR's hourly beat.)
# GEM's `cmc_gem_gdps` and `cmc_gem_rdps` stopped in May 2026.
MODEL_FOLDERS: dict[str, tuple[str, ...]] = {
    "gfs_seamless": ("ncep_gfs013", "ncep_gfs025"),
    "ecmwf_ifs025": ("ecmwf_ifs025",),
    "gem_seamless": ("cmc_gem_gdps_15km", "cmc_gem_rdps_10km", "cmc_gem_hrdps"),
    "icon_seamless": ("dwd_icon",),
    "ncep_hrrr_conus": ("ncep_hrrr_conus",),
    "ncep_nbm_conus": ("ncep_nbm_conus",),
    "gem_hrdps_continental": ("cmc_gem_hrdps",),
}

LABELS = {
    "gfs_seamless": "GFS",
    "ecmwf_ifs025": "ECMWF",
    "gem_seamless": "GEM",
    "icon_seamless": "ICON",
    "ncep_hrrr_conus": "HRRR",
    "ncep_nbm_conus": "NBM",
    "gem_hrdps_continental": "HRDPS",
}

PRELOAD_S = 5 * 60  # after a model's run is available, give the server this long
MIN_GAP_S = 40 * 60  # at most one run per location this often…
MAX_GAP_S = 3 * 3600  # …and at least one this often
WATCH_MINUTES = 5


def all_folders() -> list[str]:
    seen: dict[str, None] = {}
    for folders in MODEL_FOLDERS.values():
        seen.update(dict.fromkeys(folders))
    return list(seen)


def folders_for(models: Iterable[str]) -> set[str]:
    """The data folders a set of app models reads."""
    return {f for m in models for f in MODEL_FOLDERS.get(m, ())}


def _utc(ts: Any) -> datetime | None:
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts, UTC)
    return None


@dataclass(frozen=True)
class ModelRun:
    folder: str
    init: datetime | None
    available: datetime | None


def read_runs(
    get_json: Callable[[str], Any], folders: Iterable[str] | None = None
) -> tuple[dict[str, ModelRun], dict[str, str]]:
    """Each folder's latest run from its meta.json, and the folders that failed (why)."""
    runs: dict[str, ModelRun] = {}
    errors: dict[str, str] = {}
    for folder in folders or all_folders():
        try:
            meta = get_json(f"{DATA_URL}/{folder}/static/meta.json")
        except Exception as e:  # one folder failing never stops the others
            errors[folder] = str(e)[:200]
            continue
        if not isinstance(meta, dict):
            errors[folder] = "meta.json is not an object"
            continue
        runs[folder] = ModelRun(
            folder,
            _utc(meta.get("last_run_initialisation_time")),
            _utc(meta.get("last_run_availability_time")),
        )
    return runs, errors


def runs_for(models: Iterable[str], inits: Mapping[str, str | None]) -> dict[str, str]:
    """Snapshot.model_runs: each model's latest run (its first folder's initialisation
    time, ISO), for the models a location uses, from `model_runs` (folder → time)."""
    out: dict[str, str] = {}
    for m in models:
        folders = MODEL_FOLDERS.get(m)
        if folders and (t := inits.get(folders[0])):
            out[m] = t
    return out


@dataclass
class Planner:
    """Which locations to run, from model updates. Pure: the time is passed in.

    `observe` takes the latest runs; a folder whose availability time moves past what
    was seen schedules every location reading it `preload_s` later (the first look only
    records them). `take_due` hands out the locations whose time has come, holding any
    that ran less than `min_gap_s` ago until then, and adds any not run for `max_gap_s`.
    """

    preload_s: float = PRELOAD_S
    min_gap_s: float = MIN_GAP_S
    max_gap_s: float = MAX_GAP_S
    seen: dict[str, datetime] = field(default_factory=dict)  # folder -> availability
    last_run: dict[str, datetime] = field(default_factory=dict)  # location -> run start
    due: dict[str, datetime] = field(default_factory=dict)  # location -> run from
    why: dict[str, set[str]] = field(default_factory=dict)  # location -> folders

    def observe(
        self, runs: Mapping[str, ModelRun], uses: Mapping[str, set[str]], now: datetime
    ) -> list[str]:
        """Record the latest runs; returns the folders with a new one since the last look.
        uses: location id -> the folders it reads."""
        advanced = []
        for folder, run in runs.items():
            if run.available is None:
                continue
            before = self.seen.get(folder)
            if before is not None and run.available <= before:
                continue
            self.seen[folder] = run.available
            if before is None:
                continue  # the first look: nothing to compare with
            advanced.append(folder)
            at = now + timedelta(seconds=self.preload_s)
            for loc_id, folders in uses.items():
                if folder in folders:
                    if loc_id not in self.due or at < self.due[loc_id]:
                        self.due[loc_id] = at
                    self.why.setdefault(loc_id, set()).add(folder)
        return advanced

    def take_due(self, loc_ids: Iterable[str], now: datetime) -> list[str]:
        """The locations to run now (removed from the queue)."""
        out = []
        for loc_id in loc_ids:
            last = self.last_run.get(loc_id)
            since = None if last is None else (now - last).total_seconds()
            if since is None or since >= self.max_gap_s:
                out.append(loc_id)
                continue
            at = self.due.get(loc_id)
            if at is not None and at <= now and since >= self.min_gap_s:
                out.append(loc_id)
        for loc_id in out:
            self.due.pop(loc_id, None)
        return out

    def next_due(self, now: datetime) -> datetime | None:
        """When the next queued location may run (for the log)."""
        times = []
        for loc_id, at in self.due.items():
            last = self.last_run.get(loc_id)
            earliest = at if last is None else max(at, last + timedelta(seconds=self.min_gap_s))
            times.append(earliest)
        return min(times, default=None)

    def ran(self, loc_ids: Iterable[str], at: datetime) -> None:
        for loc_id in loc_ids:
            self.last_run[loc_id] = at
            self.why.pop(loc_id, None)

    def reasons(self, loc_ids: Iterable[str]) -> list[str]:
        """The folders that queued these locations (for the run's log line)."""
        return sorted({f for loc_id in loc_ids for f in self.why.get(loc_id, ())})
