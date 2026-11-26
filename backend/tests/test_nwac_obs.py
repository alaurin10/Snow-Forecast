"""Observations read from NWAC's observations page (snowwatch/nwac_obs.py)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from snowwatch import nwac_obs, observations
from snowwatch.api.app import create_app
from snowwatch.settings import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "nwac" / "observations-page1.json"
BOX = (31.0, -134.0, 57.0, -102.0)
NOW = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
MEDIA = nwac_obs.PHOTO_PREFIX


def page() -> dict[str, Any]:
    blob: dict[str, Any] = json.loads(FIXTURE.read_text())
    return blob


def item(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "0b6c2f6e-1111-4222-8333-944455556666",
        "status": "published",
        "center_id": "nwac",
        "observer_type": "public",
        "name": "Someone",
        "start_date": "2026-11-24",
        "location_point": {"lat": 47.42, "lng": -121.41},
        "location_name": "Source Lake",
        "zone_name": "Snoqualmie Pass",
        "media": [],
        "avalanches": [],
        "instability": {},
        "advanced_fields": {},
    }
    return base | kw


def pic(name: str, caption: str = "") -> dict[str, Any]:
    stem, ext = name.rsplit(".", 1)
    return {
        "type": "image",
        "caption": caption,
        "url": {
            "large": f"{MEDIA}{stem}-large.{ext}",
            "medium": f"{MEDIA}{stem}-medium.{ext}",
            "original": f"{MEDIA}{name}",
            "thumbnail": f"{MEDIA}{stem}-thumbnail.{ext}",
        },
    }


def test_parse_reads_what_the_page_shows_without_names() -> None:
    feats = nwac_obs.parse(page(), BOX)
    assert len(feats) == 7
    by_title = {f.properties.title: f.properties for f in feats}
    paradise = by_title["Paradise - Mt Rainier NP"]
    assert paradise.source == "nwac" and paradise.center == "NWAC"
    assert paradise.observer == "forecaster" and paradise.region == "West Slopes South"
    assert paradise.day == "2026-11-24"
    # Noon Pacific on the day observed, so it falls on that day in the Northwest.
    assert paradise.time == "2026-11-24T20:00+00:00"
    assert paradise.url is not None and paradise.url.startswith(
        "https://nwac.us/observations/#/view/observations/"
    )
    assert len(paradise.photos) == nwac_obs.MAX_PHOTOS == paradise.images
    ph = paradise.photos[0]
    assert ph.url.endswith("-large.JPG") and ph.thumb.endswith("-medium.JPG")
    # The date in front and the HTML are gone; the photographer's credit stays.
    assert ph.caption == "Snow depth at 6,000' on a SE aspect. Photo: observer"
    # Phones' HEIC photos can't be shown in most browsers: left out.
    heic = by_title["southeast ridge at top of Cascade lift"]
    assert heic.photos == [] and heic.images == 0 and "avalanche" in heic.kinds
    # An avalanche's own photos count too (two of the observation's, two of its avalanche).
    baker = by_title["Mt baker ski area, Artist point"]
    assert "avalanche" in baker.kinds and baker.images == 4
    # Other centers the page lists alongside keep their name.
    assert by_title["Mt Bachelor"].center == "COAA"
    # Nothing of the observer is kept.
    text = json.dumps([f.model_dump() for f in feats])
    assert "Someone" not in text and "Notes left out" not in text


def test_parse_skips_bad_and_outside_items() -> None:
    blob = {
        "results": [
            item(),
            item(id="x/../y"),
            item(status="draft"),
            item(location_point={"lat": 61.0, "lng": -149.0}),  # outside the box
            item(start_date="soon"),
            item(location_point=None),
            "junk",
            item(
                id="0b6c2f6e-aaaa-4222-8333-944455556666",
                media=[
                    pic("a.jpeg", "<p>Cracks &amp; whumpfs</p>"),
                    pic("a.jpeg"),  # the same photo twice
                    {"type": "video", "url": {"large": f"{MEDIA}v.mp4"}},
                    {"type": "image", "url": {"large": "https://evil.example/a.jpg"}},
                    {"type": "image", "url": {"large": f"{MEDIA}../a.jpg"}},
                    {"type": "image", "url": "nope"},
                ],
                instability={"cracking": True, "avalanches_caught": True},
                advanced_fields={"weather_summary": "<p>Windy</p>"},
            ),
        ]
    }
    feats = nwac_obs.parse(blob, BOX)
    assert [f.properties.id for f in feats] == [
        "nwac-0b6c2f6e-1111-4222-8333-944455556666",
        "nwac-0b6c2f6e-aaaa-4222-8333-944455556666",
    ]
    plain, rich = (f.properties for f in feats)
    assert plain.kinds == ["quick"] and plain.photos == []
    assert rich.kinds == ["incident", "avalanche", "snowpack", "weather"]
    assert [p.caption for p in rich.photos] == ["Cracks & whumpfs"]
    assert nwac_obs.parse(None, BOX) == [] and nwac_obs.parse({"results": "x"}, BOX) == []


def test_refresh_writes_the_last_two_weeks_and_keeps_the_file_on_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nwac.geojson"
    old = item(id="0b6c2f6e-2222-4222-8333-944455556666", start_date="2026-11-01")
    second = {"results": [item(), old]}
    asked: list[int] = []

    def scraper(pages: int) -> list[Any]:
        asked.append(pages)
        return [page(), second, page()]  # a page read twice is listed once

    out = nwac_obs.refresh(path, BOX, now=NOW, scraper=scraper)
    assert asked == [nwac_obs.MAX_PAGES]
    ids = [f.properties.id for f in out.features]
    assert len(ids) == len(set(ids)) == 8  # the fixture's 7 and Source Lake, not Nov 1
    assert [f.properties.time for f in out.features] == sorted(
        (f.properties.time for f in out.features), reverse=True
    )
    assert out.days == 14 and out.errors == []
    assert observations.read(path) == out

    def broken(pages: int) -> list[Any]:
        raise TimeoutError("page didn't load\nmore")

    kept = nwac_obs.refresh(path, BOX, now=NOW, scraper=broken)
    assert kept.features == out.features
    assert kept.errors == ["nwac: TimeoutError: page didn't load"]
    assert observations.read(path) == out  # the file itself is untouched
    fresh = nwac_obs.refresh(tmp_path / "none.geojson", BOX, now=NOW, scraper=broken)
    assert fresh.features == [] and fresh.generated_at is None


def test_merge_puts_both_sources_together_newest_first() -> None:
    def feat(fid: str, time: str, source: Any = "min") -> observations.ObsFeature:
        return observations.ObsFeature(
            geometry={"type": "Point", "coordinates": [-121.4, 47.4]},
            properties=observations.ObsProps(
                id=fid, title=fid, time=time, region="", kinds=[], images=0, url=None, source=source
            ),
        )

    a = observations.ObsOut(
        generated_at="2026-11-25T10:00:00+00:00",
        days=14,
        features=[feat("min-1", "2026-11-24T18:00+00:00")],
        errors=["min: x"],
    )
    b = observations.ObsOut(
        generated_at="2026-11-25T12:00:00+00:00",
        days=14,
        features=[feat("nwac-1", "2026-11-24T20:00+00:00", "nwac")],
    )
    both = observations.merge(a, None, b)
    assert both is not None
    assert [f.properties.id for f in both.features] == ["nwac-1", "min-1"]
    assert both.generated_at == b.generated_at and both.errors == ["min: x"]
    assert observations.merge(None, None) is None
    # A file written before the source field existed reads as Avalanche Canada's.
    old = json.loads(a.model_dump_json())
    del old["features"][0]["properties"]["source"]
    assert observations.ObsOut.model_validate(old).features[0].properties.source == "min"


@pytest.fixture
def client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    return TestClient(
        create_app(settings.model_copy(update={"static_dir": settings.data_dir / "x"}))
    )


def test_api_serves_nwac_observations_with_avalanche_canadas(
    client: TestClient, settings: Settings, conn: sqlite3.Connection
) -> None:
    from snowwatch.locations.service import import_yaml
    from snowwatch.settings import REPO_ROOT

    import_yaml(conn, REPO_ROOT / "config" / "seed-locations.yaml", max_locations=25)
    conn.commit()
    assert client.get("/api/avalanche/observations.geojson").status_code == 503
    nwac_obs.refresh(settings.nwac_obs_path, BOX, now=NOW, scraper=lambda n: [page()])
    r = client.get("/api/avalanche/observations.geojson", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert {f["properties"]["source"] for f in r.json()["features"]} == {"nwac"}
    settings.obs_path.write_text(
        observations.ObsOut(generated_at="x", days=14, features=[]).model_dump_json()
    )
    again = client.get("/api/avalanche/observations.geojson").json()
    assert len(again["features"]) == len(r.json()["features"]) == 7
    # Silver Basin (by Crystal) shows its photos on Crystal's Webcams tab.
    body = client.get("/api/locations/crystal/nearby").json()
    titles = [x["report"]["title"] for x in body["photo_reports"]]
    assert "Silver Basin" in titles
    assert all(x["report"]["source"] == "nwac" for x in body["photo_reports"])


def test_area_and_availability() -> None:
    assert nwac_obs.in_area(47.4, -121.4)  # Snoqualmie Pass
    assert not nwac_obs.in_area(50.1, -122.9)  # Whistler
    assert isinstance(nwac_obs.available(), bool)
