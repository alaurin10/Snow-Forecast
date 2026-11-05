"""The worker: scheduled runs, the job queue, backups and housekeeping (APScheduler, UTC)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from snowwatch import jobs
from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, prune_raw
from snowwatch.pipeline import run_all
from snowwatch.settings import Settings
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
                            _, results = run_all(
                                conn,
                                fetcher,
                                self.cfg,
                                kind="job",
                                only=[job["location_id"]],
                                ensembles=None,
                                spacing_s=0,
                            )
                        failed = [e for r in results if not r.ok for e in r.errors]
                        error = "; ".join(failed) or None
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

    def weekly(self) -> None:
        with self.lock:
            vacuum(connect(self.settings.database))


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
    sched.add_job(worker.process_jobs, IntervalTrigger(seconds=15), id="jobs", **opts)
    h, m = _hm(cfg.backup_utc)
    sched.add_job(worker.nightly, CronTrigger(hour=h, minute=m, timezone=UTC), id="nightly", **opts)
    sched.add_job(
        worker.weekly,
        CronTrigger(day_of_week=cfg.vacuum_weekday, hour=h, minute=(m + 30) % 60, timezone=UTC),
        id="weekly",
        **opts,
    )
    return sched
