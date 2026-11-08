"""The worker: scheduled runs, the job queue, backups and housekeeping (APScheduler, UTC)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from snowwatch import avalanche, jobs, push
from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, prune_raw
from snowwatch.locations.service import list_locations
from snowwatch.pipeline import run_all
from snowwatch.settings import Settings
from snowwatch.store import repo
from snowwatch.store.backup import backup, vacuum
from snowwatch.store.db import connect, migrate

log = logging.getLogger("snowwatch.worker")


def http_ping(url: str) -> None:
    httpx.get(url, timeout=10)


class Worker:
    """Holds one lock so a scheduled run and queued jobs never overlap."""

    def __init__(
        self, settings: Settings, cfg: ForecastConfig, *, ping: Callable[[str], None] = http_ping
    ) -> None:
        self.settings = settings
        self.cfg = cfg
        self.lock = threading.Lock()
        # The map's precipitation frames are separate files: they don't wait for runs.
        self.precip_lock = threading.Lock()
        self._ping = ping
        migrate(connect(settings.database))

    def ping(self, url: str) -> None:
        """Tell Healthchecks.io a job succeeded. Never lets a failed ping break the job."""
        if not url:
            return
        try:
            self._ping(url)
        except Exception as e:
            log.warning("healthcheck ping failed: %s", e)

    def _fetcher(self) -> Fetcher:
        return Fetcher(user_agent=self.settings.user_agent, raw_dir=self.settings.raw_dir)

    def full_run(self, ensembles: bool) -> None:
        with self.lock, self._fetcher() as fetcher:
            conn = connect(self.settings.database)
            run_id, results = run_all(
                conn, fetcher, self.cfg, ensembles=ensembles, spacing_s=self.settings.site_spacing_s
            )
            ok = sum(r.ok for r in results)
            if ok:
                self.ping(self.settings.healthchecks_run_url)
            log.info(
                "run %d: %d/%d locations ok, weight %.0f",
                run_id,
                ok,
                len(results),
                fetcher.total_weight,
            )
            self._avalanche(conn, fetcher)
            self._notify(conn, run_id)

    def _notify(self, conn: sqlite3.Connection, run_id: int) -> None:
        """Push alerts for flags first raised in this run. Never fails the run."""
        if not push.enabled(self.settings):
            return
        try:
            snaps = []
            names = {loc.id: loc.name for loc in list_locations(conn)}
            for loc_id, name in names.items():
                snap = repo.latest_snapshot(conn, loc_id)
                if snap is not None and snap.run_id == run_id:
                    snaps.append((loc_id, name, snap))
            sent = push.notify(conn, self.settings, push.new_flags_for_run(conn, run_id, snaps))
            if sent:
                log.info("sent %d push alerts", sent)
        except Exception:
            log.exception("push alerts failed")

    def _avalanche(self, conn: sqlite3.Connection, fetcher: Fetcher) -> None:
        """Avalanche forecasts. A failure is logged and never fails the run."""
        try:
            locs = list_locations(conn)
            res = avalanche.refresh(conn, fetcher, locs)
            log.info("avalanche forecasts: %d saved, %d errors", res.saved, len(res.errors))
            if push.enabled(self.settings):
                views = avalanche.views(conn, {loc.id: loc.tz or "UTC" for loc in locs})
                levels = {}
                for loc in locs:
                    v = views.get(loc.id)
                    today = datetime.now(ZoneInfo(loc.tz or "UTC")).date().isoformat()
                    if v is not None and v.status == "current":
                        levels[loc.id] = (loc.name, v.today_max, today)
                push.notify(conn, self.settings, push.avalanche_alerts(conn, levels))
            repo.save_source_status(conn, fetcher.sources)
            fetcher.sources.clear()
        except Exception:
            log.exception("avalanche refresh failed")

    def refresh_avalanche(self) -> None:
        with self.lock, self._fetcher() as fetcher:
            self._avalanche(connect(self.settings.database), fetcher)

    def process_jobs(self) -> None:
        if not self.lock.acquire(blocking=False):
            return  # a scheduled run is in progress; jobs wait
        try:
            conn = connect(self.settings.database)
            while (job := jobs.claim_next(conn)) is not None:
                error = None
                try:
                    if job["kind"] == "pull" and job["location_id"]:
                        with self._fetcher() as fetcher:
                            run_id, results = run_all(
                                conn,
                                fetcher,
                                self.cfg,
                                kind="job",
                                only=[job["location_id"]],
                                ensembles=None,
                                spacing_s=0,
                            )
                        self._notify(conn, run_id)
                        failed = [e for r in results if not r.ok for e in r.errors]
                        error = "; ".join(failed) or None
                        with self._fetcher() as fetcher:
                            self._avalanche(conn, fetcher)
                    elif job["kind"] == "lookups":
                        self.refresh_lookups(locked=True)
                    else:
                        error = f"unknown job kind {job['kind']!r}"
                except Exception as e:
                    log.exception("job %s failed", job["id"])
                    error = f"{type(e).__name__}: {e}"
                jobs.finish(conn, job["id"], error=error)
        finally:
            self.lock.release()

    def nightly(self) -> None:
        with self.lock:
            conn = connect(self.settings.database)
            path = backup(conn, self.settings.backup_dir, today=datetime.now(UTC).date())
            log.info("backup written to %s", path)
            self.ping(self.settings.healthchecks_backup_url)
            removed = prune_raw(self.settings.raw_dir)
            log.info("pruned %d cached raw responses", removed)
            from snowwatch.tiles import prune as prune_tiles

            log.info("pruned %d cached map tiles", prune_tiles(self.settings.tiles_dir))
            avalanche.prune(conn)

    def precip(self) -> None:
        """Redraw the map's precipitation frames that changed (new radar, new model runs)."""
        from snowwatch.precip import Net, Renderer, region_for

        if not self.precip_lock.acquire(blocking=False):
            return
        try:
            conn = connect(self.settings.database)
            points = [(b.lat, b.lon) for loc in list_locations(conn) for b in loc.bands[:1]]
            headers = {"User-Agent": self.settings.user_agent}
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                index = Renderer(self.settings.precip_dir, Net(client)).run(region_for(points))
            log.info("precipitation frames: %d", len(index["frames"]))
        except Exception:
            log.exception("precipitation frames failed")
        finally:
            self.precip_lock.release()

    def ski_map(self) -> None:
        """Ski runs, lifts and peaks from OpenStreetMap: weekly, or when locations change."""
        from snowwatch import osm

        try:
            conn = connect(self.settings.database)
            points = [(b.lat, b.lon) for loc in list_locations(conn) for b in loc.bands[:1]]
            headers = {"User-Agent": self.settings.user_agent}
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                osm.refresh(self.settings.osm_path, points, client)
        except Exception:
            log.exception("ski map data failed")

    def weekly(self) -> None:
        with self.lock:
            vacuum(connect(self.settings.database))
        self.refresh_lookups()

    def refresh_lookups(self, *, locked: bool = False) -> None:
        """Ski-area catalog, SNOTEL stations and avalanche zones (for the Manage page)."""
        from snowwatch.lookups import refresh

        def run() -> None:
            with self._fetcher() as fetcher:
                refresh(connect(self.settings.database), fetcher)

        if locked:
            run()
        else:
            with self.lock:
                run()


def _hm(text: str) -> tuple[int, int]:
    h, m = text.split(":")
    return int(h), int(m)


def build_scheduler(worker: Worker) -> BlockingScheduler:
    cfg = worker.cfg.schedule
    sched = BlockingScheduler(timezone=UTC)
    opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 1800}
    for t in cfg.runs_utc:
        h, m = _hm(t)
        sched.add_job(
            worker.full_run,
            CronTrigger(hour=h, minute=m, timezone=UTC),
            kwargs={"ensembles": t in cfg.ensemble_runs_utc},
            id=f"run-{t}",
            **opts,
        )
    for t in cfg.avalanche_utc:
        h, m = _hm(t)
        sched.add_job(
            worker.refresh_avalanche,
            CronTrigger(hour=h, minute=m, timezone=UTC),
            id=f"avalanche-{t}",
            **opts,
        )
    sched.add_job(worker.process_jobs, IntervalTrigger(seconds=15), id="jobs", **opts)
    # Checks hourly; only fetches when the file is a week old or the locations changed.
    sched.add_job(
        worker.ski_map,
        IntervalTrigger(hours=1),
        id="ski_map",
        next_run_time=datetime.now(UTC),
        **opts,
    )
    # RainViewer adds a radar scan every 10 minutes; models update hourly or slower.
    sched.add_job(
        worker.precip,
        IntervalTrigger(minutes=10),
        id="precip",
        next_run_time=datetime.now(UTC),
        **opts,
    )
    h, m = _hm(cfg.backup_utc)
    sched.add_job(worker.nightly, CronTrigger(hour=h, minute=m, timezone=UTC), id="nightly", **opts)
    sched.add_job(
        worker.weekly,
        CronTrigger(day_of_week=cfg.vacuum_weekday, hour=h, minute=(m + 30) % 60, timezone=UTC),
        id="weekly",
        **opts,
    )
    return sched
