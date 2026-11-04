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


def fetch(fetcher: Fetcher, req: Request, *, cache_key: str | None = None) -> Any:
    return fetcher.get_json(
        req.url, req.params or None, source=req.source, cache_key=cache_key, weight=req.weight
    )
