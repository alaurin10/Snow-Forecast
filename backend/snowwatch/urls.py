"""Checks for links shown to visitors: only plain http(s) addresses, of a sane length.

Links come from the owner (webcams), from upstream data (avalanche centres, the
ski-area catalog) and from stored rows written before these checks existed. A link
that fails is dropped rather than shown, so a `javascript:` address can never reach
an `href`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

MAX_URL = 500


def is_http_url(value: object, *, https_only: bool = False) -> bool:
    if not isinstance(value, str) or len(value) > MAX_URL or value != value.strip():
        return False
    try:
        u = urlsplit(value)
    except ValueError:
        return False
    schemes = ("https",) if https_only else ("http", "https")
    return u.scheme in schemes and bool(u.hostname) and not any(c.isspace() for c in value)


def check_url(value: str) -> str:
    """Pydantic validator: refuse anything but an http(s) link."""
    if not is_http_url(value):
        raise ValueError("must be an http:// or https:// link (at most 500 characters)")
    return value


def clean_url(value: str | None) -> str | None:
    """Pydantic validator for upstream data: a bad link becomes no link."""
    return value if is_http_url(value) else None


def clean_links(links: dict[str, str]) -> dict[str, str]:
    return {k[:60]: v for k, v in links.items() if is_http_url(v)}
