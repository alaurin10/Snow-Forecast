"""Add a ski area from the catalog without the review step (Manage's "Add from
catalog", milestone 4): resolve it as auto-detect does from the catalog's point and
elevations, take every suggestion, and save it. The worker does this for each queued
`catalog` job, then fetches its first forecast."""

from __future__ import annotations

import sqlite3

from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.locations.resolve import Pin, ResolveIn, resolve
from snowwatch.models import Location


class CatalogAddError(ValueError):
    """The ski area can't be added as it is (the owner can still add it by hand)."""


def already_added(conn: sqlite3.Connection, catalog_id: str) -> Location | None:
    """A location (active or paused) made from this catalog entry."""
    for loc in service.list_locations(conn, include_inactive=True):
        if loc.catalog_ref == catalog_id:
            return loc
    return None


def _free_id(conn: sqlite3.Connection, base: str) -> str:
    taken = {loc.id for loc in service.list_locations(conn, include_inactive=True)}
    base = base[:36].strip("-") or "ski-area"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def add_from_catalog(
    conn: sqlite3.Connection, fetcher: Fetcher, catalog_id: str, *, max_locations: int
) -> Location:
    """Resolve and save one catalog ski area. Raises CatalogAddError (not in the catalog,
    already added, elevations that don't rise) or service.LocationLimitError."""
    row = conn.execute("SELECT * FROM catalog_ski_areas WHERE id = ?", (catalog_id,)).fetchone()
    if row is None:
        raise CatalogAddError(f"{catalog_id!r} is not in the ski-area list")
    if (have := already_added(conn, catalog_id)) is not None:
        raise CatalogAddError(f"{row['name']} is already added (as {have.id})")
    out = resolve(
        conn,
        fetcher,
        ResolveIn(
            name=row["name"],
            kind="resort",
            catalog_id=catalog_id,
            pins=[Pin(band="mid", lat=row["lat"], lon=row["lon"])],
        ),
    )
    try:
        loc = Location(
            id=_free_id(conn, out.id),
            name=out.name[:80],
            kind="resort",
            region=out.region[:80],
            country=out.country,
            tz=out.tz,
            bands=out.bands,
            snotel=out.snotel,
            nws_office=out.nws_office,
            radar_station=out.radar_station,
            avy=out.avy,
            links=dict(list(out.links.items())[:12]),
            catalog_ref=catalog_id,
            active=True,
            sort_order=int(
                conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM locations").fetchone()[
                    0
                ]
            ),
        )
    except ValueError as e:  # e.g. elevations that don't rise: add it by hand to fix them
        raise CatalogAddError(f"{out.name}: {'; '.join(out.warnings) or e}") from e
    service.upsert_location(conn, loc, max_locations=max_locations, by="catalog")
    return loc
