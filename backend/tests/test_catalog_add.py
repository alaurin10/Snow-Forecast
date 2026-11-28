"""Milestone 4, ~50 locations: adding several ski areas from the catalog at once."""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from snowwatch import jobs, scheduler
from snowwatch.http import Fetcher
from snowwatch.locations import service
from snowwatch.locations.from_catalog import CatalogAddError, add_from_catalog
from snowwatch.scheduler import Worker
from snowwatch.settings import Settings
from tests.helpers import config
from tests.test_admin import H, app_settings, client, fake_upstream

__all__ = ["app_settings", "client"]


def fetcher() -> Fetcher:
    return Fetcher(
        user_agent="t", transport=httpx.MockTransport(fake_upstream), sleep=lambda s: None
    )


def test_queue_several_and_skip_what_cant_be_added(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    r = client.post(
        "/api/admin/locations/catalog", json={"ids": ["ski-1", "nope", "ski-1"]}, headers=H
    )
    assert r.status_code == 202
    body = r.json()
    assert [j["arg"] for j in body["jobs"]] == ["ski-1"] and body["jobs"][0]["kind"] == "catalog"
    assert body["skipped"] == {"nope": "not in the ski-area list"}
    again = client.post("/api/admin/locations/catalog", json={"ids": ["ski-1"]}, headers=H).json()
    assert again["jobs"] == [] and again["skipped"] == {"ski-1": "already being added"}
    assert (
        client.post("/api/admin/locations/catalog", json={"ids": []}, headers=H).status_code == 422
    )


def test_the_cap_counts_what_is_queued(client: TestClient, app_settings: Settings) -> None:
    client.app.state.settings = app_settings.model_copy(update={"max_locations": 6})  # type: ignore[attr-defined]
    r = client.post("/api/admin/locations/catalog", json={"ids": ["ski-1"]}, headers=H)
    assert r.status_code == 409 and "room for 0 more" in r.json()["detail"]


def test_only_the_owner_adds(client: TestClient) -> None:
    other = TestClient(client.app)
    r = other.post("/api/admin/locations/catalog", json={"ids": ["ski-1"]}, headers=H)
    assert r.status_code in (401, 403)


def test_add_from_catalog_takes_every_suggestion(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    loc = add_from_catalog(conn, fetcher(), "ski-1", max_locations=25)
    assert loc.id == "testpeak-ski-area" and loc.catalog_ref == "ski-1" and loc.active
    assert loc.country == "US" and loc.tz == "America/Los_Angeles" and loc.nws_office == "SEW"
    assert [b.elev_m for b in loc.bands] == [1400, 1790, 2050]  # the catalog's, mid at 60 %
    assert loc.links["Resort website"] == "https://testpeak.example"
    assert service.get_location(conn, loc.id) == loc
    with pytest.raises(CatalogAddError, match="already added"):
        add_from_catalog(conn, fetcher(), "ski-1", max_locations=25)
    with pytest.raises(CatalogAddError, match="not in the ski-area list"):
        add_from_catalog(conn, fetcher(), "nope", max_locations=25)


def test_the_cap_holds_in_the_worker(client: TestClient, conn: sqlite3.Connection) -> None:
    with pytest.raises(service.LocationLimitError):
        add_from_catalog(conn, fetcher(), "ski-1", max_locations=6)
    assert service.get_location(conn, "testpeak-ski-area") is None


def test_the_worker_adds_then_fetches(
    client: TestClient,
    conn: sqlite3.Connection,
    app_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = Worker(app_settings, config())
    monkeypatch.setattr(Worker, "_fetcher", lambda self: fetcher())
    ran: list[Any] = []

    def fake_run_all(*a: Any, **kw: Any) -> tuple[int, list[Any]]:
        ran.append(kw.get("only"))
        return 1, []

    monkeypatch.setattr(scheduler, "run_all", fake_run_all)
    ok = jobs.enqueue(conn, "catalog", None, "owner", arg="ski-1")
    bad = jobs.enqueue(conn, "catalog", None, "owner", arg="ski-1")  # a second click
    w.process_jobs()
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
    assert rows[ok]["status"] == "done" and ran == [["testpeak-ski-area"]]
    assert rows[bad]["status"] == "failed" and "already added" in rows[bad]["error"]


def test_the_map_box_stays_fixed_for_locations_in_the_west() -> None:
    """50 locations across the West leave the map's box (and so its jobs) as it is; one
    outside widens it to a degree past."""
    from snowwatch.avalanche_zones import map_box
    from snowwatch.maps.region import region_for
    from tests.conftest import make_location

    box = config().map.region
    south, west, north, east = box
    pts = [
        (
            south + 0.2 + (north - south - 0.4) * i / 49,
            west + 0.2 + (east - west - 0.4) * (i % 7) / 6,
        )
        for i in range(50)
    ]
    assert region_for(pts, box) == region_for([], box)
    locs = [make_location(id=f"l{i:02d}") for i in range(3)]
    assert map_box(box, locs) == box
    far = [(61.2, -149.9)]  # Alaska
    assert region_for(far, box) != region_for([], box)
    assert map_box(box, [*locs, make_location(id="ak", bands=[
        {"band": b, "label": b, "lat": 61.2, "lon": -149.9, "elev_m": e}
        for b, e in (("base", 100), ("mid", 500), ("summit", 900))
    ])]) == (south, -150.9, 62.2, east)  # fmt: skip
