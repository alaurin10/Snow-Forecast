"""ATES terrain ratings the owner supplies, for the map (docs/MAP-PLAN.md, B7.4).

There is no open feed of Avalanche Terrain Exposure Scale ratings. Avalanche Canada's
trip planner offers each area's ratings as a KMZ download, behind its own disclaimer;
the owner downloads it there and puts it in `data/overlays/` (or uploads it on the
Manage page). KMZ, KML and GeoJSON are read; each polygon or line keeps the rating its
file gives it (simple, challenging, complex, extreme, or non-avalanche terrain), found in
its fields, name, style or description. Anything without a recognisable rating is kept
as "unrated" so it's visible that the file needs a look.

The files are read when they change and served as one GeoJSON collection; nothing is
fetched from anywhere. The map draws them as published and says who published them.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel

from snowwatch.osm import simplify

Rating = Literal["non", "simple", "challenging", "complex", "extreme", "unrated"]
RATINGS: tuple[Rating, ...] = ("non", "simple", "challenging", "complex", "extreme", "unrated")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,78}\.(kmz|kml|geojson|json)")
MAX_BYTES = 20_000_000  # one file as uploaded
MAX_UNZIPPED = 60_000_000  # what a KMZ may expand to
MAX_FEATURES = 20_000
DIGITS = 5  # about a metre
TOLERANCE = 0.00002  # simplify by about 2 m: these are drawn by hand at coarser scales

_WORDS: list[tuple[re.Pattern[str], Rating]] = [
    (re.compile(r"non[- ]?avalanche", re.I), "non"),
    (re.compile(r"\bsimple\b", re.I), "simple"),
    (re.compile(r"\bchallenging\b", re.I), "challenging"),
    (re.compile(r"\bcomplex\b", re.I), "complex"),
    (re.compile(r"\bextreme\b", re.I), "extreme"),
]
# "ATES 2", "ates_3", "class 1": the scale's numbers (0 is non-avalanche terrain).
_NUMBER = re.compile(r"(?:ates|class|rating)[\s_:#=-]*([0-4])\b", re.I)
_BY_NUMBER: dict[str, Rating] = {
    "0": "non",
    "1": "simple",
    "2": "challenging",
    "3": "complex",
    "4": "extreme",
}
_KEYS = re.compile(r"ates|rating|class|exposure", re.I)


class BadOverlay(ValueError):
    """A file that can't be read as ATES ratings (the message says why, for the owner)."""


class AtesProps(BaseModel):
    rating: Rating
    name: str
    file: str


class AtesFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: AtesProps


class OverlayFile(BaseModel):
    name: str
    bytes: int
    features: int
    ratings: dict[str, int]
    error: str | None = None


class AtesOut(BaseModel):
    """Every ATES file the owner has supplied, as one collection."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[AtesFeature]
    files: list[OverlayFile]


def rating_of(texts: Iterable[str]) -> Rating:
    """The first rating named in any of the texts, tried in order."""
    for t in texts:
        if not t:
            continue
        t = t.replace("_", " ")  # "ates_complex" names a class too
        m = _NUMBER.search(t)
        if m:
            return _BY_NUMBER[m.group(1)]
        for pat, r in _WORDS:
            if pat.search(t):
                return r
        if t.strip() in _BY_NUMBER and len(t.strip()) == 1:
            return _BY_NUMBER[t.strip()]
    return "unrated"


def _ring(coords: list[list[float]]) -> list[list[float]] | None:
    pts = [[round(x, DIGITS), round(y, DIGITS)] for x, y in coords]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    s = simplify(pts, TOLERANCE)
    return s if len(s) >= 4 else pts if len(pts) >= 4 else None


def _line(coords: list[list[float]]) -> list[list[float]] | None:
    pts = [[round(x, DIGITS), round(y, DIGITS)] for x, y in coords]
    return simplify(pts, TOLERANCE) if len(pts) >= 2 else None


def _valid(c: list[float]) -> bool:
    return len(c) >= 2 and -180 <= c[0] <= 180 and -90 <= c[1] <= 90


# --- KML ------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ET.Element, name: str) -> Iterator[ET.Element]:
    return (c for c in el if _local(c.tag) == name)


def _find(el: ET.Element, *path: str) -> ET.Element | None:
    cur: ET.Element | None = el
    for p in path:
        cur = next(_children(cur, p), None) if cur is not None else None
    return cur


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _kml_coords(el: ET.Element | None) -> list[list[float]]:
    out = []
    for tok in _text(el).split():
        parts = tok.split(",")
        try:
            c = [float(parts[0]), float(parts[1])]
        except (IndexError, ValueError):
            continue
        if _valid(c):
            out.append(c)
    return out


def _kml_geoms(el: ET.Element) -> Iterator[dict[str, Any]]:
    """Polygons and lines in a Placemark, MultiGeometry included."""
    for g in el.iter():
        name = _local(g.tag)
        if name == "Polygon":
            outer = _ring(_kml_coords(_find(g, "outerBoundaryIs", "LinearRing", "coordinates")))
            if outer is None:
                continue
            holes = [
                r
                for b in _children(g, "innerBoundaryIs")
                if (r := _ring(_kml_coords(_find(b, "LinearRing", "coordinates"))))
            ]
            yield {"type": "Polygon", "coordinates": [outer, *holes]}
        elif name == "LineString":
            line = _line(_kml_coords(_find(g, "coordinates")))
            if line:
                yield {"type": "LineString", "coordinates": line}


def _kml_texts(pm: ET.Element, styles: dict[str, str]) -> list[str]:
    """Where a Placemark's rating may be written, most specific first."""
    data: list[str] = []
    other: list[str] = []
    for el in pm.iter():
        n = _local(el.tag)
        if n == "Data":
            key = el.get("name") or ""
            val = _text(_find(el, "value"))
            (data if _KEYS.search(key) else other).append(f"{key} {val}" if key else val)
        elif n == "SimpleData":
            key = el.get("name") or ""
            (data if _KEYS.search(key) else other).append(f"{key} {_text(el)}")
    style = _text(_find(pm, "styleUrl")).lstrip("#")
    return [
        *data,
        _text(_find(pm, "name")),
        style,
        styles.get(style, ""),
        *other,
        _text(_find(pm, "description")),
    ]


def read_kml(text: bytes, file: str) -> list[AtesFeature]:
    if b"<!ENTITY" in text[:4096]:
        raise BadOverlay("KML with entity declarations isn't read")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise BadOverlay(f"not valid KML ({e})") from e
    # A StyleMap's id often names the class ("ates_complex"); so may its styles' ids.
    styles = {
        el.get("id", ""): " ".join(_text(p) for p in el.iter() if _local(p.tag) == "styleUrl")
        for el in root.iter()
        if _local(el.tag) == "StyleMap"
    }
    out = []
    for pm in root.iter():
        if _local(pm.tag) != "Placemark":
            continue
        rating = rating_of(_kml_texts(pm, styles))
        name = _text(_find(pm, "name"))[:120]
        for geom in _kml_geoms(pm):
            out.append(
                AtesFeature(
                    geometry=geom, properties=AtesProps(rating=rating, name=name, file=file)
                )
            )
            if len(out) > MAX_FEATURES:
                raise BadOverlay(f"more than {MAX_FEATURES} shapes")
    return out


def read_kmz(data: bytes, file: str) -> list[AtesFeature]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise BadOverlay("not a KMZ (zip) file") from e
    with z:
        infos = [i for i in z.infolist() if i.filename.lower().endswith(".kml")]
        if not infos:
            raise BadOverlay("no KML inside the KMZ")
        if sum(i.file_size for i in infos) > MAX_UNZIPPED:
            raise BadOverlay("the KMZ unpacks to too much")
        out: list[AtesFeature] = []
        # doc.kml first, as Google Earth reads it.
        for info in sorted(infos, key=lambda i: i.filename.lower() != "doc.kml"):
            out += read_kml(z.read(info), file)
        return out


# --- GeoJSON --------------------------------------------------------------------


def _gj_geoms(g: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(g, dict):
        return
    t, c = g.get("type"), g.get("coordinates") or []
    try:
        if t == "Polygon":
            rings = [r for ring in c if (r := _ring([p[:2] for p in ring if _valid(p)]))]
            if rings:
                yield {"type": "Polygon", "coordinates": rings}
        elif t == "MultiPolygon":
            for poly in c:
                yield from _gj_geoms({"type": "Polygon", "coordinates": poly})
        elif t == "LineString":
            if line := _line([p[:2] for p in c if _valid(p)]):
                yield {"type": "LineString", "coordinates": line}
        elif t == "MultiLineString":
            for line in c:
                yield from _gj_geoms({"type": "LineString", "coordinates": line})
        elif t == "GeometryCollection":
            for sub in g.get("geometries") or []:
                yield from _gj_geoms(sub)
    except (TypeError, IndexError):
        return


def read_geojson(data: bytes, file: str) -> list[AtesFeature]:
    try:
        blob = json.loads(data)
    except ValueError as e:
        raise BadOverlay("not valid GeoJSON") from e
    feats = blob.get("features") if isinstance(blob, dict) else None
    if not isinstance(feats, list):
        raise BadOverlay("GeoJSON without a feature collection")
    out = []
    for f in feats:
        props = f.get("properties") if isinstance(f, dict) else None
        props = props if isinstance(props, dict) else {}
        named = [f"{k} {v}" for k, v in props.items() if _KEYS.search(str(k))]
        rest = [str(v) for k, v in props.items() if not _KEYS.search(str(k))]
        rating = rating_of([*named, *rest])
        name = str(props.get("name") or props.get("Name") or "")[:120]
        for geom in _gj_geoms(f.get("geometry") if isinstance(f, dict) else None):
            out.append(
                AtesFeature(
                    geometry=geom, properties=AtesProps(rating=rating, name=name, file=file)
                )
            )
            if len(out) > MAX_FEATURES:
                raise BadOverlay(f"more than {MAX_FEATURES} shapes")
    return out


def read_file(name: str, data: bytes) -> list[AtesFeature]:
    """Shapes and ratings from one file, or BadOverlay saying what's wrong."""
    if len(data) > MAX_BYTES:
        raise BadOverlay(f"bigger than {MAX_BYTES // 1_000_000} MB")
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "kmz":
        out = read_kmz(data, name)
    elif ext == "kml":
        out = read_kml(data, name)
    elif ext in ("geojson", "json"):
        out = read_geojson(data, name)
    else:
        raise BadOverlay("only .kmz, .kml and .geojson files are read")
    if not out:
        raise BadOverlay("no polygons or lines in it")
    return out


def valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name)) and ".." not in name


def files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and valid_name(p.name))


def key(directory: Path) -> tuple[tuple[str, int, float], ...]:
    """Changes whenever a file is added, removed or replaced."""
    out = []
    for p in files(directory):
        st = p.stat()
        out.append((p.name, st.st_size, st.st_mtime))
    return tuple(out)


def build(directory: Path) -> AtesOut:
    """Every file's shapes as one collection; a file that can't be read is listed with
    why, and contributes nothing."""
    feats: list[AtesFeature] = []
    listing = []
    for p in files(directory):
        data = p.read_bytes()
        try:
            got = read_file(p.name, data)
        except BadOverlay as e:
            listing.append(
                OverlayFile(name=p.name, bytes=len(data), features=0, ratings={}, error=str(e))
            )
            continue
        counts: dict[str, int] = {}
        for f in got:
            counts[f.properties.rating] = counts.get(f.properties.rating, 0) + 1
        listing.append(OverlayFile(name=p.name, bytes=len(data), features=len(got), ratings=counts))
        feats += got
    return AtesOut(features=feats, files=listing)
