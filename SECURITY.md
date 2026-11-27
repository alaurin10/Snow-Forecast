# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use GitHub's
**Report a vulnerability** button on the repository's Security tab. Include what
you found, how to reproduce it, and what an attacker could do with it. You should
hear back within a week.

## Supported versions

Only the latest release on `main` gets fixes.

## How Snow Watch is meant to be run

- Behind HTTPS (a reverse proxy or a tunnel), with `ENV=prod` (which
  `docker-compose.yml` sets): owner cookies are then HTTPS-only and HSTS is on.
- With a long, unique `OWNER_PASSWORD`. Anyone with it can add, change and remove
  locations; nobody else can change anything. After changing it, run
  `snowwatch owner logout-all`.
- With `TRUSTED_PROXY=1` only when a proxy that sets `X-Forwarded-For` or
  `CF-Connecting-IP` sits in front; otherwise visitors could pick their own
  address for the rate limits.
- Keep `VAPID_PRIVATE_KEY` secret: it signs push notifications.
- With `OPEN_METEO_URL` set, any visitor can ask for a forecast for a point on the map
  (`/api/spot`), which makes the API call the self-hosted Open-Meteo server, NWS and the
  public ensemble API on their behalf. Those builds are cached, rate limited per visitor
  and for the whole site, and capped at two at once (docs/ARCHITECTURE.md, "Security
  model"); `TRUSTED_PROXY` matters for those limits too.

What the app does to protect itself is described under "Security model" in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
