"""Who is viewing: Cloudflare Access identifies them, ADMIN_EMAILS makes them the owner.

Every request that passes Cloudflare Access carries a signed JWT in the
`Cf-Access-Jwt-Assertion` header. It is verified here against the team's public
keys, the issuer and the Access application's audience tag. A request without a
valid token (for example from the LAN, straight to port 8090) is a viewer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request

from snowwatch.settings import Settings

log = logging.getLogger("snowwatch.auth")
HEADER = "cf-access-jwt-assertion"
COOKIE = "CF_Authorization"


@dataclass(frozen=True)
class Viewer:
    email: str | None
    is_owner: bool


class AccessVerifier:
    """Verifies Cloudflare Access tokens. `key_for` is injectable for tests."""

    def __init__(
        self,
        team: str,
        audiences: list[str],
        key_for: Callable[[str], Any] | None = None,
    ) -> None:
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self.audiences = audiences
        if key_for is None:
            client = jwt.PyJWKClient(f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True)
            key_for = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self._key_for = key_for

    def email(self, token: str) -> str | None:
        try:
            claims = jwt.decode(
                token,
                self._key_for(token),
                algorithms=["RS256"],
                audience=self.audiences,
                issuer=self.issuer,
            )
        except (jwt.PyJWTError, KeyError, ValueError) as e:
            log.info("rejected Access token: %s", e)
            return None
        email = claims.get("email")
        return email.lower() if isinstance(email, str) else None


def viewer_from(request: Request) -> Viewer:
    settings: Settings = request.app.state.settings
    owners = settings.admin_email_list
    verifier: AccessVerifier | None = getattr(request.app.state, "access", None)
    if verifier is None:
        if settings.env == "dev" and settings.dev_admin_email:
            dev = settings.dev_admin_email.lower()
            return Viewer(dev, dev in owners or not owners)
        return Viewer(None, False)
    token = request.headers.get(HEADER) or request.cookies.get(COOKIE)
    email = verifier.email(token) if token else None
    return Viewer(email, email is not None and email in owners)


def make_verifier(settings: Settings) -> AccessVerifier | None:
    if settings.cf_access_team and settings.access_aud_list:
        return AccessVerifier(settings.cf_access_team, settings.access_aud_list)
    return None


def require_owner(request: Request) -> Viewer:
    v = viewer_from(request)
    if not v.is_owner:
        raise HTTPException(403, "only the owner can do this")
    return v


Owner = Annotated[Viewer, Depends(require_owner)]
CurrentViewer = Annotated[Viewer, Depends(viewer_from)]
