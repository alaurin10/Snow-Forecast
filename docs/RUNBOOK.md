# Snow Watch runbook

How to run Snow Watch on the mini PC (HP EliteDesk, Proxmox) and publish it at
`https://snow.andrewlaurin.com` behind Cloudflare Access. It follows the same
setup as Home-Hub's dashboard (`apps/dashboard/`, `docs/10-remote-access.md`).

Nothing here needs an open router port: the tunnel is outbound only.

## What runs where

| Where | What |
|---|---|
| Docker VM (Debian 12) | `api` (web app + API, port 8090) and `worker` (forecast runs, backups) |
| Home Assistant VM | The Cloudflared app, which already runs the tunnel for `ha.` and `dash.` |
| Cloudflare | DNS, the tunnel edge, the Access login |
| `./data` on the Docker VM | The database, the raw-response cache and backups |

---

## First-time setup

### 1. Give the Docker VM room

In Proxmox, raise the Docker VM's RAM from 4 GB to **6 GB** (the frontend build
needs headroom next to the Garmin stacks), then reboot it. Check disk:
`df -h /` should show at least 5 GB free.

### 2. Get the code

The repo is private, so give the VM a read-only deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/snowwatch_deploy -N "" -C "snowwatch deploy"
```
```bash
cat ~/.ssh/snowwatch_deploy.pub
```

Add that public key in GitHub → alaurin10/Snow-Forecast → Settings → Deploy
keys (leave "Allow write access" off). Then:

```bash
printf 'Host github-snowwatch\n  HostName github.com\n  IdentityFile ~/.ssh/snowwatch_deploy\n' >> ~/.ssh/config
```
```bash
sudo mkdir -p /opt/snow-forecast && sudo chown "$USER" /opt/snow-forecast
```
```bash
git clone git@github-snowwatch:alaurin10/Snow-Forecast.git /opt/snow-forecast
```

### 3. Settings

```bash
cd /opt/snow-forecast && cp .env.example .env && mkdir -p data
```

Edit `.env`:

| Setting | Value |
|---|---|
| `NWS_CONTACT` | Your email (the National Weather Service asks for one) |
| `TZ` | `America/Los_Angeles` |
| `HEALTHCHECKS_RUN_URL`, `HEALTHCHECKS_BACKUP_URL` | From step 8 (optional) |

The containers run as uid 1000. If `id -u` isn't 1000, run
`sudo chown 1000:1000 data`.

### 4. Start it

```bash
docker compose up -d --build
```
```bash
docker compose run --rm worker snowwatch init
```
```bash
docker compose run --rm worker snowwatch lookups refresh
```
```bash
docker compose run --rm worker snowwatch pull
```

`init` creates the database and adds the six starting locations. `lookups
refresh` loads the ski-area catalog, the SNOTEL station list and the avalanche
zones that the Manage page uses (the worker refreshes them weekly). `pull` fetches
the first forecast (about 2–3 minutes; it pauses 20 s between locations). After
that the worker runs on its own at 03:30, 09:30, 15:30 and 21:30 UTC.

Check it on the LAN: `http://<docker-vm-ip>:8090`, and
`curl -s http://localhost:8090/api/health` should say `"status":"ok"`.

### 5. Publish it through the existing tunnel

In Home Assistant: Settings → Apps → **Cloudflared** → Configuration. Add to
`additional_hosts`:

```yaml
- hostname: "snow.andrewlaurin.com"
  service: "http://<docker-vm-ip>:8090"
```

Save and restart the app. It creates the DNS record. **Don't open the URL yet
from outside**: until step 6 it is public.

### 6. Put Cloudflare Access in front

In Cloudflare Zero Trust (one.dash.cloudflare.com) → Access → Applications:

**a. The whole site** — Add an application → Self-hosted:
- Name `Snow Watch`, domain `snow.andrewlaurin.com`.
- Policy `Allow`, Include → Emails: your email, plus anyone you invite (or an
  Access group named `snow-viewers`, which is easier to maintain).
- Login methods: Google, plus One-time PIN as a fallback.
- Session duration: **1 month**, so phones rarely ask again.
- Under Settings → CORS / cookies, leave defaults.

**b. The owner-only paths** (used from milestone M4) — another Self-hosted app:
- Domain `snow.andrewlaurin.com`, paths `admin` and `api/admin`.
- Policy `Allow`, Include → Emails: your email only.

Cloudflare applies the more specific path first, so friends can open the app
but never the admin pages. Copy each application's **AUD tag** (Overview tab)
into `.env` as `CF_ACCESS_AUDS=<aud a>,<aud b>`, set `CF_ACCESS_TEAM` to your
team name and `ADMIN_EMAILS` to your email, then `docker compose up -d`.

### 7. Turn on automatic updates

```bash
sudo cp deploy/snowwatch-deploy.service deploy/snowwatch-deploy.timer /etc/systemd/system/
```
```bash
sudo sed -i "s/REPLACE_WITH_YOUR_USER/$USER/" /etc/systemd/system/snowwatch-deploy.service
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now snowwatch-deploy.timer
```

Every 5 minutes the VM checks GitHub's `main`; when app files changed it
rebuilds and restarts. Watch it with `journalctl -u snowwatch-deploy -f`.

### 8. Monitoring

- **Uptime Kuma** (Home-Hub roadmap M1): add an HTTP monitor for
  `http://<docker-vm-ip>:8090/api/health`. It returns 503 when the forecast is
  more than 12 hours old, so the monitor catches both "down" and "stuck".
- **Healthchecks.io** (roadmap M2): create two checks, `snowwatch-run` (period
  6 h, grace 2 h) and `snowwatch-backup` (period 1 day, grace 2 h). Put their
  ping URLs in `.env` as `HEALTHCHECKS_RUN_URL` and `HEALTHCHECKS_BACKUP_URL`,
  then `docker compose up -d`. A missed ping means the worker or the whole box
  is down.

### 9. Check from outside

On a phone with **Wi-Fi off**:

- [ ] `https://snow.andrewlaurin.com` shows the Cloudflare login, then the Overview.
- [ ] A private/incognito window stops at the login page.
- [ ] `https://snow.andrewlaurin.com/admin` is refused for a friend's account.
- [ ] Add to Home Screen works (Safari: Share → Add to Home Screen; Chrome: ⋮ → Install app).
- [ ] The router still has no port-forward rules.

---

## Everyday tasks

**Add a friend:** Zero Trust → Access → the `Snow Watch` app's policy (or the
`snow-viewers` group) → add their email. They sign in with a one-time PIN sent
to that address.

**Add or change locations:** open **More → Manage locations** (owner only).
Search the catalog for a resort, or drop a trailhead and a high-point pin for a
tour; the app fills in elevations, timezone, NWS office, the nearest SNOTEL
station and the avalanche zone for you to check. The first forecast appears
within about 2 minutes of saving. The terminal route still works with a YAML export:
```bash
docker compose run --rm worker snowwatch locations export /data/locations.yaml
```
Edit `data/locations.yaml`, then:
```bash
docker compose run --rm worker snowwatch locations import /data/locations.yaml
```

**See a forecast in the terminal:** `docker compose run --rm worker snowwatch show crystal`

**Logs:** `docker compose logs -f worker` (forecast runs) and `docker compose logs -f api`.

## Backups and restore

The worker writes `data/backups/snowwatch-YYYYMMDD.db` and
`data/backups/locations-YYYYMMDD.yaml` every night at 10:00 UTC and keeps 14 of
each. The Proxmox backup of the Docker VM covers them too. Only the location
list and the forecast history are irreplaceable; forecasts regenerate on the
next run.

To restore:
```bash
docker compose stop
```
```bash
cp data/backups/snowwatch-20261120.db data/snowwatch.db && rm -f data/snowwatch.db-wal data/snowwatch.db-shm
```
```bash
docker compose up -d
```

## Rolling back a bad update

```bash
cd /opt/snow-forecast && git log --oneline -5
```
```bash
sudo systemctl stop snowwatch-deploy.timer && git checkout <good-commit> && docker compose up -d --build
```

When the fix is on `main`: `git checkout main && sudo systemctl start snowwatch-deploy.timer`.
Or restore the Docker VM's Proxmox snapshot.

## Troubleshooting

| Symptom | What to check |
|---|---|
| "The forecast hasn't updated for N hours" | `docker compose logs worker`. Is the worker running? `docker compose ps` |
| `rate limited … by an upstream API` in the logs | Open-Meteo's per-minute limit; the worker waits 65 s and retries. Fine unless it happens every run |
| The site won't load from outside, works on the LAN | The Cloudflared app in Home Assistant (is HA up? check the app's log), and the `additional_hosts` entry |
| A login loop on the phone app | Sign out of Access (`https://<team>.cloudflareaccess.com/cdn-cgi/access/logout`), close the app, open the site in the browser once, then reopen the app |
| "Your sign-in has expired" bar | Tap **Sign in again**; Access sessions last a month |
| Build fails after an update | `journalctl -u snowwatch-deploy`. The old containers keep running; fix on `main` or roll back |
| Disk filling up | `docker image prune -f`; old raw responses are pruned nightly |
