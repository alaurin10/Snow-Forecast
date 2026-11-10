"""Lookup tables for the Manage page: the ski-area catalog, SNOTEL stations and
avalanche forecast zones. Refreshed weekly by the worker and by
`snowwatch lookups refresh`."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from snowwatch.geo import bbox, centroid
from snowwatch.http import Fetcher
from snowwatch.sources import avalanche_ca, avalanche_us, bc_asws, catalog, snotel
from snowwatch.sources.base import fetch
from snowwatch.store import repo
from snowwatch.store.db import utcnow_iso

log = logging.getLogger("snowwatch.lookups")
COUNTRIES = ("US", "CA")
MIN_KEEP_SHARE = 0.5  # a refresh with under half the stored rows is treated as broken


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


class SuspiciousUpdateError(ValueError):
    """An upstream answer had far fewer rows than we hold: keep the old ones."""


def check_not_shrunk(existing: int, new: int, what: str) -> None:
    """A valid but empty or reshaped answer must not wipe a lookup table."""
    if new == 0 or new < existing * MIN_KEEP_SHARE:
        raise SuspiciousUpdateError(
            f"{what}: got {new} rows where {existing} are stored; keeping the stored ones"
        )


def save_catalog(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> int:
    existing = conn.execute("SELECT COUNT(*) FROM catalog_ski_areas").fetchone()[0]
    check_not_shrunk(existing, len(rows), "ski-area catalog")
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
    for prov in providers:
        existing = conn.execute(
            "SELECT COUNT(*) FROM avy_zones WHERE provider = ?", (prov,)
        ).fetchone()[0]
        check_not_shrunk(existing, sum(1 for r in rows if r[0] == prov), f"{prov} avalanche zones")
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
    """Fetch and store every lookup table. Each part fails on its own, and a part
    that fails (or comes back suspiciously small) leaves its stored rows alone."""
    out: dict[str, int | str] = {}

    def step(name: str, work: Callable[[], int]) -> None:
        try:
            out[name] = work()
        except Exception as e:
            log.warning("lookup %s failed: %s", name, e)
            out[name] = f"failed: {e}"

    step(
        "snotel_stations",
        lambda: repo.save_stations(conn, fetch(fetcher, snotel.all_stations_request())),
    )
    step(
        "bc_stations",
        lambda: repo.save_station_rows(
            conn, bc_asws.station_rows(fetch(fetcher, bc_asws.stations_request()))
        ),
    )
    layers: dict[str, Any] = {}

    def layer(provider: str, req: Any) -> int:
        data = fetch(fetcher, req)
        if not isinstance(data, dict):
            raise ValueError(f"unexpected {type(data).__name__} answer")
        layers[provider] = data
        return len(data.get("features") or [])

    step("avy_us", lambda: layer("nac", avalanche_us.map_layer_request()))
    step("avy_ca", lambda: layer("avcan", avalanche_ca.areas_request()))
    if layers:
        step(
            "avy_zones",
            lambda: save_zones(
                conn, zone_rows(layers.get("nac"), layers.get("avcan")), list(layers)
            ),
        )
    step(
        "ski_areas",
        lambda: save_catalog(
            conn, catalog_rows(fetch(fetcher, catalog.ski_areas_request()).get("features", []))
        ),
    )
    log.info("lookups refreshed: %s", out)
    return out
