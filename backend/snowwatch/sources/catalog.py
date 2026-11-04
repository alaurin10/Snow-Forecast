"""Ski-area catalog from OpenSkiMap (OpenStreetMap data, ODbL). About 21 MB, updated daily."""

from __future__ import annotations

from snowwatch.sources.base import Request

SKI_AREAS_URL = "https://tiles.openskimap.org/geojson/ski_areas.geojson"
SOURCE = "openskimap"


def ski_areas_request() -> Request:
    return Request("ski_areas", SOURCE, SKI_AREAS_URL)
