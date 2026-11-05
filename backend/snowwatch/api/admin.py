"""Owner-only endpoints for the Manage page. Cloudflare Access also guards
/admin and /api/admin at its edge (docs/RUNBOOK.md step 6); this checks again."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from snowwatch import jobs
from snowwatch.api.auth import Owner
from snowwatch.config import get_forecast_config
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.locations.resolve import ResolveIn, ResolveOut, resolve
from snowwatch.models import Location
from snowwatch.settings import Settings
from snowwatch.sources.openmeteo import daily_weight
from snowwatch.store.db import connect


class CatalogItem(BaseModel):
    id: str
    name: str
    country: str | None
    region: str | None
    lat: float
    lon: float
    min_elev_m: float | None
    max_elev_m: float | None
    website: str | None


class JobOut(BaseModel):
    id: int
    kind: str
    location_id: str | None
    status: str
    created_at: str
    finished_at: str | None
    error: str | None


class SaveOut(BaseModel):
    location: Location
    job_id: int | None


class BudgetOut(BaseModel):
    per_location: dict[str, float]
    total: float
    budget: int
    active: int
    max_locations: int


class LookupStatus(BaseModel):
    ski_areas: int
    snotel_stations: int
    avy_zones: int


def db_rw(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    conn = connect(settings.database)
    try:
        yield conn
    finally:
        conn.close()


RW = Annotated[sqlite3.Connection, Depends(db_rw)]


def _fetcher(request: Request) -> Fetcher:
    make: Callable[[], Fetcher] = request.app.state.make_fetcher
    return make()


def make_admin_router() -> APIRouter:
    r = APIRouter(prefix="/api/admin")

    @r.get("/locations", response_model=list[Location])
    def all_locations(_: Owner, conn: RW) -> list[Location]:
        return service.list_locations(conn, include_inactive=True)

    @r.get("/lookups", response_model=LookupStatus)
    def lookups(_: Owner, conn: RW) -> LookupStatus:
        def n(table: str) -> int:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        return LookupStatus(
            ski_areas=n("catalog_ski_areas"),
            snotel_stations=n("snotel_stations"),
            avy_zones=n("avy_zones"),
        )

    @r.post("/lookups/refresh", response_model=JobOut)
    def refresh_lookups(v: Owner, conn: RW) -> JobOut:
        return _job(conn, jobs.enqueue(conn, "lookups", None, v.email))

    @r.get("/catalog/search", response_model=list[CatalogItem])
    def catalog_search(
        _: Owner, conn: RW, q: str = Query(min_length=2, max_length=60)
    ) -> list[CatalogItem]:
        where, params = catalog_query(q)
        rows = conn.execute(
            f"SELECT * FROM catalog_ski_areas WHERE {where} ORDER BY length(name), name LIMIT 20",
            params,
        )
        return [CatalogItem.model_validate(dict(row)) for row in rows]

    @r.post("/locations/resolve", response_model=ResolveOut)
    def resolve_location(body: ResolveIn, request: Request, _: Owner, conn: RW) -> ResolveOut:
        with _fetcher(request) as fetcher:
            return resolve(conn, fetcher, body)

    @r.post("/locations", response_model=SaveOut, status_code=201)
    def create(loc: Location, request: Request, v: Owner, conn: RW) -> SaveOut:
        if service.get_location(conn, loc.id) is not None:
            raise HTTPException(409, f"a location with id {loc.id!r} already exists")
        loc = loc.model_copy(update={"sort_order": _next_order(conn)})
        _upsert(request, conn, loc, v.email)
        job = jobs.enqueue(conn, "pull", loc.id, v.email) if loc.active else None
        return SaveOut(location=loc, job_id=job)

    @r.put("/locations/order")
    def reorder(ids: list[str], _: Owner, conn: RW) -> dict[str, bool]:
        service.set_order(conn, ids)
        return {"ok": True}

    @r.put("/locations/{location_id}", response_model=SaveOut)
    def update(location_id: str, loc: Location, request: Request, v: Owner, conn: RW) -> SaveOut:
        old = service.get_location(conn, location_id)
        if old is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        if loc.id != location_id:
            raise HTTPException(400, "the id can't be changed")
        loc = loc.model_copy(update={"sort_order": old.sort_order})
        _upsert(request, conn, loc, v.email)
        changed = (old.bands, old.country, old.active) != (loc.bands, loc.country, loc.active)
        job = jobs.enqueue(conn, "pull", loc.id, v.email) if loc.active and changed else None
        return SaveOut(location=loc, job_id=job)

    @r.delete("/locations/{location_id}")
    def archive(location_id: str, _: Owner, conn: RW) -> dict[str, bool]:
        if service.get_location(conn, location_id) is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        service.archive_location(conn, location_id)
        return {"ok": True}

    @r.post("/locations/{location_id}/refresh", response_model=JobOut)
    def refresh(location_id: str, v: Owner, conn: RW) -> JobOut:
        if service.get_location(conn, location_id) is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        return _job(conn, jobs.enqueue(conn, "pull", location_id, v.email))

    @r.get("/jobs/{job_id}", response_model=JobOut)
    def job(job_id: int, _: Owner, conn: RW) -> JobOut:
        return _job(conn, job_id)

    @r.get("/budget", response_model=BudgetOut)
    def budget(request: Request, _: Owner, conn: RW) -> BudgetOut:
        settings: Settings = request.app.state.settings
        cfg = get_forecast_config()
        locs = service.list_locations(conn)
        per = {loc.id: daily_weight(loc, cfg) for loc in locs}
        return BudgetOut(
            per_location=per,
            total=round(sum(per.values()), 1),
            budget=settings.open_meteo_daily_budget,
            active=len(locs),
            max_locations=settings.max_locations,
        )

    return r


SYNONYMS = {
    "mt": ("mt", "mount"),
    "mount": ("mount", "mt"),
    "st": ("st", "saint"),
    "saint": ("saint", "st"),
}
NORMALISED_NAME = "REPLACE(REPLACE(LOWER(name), '.', ''), '-', ' ')"


def catalog_query(q: str) -> tuple[str, list[str]]:
    """Every word must appear in the name, ignoring case and punctuation
    ("mt baker" finds "Mt Baker"; "mount hood" finds "Mt. Hood Meadows")."""
    words = re.findall(r"[a-z0-9]+", q.lower()) or [""]
    clauses, params = [], []
    for w in words:
        alts = SYNONYMS.get(w, (w,))
        clauses.append("(" + " OR ".join(f"{NORMALISED_NAME} LIKE ?" for _ in alts) + ")")
        params += [f"%{a}%" for a in alts]
    return " AND ".join(clauses), params


def _next_order(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM locations").fetchone()
    return int(row[0])


def _upsert(request: Request, conn: sqlite3.Connection, loc: Location, by: str | None) -> None:
    settings: Settings = request.app.state.settings
    try:
        service.upsert_location(conn, loc, max_locations=settings.max_locations, by=by)
    except service.LocationLimitError as e:
        raise HTTPException(409, str(e)) from e


def _job(conn: sqlite3.Connection, job_id: int) -> JobOut:
    row: Any = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no job {job_id}")
    return JobOut.model_validate(dict(row))
