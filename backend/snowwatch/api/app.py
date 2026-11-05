"""FastAPI app: JSON under /api, plus the built frontend with an SPA fallback."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from snowwatch import __version__
from snowwatch.api.admin import make_admin_router
from snowwatch.api.auth import CurrentViewer, make_verifier
from snowwatch.api.public import make_router
from snowwatch.http import Fetcher
from snowwatch.settings import Settings, get_settings
from snowwatch.store.db import connect


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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Snow Watch",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

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
    app.state.access = make_verifier(settings)
    app.state.make_fetcher = lambda: Fetcher(user_agent=settings.user_agent, tries=2, timeout_s=20)

    @app.get("/api/me")
    def me(viewer: CurrentViewer) -> dict[str, Any]:
        """Who is viewing, so the app shows owner-only controls."""
        return {"email": viewer.email, "is_owner": viewer.is_owner}

    app.include_router(make_router())
    app.include_router(make_admin_router())

    static = settings.static_root
    if static is not None and (static / "index.html").exists():
        root = static.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/") or path == "api":
                raise HTTPException(status_code=404)
            target = (root / path).resolve()
            if path and target.is_file() and target.is_relative_to(root):
                return FileResponse(target)
            return FileResponse(root / "index.html")

    return app


app = create_app()
