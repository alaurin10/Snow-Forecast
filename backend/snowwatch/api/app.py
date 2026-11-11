"""FastAPI app: JSON under /api, plus the built frontend with an SPA fallback."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from snowwatch import __version__
from snowwatch.api.admin import make_admin_router
from snowwatch.api.auth import MIN_PASSWORD, make_auth_router
from snowwatch.api.models import MetaOut
from snowwatch.api.public import make_router
from snowwatch.api.push_api import make_push_router
from snowwatch.api.ratelimit import RateLimiter
from snowwatch.config import load_forecast_config
from snowwatch.http import Fetcher
from snowwatch.maps.sat import SatOut, allowed_items, read_index
from snowwatch.settings import Settings, get_settings
from snowwatch.store.db import connect
from snowwatch.tiles import TileCache, gibs_path, gibs_tile, glyphs, s2_path, s2_tile

log = logging.getLogger("snowwatch.api")
access = logging.getLogger("snowwatch.access")


def _last_good_run(db: Path) -> dict[str, Any] | None:
    if not db.exists():
        return None
    try:
        conn = connect(db, readonly=True)
        row = conn.execute(
            "SELECT id, kind, status, started_at, finished_at, api_weight, errors_json FROM runs "
            "WHERE status IN ('ok', 'partial') AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    out = dict(row)
    out["errors"] = len(json.loads(out.pop("errors_json") or "[]"))
    return out


def inline_script_hashes(index: Path) -> list[str]:
    """CSP hashes of the inline scripts in the built index.html (SvelteKit's start-up code)."""
    if not index.exists():
        return []
    html = index.read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S)
    return [
        "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
        for s in scripts
        if s.strip()
    ]


def content_security_policy(script_hashes: list[str]) -> str:
    """What the page may load. Third parties: Mapterhorn elevation tiles (with AWS terrain
    tiles as the fallback) for 3D, shading, slope and contours (fetched),
    and any https image (webcam stills come from each resort's own server)."""
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' " + " ".join(script_hashes),
            "worker-src 'self' blob:",
            "child-src 'self' blob:",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "font-src 'self' data:",
            "connect-src 'self' https://tiles.mapterhorn.com https://s3.amazonaws.com",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    prod = settings.env == "prod"
    app = FastAPI(
        title="Snow Watch",
        version=__version__,
        # The interactive API docs are for development; the public site doesn't need them.
        docs_url=None if prod else "/api/docs",
        openapi_url=None if prod else "/api/openapi.json",
        redoc_url=None,
    )
    static = settings.static_root
    csp = content_security_policy(inline_script_hashes(static / "index.html") if static else [])
    security_headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if prod:
        security_headers["Strict-Transport-Security"] = "max-age=31536000"

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id", "")[:64] or secrets.token_hex(6)
        try:
            response = await call_next(request)
        except Exception:
            access.exception("%s %s failed [%s]", request.method, request.url.path, request_id)
            raise
        ms = (time.perf_counter() - started) * 1000
        # Errors, writes and slow requests at INFO; the steady stream of reads at DEBUG.
        level = (
            logging.INFO
            if response.status_code >= 400 or request.method != "GET" or ms > 2000
            else logging.DEBUG
        )
        access.log(
            level,
            "%s %s %d %.0f ms [%s]",
            request.method,
            request.url.path,
            response.status_code,
            ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        for name, value in security_headers.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/api/livez")
    def livez() -> dict[str, bool]:
        """Process is up. Used by the Docker healthcheck."""
        return {"ok": True}

    @app.get("/api/health")
    def health() -> JSONResponse:
        """Data freshness. 503 when there is no good run or it is older than STALE_AFTER_H."""
        run = _last_good_run(settings.database)
        stale_after_s = settings.stale_after_h * 3600
        if run is None:
            body: dict[str, Any] = {"status": "no_data", "last_run": None, "age_s": None}
            return JSONResponse(body, status_code=503)
        finished = datetime.fromisoformat(run["finished_at"])
        age_s = (datetime.now(UTC) - finished).total_seconds()
        stale = age_s > stale_after_s
        body = {
            "status": "stale" if stale else "ok",
            "last_run": run,
            "age_s": round(age_s),
            "stale_after_s": round(stale_after_s),
        }
        return JSONResponse(body, status_code=503 if stale else 200)

    app.state.settings = settings
    app.state.forecast_config = load_forecast_config(settings.config_dir / "forecast.yaml")
    app.state.make_fetcher = lambda: Fetcher(
        user_agent=settings.user_agent,
        contact_user_agent=settings.contact_user_agent,
        tries=2,
        timeout_s=20,
    )

    @app.get("/api/meta", response_model=MetaOut)
    def meta() -> MetaOut:
        """Version and the server-side numbers the app shows (budgets, alert thresholds)."""
        cfg = app.state.forecast_config
        return MetaOut(
            version=__version__,
            commit=settings.git_commit or None,
            open_meteo_daily_budget=settings.open_meteo_daily_budget,
            powder_cm=cfg.flags.powder_cm,
            storm_cm=cfg.flags.storm_cm,
            snowfall_cm_per_mm=cfg.snowfall_cm_per_mm,
        )

    @app.get("/api/precip")
    def precip_index() -> FileResponse:
        """The map's precipitation timeline: frame files, times and the box they cover."""
        path = settings.precip_dir / "index.json"
        if not path.exists():
            raise HTTPException(503, "precipitation frames not ready yet")
        return FileResponse(
            path, media_type="application/json", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/precip/{name}")
    def precip_frame(name: str) -> FileResponse:
        """One frame. Names carry a hash of the pixels, so they never change."""
        if not re.fullmatch(r"[rnft]\d+-[0-9a-f]{12}\.png", name):
            raise HTTPException(404)
        path = settings.precip_dir / name
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    tile_cache: TileCache | None = None
    # Tiles already cached are free; each visitor may cause a burst of 300 upstream
    # fetches (a few map screens), then 10 a second.
    tile_misses = RateLimiter(rate=10, burst=300)

    def tiles() -> TileCache:
        nonlocal tile_cache
        tile_cache = tile_cache or TileCache(
            settings.tiles_dir, settings.user_agent, max_bytes=settings.tiles_max_mb * 1_000_000
        )
        return tile_cache

    @app.get("/api/tiles/{layer}/{z}/{x}/{y}.png")
    def tile(layer: str, z: int, x: int, y: int, request: Request) -> Response:
        """Base map and ski-run tiles, cached here (see snowwatch/tiles.py)."""
        cache = tiles()
        if not cache.cached(layer, z, x, y):
            tile_misses.check(request)
        got = cache.get(layer, z, x, y)
        if got is None:
            raise HTTPException(404)
        data, media_type = got
        return Response(
            data, media_type=media_type, headers={"Cache-Control": "public, max-age=604800"}
        )

    # The satellite index, re-read when the worker rewrites it: (mtime, index, item ids).
    sat_cache: dict[str, tuple[float, SatOut | None, set[str]]] = {}

    def sat_index() -> tuple[SatOut | None, set[str]]:
        path = settings.sat_dir / "index.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None, set()
        hit = sat_cache.get("index")
        if hit is None or hit[0] != mtime:
            index = read_index(path)
            hit = (mtime, index, allowed_items(index))
            sat_cache["index"] = hit
        return hit[1], hit[2]

    @app.get("/api/sat", response_model=SatOut)
    def sat() -> SatOut:
        """Recent satellite imagery: the clear Sentinel-2 scenes near each location and
        the newest daily VIIRS and HLS days (see snowwatch/maps/sat.py)."""
        index, _ = sat_index()
        if index is None:
            raise HTTPException(503, "satellite scenes not looked for yet")
        return index

    @app.get("/api/tiles/s2/{mode}/{item}/{z}/{x}/{y}.webp")
    def s2(mode: str, item: str, z: int, x: int, y: int, request: Request) -> Response:
        """Sentinel-2 tiles, only for scenes in the satellite index, cached here."""
        cache = tiles()
        _, allowed = sat_index()
        path = s2_path(cache, mode, item, z, x, y, allowed)
        if path is None:
            raise HTTPException(404)
        if not path.exists():
            tile_misses.check(request)
        data = s2_tile(cache, mode, item, z, x, y, allowed)
        if data is None:
            raise HTTPException(404)
        # A scene never changes.
        return Response(
            data, media_type="image/webp", headers={"Cache-Control": "public, max-age=2592000"}
        )

    @app.get("/api/tiles/gibs/{layer}/{day}/{z}/{x}/{y}")
    def gibs(layer: str, day: str, z: int, x: int, y: int, request: Request) -> Response:
        """NASA GIBS daily imagery (VIIRS, HLS) for one day, cached here."""
        cache = tiles()
        path = gibs_path(cache, layer, day, z, x, y)
        if path is None:
            raise HTTPException(404)
        if not path.exists():
            tile_misses.check(request)
        got = gibs_tile(cache, layer, day, z, x, y)
        if got is None:
            raise HTTPException(404)
        data, media_type = got
        return Response(
            data, media_type=media_type, headers={"Cache-Control": "public, max-age=604800"}
        )

    @app.get("/api/glyphs/{stack}/{rng}.pbf")
    def glyph(stack: str, rng: str) -> Response:
        """Fonts for the map's labels, cached here."""
        data = glyphs(tiles(), stack, rng)
        if data is None:
            raise HTTPException(404)
        return Response(
            data,
            media_type="application/x-protobuf",
            headers={"Cache-Control": "public, max-age=2592000"},
        )

    @app.get("/api/osm/ski.geojson")
    def ski_map() -> FileResponse:
        """Ski runs, lifts and peaks around the locations (refreshed weekly by the worker)."""
        if not settings.osm_path.exists():
            raise HTTPException(503, "ski map data not fetched yet")
        return FileResponse(
            settings.osm_path,
            media_type="application/geo+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    if settings.owner_password and len(settings.owner_password) < MIN_PASSWORD:
        log.error(
            "OWNER_PASSWORD is shorter than %d characters; owner sign-in is off", MIN_PASSWORD
        )
    app.include_router(make_auth_router())
    app.include_router(make_router())
    app.include_router(make_admin_router())
    app.include_router(make_push_router())

    if static is not None and (static / "index.html").exists():
        root = static.resolve()
        fresh = {"Cache-Control": "no-cache"}  # always check for a new version
        forever = {"Cache-Control": "public, max-age=31536000, immutable"}

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/") or path == "api":
                raise HTTPException(status_code=404)
            target = (root / path).resolve()
            if path and target.is_file() and target.is_relative_to(root):
                # File names under _app/immutable carry a content hash.
                headers = forever if path.startswith("_app/immutable/") else fresh
                return FileResponse(target, headers=headers)
            return FileResponse(root / "index.html", headers=fresh)

    return app


def production_app() -> FastAPI:
    """What the server runs (`uvicorn --factory snowwatch.api.app:production_app`):
    the app with JSON-line logging."""
    from snowwatch.logs import setup_logging

    setup_logging()
    return create_app()


app = create_app()
