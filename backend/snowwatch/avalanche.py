"""Avalanche forecasts: fetch, normalise, store, and decide what may be shown.

The forecasts come from avalanche.org (US centers) and Avalanche Canada. Their
terms ask that danger ratings are shown as published and expired on time, so
they are stored apart from the forecast snapshots and checked against the clock
on every request (`view`): an expired forecast shows as Expired, never as
current. The text is the center's own, with HTML tags removed.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from snowwatch.geo import contains
from snowwatch.http import Fetcher, FetchError
from snowwatch.models import Location
from snowwatch.sources import avalanche_ca, avalanche_us
from snowwatch.sources.base import fetch
from snowwatch.store.db import utcnow_iso

log = logging.getLogger("snowwatch.avalanche")

WORDS = {1: "Low", 2: "Moderate", 3: "Considerable", 4: "High", 5: "Extreme"}
CA_LEVELS = {"low": 1, "moderate": 2, "considerable": 3, "high": 4, "extreme": 5}
Status = Literal["current", "expired", "no_rating", "none"]


class AvyDay(BaseModel):
    date: str
    alpine: int | None  # 1–5, None = no rating
    treeline: int | None
    below: int | None


class AvyProblem(BaseModel):
    name: str
    likelihood: str | None = None
    size: str | None = None  # e.g. "1–1.5"
    aspects: list[str] = []  # N, NE, …
    elevations: list[str] = []  # alpine, treeline, below


class AvalancheDoc(BaseModel):
    """One location's forecast, normalised from either provider."""

    provider: str  # nac or avcan
    center: str | None
    center_id: str | None
    zone: str | None
    link: str | None
    issued_at: str | None  # UTC ISO
    expires_at: str | None
    days: list[AvyDay] = []
    problems: list[AvyProblem] = []
    summary: str | None = None  # the center's bottom line, as published (tags removed)
    off_season: bool = False


class AvalancheView(BaseModel):
    """What the app may show right now."""

    location_id: str
    status: Status
    doc: AvalancheDoc | None
    today_max: int | None  # the highest rating for today, when current


# --- parsing -----------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"</p>|<br\s*/?>", re.IGNORECASE)


def plain_text(raw: str | None) -> str | None:
    """HTML to plain text, keeping paragraph breaks. The wording is left alone."""
    if not raw:
        return None
    text = _BREAK.sub("\n", raw)
    text = html.unescape(_TAG.sub("", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out = "\n".join(line for line in lines if line)
    return out or None


def _level(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return int(v) if 1 <= v <= 5 else None
    if isinstance(v, str):
        if v.strip().isdigit():
            return _level(int(v))
        return CA_LEVELS.get(v.strip().lower())
    return None


def _utc(text: Any) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC).isoformat(timespec="minutes")


def _forecast_day(issued_utc: str | None, tz: ZoneInfo) -> date | None:
    """The day a forecast is for: afternoon and evening issues are for the next day."""
    if not issued_utc:
        return None
    local = datetime.fromisoformat(issued_utc).astimezone(tz)
    return local.date() + timedelta(days=1) if local.hour >= 12 else local.date()


_ASPECTS = {
    "north": "N",
    "northeast": "NE",
    "east": "E",
    "southeast": "SE",
    "south": "S",
    "southwest": "SW",
    "west": "W",
    "northwest": "NW",
}
_US_ELEV = {"upper": "alpine", "middle": "treeline", "lower": "below"}


def parse_us(
    product: Mapping[str, Any] | None,
    layer: Mapping[str, Any] | None,
    zone_id: str,
    tz: ZoneInfo,
) -> AvalancheDoc:
    """avalanche.org: the zone's forecast product, with the map layer as a fallback."""
    product = product or {}
    props = (layer or {}).get("properties") or {}
    center = product.get("avalanche_center") or {}
    zone_name = props.get("name")
    link = props.get("link")
    for z in product.get("forecast_zone") or []:
        if str(z.get("id")) == str(zone_id):
            zone_name = z.get("name") or zone_name
            link = z.get("url") or link
    issued = _utc(product.get("published_time"))
    expires = _utc(product.get("expires_time"))
    days: list[AvyDay] = []
    first = _forecast_day(issued, tz)
    for d in product.get("danger") or []:
        offset = {"current": 0, "tomorrow": 1}.get(str(d.get("valid_day")))
        if offset is None or first is None:
            continue
        days.append(
            AvyDay(
                date=(first + timedelta(days=offset)).isoformat(),
                alpine=_level(d.get("upper")),
                treeline=_level(d.get("middle")),
                below=_level(d.get("lower")),
            )
        )
    if not days and _level(props.get("danger_level")) is not None:
        # No product detail: the map layer's single rating for the whole zone.
        lvl = _level(props.get("danger_level"))
        start = _utc(props.get("start_date"))
        expires = expires or _utc(props.get("end_date"))
        issued = issued or start
        day = _forecast_day(start, tz)
        if day is not None:
            days.append(AvyDay(date=day.isoformat(), alpine=lvl, treeline=lvl, below=lvl))
    problems = []
    for p in sorted(
        product.get("forecast_avalanche_problems") or [], key=lambda x: x.get("rank") or 0
    ):
        aspects: list[str] = []
        elevations: list[str] = []
        for spot in p.get("location") or []:
            words = str(spot).lower().split()
            if len(words) == 2:
                a, e = _ASPECTS.get(words[0]), _US_ELEV.get(words[1])
                if a and a not in aspects:
                    aspects.append(a)
                if e and e not in elevations:
                    elevations.append(e)
        size = p.get("size") or []
        problems.append(
            AvyProblem(
                name=str(p.get("name") or "Avalanche problem"),
                likelihood=p.get("likelihood"),
                size="–".join(str(x) for x in size) if size else None,
                aspects=aspects,
                elevations=[e for e in ("alpine", "treeline", "below") if e in elevations],
            )
        )
    return AvalancheDoc(
        provider="nac",
        center=center.get("name") or props.get("center"),
        center_id=center.get("id") or props.get("center_id"),
        zone=zone_name,
        link=link or center.get("url"),
        issued_at=issued,
        expires_at=expires,
        days=days,
        problems=problems,
        summary=plain_text(product.get("bottom_line")),
        off_season=bool(props.get("off_season")) or product.get("product_type") == "summary",
    )


def find_ca_area(areas: Mapping[str, Any], lat: float, lon: float) -> str | None:
    for f in areas.get("features") or []:
        geom = f.get("geometry")
        if geom and contains(geom, lat, lon):
            return str(f.get("id"))
    return None


def parse_ca(product: Mapping[str, Any]) -> AvalancheDoc:
    report = product.get("report") or {}
    days = []
    for d in report.get("dangerRatings") or []:
        when = _utc((d.get("date") or {}).get("value"))
        if not when:
            continue
        tz = ZoneInfo(report.get("timezone") or "America/Vancouver")
        ratings = d.get("ratings") or {}

        def lvl(key: str, ratings: Mapping[str, Any] = ratings) -> int | None:
            return _level((((ratings.get(key) or {}).get("rating")) or {}).get("value"))

        days.append(
            AvyDay(
                date=datetime.fromisoformat(when).astimezone(tz).date().isoformat(),
                alpine=lvl("alp"),
                treeline=lvl("tln"),
                below=lvl("btl"),
            )
        )
    problems = []
    for p in report.get("problems") or []:
        data = p.get("data") or {}
        size = data.get("expectedSize") or {}
        problems.append(
            AvyProblem(
                name=str((p.get("type") or {}).get("display") or "Avalanche problem"),
                likelihood=(data.get("likelihood") or {}).get("display"),
                size=f"{size.get('min')}–{size.get('max')}" if size.get("min") else None,
                aspects=[str(a.get("value")).upper() for a in data.get("aspects") or []],
                elevations=[
                    {"alp": "alpine", "tln": "treeline", "btl": "below"}.get(e.get("value"), "")
                    for e in data.get("elevations") or []
                    if e.get("value") in ("alp", "tln", "btl")
                ],
            )
        )
    title = report.get("title")
    return AvalancheDoc(
        provider="avcan",
        center=report.get("forecaster") or "Avalanche Canada",
        center_id="avcan",
        # Early and late season, one forecast covers many regions and the title
        # lists them all; show the forecaster's name instead of that list.
        zone=title if isinstance(title, str) and len(title) <= 40 else None,
        link=product.get("url"),
        issued_at=_utc(report.get("dateIssued")),
        expires_at=_utc(report.get("validUntil")),
        days=days[:2],
        problems=problems,
        summary=plain_text(report.get("highlights")),
    )


# --- what may be shown ---------------------------------------------------------


def view(location_id: str, doc: AvalancheDoc | None, now: datetime, tz: ZoneInfo) -> AvalancheView:
    """Apply expiry against the clock. Expired or past days are never shown as current."""
    if doc is None:
        return AvalancheView(location_id=location_id, status="none", doc=None, today_max=None)
    if doc.expires_at and now >= datetime.fromisoformat(doc.expires_at):
        hidden = doc.model_copy(update={"days": [], "problems": []})
        return AvalancheView(location_id=location_id, status="expired", doc=hidden, today_max=None)
    today = now.astimezone(tz).date().isoformat()
    days = [d for d in doc.days if d.date >= today]
    shown = doc.model_copy(update={"days": days})
    rated = [lvl for d in days for lvl in (d.alpine, d.treeline, d.below) if lvl is not None]
    if not rated:
        return AvalancheView(location_id=location_id, status="no_rating", doc=shown, today_max=None)
    today_levels = [
        lvl
        for d in days
        if d.date == today
        for lvl in (d.alpine, d.treeline, d.below)
        if lvl is not None
    ]
    return AvalancheView(
        location_id=location_id,
        status="current",
        doc=shown,
        today_max=max(today_levels) if today_levels else None,
    )


# --- fetch and store -----------------------------------------------------------


@dataclass
class RefreshResult:
    saved: int = 0
    errors: list[str] = field(default_factory=list)


def refresh(
    conn: sqlite3.Connection, fetcher: Fetcher, locations: Iterable[Location]
) -> RefreshResult:
    """Fetch the current forecast for every active location's zone and store it.

    Each US zone is fetched once however many locations share it; Canada's
    products and areas are fetched once. A failed fetch keeps the stored forecast.
    """
    out = RefreshResult()
    locs = [loc for loc in locations if loc.active and loc.avy is not None]
    us = [loc for loc in locs if loc.avy and loc.avy.provider == "nac" and loc.avy.zone_id]
    ca = [loc for loc in locs if loc.avy and loc.avy.provider == "avcan"]
    layer: dict[str, Any] = {}
    if us:
        try:
            data = fetch(fetcher, avalanche_us.map_layer_request())
            layer = {str(f.get("id")): f for f in data.get("features") or []}
        except FetchError as e:
            out.errors.append(f"avalanche.org map layer: {e}")
    products: dict[tuple[str, str], Any] = {}
    for loc in us:
        assert loc.avy is not None and loc.avy.center_id and loc.avy.zone_id
        key = (loc.avy.center_id, loc.avy.zone_id)
        if key not in products:
            try:
                products[key] = fetch(fetcher, avalanche_us.product_request(*key))
            except FetchError as e:
                out.errors.append(f"avalanche.org {key[0]} {key[1]}: {e}")
                products[key] = None
        if products[key] is None and key[1] not in layer:
            continue
        doc = parse_us(products[key], layer.get(key[1]), key[1], ZoneInfo(loc.tz or "UTC"))
        save(conn, loc.id, doc)
        out.saved += 1
    if ca:
        try:
            areas = fetch(fetcher, avalanche_ca.areas_request())
            prods = fetch(fetcher, avalanche_ca.products_request())
        except FetchError as e:
            out.errors.append(f"Avalanche Canada: {e}")
        else:
            by_area = {str((p.get("area") or {}).get("id")): p for p in prods or []}
            for loc in ca:
                mid = loc.band("mid")
                area = find_ca_area(areas, mid.lat, mid.lon)
                if area is None or area not in by_area:
                    continue
                save(conn, loc.id, parse_ca(by_area[area]))
                out.saved += 1
    for err in out.errors:
        log.warning(err)
    return out


def save(conn: sqlite3.Connection, location_id: str, doc: AvalancheDoc) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO avalanche (location_id, fetched_at, issued_at, expires_at, "
            "center, zone, ratings_json, problems_json, url, doc_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                location_id,
                utcnow_iso(),
                doc.issued_at,
                doc.expires_at,
                doc.center,
                doc.zone,
                json.dumps([d.model_dump() for d in doc.days]),
                json.dumps([p.model_dump() for p in doc.problems]),
                doc.link,
                doc.model_dump_json(),
            ),
        )


def latest(conn: sqlite3.Connection) -> dict[str, AvalancheDoc]:
    """The newest stored forecast per location."""
    rows = conn.execute(
        "SELECT a.location_id, a.doc_json FROM avalanche a "
        "JOIN (SELECT location_id, MAX(fetched_at) AS f FROM avalanche GROUP BY location_id) m "
        "ON a.location_id = m.location_id AND a.fetched_at = m.f "
        "WHERE a.doc_json IS NOT NULL"
    ).fetchall()
    return {r[0]: AvalancheDoc.model_validate_json(r[1]) for r in rows}


def prune(conn: sqlite3.Connection, keep_days: int = 30) -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=keep_days)).isoformat(timespec="seconds")
    with conn:
        return conn.execute("DELETE FROM avalanche WHERE fetched_at < ?", (cutoff,)).rowcount


def views(
    conn: sqlite3.Connection, tz_of: Mapping[str, str], now: datetime | None = None
) -> dict[str, AvalancheView]:
    now = now or datetime.now(UTC)
    docs = latest(conn)
    return {
        loc_id: view(loc_id, docs.get(loc_id), now, ZoneInfo(tz or "UTC"))
        for loc_id, tz in tz_of.items()
    }
