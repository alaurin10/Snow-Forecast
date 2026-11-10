from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from snowwatch import avalanche
from snowwatch.avalanche import AvalancheDoc, AvyDay, parse_ca, parse_us, plain_text, view
from snowwatch.http import Fetcher
from snowwatch.locations import service
from tests.helpers import FIXTURES, SEED

AVY = Path(__file__).parent / "fixtures" / "avalanche"
DENVER = ZoneInfo("America/Denver")
PACIFIC = ZoneInfo("America/Los_Angeles")


def load(name: str) -> Any:
    return json.loads((AVY / name).read_text())


def shared(name: str) -> Any:
    return json.loads(gzip.decompress((FIXTURES / "shared" / name).read_bytes()))


def ca_product(area_id: str, issued: str = "2026-12-10T16:00:00Z") -> dict[str, Any]:
    """An Avalanche Canada product shaped like the live one, with ratings and a problem."""

    def ratings(alp: str, tln: str, btl: str) -> dict[str, Any]:
        return {
            k: {"display": k, "rating": {"value": v, "display": v.title()}}
            for k, v in (("alp", alp), ("tln", tln), ("btl", btl))
        }

    return {
        "url": f"https://avalanche.ca/forecasts/{area_id}",
        "area": {"id": area_id},
        "report": {
            "forecaster": "Avalanche Canada",
            "title": "Sea To Sky",
            "timezone": "America/Vancouver",
            "dateIssued": issued,
            "validUntil": "2026-12-11T16:00:00Z",
            "highlights": "<p>Fresh wind slabs&nbsp;near ridgetops.</p>",
            "dangerRatings": [
                {
                    "date": {"value": "2026-12-10T16:00:00Z"},
                    "ratings": ratings("considerable", "moderate", "low"),
                },
                {
                    "date": {"value": "2026-12-11T16:00:00Z"},
                    "ratings": ratings("moderate", "moderate", "low"),
                },
                {
                    "date": {"value": "2026-12-12T16:00:00Z"},
                    "ratings": ratings("noRating", "noRating", "noRating"),
                },
            ],
            "problems": [
                {
                    "type": {"value": "windSlab", "display": "Wind slab"},
                    "data": {
                        "aspects": [{"value": "ne"}, {"value": "e"}],
                        "elevations": [{"value": "alp"}, {"value": "tln"}],
                        "likelihood": {"display": "Likely"},
                        "expectedSize": {"min": "1", "max": "2"},
                    },
                }
            ],
        },
    }


def test_us_rated_product() -> None:
    doc = parse_us(load("us_product_caic_2755.json"), None, "2755", DENVER)
    assert doc.provider == "nac" and doc.center_id == "CAIC"
    # Published 4 Nov 16:30 Mountain, so "current" is 5 Nov.
    assert [d.date for d in doc.days] == ["2026-11-05", "2026-11-06"]
    assert (doc.days[0].alpine, doc.days[0].treeline, doc.days[0].below) == (2, 1, 1)
    p = doc.problems[0]
    assert p.name == "Wind Slab" and p.likelihood == "possible" and p.size == "1.0–1.5"
    assert p.aspects == ["N", "NE", "E", "NW"] and p.elevations == ["alpine"]
    assert doc.summary and doc.summary.startswith("Fresh snow means")
    assert "<p>" not in doc.summary
    assert doc.expires_at == "2026-11-05T23:30+00:00"


def test_us_off_season_summary() -> None:
    layer = next(
        f for f in shared("avalanche_us_map_layer.json.gz")["features"] if str(f["id"]) == "3028"
    )
    doc = parse_us(load("us_product_nwac_3028_offseason.json"), layer, "3028", PACIFIC)
    assert doc.off_season and doc.days == [] and doc.zone == "Snoqualmie Pass"
    assert doc.link and "nwac.us" in doc.link
    v = view("snoqualmie", doc, datetime(2026, 11, 5, 12, tzinfo=UTC), PACIFIC)
    assert v.status == "no_rating" and v.today_max is None


def test_map_layer_rating_when_the_product_is_missing() -> None:
    layer = {
        "properties": {
            "name": "Zone",
            "danger_level": 3,
            "start_date": "2026-12-01T14:00:00",
            "end_date": "2026-12-02T14:00:00",
            "link": "https://example.org",
        }
    }
    doc = parse_us(None, layer, "1", PACIFIC)
    assert doc.days == [AvyDay(date="2026-12-01", alpine=3, treeline=3, below=3)]


def test_canada_product() -> None:
    doc = parse_ca(ca_product("abc"))
    assert doc.provider == "avcan" and doc.zone == "Sea To Sky"
    assert [(d.date, d.alpine, d.treeline, d.below) for d in doc.days] == [
        ("2026-12-10", 3, 2, 1),
        ("2026-12-11", 2, 2, 1),
    ]
    p = doc.problems[0]
    assert p.name == "Wind slab" and p.aspects == ["NE", "E"] and p.size == "1–2"
    assert p.elevations == ["alpine", "treeline"]
    assert doc.summary == "Fresh wind slabs near ridgetops."


def test_canada_no_forecast_and_long_titles() -> None:
    live = shared("avalanche_ca_products.json.gz")
    big = next(p for p in live if len(p["report"]["title"]) > 40)
    doc = parse_ca(big)
    assert doc.zone is None  # the title lists dozens of regions
    assert all(d.alpine is None for d in doc.days)


def test_view_expires_on_time() -> None:
    doc = parse_ca(ca_product("abc"))
    tz = ZoneInfo("America/Vancouver")
    before = view("w", doc, datetime(2026, 12, 10, 20, tzinfo=UTC), tz)
    assert before.status == "current" and before.today_max == 3
    after = view("w", doc, datetime(2026, 12, 11, 16, 1, tzinfo=UTC), tz)
    assert after.status == "expired" and after.doc is not None
    assert after.doc.days == [] and after.doc.problems == [] and after.today_max is None


def test_view_drops_past_days() -> None:
    doc = AvalancheDoc(
        provider="nac",
        center="C",
        center_id="C",
        zone="Z",
        link=None,
        issued_at=None,
        expires_at=None,
        days=[
            AvyDay(date="2026-12-01", alpine=4, treeline=4, below=4),
            AvyDay(date="2026-12-02", alpine=2, treeline=None, below=None),
        ],
    )
    v = view("x", doc, datetime(2026, 12, 2, 20, tzinfo=UTC), PACIFIC)
    assert v.status == "current" and v.today_max == 2
    assert v.doc is not None and [d.date for d in v.doc.days] == ["2026-12-02"]
    assert view("x", None, datetime.now(UTC), PACIFIC).status == "none"


def test_plain_text_keeps_paragraphs() -> None:
    assert plain_text("<p>One &amp; two.</p><p>Three<br>four</p>") == "One & two.\nThree\nfour"
    assert plain_text(None) is None and plain_text("<p></p>") is None


def transport(*, fail: bool = False) -> httpx.MockTransport:
    caic = load("us_product_caic_2755.json")
    nwac = load("us_product_nwac_3028_offseason.json")
    areas = shared("avalanche_ca_areas.json.gz")
    whistler = avalanche.find_ca_area(areas, 50.06, -122.95) or "none"

    def handler(req: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(500)
        url = str(req.url)
        if "map-layer" in url:
            return httpx.Response(200, json=shared("avalanche_us_map_layer.json.gz"))
        if "/product?" in url:
            zone = req.url.params.get("zone_id")
            return httpx.Response(200, json=caic if zone == "3023" else nwac)
        if url.endswith("/areas"):
            return httpx.Response(200, json=areas)
        if url.endswith("/products"):
            return httpx.Response(200, json=[ca_product(whistler)])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def test_refresh_stores_and_keeps_old_rows_on_failure(seeded: sqlite3.Connection) -> None:
    locs = service.list_locations(seeded)
    calls: list[str] = []
    real = transport()

    def counting(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return real.handle_request(req)

    with Fetcher(user_agent="t", transport=httpx.MockTransport(counting), tries=1) as f:
        res = avalanche.refresh(seeded, f, locs)
    assert res.errors == []
    stored = avalanche.latest(seeded)
    assert stored["crystal"].center_id == "CAIC"  # the fake answers zone 3023 with CAIC's product
    assert stored["snoqualmie"].off_season
    assert stored["whistler"].zone == "Sea To Sky"
    # Three NWAC zones and one map layer; Canada's areas and products once each.
    assert sum("/product?" in c for c in calls) == 3 and sum("map-layer" in c for c in calls) == 1
    assert sum(c.endswith("/products") for c in calls) == 1

    with Fetcher(user_agent="t", transport=transport(fail=True), tries=1) as f:
        res = avalanche.refresh(seeded, f, locs)
    assert res.errors and res.saved == 0
    assert avalanche.latest(seeded)["crystal"].center_id == "CAIC"


def test_a_failed_product_keeps_the_stored_full_forecast(seeded: sqlite3.Connection) -> None:
    locs = service.list_locations(seeded)
    with Fetcher(user_agent="t", transport=transport(), tries=1) as f:
        avalanche.refresh(seeded, f, locs)
    full = avalanche.latest(seeded)["crystal"]
    real = transport()

    def no_products(req: httpx.Request) -> httpx.Response:
        if "/product?" in str(req.url):
            return httpx.Response(500)
        return real.handle_request(req)

    with Fetcher(user_agent="t", transport=httpx.MockTransport(no_products), tries=1) as f:
        res = avalanche.refresh(seeded, f, locs)
    assert res.errors
    assert avalanche.latest(seeded)["crystal"] == full  # not replaced by the thin map layer


def test_one_broken_product_does_not_stop_the_rest(seeded: sqlite3.Connection) -> None:
    locs = service.list_locations(seeded)
    real = transport()

    def broken_ca(req: httpx.Request) -> httpx.Response:
        if str(req.url).endswith("/products"):
            return httpx.Response(200, json=[{"area": {"id": "x"}, "report": "not a dict"}])
        return real.handle_request(req)

    with Fetcher(user_agent="t", transport=httpx.MockTransport(broken_ca), tries=1) as f:
        res = avalanche.refresh(seeded, f, locs)
    assert res.saved >= 3  # the US zones still saved


def test_prune_keeps_recent(seeded: sqlite3.Connection) -> None:
    doc = parse_ca(ca_product("abc"))
    avalanche.save(seeded, "whistler", doc)
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat(timespec="seconds")
    with seeded:
        seeded.execute(
            "INSERT INTO avalanche (location_id, fetched_at, doc_json) VALUES ('whistler', ?, ?)",
            (old, doc.model_dump_json()),
        )
    assert avalanche.prune(seeded) == 1
    assert "whistler" in avalanche.latest(seeded)
