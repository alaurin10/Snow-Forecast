"""Save real upstream responses as gzipped test fixtures (`snowwatch capture-fixtures`)."""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, FetchError
from snowwatch.models import Location
from snowwatch.sources import avalanche_ca, avalanche_us, nws, snotel
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import location_requests, station_request

Position = tuple[float, float, float]  # lat, lon, elevation (m)


def location_capture_requests(
    loc: Location,
    cfg: ForecastConfig,
    today: date,
    station: Position | None = None,
    *,
    rich: bool = False,
) -> list[Request]:
    """station: where the location's snow station is, for its scorecard forecast. rich:
    the longer variable lists a self-hosted server is asked for (milestone 3)."""
    mid = loc.band("mid")
    reqs = list(location_requests(loc, cfg, rich=rich))
    if station is not None:
        reqs.append(station_request(*station, cfg.models_for(loc.country)))
    if loc.country == "US":
        reqs += [nws.alerts_request(mid.lat, mid.lon), nws.points_request(mid.lat, mid.lon)]
    if loc.snotel:
        reqs += [
            snotel.daily_request(loc.snotel, today - timedelta(days=45), today),
            snotel.hourly_request(loc.snotel, today - timedelta(days=4), today),
        ]
    return reqs


def shared_capture_requests(locs: list[Location]) -> list[Request]:
    states = sorted({loc.snotel.split(":")[1] for loc in locs if loc.snotel})
    return [
        avalanche_us.map_layer_request(),
        avalanche_ca.areas_request(),
        avalanche_ca.products_request(),
        *[snotel.stations_request(s) for s in states],
    ]


def write_gz(path: Path, data: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
    path.write_bytes(blob)
    return len(blob)


def capture_fixtures(
    locs: list[Location],
    fetcher: Fetcher,
    out_dir: Path,
    cfg: ForecastConfig,
    *,
    spacing_s: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    today: date | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Fetch every request the pipeline and the parity test need, and save each response.

    Layout: `<out_dir>/<location id>/<request name>.json.gz`, shared responses in
    `<out_dir>/shared/`, and `<out_dir>/meta.json` describing every request.
    """
    today = today or date.today()
    meta: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "locations": [loc.model_dump(mode="json") for loc in locs],
        "requests": {},
        "errors": [],
    }

    def save(folder: str, req: Request) -> Any:
        key = f"{folder}/{req.name}"
        try:
            data = fetch(fetcher, req)
        except FetchError as e:
            meta["errors"].append(f"{key}: {e}")
            log(f"  ! {key}: {e}")
            return None
        size = write_gz(out_dir / folder / f"{req.name}.json.gz", data)
        meta["requests"][key] = {"url": req.url, "params": req.params, "bytes_gz": size}
        log(f"  {key} ({size / 1024:.0f} KB)")
        return data

    log("shared")
    positions: dict[str, Position] = {}
    for req in shared_capture_requests(locs):
        data = save("shared", req)
        if req.name.startswith("snotel_stations_") and isinstance(data, list):
            positions |= station_positions(data)
    for i, loc in enumerate(locs):
        if i:
            sleep(spacing_s)
        log(loc.id)
        station = positions.get(loc.snotel) if loc.snotel else None
        for req in location_capture_requests(
            loc, cfg, today, station, rich=bool(fetcher.local_url)
        ):
            save(loc.id, req)

    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    return meta


def station_positions(stations: list[Any]) -> dict[str, Position]:
    """{triplet: (lat, lon, elevation m)} from an AWDB station list (elevation in feet)."""
    out: dict[str, Position] = {}
    for s in stations:
        if not isinstance(s, dict):
            continue
        lat, lon, ft = s.get("latitude"), s.get("longitude"), s.get("elevation")
        if s.get("stationTriplet") and lat is not None and lon is not None and ft is not None:
            out[s["stationTriplet"]] = (float(lat), float(lon), float(ft) * 0.3048)
    return out


def load_fixture(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))
