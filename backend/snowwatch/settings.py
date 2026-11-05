"""Runtime settings, read from the environment (and `.env` in development)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # Owner role. ADMIN_EMAILS is comma-separated. CF_ACCESS_TEAM is the Zero Trust
    # team name (<team>.cloudflareaccess.com); CF_ACCESS_AUDS lists the AUD tags of
    # the Access applications in front of the site.
    admin_emails: str = ""
    cf_access_team: str = ""
    cf_access_auds: str = ""
    # Development only (ENV=dev and no CF_ACCESS_TEAM): treat every request as this owner.
    dev_admin_email: str = ""
    # Web Push alerts: `snowwatch push keys` prints a pair. Empty = push is off.
    vapid_public_key: str = ""
    vapid_private_key: str = ""

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
    def user_agent(self) -> str:
        return f"snowwatch/0.1 ({self.nws_contact})"

    @property
    def access_aud_list(self) -> list[str]:
        return [a.strip() for a in self.cf_access_auds.split(",") if a.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
