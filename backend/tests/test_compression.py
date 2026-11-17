"""Answers sent compressed (performance pass, PR 5): JSON and the app's scripts, not
pictures, and nothing compressed twice."""

from __future__ import annotations

import gzip
import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from snowwatch.api.app import create_app
from snowwatch.settings import Settings


def png(size: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), (10, 20, 30, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_the_precipitation_index_comes_compressed(settings: Settings) -> None:
    d = settings.precip_dir
    d.mkdir(parents=True)
    index = {"frames": [{"file": f"f{i}-0123456789ab.png", "t": i} for i in range(200)]}
    (d / "index.json").write_text(json.dumps(index))
    client = TestClient(create_app(settings))
    r = client.get("/api/precip", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    assert r.json() == index  # the client undoes it
    with client.stream("GET", "/api/precip", headers={"Accept-Encoding": "gzip"}) as raw:
        sent = b"".join(raw.iter_raw())
    assert len(sent) < len(json.dumps(index)) / 4
    # The security headers still go on.
    assert r.headers["x-content-type-options"] == "nosniff"
    # A client that doesn't ask for it gets it plain.
    plain = client.get("/api/precip", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == index


def test_pictures_and_small_answers_are_sent_as_they_are(settings: Settings) -> None:
    d = settings.precip_dir
    d.mkdir(parents=True)
    (d / "index.json").write_text('{"frames": []}')
    (d / "f1-0123456789ab.png").write_bytes(png(64))
    client = TestClient(create_app(settings))
    pic = client.get("/api/precip/f1-0123456789ab.png", headers={"Accept-Encoding": "gzip"})
    assert pic.status_code == 200 and "content-encoding" not in pic.headers
    # Under a kilobyte, not worth it (/api/livez is a few bytes).
    small = client.get("/api/livez", headers={"Accept-Encoding": "gzip"})
    assert small.status_code == 200 and "content-encoding" not in small.headers


def test_answers_already_compressed_are_not_compressed_again(settings: Settings) -> None:
    stations = {
        "generated_at": None,
        "errors": [],
        "stations": [{"id": str(i)} for i in range(300)],
    }
    settings.stations_path.parent.mkdir(parents=True, exist_ok=True)
    settings.stations_path.write_text(json.dumps(stations))
    client = TestClient(create_app(settings))
    # Read the raw body: compressed once means one gunzip gives the JSON.
    with client.stream("GET", "/api/map/stations", headers={"Accept-Encoding": "gzip"}) as r:
        assert r.headers["content-encoding"] == "gzip"
        raw = b"".join(r.iter_raw())
    assert json.loads(gzip.decompress(raw)) == stations


def test_frames_as_numbers_and_the_wide_radar_are_served(settings: Settings) -> None:
    d = settings.precip_dir
    (d / "wide").mkdir(parents=True)
    (d / "r1-0123456789ab.bin").write_bytes(b"\x1f\x8b numbers")
    (d / "wide" / "index.json").write_text('{"frames": []}')
    (d / "wide" / "r2-0123456789ab.bin").write_bytes(b"\x1f\x8b wide")
    client = TestClient(create_app(settings))
    r = client.get("/api/precip/r1-0123456789ab.bin", headers={"Accept-Encoding": "gzip"})
    # Already a gzip stream: sent as it is, for the browser to inflate itself.
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"
    assert "content-encoding" not in r.headers and "immutable" in r.headers["cache-control"]
    assert client.get("/api/precip/wide").json() == {"frames": []}
    assert client.get("/api/precip/wide/r2-0123456789ab.bin").content == b"\x1f\x8b wide"
    # Each route reads its own folder only; nothing from the request picks another.
    assert client.get("/api/precip/wide/r1-0123456789ab.bin").status_code == 404
    assert client.get("/api/precip/r2-0123456789ab.bin?folder=wide").status_code == 404
    assert client.get("/api/precip/wide/..%2Findex.json").status_code == 404
