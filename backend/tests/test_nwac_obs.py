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
    assert "Someone" not in text
    # What they wrote is kept: the summary and the signs of instability.
    austin = by_title["Austin Pass"]
    assert austin.summary == "Notes left out of the fixture."
    assert [(g.kind, g.extent) for g in austin.signs] == [
        ("avalanches_observed", None),
        ("collapsing", "widespread"),
        ("cracking", "specific"),
    ]
    assert by_title["Pan Point"].signs == []


def test_parse_keeps_the_observers_words_in_paragraphs() -> None:
    long = "<p>" + "word " * 600 + "</p>"
    feats = nwac_obs.parse(
        {
            "results": [
                item(
                    observation_summary=(
                        "<p>Thin cover&nbsp;below 5,000'.</p>\n<p>Better up high.<br>Cold.</p>"
                    ),
                    instability_summary="<p>Shooting cracks on test slopes.</p>",
                    avalanches_summary="One small natural slab.",
                    instability={
                        "cracking": True,
                        "cracking_description": "Widespread",
                        "collapsing": True,
                        "collapsing_description": "everywhere!",
                        "avalanches_caught": True,
                    },
                ),
                item(id="0b6c2f6e-3333-4222-8333-944455556666", observation_summary=long),
                item(
                    id="0b6c2f6e-4444-4222-8333-944455556666",
                    observation_summary=None,
                    instability="x",
                ),
            ]
        },
        BOX,
    )
    a, b, c = (f.properties for f in feats)
    assert a.summary == "Thin cover below 5,000'.\n\nBetter up high.\n\nCold."
    assert a.instability_note == "Shooting cracks on test slopes."
    assert a.avalanche_note == "One small natural slab."
    assert [(g.kind, g.extent) for g in a.signs] == [
        ("avalanches_caught", None),
        ("collapsing", None),  # not one of the form's words: left out
        ("cracking", "widespread"),
    ]
    assert b.summary is not None and len(b.summary) <= nwac_obs.SUMMARY_MAX + 1
    assert b.summary.endswith("word…")
    assert c.summary is None and c.signs == [] and c.instability_note is None


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
    # Crystal's Webcams tab: Silver Basin (3 km) is near; Paradise (24 km) is farther but in
    # Crystal's zone, West Slopes South. Nothing from other zones.
    body = client.get("/api/locations/crystal/nearby").json()
    groups = [(x["report"]["title"], x["group"]) for x in body["photo_reports"]]
    assert groups == [("Silver Basin", "near"), ("Paradise - Mt Rainier NP", "zone")]
    assert body["zone_name"] == "West Slopes South" and body["near_km"] == 20
    assert all(x["report"]["zone"] == "nac:3023" for x in body["photo_reports"])
    # The Backcountry tab: the same groups, photos or not (Pan Point has none).
    area = [(x["report"]["title"], x["group"]) for x in body["area_reports"]]
    assert ("Pan Point", "zone") in area and area[0] == ("Silver Basin", "near")
    assert body["area_reports"][0]["report"]["signs"] == [
        {"kind": "cracking", "extent": "specific"}
    ]
    # The Observed tab still lists every report within 60 km.
    assert {x["report"]["title"] for x in body["reports"]} >= {"Silver Basin", "Pan Point"}
    # Snoqualmie (zone 3028) has neither near.
    assert client.get("/api/locations/snoqualmie/nearby").json()["photo_reports"] == []


def test_photos_go_to_the_closest_location_and_zones_come_from_outlines(tmp_path: Path) -> None:
    from snowwatch.api import public
    from snowwatch.api.models import NearbyReport

    def rep(rid: str, km: float, zone: str | None = None) -> NearbyReport:
        props = observations.ObsProps(
            id=rid,
            title=rid,
            time="2026-11-24T20:00+00:00",
            region="",
            kinds=[],
            images=1,
            url=None,
            zone=zone,
            photos=[observations.ObsPhoto(url=f"{MEDIA}a.jpg", thumb=f"{MEDIA}b.jpg")],
        )
        return NearbyReport(report=props, distance_km=km)

    square = {
        "type": "Polygon",
        "coordinates": [[[-122, 46], [-121, 46], [-121, 47], [-122, 47], [-122, 46]]],
    }
    zfile = tmp_path / "zones.geojson"
    zfile.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "nac:3023",
                        "geometry": square,
                        "properties": {"doc": {"zone": "West Slopes South"}},
                    },
                    {"id": "nac:bad", "geometry": None},
                ]
            }
        )
    )
    index = public.read_zone_index(zfile)
    assert index is not None and [z[0] for z in index] == ["nac:3023"]
    assert public.zone_at(index, 46.5, -121.5) == "nac:3023"
    assert public.zone_at(index, 48.0, -121.5) is None
    assert public.read_zone_index(tmp_path / "none.geojson") is None

    crystal, paradise = ("crystal", 46.935, -121.475), ("paradise", 46.786, -121.735)
    reports = [
        (rep("muir", 26.0), 46.83, -121.73),  # by Paradise: in the zone (by its outline)
        (rep("silver", 2.0), 46.91, -121.49),  # by Crystal
        (rep("paradise-near", 18.0), 46.80, -121.72),  # within 20 km, but Paradise's
        (rep("east", 30.0, zone="nac:3027"), 46.9, -121.1),  # another zone
        (rep("nopics", 1.0), 46.93, -121.47),
    ]
    reports[-1][0].report.photos = []
    got = public.area_groups(
        "crystal", "nac:3023", reports, [crystal, paradise], index, photos_only=True
    )
    assert [(r.report.id, r.group) for r in got] == [
        ("silver", "near"),
        ("muir", "zone"),
        ("paradise-near", "zone"),
    ]
    at_paradise = public.area_groups(
        "paradise", "nac:3023", reports, [crystal, paradise], index, photos_only=True
    )
    assert (at_paradise[0].report.id, at_paradise[0].group) == ("paradise-near", "near")
    # A location with no known zone shows only what's near it.
    alone = public.area_groups("crystal", None, reports, [crystal], index, photos_only=True)
    assert [r.report.id for r in alone] == ["silver", "paradise-near"]


def test_area_and_availability() -> None:
    assert nwac_obs.in_area(47.4, -121.4)  # Snoqualmie Pass
    assert not nwac_obs.in_area(50.1, -122.9)  # Whistler
    assert isinstance(nwac_obs.available(), bool)
