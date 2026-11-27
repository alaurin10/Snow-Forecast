"""A request description shared by all sources, so builders stay pure and testable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from snowwatch.http import Fetcher


@dataclass(frozen=True)
class Request:
    name: str
    source: str
    url: str
    params: dict[str, str] = field(default_factory=dict)
    weight: float = 0.0


def fetch(
    fetcher: Fetcher,
    req: Request,
    *,
    cache_key: str | None = None,
    optional: bool = False,
    allow_fallback: bool = True,
) -> Any:
    """GET a request. `optional`: a run can do without it, so it leaves room in the
    public budget for the required forecasts; `allow_fallback`: may retry on the public
    API when the self-hosted server fails."""
    return fetcher.get_json(
        req.url,
        req.params or None,
        source=req.source,
        cache_key=cache_key,
        weight=req.weight,
        optional=optional,
        allow_fallback=allow_fallback,
    )
