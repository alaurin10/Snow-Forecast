"""Rivers, creeks and lakes named over imagery, from OpenStreetMap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from snowwatch import osm, osmlabels
from snowwatch.api.app import create_app
from snowwatch.settings import Settings


def geom(*pts: tuple[float, float]) -> list[dict[str, float]]:
    return [{"lon": x, "lat": y} for x, y in pts]


def test_a_river_mapped_as_many_ways_is_joined_into_one_line() -> None:
    a = [[0.0, 0.0], [1.0, 0.0]]
    b = [[2.0, 0.0], [1.0, 0.0]]  # drawn the other way
    c = [[2.0, 0.0], [3.0, 1.0]]
    apart = [[10.0, 10.0], [11.0, 10.0]]
    lines = osmlabels.join([c, a, apart, b])
    assert len(lines) == 2
    whole = max(lines, key=len)
    assert whole in ([[0, 0], [1, 0], [2, 0], [3, 1]], [[3, 1], [2, 0], [1, 0], [0, 0]])


def test_a_lakes_name_goes_inside_it_even_when_bent() -> None:
    # A "C": its centroid is in the open middle, on shore.
    c = [[0, 0], [10, 0], [10, 2], [2, 2], [2, 8], [10, 8], [10, 10], [0, 10], [0, 0]]
    x, y = osmlabels.label_point([[float(v) for v in p] for p in c])
    assert osm._inside([x, y], [[float(v) for v in p] for p in c])
    square = [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]
    assert abs(osmlabels.ring_area_km2(square) - 1.113**2 * 1.0) < 0.05  # ~1.1 km a side


def test_to_geojson_names_rivers_and_lakes() -> None:
    lake_ring = geom((-121.40, 47.30), (-121.33, 47.30), (-121.33, 47.36), (-121.40, 47.36))
    lake_ring.append(lake_ring[0])
    elements: list[dict[str, Any]] = [
        # One creek in two ways, and a stub too short to name.
        {
            "type": "way",
            "id": 1,
            "tags": {"waterway": "stream", "name": "Gold Creek"},
            "geometry": geom((-121.40, 47.40), (-121.39, 47.41)),
        },
        {
            "type": "way",
            "id": 2,
            "tags": {"waterway": "stream", "name": "Gold Creek"},
            "geometry": geom((-121.39, 47.41), (-121.38, 47.43)),
        },
        {
            "type": "way",
            "id": 3,
            "tags": {"waterway": "stream", "name": "Tiny Creek"},
            "geometry": geom((-121.40, 47.40), (-121.4001, 47.4001)),
        },
        # A reservoir mapped as a multipolygon, its outline in two ways.
        {
            "type": "relation",
            "id": 4,
            "tags": {"natural": "water", "water": "reservoir", "name": "Keechelus Lake"},
            "members": [
                {"type": "way", "role": "outer", "geometry": lake_ring[:3]},
                {"type": "way", "role": "outer", "geometry": lake_ring[2:]},
            ],
        },
        {
            "type": "way",
            "id": 5,
            "tags": {"natural": "water", "name": "Lost Lake"},
            "geometry": geom(
                (-121.41, 47.33), (-121.40, 47.33), (-121.40, 47.335), (-121.41, 47.33)
            ),
        },
        {"type": "way", "id": 7, "tags": {"natural": "water"}, "geometry": lake_ring},  # unnamed
    ]
    bxs = osm.boxes([(47.424, -121.418)])
    fc = osmlabels.to_geojson(elements, bxs)
    by = {(f["properties"]["kind"], f["properties"]["name"]): f for f in fc["features"]}
    assert set(by) == {
        ("water", "Gold Creek"),
        ("lake", "Keechelus Lake"),
        ("lake", "Lost Lake"),
    }
    assert len(by[("water", "Gold Creek")]["geometry"]["coordinates"]) == 3  # joined
    assert by[("water", "Gold Creek")]["properties"]["class"] == "stream"
    keech = by[("lake", "Keechelus Lake")]
    assert 20 < keech["properties"]["area"] < 40  # ~5.3 x 6.7 km
    assert osm._inside(keech["geometry"]["coordinates"], osm._coords(lake_ring))
    s, w, n, e = bxs[0]
    assert fc["boxes"] == [[w, s, e, n]]


def test_refresh_asks_twice_a_box_and_keeps_what_a_failed_box_had(tmp_path: Path) -> None:
    asked: list[str] = []
    down: set[str] = set()  # boxes (as their south edge) whose queries fail

    def answer(req: httpx.Request) -> httpx.Response:
        q = dict(httpx.QueryParams(req.content.decode()))["data"]
        asked.append(q)
        if any(f"({s}," in q for s in down):
            return httpx.Response(504)
        south = float(q.split('"name"](')[1].split(",")[0])
        if "waterway" in q:
            els = [
                {
                    "type": "way",
                    "id": int(south * 1000),
                    "tags": {"waterway": "river", "name": f"River {south}"},
                    "geometry": geom((-121.3, south + 0.1), (-121.2, south + 0.05)),
                }
            ]
        else:
            assert "out geom;" in q and "out tags geom" not in q  # relations need members
            ring = geom((-121.35, 47.55), (-121.34, 47.55), (-121.34, 47.552), (-121.35, 47.55))
            els = [
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"natural": "water", "name": "Gold Lake"},
                    "geometry": ring,
                }
            ]
        return httpx.Response(200, json={"elements": els})

    path = tmp_path / "labels.geojson"
    client = httpx.Client(transport=httpx.MockTransport(answer))
    pts = [(47.424, -121.418), (50.06, -122.95)]
    bxs = osm.boxes(pts)
    down.add(str(bxs[1][0]))  # the second box fails the first time
    assert osmlabels.refresh(path, pts, client, now=1000.0, pause=0)
    fc = json.loads(path.read_text())
    assert len(fc["boxes"]) == 1  # only the box it got; the tiles name the other
    assert sorted(f["properties"]["kind"] for f in fc["features"]) == ["lake", "water"]
    # Next hour: the good box is fresh, the failed one is tried again and now answers.
    down.clear()
    asked.clear()
    assert osmlabels.refresh(path, pts, client, now=1000.0 + 3600, pause=0)
    assert len(asked) == 2 and len(json.loads(path.read_text())["boxes"]) == 2
    # Nothing to do while both are fresh.
    assert not osmlabels.refresh(path, pts, client, now=1000.0 + 7200, pause=0)
    # A week on, every server down: the file and each box keep what they had.
    before = path.read_text()
    dead = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(504)))
    assert not osmlabels.refresh(path, pts, dead, now=1000.0 + 8 * 86400, pause=0)
    assert path.read_text() == before
    # A location removed: its box goes.
    assert osmlabels.refresh(path, pts[:1], client, now=1000.0 + 8 * 86400, pause=0)
    assert len(json.loads(path.read_text())["boxes"]) == 1
    assert len(list((tmp_path / "labels-boxes").iterdir())) == 1


def test_api_serves_the_label_file(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/osm/labels.geojson").status_code == 503  # not fetched yet
    settings.osm_labels_path.parent.mkdir(parents=True, exist_ok=True)
    settings.osm_labels_path.write_text('{"type":"FeatureCollection","boxes":[],"features":[]}')
    r = client.get("/api/osm/labels.geojson")
    assert r.status_code == 200 and r.json()["type"] == "FeatureCollection"
