"""Field reports from Avalanche Canada's Mountain Information Network (MIN), for the map
(docs/MAP-PLAN.md, B7.5).

The worker writes the last two weeks of reports in the map's box to
`data/avalanche/observations.geojson` every hour: where, when, the title, which kinds of
observation it has (avalanche, snowpack, weather, incident, quick), its photos (address,
a small copy and the caption, for the Webcams tab) and a link to the full report on
avalanche.ca. The reporter's name and account aren't kept. Reports are what people saw,
unchecked; the map and the Webcams tab say so.

Photos are listed only in each report's own record, so a report with photos costs one
more request, once: the next refresh takes them from the file it wrote.

US centers' observations need an API key (avalanche.org's observation API answers only
the centers' own sites). NWAC agreed to its observations page being read, so
`nwac_obs.py` loads that page in a headless browser and writes its own file; `merge`
puts the two together for the map and the location pages.
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
DETAIL = URL + "/{id}"
SOURCE = "avalanche-ca-min"
REPORT = "https://avalanche.ca/mountain-information-network/submissions/{id}"
MAX_DAYS = 30  # the API refuses more than 31 days, counting both ends
PAGE_SIZE = 500
MAX_PAGES = 6
KINDS = ("avalanche", "incident", "snowpack", "weather", "quick")
MAX_DETAILS = 40  # reports whose photos are fetched in one refresh (newest first)
MAX_PHOTOS = 6  # per report
# MIN photos live on Avalanche Canada's Cloudinary account; anything else is dropped.
PHOTO_PREFIX = "https://res.cloudinary.com/avcan-min/image/upload/"

Box = tuple[float, float, float, float]  # south, west, north, east


class ObsPhoto(BaseModel):
    url: str  # a large copy (at most 1600 px wide)
    thumb: str  # a small copy (480 px wide) for the Webcams tab
    caption: str = ""
    width: int | None = None  # of the original, when the report says
    height: int | None = None


class ObsProps(BaseModel):
    id: str
    title: str
    time: str  # UTC, ISO: when it was observed (noon Pacific when only the day is known)
    region: str
    kinds: list[str]  # which observation forms it has, most telling first
    images: int
    url: str | None
    photos: list[ObsPhoto] = Field(default_factory=list)  # empty until fetched
    # Where it came from: "min" (Avalanche Canada's Mountain Information Network) or
    # "nwac" (the observations page of the Northwest Avalanche Center, nwac_obs.py).
    source: Literal["min", "nwac"] = "min"
    day: str | None = None  # the local date observed, when there's no time of day
    center: str | None = None  # the avalanche center it was sent to ("NWAC")
    observer: str | None = None  # "forecaster", "professional", "public"…
    # The avalanche forecast zone it's in, as the map's zones name them ("nac:3023"), when
    # the source says; otherwise the API looks it up from the zones' outlines.
    zone: str | None = None


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


def _sized(url: str, transform: str) -> str:
    return PHOTO_PREFIX + transform + "/" + url[len(PHOTO_PREFIX) :]


def parse_photos(blob: Any) -> list[ObsPhoto]:
    """The photos in one report's record: only Avalanche Canada's own image addresses."""
    images = blob.get("images") if isinstance(blob, dict) else None
    out = []
    for im in images if isinstance(images, list) else []:
        url = clean_url(im.get("url")) if isinstance(im, dict) else None
        rest = url[len(PHOTO_PREFIX) :] if url and url.startswith(PHOTO_PREFIX) else ""
        if url is None or not rest or any(c in rest for c in "?#,") or ".." in rest:
            continue
        w, h = im.get("width"), im.get("height")
        out.append(
            ObsPhoto(
                url=_sized(url, "c_limit,w_1600"),
                thumb=_sized(url, "c_limit,w_480"),
                caption=str(im.get("caption") or "")[:200],
                width=w if isinstance(w, int) and w > 0 else None,
                height=h if isinstance(h, int) and h > 0 else None,
            )
        )
        if len(out) >= MAX_PHOTOS:
            break
    return out


def _add_photos(fetcher: Fetcher, feats: list[ObsFeature], old: ObsOut | None) -> None:
    """Fill in each report's photos: from the last file when it has them, else from the
    report's own record (a few dozen at most per refresh; the rest wait for the next)."""
    known = {f.properties.id: f.properties.photos for f in (old.features if old else [])}
    budget = MAX_DETAILS
    for f in feats:
        p = f.properties
        if p.images <= 0:
            continue
        if known.get(p.id):
            p.photos = known[p.id]
            continue
        if budget <= 0:
            continue
        budget -= 1
        try:
            blob = fetch(fetcher, Request(f"min_submission_{p.id}", SOURCE, DETAIL.format(id=p.id)))
        except FetchError as e:
            log.warning("photos for report %s: %s", p.id, e)
            continue
        p.photos = parse_photos(blob)


def read(path: Path) -> ObsOut | None:
    try:
        return ObsOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def merge(*files: ObsOut | None) -> ObsOut | None:
    """Several report files as one, newest first: the map and the location pages show
    Avalanche Canada's reports and NWAC's observations together. None if none is there."""
    have = [f for f in files if f is not None]
    if not have:
        return None
    feats = sorted(
        (f for out in have for f in out.features), key=lambda f: f.properties.time, reverse=True
    )
    stamps = [f.generated_at for f in have if f.generated_at]
    return ObsOut(
        generated_at=max(stamps) if stamps else None,
        days=max(f.days for f in have),
        features=feats,
        errors=[e for f in have for e in f.errors],
    )


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
    _add_photos(fetcher, keep, read(path))
    out = ObsOut(generated_at=now.isoformat(timespec="seconds"), days=days, features=keep)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out.model_dump_json())
    tmp.replace(path)
    return out
