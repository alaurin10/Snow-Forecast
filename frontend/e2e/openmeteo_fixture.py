"""A stand-in self-hosted Open-Meteo server for the e2e tests (e2e/serve.sh), so the API
can make spots (forecasts anywhere) with no network.

It answers any point with Crystal's saved responses (backend/tests/fixtures), moved on
by whole days so they reach from now (a spot is built for the present):
- /v1/forecast: the blend, multi-model, upper-air or clouds answer, told apart by what
  is asked for (clouds are made up, as tests/helpers.py does); a one-model request gets
  that model's columns, as the real server answers
- /v1/ensemble: Crystal's ensembles, so they come "from the server" (with
  OPEN_METEO_ENSEMBLES=local and the meta.json files written at start, they're fresh)
- /v1/elevation: ground rising 300 m a km to the north from 1,500 m at the first point,
  so a spot sits on a slope and its bands are 750 m below and above it

Usage: python openmeteo_fixture.py PORT DATA_DIR (DATA_DIR gets the ensembles' meta.json).
"""

from __future__ import annotations

import json
import math
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from snowwatch.capture import load_fixture
from snowwatch.ensembles import SYSTEMS

FIXTURES = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "live-20261104"
CRYSTAL = FIXTURES / "crystal"
CAPTURED = 1793828092  # 2026-11-04T21:34:52Z, meta.json's captured_at
DAY = 86400
# Whole days from the capture to just past now: the data keeps its time of day.
SHIFT = math.ceil((time.time() - CAPTURED) / DAY) * DAY
TIME_KEYS = {"time", "sunrise", "sunset"}


def shifted(data: Any) -> Any:
    """Every Unix time in an answer, moved on by SHIFT."""
    if isinstance(data, list):
        return [shifted(x) for x in data]
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        if k in TIME_KEYS and isinstance(v, list):
            out[k] = [t + SHIFT if isinstance(t, int | float) else t for t in v]
        else:
            out[k] = shifted(v)
    return out


NAMES = ("blend", "multi", "upper", "ens_gfs_seamless", "ens_ecmwf_ifs025", "ens_gem_global")
ANSWERS = {name: shifted(load_fixture(CRYSTAL / f"{name}.json.gz")) for name in NAMES}


def clouds(days: int) -> dict[str, Any]:
    levels = (1000, 950, 900, 850, 800, 750, 700, 650, 600, 500, 400, 300)
    start = (int(time.time()) // DAY) * DAY
    times = [start + h * 3600 for h in range(days * 24)]
    hourly: dict[str, list[float]] = {"time": times}
    for i, p in enumerate(levels):
        hourly[f"geopotential_height_{p}hPa"] = [110.0 + 700 * i] * len(times)
        hourly[f"cloud_cover_{p}hPa"] = [60.0 if p in (800, 750) else 0.0] * len(times)
    return {"timezone": "UTC", "utc_offset_seconds": 0, "hourly": hourly}


def one_model(data: Any, models: str) -> Any:
    """A saved multi-model answer as the server gives it for one model (spots ask for one
    model per request): that model's columns, without the suffix."""
    if "," in models or not models:
        return data
    suffix = f"_{models}"

    def point(p: dict[str, Any]) -> dict[str, Any]:
        h = p.get("hourly") or {}
        keep = {k[: -len(suffix)]: v for k, v in h.items() if k.endswith(suffix)}
        return {**p, "hourly": {"time": h.get("time", []), **keep}}

    return [point(p) for p in data] if isinstance(data, list) else point(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def answer(self, code: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        hourly = q.get("hourly", "").split(",")
        if url.path == "/v1/elevation":
            lats = [float(x) for x in q["latitude"].split(",")]
            n = len(q["longitude"].split(","))
            return self.answer(
                200, {"elevation": [1500 + 300 * (lat - lats[0]) * 111.2 for lat in lats[:n]]}
            )
        if url.path == "/v1/ensemble":
            key = f"ens_{q.get('models', '')}"
            return self.answer(200, ANSWERS[key]) if key in ANSWERS else self.answer(400, {})
        if url.path == "/v1/forecast":
            if "cloud_cover_850hPa" in hourly:
                return self.answer(200, clouds(int(q.get("forecast_days", "10"))))
            if "daily" in q:
                return self.answer(200, ANSWERS["blend"])
            name = "upper" if "wind_speed_850hPa" in hourly else "multi"
            return self.answer(200, one_model(ANSWERS[name], q.get("models", "")))
        self.answer(404, {"error": True, "reason": "not here"})


def main(port: int, data_dir: Path) -> None:
    # Each ensemble domain's newest run, just made, as the downloader would leave it.
    now = int(time.time())
    for parts in SYSTEMS.values():
        for part in parts:
            meta = data_dir / part.folder / "static" / "meta.json"
            meta.parent.mkdir(parents=True, exist_ok=True)
            run = {"last_run_initialisation_time": now - 7200, "data_end_time": now + 380 * 3600}
            meta.write_text(json.dumps(run))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]), Path(sys.argv[2]))
