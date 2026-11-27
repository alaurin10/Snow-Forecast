# Deployment notes: the home setup

One real installation of Snow Watch, as an example to adapt: a mini PC at home
(Proxmox, with a Debian Docker VM), published at `https://snow.andrewlaurin.com`
through the Cloudflare Tunnel that the Home Assistant VM already runs. No router
port is open: the tunnel is outbound only.

The general steps are in [`DEPLOYMENT.md`](DEPLOYMENT.md); this file only adds
what is specific to this machine.

## What runs where

| Where | What |
|---|---|
| Docker VM (Debian 12) | `api` (port 8090), `worker` and `openmeteo` (self-hosted forecasts), from `/opt/snow-forecast` |
| Home Assistant VM | The Cloudflared app, which also runs the tunnel for `ha.` and `dash.` |
| Cloudflare | DNS and the tunnel edge (HTTPS) |

## Machine-specific steps

1. **VM size:** give the Docker VM 4 cores, 10 GB of memory, a 60 GB disk and the CPU
   type `host` (Proxmox: VM → Hardware → Processors → Type). `host` passes AVX2 through,
   which the self-hosted Open-Meteo server needs (the default type hides it); the
   memory covers the frontend build next to the other stacks plus the server. The disk
   can't grow here: the mini PC has 128 GB and Home Assistant OS holds 64 GB, which it
   can't give back. 60 GB is enough: about 14 GB for the app, its data and images, the
   server's cache (`OPEN_METEO_CACHE_SIZE=10GB`, reserved in full when it starts) and,
   with self-hosted ensembles (OPEN-METEO-PLAN.md, milestone 1b), 5–10 GB of downloaded
   runs. Keep 15 GB free (`df -h /`). In Nov 2026 the disk filled up: a 30 GB cache
   plus 16.8 GB of Docker build cache, which the deploy now prunes after a week;
   `docker builder prune -f` clears it all at once.
2. **Code:** the repository is private, so the VM uses a read-only deploy key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/snowwatch_deploy -N "" -C "snowwatch deploy"
   ```
   Add `~/.ssh/snowwatch_deploy.pub` under GitHub → Settings → Deploy keys (no
   write access), then:
   ```bash
   printf 'Host github-snowwatch\n  HostName github.com\n  IdentityFile ~/.ssh/snowwatch_deploy\n' >> ~/.ssh/config
   ```
   ```bash
   git clone git@github-snowwatch:alaurin10/Snow-Forecast.git /opt/snow-forecast
   ```
3. **Settings and first start:** [`DEPLOYMENT.md`](DEPLOYMENT.md) steps 1–2. In
   `.env`: `TZ=America/Los_Angeles`, `PUBLIC_URL=https://snow.andrewlaurin.com`,
   `TRUSTED_PROXY=1`, a long `OWNER_PASSWORD`.
4. **Tunnel:** in Home Assistant → Settings → Apps → Cloudflared → Configuration,
   add to `additional_hosts`, then restart the app:
   ```yaml
   - hostname: "snow.andrewlaurin.com"
     service: "http://<docker-vm-ip>:8090"
   ```
5. **Self-hosted forecasts:** [`DEPLOYMENT.md`](DEPLOYMENT.md) step 5. Two lines in
   `.env` (`COMPOSE_PROFILES=openmeteo`, `OPEN_METEO_URL=http://openmeteo:8080`; drop any
   `MAX_LOCATIONS=25`), `docker compose up -d`, then `docker compose run --rm worker
   snowwatch openmeteo status` should end with `OK`. The home connection downloads
   roughly 300–450 GB a month for it.
6. **Automatic updates and monitoring:** [`DEPLOYMENT.md`](DEPLOYMENT.md) step 4
   (the timer, Uptime Kuma on `/api/health`, two Healthchecks.io checks).
7. **Check from outside**, on a phone with Wi-Fi off: the site opens, Manage asks
   for the password, Add to Home Screen works, and the router still has no
   port-forward rules.

The Home Assistant VM carries the tunnel, so the site is briefly unreachable
from outside while Home Assistant restarts. If that becomes a problem, run a
`cloudflared` container with its own tunnel token next to Snow Watch instead.

## Moving from Cloudflare Access to the owner password (version 1.0)

Before 1.0 the site sat behind Cloudflare Access, which also made the owner the
owner. Snow Watch now has its own owner password and the forecasts are public.
Once, after the timer deploys 1.0:

1. Put a long `OWNER_PASSWORD` (12+ characters), `PUBLIC_URL` and
   `TRUSTED_PROXY=1` in `.env`, and remove `ADMIN_EMAILS`, `CF_ACCESS_TEAM`,
   `CF_ACCESS_AUDS` and `DEV_ADMIN_EMAIL` (they are ignored now). Then:
   ```bash
   docker compose up -d
   ```
2. Open the site, go to Settings → Manage locations and sign in with the password.
3. In Cloudflare Zero Trust → Access → Applications, delete the two Snow Watch
   applications (the whole site, and the `admin` / `api/admin` paths). Until you
   do, Access still asks visitors to log in.
4. Read the display terms of avalanche.org and Avalanche Canada again, now that
   the ratings are public (Snow Watch shows them exactly as published, hides
   them once expired, and links to the center).

Push subscriptions made before 1.0 keep working.
