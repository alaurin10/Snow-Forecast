"""Recent observations from the Northwest Avalanche Center's observations page, for the
location pages' Webcams tab (their photos) and the map's field reports.

NWAC agreed to Snow Watch reading its observations page (nwac.us/observations, Nov
2026); no API key is involved. The page builds its list in the browser, so the worker
opens it in headless Chromium (Playwright, the `scrape` extra), keeps the observation
list the page loads to show, and steps through the page's own pager. It reads what a
visitor sees: where and when, the zone, who observed (forecaster or public), what kinds
of observation it has, the photos and their captions, and a link back to the
observation on nwac.us. The observer's name, contact and written notes aren't kept.

The page shows the last two weeks of observations in its map's area (NWAC's, plus the
Central Oregon center's it lists alongside); only those in Snow Watch's map box are
kept. One visit every few hours (`map.nwac_obs_minutes`); if it fails, the
last file stays as it was.

The worker image installs Chromium for this (docker/Dockerfile). Without Playwright the
job logs once and does nothing.
"""

from __future__ import annotations

import html
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from snowwatch.observations import Box, ObsFeature, ObsOut, ObsPhoto, ObsProps, read
from snowwatch.urls import clean_url

log = logging.getLogger("snowwatch.nwac_obs")

PAGE = "https://nwac.us/observations/"
REPORT = "https://nwac.us/observations/#/view/observations/{id}"
# The page's list loads from here; only these responses are read.
LIST_PATH = "/obs/v1/public/observation/list/"
NEXT = "#nac-observation-list-pagination li:last-child"
DAYS = 14  # the page's default range ("Past 2 Weeks")
MAX_PAGES = 12  # 25 observations a page
MAX_PHOTOS = 8  # per observation
# Observation photos live in avalanche.org's media bucket; anything else is dropped.
PHOTO_PREFIX = "https://avalanche-org-media.s3.us-west-2.amazonaws.com/"
PACIFIC = ZoneInfo("America/Los_Angeles")
_ID = re.compile(r"^[0-9a-f-]{8,64}$")
_WORD = re.compile(r"^[a-z_ ]{1,30}$")
_TAG = re.compile(r"<[^>]+>")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PICTURE = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_DATED = re.compile(r"^\(\d{1,2}/\d{1,2}/\d{4}\)\s*")  # captions start "(11/24/2026)"

Scraper = Callable[[int], list[Any]]


def _text(value: Any, limit: int) -> str:
    """Plain text from the page's HTML snippets: tags dropped, entities read, one line."""
    if not isinstance(value, str):
        return ""
    s = html.unescape(_TAG.sub(" ", value))
    return " ".join(s.split())[:limit]


def _photo(m: Any) -> ObsPhoto | None:
    if not isinstance(m, dict) or m.get("type") not in (None, "image"):
        return None
    urls = m.get("url")
    if not isinstance(urls, dict):
        return None

    def ok(key: str) -> str | None:
        u = clean_url(urls.get(key)) if isinstance(urls.get(key), str) else None
        rest = u[len(PHOTO_PREFIX) :] if u and u.startswith(PHOTO_PREFIX) else ""
        if not rest or any(c in rest for c in "?#\"'<> ") or ".." in rest:
            return None
        # Browsers other than Safari can't show HEIC, which phones upload.
        return u if rest.lower().endswith(_PICTURE) else None

    big = ok("large") or ok("original") or ok("medium")
    small = ok("medium") or ok("thumbnail") or big
    if big is None or small is None:
        return None
    caption = _DATED.sub("", _text(m.get("caption"), 220))[:200]
    return ObsPhoto(url=big, thumb=small, caption=caption)


def parse_photos(item: dict[str, Any]) -> list[ObsPhoto]:
    """The observation's photos, then its avalanches' photos, at most MAX_PHOTOS."""
    media = list(item.get("media") or [])
    for av in item.get("avalanches") or []:
        if isinstance(av, dict):
            media += av.get("media") or []
    out: list[ObsPhoto] = []
    seen: set[str] = set()
    for m in media:
        ph = _photo(m)
        if ph is None or ph.url in seen:
            continue
        seen.add(ph.url)
        out.append(ph)
        if len(out) >= MAX_PHOTOS:
            break
    return out


def _kinds(item: dict[str, Any]) -> list[str]:
    inst: dict[str, Any] = item.get("instability") or {}
    adv: dict[str, Any] = item.get("advanced_fields") or {}
    if not isinstance(inst, dict):
        inst = {}
    if not isinstance(adv, dict):
        adv = {}
    kinds = []
    if inst.get("avalanches_caught"):
        kinds.append("incident")
    if item.get("avalanches") or any(
        inst.get(k) for k in ("avalanches_observed", "avalanches_triggered", "avalanches_caught")
    ):
        kinds.append("avalanche")
    if inst.get("cracking") or inst.get("collapsing") or _text(adv.get("snowpack_summary"), 1):
        kinds.append("snowpack")
    if _text(adv.get("weather_summary"), 1) or adv.get("weather"):
        kinds.append("weather")
    return kinds or ["quick"]


def parse(blob: Any, box: Box) -> list[ObsFeature]:
    """The published observations in one page of the list that fall in the box. Anything
    malformed is skipped."""
    results = blob.get("results") if isinstance(blob, dict) else None
    out = []
    s, w, n, e = box
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict) or item.get("status", "published") != "published":
            continue
        try:
            pt = item["location_point"]
            lat, lon = float(pt["lat"]), float(pt["lng"])
            oid = str(item["id"])
            day = str(item["start_date"])[:10]
            noon = datetime.fromisoformat(day + "T12:00").replace(tzinfo=PACIFIC)
        except (KeyError, TypeError, ValueError):
            continue
        if not (s <= lat <= n and w <= lon <= e) or not _ID.match(oid) or not _DATE.match(day):
            continue
        photos = parse_photos(item)
        center = str(item.get("center_id") or "").upper()[:8] or None
        zone_id = str(item.get("zone_id") or "")
        observer = str(item.get("observer_type") or "").lower()
        out.append(
            ObsFeature(
                geometry={"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                properties=ObsProps(
                    id=f"nwac-{oid}",
                    title=_text(item.get("location_name"), 160),
                    time=noon.astimezone(UTC).isoformat(timespec="minutes"),
                    region=_text(item.get("zone_name"), 80),
                    kinds=_kinds(item),
                    images=len(photos),
                    url=clean_url(REPORT.format(id=oid)),
                    photos=photos,
                    source="nwac",
                    day=day,
                    center=center if center and center.isalpha() else None,
                    observer=observer if _WORD.match(observer) else None,
                    zone=f"nac:{zone_id}" if zone_id.isdigit() and len(zone_id) < 9 else None,
                ),
            )
        )
    return out


def scrape(max_pages: int = MAX_PAGES) -> list[Any]:
    """Open NWAC's observations page in headless Chromium and return each page of the
    observation list it shows, following its pager. Pictures, fonts and map tiles aren't
    downloaded, and the browser says it is Snow Watch. Raises if Playwright or Chromium
    is missing or the page doesn't load."""
    from playwright.sync_api import sync_playwright

    def is_list(r: Any) -> bool:
        return LIST_PATH in r.url and r.request.method == "GET"

    def skip(route: Any) -> None:
        req = route.request
        if req.resource_type in ("image", "font", "media") or ".mvt" in req.url:
            route.abort()
        else:
            route.continue_()

    pages: list[Any] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("SNOWWATCH_CHROMIUM") or None,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            ua = browser.new_page().evaluate("navigator.userAgent")
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 1000},
                service_workers="block",
                user_agent=f"{ua} SnowWatch (self-hosted snow forecasts)",
            )
            page = ctx.new_page()
            page.set_default_timeout(60_000)
            page.route("**/*", skip)
            with page.expect_response(is_list, timeout=90_000) as got:
                page.goto(PAGE, wait_until="domcontentloaded")
            pages.append(got.value.json())
            while len(pages) < max_pages:
                last = pages[-1] if isinstance(pages[-1], dict) else {}
                total, current = last.get("pages"), last.get("current_page")
                if not isinstance(total, int) or not isinstance(current, int):
                    break
                if current >= total:
                    break
                nxt = page.locator(NEXT)
                if not nxt.count() or "disabled" in (nxt.get_attribute("class") or ""):
                    break
                with page.expect_response(is_list) as got:
                    nxt.locator("a").click()
                pages.append(got.value.json())
        finally:
            browser.close()
    return pages


# Roughly the area the page's map shows in the browser's 1280 x 1000 window (its list
# covers that map): Washington and Oregon north of Bend, NWAC's whole area. A taller
# window shows more of Oregon but costs Chromium more memory (~600 MB at this size).
AREA: Box = (44.0, -125.3, 49.5, -116.5)


def in_area(lat: float, lon: float) -> bool:
    s, w, n, e = AREA
    return s <= lat <= n and w <= lon <= e


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def refresh(
    path: Path,
    box: Box,
    days: int = DAYS,
    now: datetime | None = None,
    scraper: Scraper | None = None,
) -> ObsOut:
    """Read the page and write the file. If it fails the old file stays, as it was."""
    now = now or datetime.now(UTC)
    days = max(1, min(days, DAYS))
    try:
        blobs = (scraper or scrape)(MAX_PAGES)
    except Exception as e:  # Playwright's errors, timeouts, a page that changed
        log.warning("NWAC observations: %s", e)
        msg = f"nwac: {type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
        old = read(path)
        if old is not None:
            return old.model_copy(update={"errors": [msg]})
        return ObsOut(generated_at=None, days=days, features=[], errors=[msg])
    first = (now.astimezone(PACIFIC) - timedelta(days=days)).date().isoformat()
    seen: set[str] = set()
    keep = []
    for blob in blobs:
        for f in parse(blob, box):
            p = f.properties
            if p.id in seen or (p.day or "") < first:
                continue
            seen.add(p.id)
            keep.append(f)
    keep.sort(key=lambda f: f.properties.time, reverse=True)
    out = ObsOut(generated_at=now.isoformat(timespec="seconds"), days=days, features=keep)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out.model_dump_json())
    tmp.replace(path)
    return out
