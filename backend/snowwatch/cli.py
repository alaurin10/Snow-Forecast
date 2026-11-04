"""`snowwatch` command-line interface."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from snowwatch.config import get_forecast_config
from snowwatch.http import Fetcher
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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "locations" and args.action == "import" and not args.path:
        print("locations import needs a YAML path", file=sys.stderr)
        return 2
    return int(args.func(args, get_settings()))


if __name__ == "__main__":
    raise SystemExit(main())
