"""Avalanche Canada forecasts. Area ids change during the season, so zones are found by point."""

from __future__ import annotations

from snowwatch.sources.base import Request

BASE = "https://api.avalanche.ca/forecasts/en"
SOURCE = "avalanche-ca"


def areas_request() -> Request:
    return Request("avalanche_ca_areas", SOURCE, f"{BASE}/areas")


def products_request() -> Request:
    return Request("avalanche_ca_products", SOURCE, f"{BASE}/products")
