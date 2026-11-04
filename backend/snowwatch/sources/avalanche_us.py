"""US avalanche forecasts from the National Avalanche Center's public API (avalanche.org).

Terms: danger ratings must be shown as published and expired on time, and their
intent must not be changed.
"""

from __future__ import annotations

from snowwatch.sources.base import Request

BASE = "https://api.avalanche.org/v2/public"
SOURCE = "avalanche-us"


def map_layer_request() -> Request:
    return Request("avalanche_us_map_layer", SOURCE, f"{BASE}/products/map-layer")


def product_request(center_id: str, zone_id: str) -> Request:
    return Request(
        "avalanche_us_product",
        SOURCE,
        f"{BASE}/product",
        {"type": "forecast", "center_id": center_id, "zone_id": zone_id},
    )
