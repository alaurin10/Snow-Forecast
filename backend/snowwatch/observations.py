"""Field reports from Avalanche Canada's Mountain Information Network (MIN), for the map
(docs/MAP-PLAN.md, B7.5).

The worker writes the last two weeks of reports in the map's box to
`data/avalanche/observations.geojson` every hour: where, when, the title, which kinds of
observation it has (avalanche, snowpack, weather, incident, quick) and a link to the full
report on avalanche.ca. The reporter's name and account aren't kept. Reports are what
people saw, unchecked; the map says so.

US centers' observations need an API key (avalanche.org answers 401), so the map links
to each center instead.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from snowwatch.http import Fetcher, FetchError
from snowwatch.sources.base import Request, fetch
from snowwatch.urls import clean_url

log = logging.getLogger("snowwatch.observations")

URL = "https://api.avalanche.ca/min/en/submissions"
SOURCE = "avalanche-ca-min"
REPORT = "https://avalanche.ca/mountain-information-network/submissions/{id}"
MAX_DAYS = 30  # the API refuses more than 31 days, counting both ends
PAGE_SIZE = 500
MAX_PAGES = 6
KINDS = ("avalanche", "incident", "snowpack", "weather", "quick")

Box = tuple[float, float, float, float]  # south, west, north, east


class ObsProps(BaseModel):
    id: str
    title: str
    time: str  # UTC, ISO: when it was observed
    region: str
    kinds: list[str]  # which observation forms it has, most telling first
    images: int
    url: str | None


class ObsFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: ObsProps


class ObsOut(BaseModel):
    """Recent field reports in the map's box."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    generated_at: str | None
    days: int
    features: list[ObsFeature]
    errors: list[str] = Field(default_factory=list)


def request(start: datetime, end: datetime, page: int) -> Request:
    return Request(
        f"min_submissions_{page}",
        SOURCE,
        URL,
        {
            "fromdate": start.date().isoformat(),
            "todate": end.date().isoformat(),
            "pagesize": str(PAGE_SIZE),
            "page": str(page),
        },
    )


def parse(blob: Any, box: Box) -> list[ObsFeature]:
    """Reports in the box. Anything malformed is skipped."""
    data = ((blob or {}).get("items") or {}).get("data") if isinstance(blob, dict) else None
    out = []
    s, w, n, e = box
    for item in data if isinstance(data, list) else []:
        try:
            loc = item["location"]
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
            sid = str(item["id"])
            t = datetime.fromisoformat(str(item["datetime"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if not (s <= lat <= n and w <= lon <= e) or not sid.replace("-", "").isalnum():
            continue
        counts = item.get("observations") or {}
        kinds = [k for k in KINDS if isinstance(counts.get(k), int) and counts[k] > 0]
        out.append(
            ObsFeature(
                geometry={"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                properties=ObsProps(
                    id=sid,
                    title=str(item.get("title") or "")[:160],
                    time=t.astimezone(UTC).isoformat(timespec="minutes"),
                    region=str(item.get("region") or "")[:80],
                    kinds=kinds,
                    images=int(item.get("imageCount") or 0),
                    url=clean_url(REPORT.format(id=sid)),
                ),
            )
        )
    return out


def read(path: Path) -> ObsOut | None:
    try:
        return ObsOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def refresh(
    path: Path, fetcher: Fetcher, box: Box, days: int = 14, now: datetime | None = None
) -> ObsOut:
    """Fetch the last `days` of reports and write the file. If the network fails the old
    file stays, as it was."""
    now = now or datetime.now(UTC)
    days = max(1, min(days, MAX_DAYS))
    start = now - timedelta(days=days)
    feats: list[ObsFeature] = []
    try:
        for page in range(1, MAX_PAGES + 1):
            blob = fetch(fetcher, request(start, now, page))
            feats += parse(blob, box)
            pages = blob.get("totalPages") if isinstance(blob, dict) else None
            if not isinstance(pages, int) or page >= pages:
                break
    except FetchError as e:
        old = read(path)
        if old is not None:
            return old.model_copy(update={"errors": [f"min: {e}"]})
        return ObsOut(generated_at=None, days=days, features=[], errors=[f"min: {e}"])
    cut = start.isoformat(timespec="minutes")
    seen: set[str] = set()
    keep = []
    for f in feats:
        if f.properties.id in seen or f.properties.time < cut:
            continue
        seen.add(f.properties.id)
        keep.append(f)
    keep.sort(key=lambda f: f.properties.time, reverse=True)
    out = ObsOut(generated_at=now.isoformat(timespec="seconds"), days=days, features=keep)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out.model_dump_json())
    tmp.replace(path)
    return out
