"""Reading and writing the managed location list."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from snowwatch.models import AvyRef, Band, Location, Webcam
from snowwatch.store.db import utcnow_iso
from snowwatch.urls import clean_links

log = logging.getLogger("snowwatch.locations")


class LocationLimitError(ValueError):
    """Adding or activating this location would exceed MAX_LOCATIONS."""


def _webcams(raw: str | None) -> list[Webcam]:
    out = []
    for w in json.loads(raw or "[]"):
        try:
            out.append(Webcam.model_validate(w))
        except ValidationError:
            log.warning("dropped an invalid stored webcam: %r", w)
    return out


def _from_row(row: sqlite3.Row) -> Location:
    """A stored location. Links and webcams that fail today's checks are dropped, so an
    old row can't break the list or put an unsafe link on the page."""
    return Location(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        region=row["region"],
        country=row["country"],
        tz=row["tz"],
        bands=[Band.model_validate(b) for b in json.loads(row["bands_json"])],
        snotel=row["snotel_triplet"],
        nws_office=row["nws_office"],
        radar_station=row["radar_station"],
        avy=AvyRef.model_validate_json(row["avy_json"]) if row["avy_json"] else None,
        links=dict(list(clean_links(json.loads(row["links_json"])).items())[:12]),
        webcams=_webcams(row["webcams_json"])[:12],
        catalog_ref=row["catalog_ref"],
        active=bool(row["active"]),
        sort_order=row["sort_order"],
    )


def list_locations(
    conn: sqlite3.Connection, *, include_inactive: bool = False, include_archived: bool = False
) -> list[Location]:
    where = []
    if not include_archived:
        where.append("archived_at IS NULL")
    if not include_inactive:
        where.append("active = 1")
    sql = "SELECT * FROM locations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sort_order, name"
    out = []
    for r in conn.execute(sql):
        try:
            out.append(_from_row(r))
        except ValidationError as e:
            log.error("skipped stored location %r: %s", r["id"], e)
    return out


def get_location(conn: sqlite3.Connection, location_id: str) -> Location | None:
    row = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    return _from_row(row) if row else None


def count_active(conn: sqlite3.Connection, *, excluding: str | None = None) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM locations WHERE active = 1 AND archived_at IS NULL AND id != ?",
        (excluding or "",),
    ).fetchone()
    return int(row[0])


def upsert_location(
    conn: sqlite3.Connection, loc: Location, *, max_locations: int, by: str | None = None
) -> None:
    """Insert or update a location. Raises LocationLimitError past the active cap."""
    if loc.active and count_active(conn, excluding=loc.id) >= max_locations:
        raise LocationLimitError(f"at most {max_locations} active locations")
    now = utcnow_iso()
    values: dict[str, Any] = {
        "id": loc.id,
        "name": loc.name,
        "kind": loc.kind,
        "region": loc.region,
        "country": loc.country,
        "tz": loc.tz,
        "active": int(loc.active),
        "sort_order": loc.sort_order,
        "bands_json": json.dumps([b.model_dump() for b in loc.bands]),
        "snotel_triplet": loc.snotel,
        "nws_office": loc.nws_office,
        "radar_station": loc.radar_station,
        "avy_json": loc.avy.model_dump_json() if loc.avy else None,
        "links_json": json.dumps(loc.links),
        "webcams_json": json.dumps([w.model_dump(exclude_none=True) for w in loc.webcams]),
        "catalog_ref": loc.catalog_ref,
        "now": now,
        "by": by,
    }
    with conn:
        conn.execute(
            """
            INSERT INTO locations (id, name, kind, region, country, tz, active, sort_order,
                bands_json, snotel_triplet, nws_office, radar_station, avy_json, links_json,
                webcams_json, catalog_ref, created_at, updated_at, updated_by)
            VALUES (:id, :name, :kind, :region, :country, :tz, :active, :sort_order,
                :bands_json, :snotel_triplet, :nws_office, :radar_station, :avy_json,
                :links_json, :webcams_json, :catalog_ref, :now, :now, :by)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name, kind = excluded.kind, region = excluded.region,
                country = excluded.country, tz = excluded.tz, active = excluded.active,
                sort_order = excluded.sort_order, bands_json = excluded.bands_json,
                snotel_triplet = excluded.snotel_triplet, nws_office = excluded.nws_office,
                radar_station = excluded.radar_station, avy_json = excluded.avy_json,
                links_json = excluded.links_json, webcams_json = excluded.webcams_json,
                catalog_ref = excluded.catalog_ref,
                updated_at = excluded.updated_at, updated_by = excluded.updated_by,
                archived_at = NULL
            """,
            values,
        )


def set_tz(conn: sqlite3.Connection, location_id: str, tz: str) -> None:
    with conn:
        conn.execute("UPDATE locations SET tz = ? WHERE id = ? AND tz IS NULL", (tz, location_id))


def set_order(conn: sqlite3.Connection, ids: list[str]) -> None:
    with conn:
        for i, location_id in enumerate(ids):
            conn.execute(
                "UPDATE locations SET sort_order = ?, updated_at = ? WHERE id = ?",
                (i, utcnow_iso(), location_id),
            )


def archive_location(conn: sqlite3.Connection, location_id: str) -> None:
    """Hide a location and stop fetching it. Its history stays in the database."""
    with conn:
        conn.execute(
            "UPDATE locations SET archived_at = ?, active = 0, updated_at = ? WHERE id = ?",
            (utcnow_iso(), utcnow_iso(), location_id),
        )


def load_yaml(path: Path) -> list[Location]:
    items = yaml.safe_load(path.read_text()) or []
    locs = []
    for i, item in enumerate(items):
        item.setdefault("sort_order", i)
        locs.append(Location.model_validate(item))
    ids = [loc.id for loc in locs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate location ids in {path}")
    return locs


def import_yaml(conn: sqlite3.Connection, path: Path, *, max_locations: int) -> int:
    locs = load_yaml(path)
    for loc in locs:
        upsert_location(conn, loc, max_locations=max_locations, by="import")
    return len(locs)


def export_yaml(conn: sqlite3.Connection) -> str:
    locs = list_locations(conn, include_inactive=True)
    # Order is implied by list position, so sort_order is left out.
    data = [loc.model_dump(exclude_none=True, exclude={"sort_order"}) for loc in locs]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
