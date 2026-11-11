from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from snowwatch.config import ForecastConfig, load_forecast_config
from snowwatch.models import Location
from snowwatch.settings import REPO_ROOT, Settings
from snowwatch.store.db import connect, migrate

SEED = REPO_ROOT / "config" / "seed-locations.yaml"


APP_ENV_VARS = (
    "ENV",
    "DATA_DIR",
    "DB_PATH",
    "STATIC_DIR",
    "CONFIG_DIR",
    "NWS_CONTACT",
    "OWNER_PASSWORD",
    "PUBLIC_URL",
    "TRUSTED_PROXY",
    "CONTACT_EMAIL",
    "MAX_LOCATIONS",
    "HEALTHCHECKS_RUN_URL",
    "HEALTHCHECKS_BACKUP_URL",
    "HAZARD_INDEX",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not see the real app settings of the machine they run on."""
    for name in APP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", site_spacing_s=0, max_locations=25)


@pytest.fixture
def conn(settings: Settings) -> sqlite3.Connection:
    c = connect(settings.database)
    migrate(c)
    return c


@pytest.fixture(scope="session")
def cfg() -> ForecastConfig:
    return load_forecast_config(REPO_ROOT / "config" / "forecast.yaml")


def make_location(**over: Any) -> Location:
    data: dict[str, Any] = {
        "id": "testhill",
        "name": "Test Hill",
        "kind": "resort",
        "country": "US",
        "tz": "America/Los_Angeles",
        "bands": [
            {"band": "base", "label": "Base", "lat": 47.0, "lon": -121.0, "elev_m": 1000},
            {"band": "mid", "label": "Mid", "lat": 47.0, "lon": -121.0, "elev_m": 1500},
            {"band": "summit", "label": "Top", "lat": 47.01, "lon": -121.01, "elev_m": 2000},
        ],
    }
    data.update(over)
    return Location.model_validate(data)
