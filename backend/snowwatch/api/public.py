"""Read-only endpoints for location data."""

from __future__ import annotations

import gzip
import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from snowwatch.api.models import (
    BandSummary,
    LocationSummary,
    OverviewPeriod,
    OverviewRow,
    RunOut,
    TrendOut,
    TrendRun,
)
from snowwatch.doc import Snapshot
from snowwatch.locations import service
from snowwatch.settings import Settings
from snowwatch.store import repo
from snowwatch.store.db import connect

CACHE = "public, max-age=300, stale-while-revalidate=3600"


def db(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    if not settings.database.exists():
        raise HTTPException(503, "no database yet; run `snowwatch init`")
    conn = connect(settings.database, readonly=True)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(db)]

# Decoded snapshots, by location: (run_id, snapshot). A newer run replaces the entry.
_snapshots: dict[str, tuple[int, Snapshot]] = {}


def latest_snapshots(conn: sqlite3.Connection) -> dict[str, Snapshot]:
    """The newest snapshot of every location, decoding only those that changed."""
    latest = {
        r["location_id"]: r["run_id"]
        for r in conn.execute(
            "SELECT location_id, MAX(run_id) AS run_id FROM snapshots GROUP BY location_id"
        )
    }
    out: dict[str, Snapshot] = {}
    for loc_id, run_id in latest.items():
        cached = _snapshots.get(loc_id)
        if cached is None or cached[0] != run_id:
            snap = repo.latest_snapshot(conn, loc_id)
            if snap is None:
                continue
            _snapshots[loc_id] = cached = (run_id, snap)
        out[loc_id] = cached[1]
    return out


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    _snapshots.clear()  # a new app may point at a different database

    @router.get("/locations", response_model=list[LocationSummary])
    def locations(conn: Conn, response: Response) -> list[LocationSummary]:
        out = []
        snaps = latest_snapshots(conn)
        for loc in service.list_locations(conn):
            item = LocationSummary(
                id=loc.id,
                name=loc.name,
                kind=loc.kind,
                region=loc.region,
                country=loc.country,
                tz=loc.tz,
                bands=[BandSummary(band=b.band, label=b.label, elev_m=b.elev_m) for b in loc.bands],
            )
            snap = snaps.get(loc.id)
            if snap is not None:
                mid = snap.bands[1]
                w5, w10 = mid.windows["next5"], mid.windows["d6_10"]
                item.run_id = snap.run_id
                item.generated_at = snap.generated_at
                item.next5_cm = w5.snow_cm
                item.next5_p10_cm = w5.ens.p10 if w5.ens else None
                item.next5_p90_cm = w5.ens.p90 if w5.ens else None
                item.d6_10_cm = w10.snow_cm
                item.last24_cm = mid.stats.last24_cm
                item.alerts = len(snap.alerts)
            out.append(item)
        response.headers["Cache-Control"] = CACHE
        return out

    @router.get("/overview", response_model=list[OverviewRow])
    def overview(conn: Conn, response: Response) -> list[OverviewRow]:
        """Every active location with its headline numbers and 20 period totals."""
        snaps = latest_snapshots(conn)
        rows = []
        for loc in service.list_locations(conn):
            row = OverviewRow(
                id=loc.id, name=loc.name, kind=loc.kind, region=loc.region, country=loc.country
            )
            snap = snaps.get(loc.id)
            if snap is not None:
                mid = snap.bands[1]
                w5, w10 = mid.windows["next5"], mid.windows["d6_10"]
                row.run_id = snap.run_id
                row.generated_at = snap.generated_at
                row.last24_cm = mid.stats.last24_cm
                row.next5_cm = w5.snow_cm
                row.next5_p10_cm = w5.ens.p10 if w5.ens else None
                row.next5_p90_cm = w5.ens.p90 if w5.ens else None
                row.d6_10_cm = w10.snow_cm
                row.alerts = [a.event or "Alert" for a in snap.alerts]
                row.snow_depth_cm = snap.snotel.depth_cm if snap.snotel else None
                row.periods = [
                    OverviewPeriod(
                        key=p.key, label=p.label, kind=p.kind, date=p.date, snow_cm=p.snow_cm
                    )
                    for p in mid.periods
                ]
            rows.append(row)
        response.headers["Cache-Control"] = CACHE
        return rows

    @router.get("/locations/{location_id}")
    def location(location_id: str, conn: Conn, request: Request) -> Response:
        """The latest snapshot, sent as stored (gzipped JSON)."""
        row = conn.execute(
            "SELECT run_id, doc_gz FROM snapshots WHERE location_id = ? "
            "ORDER BY run_id DESC LIMIT 1",
            (location_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"no forecast for {location_id!r}")
        etag = f'"{row["run_id"]}"'
        headers = {"ETag": etag, "Cache-Control": CACHE, "Vary": "Accept-Encoding"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        body: bytes = row["doc_gz"]
        if "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
        else:
            body = gzip.decompress(body)
        return Response(body, media_type="application/json", headers=headers)

    @router.get("/locations/{location_id}/trend", response_model=TrendOut)
    def trend(location_id: str, conn: Conn, runs: int = Query(10, ge=1, le=40)) -> TrendOut:
        if service.get_location(conn, location_id) is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        rows = conn.execute(
            "SELECT run_id, issued_at, target_date, snow_cm FROM forecast_daily "
            "WHERE location_id = ? AND source = 'cons' AND run_id IN ("
            "  SELECT DISTINCT run_id FROM forecast_daily WHERE location_id = ? "
            "  ORDER BY run_id DESC LIMIT ?"
            ") ORDER BY run_id, target_date",
            (location_id, location_id, runs),
        ).fetchall()
        by_run: dict[int, TrendRun] = {}
        for r in rows:
            tr = by_run.setdefault(
                r["run_id"],
                TrendRun(run_id=r["run_id"], issued_at=r["issued_at"], next5_cm=None, daily={}),
            )
            tr.daily[r["target_date"]] = r["snow_cm"]
        for tr in by_run.values():
            start = date.fromisoformat(min(tr.daily)) if tr.daily else None
            if start is not None:
                window = [(start + timedelta(days=i)).isoformat() for i in range(5)]
                vals = [tr.daily.get(d) for d in window]
                tr.next5_cm = (
                    None if any(v is None for v in vals) else round(sum(v or 0 for v in vals), 1)
                )
        return TrendOut(location_id=location_id, runs=list(by_run.values()))

    @router.get("/runs", response_model=list[RunOut])
    def runs(conn: Conn, limit: int = Query(20, ge=1, le=200)) -> list[RunOut]:
        return [RunOut.model_validate(r) for r in repo.recent_runs(conn, limit)]

    return router
