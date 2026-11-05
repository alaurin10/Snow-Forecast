"""Lookup tables for the Manage page: the ski-area catalog, SNOTEL stations and
avalanche forecast zones. Refreshed weekly by the worker and by
`snowwatch lookups refresh`."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from snowwatch.geo import bbox, centroid
from snowwatch.http import Fetcher, FetchError
from snowwatch.sources import avalanche_ca, avalanche_us, bc_asws, catalog, snotel
from snowwatch.sources.base import fetch
from snowwatch.store import repo
from snowwatch.store.db import utcnow_iso

log = logging.getLogger("snowwatch.lookups")
COUNTRIES = ("US", "CA")


def catalog_rows(features: Iterable[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
    """Named, operating downhill ski areas in the US and Canada."""
    rows = []
    now = utcnow_iso()
    for f in features:
        p = f.get("properties") or {}
        places = p.get("places") or []
        place = next((pl for pl in places if pl.get("iso3166_1Alpha2") in COUNTRIES), None)
        if (
            place is None
            or not p.get("name")
            or p.get("status") != "operating"
            or "downhill" not in (p.get("activities") or [])
        ):
            continue
        c = centroid(f.get("geometry") or {})
        if c is None:
            continue
        stats = p.get("statistics") or {}
        region = ((place.get("localized") or {}).get("en") or {}).get("region")
        websites = p.get("websites") or []
        rows.append(
            (
                p["id"],
                p["name"],
                place["iso3166_1Alpha2"],
                region or place.get("iso3166_2"),
                c[0],
                c[1],
                stats.get("minElevation"),
                stats.get("maxElevation"),
                ",".join(p.get("activities") or []),
                p.get("status"),
                websites[0] if websites else None,
                now,
            )
        )
    return rows


def save_catalog(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> int:
    with conn:
        conn.execute("DELETE FROM catalog_ski_areas")
        conn.executemany(
            "INSERT OR REPLACE INTO catalog_ski_areas (id, name, country, region, lat, lon, "
            "min_elev_m, max_elev_m, activities, status, website, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def zone_rows(
    us_layer: Mapping[str, Any] | None, ca_areas: Mapping[str, Any] | None
) -> list[tuple[Any, ...]]:
    now = utcnow_iso()
    rows = []
    for f in (us_layer or {}).get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        b = bbox(g)
        if b is None:
            continue
        rows.append(
            (
                "nac",
                str(f.get("id")),
                p.get("center_id"),
                p.get("name"),
                p.get("link"),
                json.dumps(b),
                json.dumps(g),
                now,
            )
        )
    for f in (ca_areas or {}).get("features", []):
        g = f.get("geometry") or {}
        b = bbox(g)
        if b is None:
            continue
        rows.append(
            (
                "avcan",
                str(f.get("id")),
                "avcan",
                None,
                "https://avalanche.ca/map",
                json.dumps(b),
                json.dumps(g),
                now,
            )
        )
    return rows


def save_zones(
    conn: sqlite3.Connection, rows: list[tuple[Any, ...]], providers: Iterable[str]
) -> int:
    with conn:
        for prov in providers:
            conn.execute("DELETE FROM avy_zones WHERE provider = ?", (prov,))
        conn.executemany(
            "INSERT OR REPLACE INTO avy_zones (provider, zone_id, center_id, name, link, "
            "bbox_json, geometry_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def refresh(conn: sqlite3.Connection, fetcher: Fetcher) -> dict[str, int | str]:
    """Fetch and store every lookup table. Each part fails on its own."""
    out: dict[str, int | str] = {}
    try:
        stations = fetch(fetcher, snotel.all_stations_request())
        out["snotel_stations"] = repo.save_stations(conn, stations)
    except FetchError as e:
        out["snotel_stations"] = f"failed: {e}"
    try:
        wfs = fetch(fetcher, bc_asws.stations_request())
        out["bc_stations"] = repo.save_station_rows(conn, bc_asws.station_rows(wfs))
    except FetchError as e:
        out["bc_stations"] = f"failed: {e}"
    us = ca = None
    try:
        us = fetch(fetcher, avalanche_us.map_layer_request())
    except FetchError as e:
        out["avy_us"] = f"failed: {e}"
    try:
        ca = fetch(fetcher, avalanche_ca.areas_request())
    except FetchError as e:
        out["avy_ca"] = f"failed: {e}"
    providers = [p for p, d in (("nac", us), ("avcan", ca)) if d is not None]
    if providers:
        out["avy_zones"] = save_zones(conn, zone_rows(us, ca), providers)
    try:
        areas = fetch(fetcher, catalog.ski_areas_request())
        out["ski_areas"] = save_catalog(conn, catalog_rows(areas.get("features", [])))
    except FetchError as e:
        out["ski_areas"] = f"failed: {e}"
    log.info("lookups refreshed: %s", out)
    return out
