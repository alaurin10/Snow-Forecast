"""Runtime settings, read from the environment (and `.env` in development)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from snowwatch import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # The repo-root .env (what the README describes), then one in the working
    # directory, which wins if both exist.
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    env: str = "dev"
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path | None = None
    config_dir: Path = REPO_ROOT / "config"
    static_dir: Path | None = None

    # Sent in the User-Agent; NWS asks for contact details.
    nws_contact: str = "snowwatch (self-hosted)"

    max_locations: int = 25
    open_meteo_daily_budget: int = 10_000
    site_spacing_s: float = 20.0
    stale_after_h: float = 12.0

    # Healthchecks.io ping URLs (optional): one check for forecast runs, one for backups.
    healthchecks_run_url: str = ""
    healthchecks_backup_url: str = ""

    # The owner password that unlocks the Manage page (at least 12 characters).
    # Empty = Manage is off; locations are managed with `snowwatch locations`.
    owner_password: str = ""
    # The site's public address, e.g. https://snow.example.com (used to check that
    # owner requests come from the site itself when a proxy rewrites the Host header).
    public_url: str = ""
    # Trust CF-Connecting-IP / X-Forwarded-For for the visitor's address (rate limits).
    # Turn on only behind Cloudflare or a reverse proxy that sets them.
    trusted_proxy: bool = False
    # An email for push services (the VAPID contact). Falls back to NWS_CONTACT.
    contact_email: str = ""
    # Web Push alerts: `snowwatch push keys` prints a pair. Empty = push is off.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # The git commit this build came from (set by the Docker build), shown in About.
    git_commit: str = ""
    # Most push subscriptions the server keeps (one per device).
    push_max_subscriptions: int = 500
    # Most disk the map tile cache may use; the oldest-used tiles go first.
    tiles_max_mb: int = 2000
    # The map's experimental terrain concern index (docs/MAP-PLAN.md, B7.3), for every
    # visitor: on (each browser accepts its warning once) or off for the whole site.
    hazard_index: Literal["on", "off"] = "on"

    @field_validator("hazard_index", mode="before")
    @classmethod
    def _on_off(cls, v: object) -> object:
        """on/off, also as true/false, 1/0 or yes/no; "public" and "owner" from before it
        was for everyone both mean on."""
        if isinstance(v, bool):
            return "on" if v else "off"
        if isinstance(v, str):
            w = v.strip().lower()
            if w in ("on", "true", "1", "yes", "public", "owner"):
                return "on"
            if w in ("off", "false", "0", "no"):
                return "off"
        return v

    @property
    def static_root(self) -> Path | None:
        """Where the built frontend is: STATIC_DIR, or frontend/build when it exists."""
        if self.static_dir is not None:
            return self.static_dir
        default = REPO_ROOT / "frontend" / "build"
        return default if (default / "index.html").exists() else None

    @property
    def database(self) -> Path:
        return self.db_path or self.data_dir / "snowwatch.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def heartbeat_path(self) -> Path:
        """Touched by the worker every 30 s; its health check reads the age."""
        return self.data_dir / "worker.heartbeat"

    @property
    def osm_path(self) -> Path:
        """Ski runs, lifts and peaks for the map (see snowwatch/osm.py)."""
        return self.data_dir / "osm" / "ski.geojson"

    @property
    def zones_path(self) -> Path:
        """Every avalanche forecast zone in the map's box (see snowwatch/avalanche_zones.py)."""
        return self.data_dir / "avalanche" / "zones.geojson"

    @property
    def sat_dir(self) -> Path:
        """Recent satellite scenes for the map (see snowwatch/maps/sat.py)."""
        return self.data_dir / "sat"

    @property
    def tiles_dir(self) -> Path:
        """Cached map tiles (see snowwatch/tiles.py)."""
        return self.data_dir / "tiles"

    @property
    def precip_dir(self) -> Path:
        """Precipitation frames for the map (see snowwatch/precip.py)."""
        return self.data_dir / "precip"

    @property
    def user_agent(self) -> str:
        """Sent to every upstream service. No personal details."""
        return f"snowwatch/{__version__} (self-hosted snow forecast)"

    @property
    def contact_user_agent(self) -> str:
        """Sent only to the National Weather Service, which asks for contact details."""
        return f"snowwatch/{__version__} ({self.nws_contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
