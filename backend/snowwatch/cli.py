"""`snowwatch` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from snowwatch.config import get_forecast_config
from snowwatch.http import Fetcher
from snowwatch.inputs import load_responses
from snowwatch.locations import service
from snowwatch.settings import REPO_ROOT, Settings, get_settings
from snowwatch.sources.openmeteo import daily_weight
from snowwatch.store.db import connect, migrate

DEFAULT_SEED = REPO_ROOT / "config" / "seed-locations.yaml"
FIXTURES_DIR = REPO_ROOT / "backend" / "tests" / "fixtures"


def _fetcher(settings: Settings, *, cache: bool = False) -> Fetcher:
    return Fetcher(user_agent=settings.user_agent, raw_dir=settings.raw_dir if cache else None)


def cmd_init(args: argparse.Namespace, settings: Settings) -> int:
    conn = connect(settings.database)
    applied = migrate(conn)
    print(f"database {settings.database}: applied {applied or 'no'} migrations")
    existing = service.list_locations(conn, include_inactive=True, include_archived=True)
    if existing and not args.force_seed:
        print(f"{len(existing)} locations already present; seed skipped (use --force-seed)")
        return 0
    n = service.import_yaml(conn, Path(args.seed), max_locations=settings.max_locations)
    print(f"seeded {n} locations from {args.seed}")
    return 0


def cmd_migrate(args: argparse.Namespace, settings: Settings) -> int:
    applied = migrate(connect(settings.database))
    print(f"applied {applied or 'no'} migrations")
    return 0


def cmd_locations(args: argparse.Namespace, settings: Settings) -> int:
    conn = connect(settings.database)
    migrate(conn)
    if args.action == "list":
        cfg = get_forecast_config()
        for loc in service.list_locations(conn, include_inactive=True):
            elevs = "/".join(f"{b.elev_m:g}" for b in loc.bands)
            state = "active" if loc.active else "paused"
            print(
                f"{loc.id:14s} {loc.kind:11s} {loc.country} {state:6s} {elevs:16s} "
                f"~{daily_weight(loc, cfg):.0f} calls/day  {loc.name}"
            )
    elif args.action == "import":
        n = service.import_yaml(conn, Path(args.path), max_locations=settings.max_locations)
        print(f"imported {n} locations")
    elif args.action == "export":
        text = service.export_yaml(conn)
        if args.path:
            Path(args.path).write_text(text)
        else:
            sys.stdout.write(text)
    return 0


def cmd_budget(args: argparse.Namespace, settings: Settings) -> int:
    conn = connect(settings.database)
    migrate(conn)
    cfg = get_forecast_config()
    locs = service.list_locations(conn)
    total = sum(daily_weight(loc, cfg) for loc in locs)
    budget = settings.open_meteo_daily_budget
    print(
        f"{len(locs)} active locations, about {total:.0f} of {budget} daily Open-Meteo calls "
        f"({100 * total / budget:.0f}%)"
    )
    return 0


def cmd_capture(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.capture import capture_fixtures

    locs = service.load_yaml(Path(args.seed))
    if args.only:
        locs = [loc for loc in locs if loc.id in args.only]
    out = Path(args.out) if args.out else FIXTURES_DIR / f"live-{date.today():%Y%m%d}"
    with _fetcher(settings) as fetcher:
        meta = capture_fixtures(locs, fetcher, out, get_forecast_config(), spacing_s=args.spacing)
    print(f"saved {len(meta['requests'])} responses to {out}; {len(meta['errors'])} errors")
    return 1 if meta["errors"] else 0


def cmd_check_sources(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.checks import build_report

    locs = service.load_yaml(Path(args.seed))
    with _fetcher(settings) as fetcher:
        report = build_report(fetcher, locs, get_forecast_config())
    if args.write:
        Path(args.write).write_text(report)
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(report)
    return 0


def cmd_pull(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.pipeline import run_all

    conn = connect(settings.database)
    migrate(conn)
    with _fetcher(settings, cache=True) as fetcher:
        run_id, results = run_all(
            conn,
            fetcher,
            get_forecast_config(),
            kind="manual",
            only=args.only or None,
            ensembles=args.ensembles,
            spacing_s=settings.site_spacing_s if args.spacing is None else args.spacing,
        )
        weight = fetcher.total_weight
        limited = fetcher.rate_limited
    for r in results:
        print(f"{r.location_id:14s} {'ok' if r.ok else 'FAILED'} {r.doc_bytes / 1024:5.1f} KB")
        for e in r.errors:
            print(f"    {e}")
    print(f"run {run_id}: {sum(r.ok for r in results)}/{len(results)} ok, ~{weight:.0f} calls")
    if limited:
        print(f"rate limited {limited} times by an upstream API (65 s wait each)")
    return 0 if results and all(r.ok for r in results) else 1


def cmd_worker(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.logs import setup_logging
    from snowwatch.scheduler import Worker, build_scheduler

    setup_logging()
    worker = Worker(settings, get_forecast_config())
    if args.run_now:
        worker.full_run(ensembles=True)
    build_scheduler(worker).start()
    return 0


def cmd_rebuild(args: argparse.Namespace, settings: Settings) -> int:
    """Rebuild snapshots without calling any API: from the raw cache or a fixture folder."""
    from snowwatch.pipeline import latest_cached, run_location
    from snowwatch.store import repo

    conn = connect(settings.database)
    migrate(conn)
    cfg = get_forecast_config()
    run_id = repo.start_run(conn, "rebuild")
    errors: list[str] = []
    now = None
    if args.source:
        meta = json.loads((Path(args.source) / "meta.json").read_text())
        now = datetime.fromisoformat(meta["captured_at"])
    with _fetcher(settings) as fetcher:
        for loc in service.list_locations(conn):
            if args.source:
                responses = load_responses(Path(args.source) / loc.id)
            else:
                responses = latest_cached(settings.raw_dir, loc.id)
            if not responses:
                errors.append(f"{loc.id}: nothing cached")
                continue
            res = run_location(
                conn,
                loc,
                fetcher,
                cfg,
                run_id=run_id,
                now=now or datetime.now(UTC),
                ensembles=False,
                responses=responses,
            )
            print(f"{loc.id:14s} {'ok' if res.ok else 'FAILED'}")
            errors += res.errors
    repo.finish_run(conn, run_id, "partial" if errors else "ok", errors, 0.0)
    return 0


def cmd_backup(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.store.backup import backup

    path = backup(connect(settings.database), settings.backup_dir, today=date.today())
    print(f"wrote {path}")
    return 0


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    from snowwatch.show import render
    from snowwatch.store import repo

    conn = connect(settings.database)
    snap = repo.latest_snapshot(conn, args.id)
    if snap is None:
        print(f"no snapshot for {args.id}; run `snowwatch pull` first", file=sys.stderr)
        return 1
    sys.stdout.write(render(snap, band=args.band))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snowwatch", description="Snow Watch pipeline and tools")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create or migrate the database and seed locations")
    s.add_argument("--seed", default=str(DEFAULT_SEED))
    s.add_argument("--force-seed", action="store_true", help="re-import the seed file")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("migrate", help="apply database migrations")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("locations", help="list, import or export locations")
    s.add_argument("action", choices=["list", "import", "export"])
    s.add_argument("path", nargs="?", help="YAML file for import/export")
    s.set_defaults(func=cmd_locations)

    s = sub.add_parser("budget", help="estimated daily Open-Meteo usage")
    s.set_defaults(func=cmd_budget)

    s = sub.add_parser("capture-fixtures", help="save real responses as test fixtures")
    s.add_argument("--seed", default=str(DEFAULT_SEED))
    s.add_argument("--out", help="output folder (default backend/tests/fixtures/live-DATE)")
    s.add_argument("--only", nargs="*", help="location ids")
    s.add_argument("--spacing", type=float, default=20.0, help="seconds between locations")
    s.set_defaults(func=cmd_capture)

    s = sub.add_parser("check-sources", help="probe every upstream source and report")
    s.add_argument("--seed", default=str(DEFAULT_SEED))
    s.add_argument("--write", help="write the report here (e.g. docs/SOURCES.md)")
    s.set_defaults(func=cmd_check_sources)

    s = sub.add_parser("pull", help="fetch, analyse and store forecasts now")
    s.add_argument("--only", nargs="*", help="location ids")
    ens = s.add_mutually_exclusive_group()
    ens.add_argument("--ensembles", dest="ensembles", action="store_const", const=True)
    ens.add_argument("--no-ensembles", dest="ensembles", action="store_const", const=False)
    s.add_argument("--spacing", type=float, help="seconds between locations")
    s.set_defaults(func=cmd_pull, ensembles=None)

    s = sub.add_parser("worker", help="run the scheduler (runs, job queue, backups)")
    s.add_argument("--run-now", action="store_true", help="do a full run before waiting")
    s.set_defaults(func=cmd_worker)

    s = sub.add_parser("rebuild", help="rebuild snapshots from cached or saved responses")
    s.add_argument("--from", dest="source", help="a fixture folder instead of the raw cache")
    s.set_defaults(func=cmd_rebuild)

    s = sub.add_parser("backup", help="write a database backup now")
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("show", help="print a location's latest forecast as a table")
    s.add_argument("id")
    s.add_argument("--band", choices=["base", "mid", "summit"], default="mid")
    s.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "locations" and args.action == "import" and not args.path:
        print("locations import needs a YAML path", file=sys.stderr)
        return 2
    return int(args.func(args, get_settings()))


if __name__ == "__main__":
    raise SystemExit(main())
