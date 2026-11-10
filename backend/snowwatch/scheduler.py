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
from snowwatch.store import repo, retention
from snowwatch.store.backup import backup, vacuum
from snowwatch.store.db import connect, migrate

log = logging.getLogger("snowwatch.worker")
RUN_TIME_BUDGET_S = 45 * 60


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
        # The map's pictures are separate files: they don't wait for runs. Each map job
        # skips a turn if its previous one is still going.
        self.map_locks = {name: threading.Lock() for name in ("radar", "forecast", "totals")}
        self._ping = ping
        conn = connect(settings.database)
        applied = migrate(conn)
        if applied:
            log.info("applied database migrations: %s", ", ".join(applied))
        runs, jobs_failed = retention.recover_interrupted(conn)
        if runs or jobs_failed:
            log.warning("marked %d interrupted runs and %d jobs as failed", runs, jobs_failed)

    def heartbeat(self) -> None:
        """Show the scheduler is alive (separate from the run lock, so a long run counts)."""
        path = self.settings.heartbeat_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def ping(self, url: str) -> None:
        """Tell Healthchecks.io a job succeeded. Never lets a failed ping break the job."""
        if not url:
            return
        try:
            self._ping(url)
        except Exception as e:
            log.warning("healthcheck ping failed: %s", e)

    def _fetcher(self) -> Fetcher:
        return Fetcher(
            user_agent=self.settings.user_agent,
            contact_user_agent=self.settings.contact_user_agent,
            raw_dir=self.settings.raw_dir,
            # A full run takes ~10 minutes; past this, retries stop so an upstream
            # outage can't hold the lock (and the queue behind it) for hours.
            time_budget_s=RUN_TIME_BUDGET_S,
        )

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

            max_bytes = self.settings.tiles_max_mb * 1_000_000
            removed = prune_tiles(self.settings.tiles_dir, max_bytes=max_bytes)
            log.info("pruned %d cached map tiles", removed)
            avalanche.prune(conn)
            log.info("retention: %s", retention.prune(conn))

    def _map_job(self, name: str) -> None:
        """Redraw one part of the map's pictures (only what changed) and update the index."""
        from snowwatch.maps.geomet import Net
        from snowwatch.maps.region import region_for
        from snowwatch.maps.render import Renderer

        lock = self.map_locks[name]
        if not lock.acquire(blocking=False):
            return
        try:
            conn = connect(self.settings.database)
            points = [(b.lat, b.lon) for loc in list_locations(conn) for b in loc.bands[:1]]
            region = region_for(points, self.cfg.map.region, self.cfg.map.width)
            headers = {"User-Agent": self.settings.user_agent}
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                r = Renderer(
                    self.settings.precip_dir,
                    Net(client),
                    work_dir=self.settings.data_dir / "maps",
                    nbm_cycles=tuple(self.cfg.map.nbm_cycles),
                    slr_bands=self.cfg.slr_bands,
                )
                job = {"radar": r.radar, "forecast": r.forecast, "totals": r.snow_totals}[name]
                index = job(region)
            kinds: dict[str, int] = {}
            for f in index.get("frames", []):
                kinds[f.get("kind", "")] = kinds.get(f.get("kind", ""), 0) + 1
            log.info("map %s: %s, %d totals", name, kinds, len(index.get("totals", [])))
        except Exception:
            log.exception("map %s failed", name)
        finally:
            lock.release()

    def radar(self) -> None:
        """Radar and nowcast frames (a new scan every 6 minutes)."""
        self._map_job("radar")

    def forecast_frames(self) -> None:
        """Forecast frames to 10 days (new model runs hourly or slower)."""
        self._map_job("forecast")

    def totals_fields(self) -> None:
        """Snow totals."""
        self._map_job("totals")

    def precip(self) -> None:
        """All of the map's pictures, one part after another (`snowwatch precip`)."""
        self.radar()
        self.forecast_frames()
        self.totals_fields()

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
    sched.add_job(
        worker.heartbeat,
        IntervalTrigger(seconds=30),
        id="heartbeat",
        next_run_time=datetime.now(UTC),
        **opts,
    )
    # Checks hourly; only fetches when the file is a week old or the locations changed.
    sched.add_job(
        worker.ski_map,
        IntervalTrigger(hours=1),
        id="ski_map",
        next_run_time=datetime.now(UTC),
        **opts,
    )
    # The map's pictures: radar scans arrive every 6 minutes, model runs hourly or slower.
    mc = worker.cfg.map
    for job, minutes, name in (
        (worker.radar, mc.radar_minutes, "radar"),
        (worker.forecast_frames, mc.forecast_minutes, "forecast_frames"),
        (worker.totals_fields, mc.totals_minutes, "totals_fields"),
    ):
        sched.add_job(
            job,
            IntervalTrigger(minutes=minutes),
            id=name,
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
