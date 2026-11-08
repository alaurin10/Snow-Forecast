# Snow Watch runbook

How to run Snow Watch on the mini PC (HP EliteDesk, Proxmox) and publish it at
`https://snow.andrewlaurin.com` behind Cloudflare Access. It follows the same
setup as Home-Hub's dashboard (`apps/dashboard/`, `docs/10-remote-access.md`).

Nothing here needs an open router port: the tunnel is outbound only.

**This is the one document for everything you do yourself.** Anything the app
can't do for you is in the checklist below, with the exact commands or clicks.

## Owner checklist

Tick these off once; each links to the step with the details.

- [ ] **First-time setup on the mini PC:** steps 1–9 below.
- [ ] **Cloudflare Access** (step 6). This is what makes you the owner (Manage
      locations) and keeps the site private. Until it's done, everyone who reaches
      the site is a viewer.
- [ ] **Avalanche data terms:** before inviting friends, read the display terms of
      [avalanche.org](https://avalanche.org) and
      [Avalanche Canada](https://avalanche.ca). Snow Watch shows ratings exactly as
      published, hides them once they expire and links to the center; check that
      this is acceptable for private use with friends.
- [ ] **Push alerts** (step 10): create the keys once, then turn alerts on on each
      phone.
- [ ] **After updating to M6** (section below): load the BC snow stations and fill
      in the Canadian locations' stations.
- [ ] **Webcams** (Everyday tasks): add any you want on the Manage page.
- [ ] **In about a week:** read the forecast scorecard and decide on the snow depth
      method (Everyday tasks → "Raw or snow-ratio depth").
- [ ] **Optional:** Banff Sunshine's nearest snow station (Floe Lake) is in BC, over
      the divide. An Alberta snow pillow would be closer; ask for it as a follow-up.

## What runs where

| Where | What |
|---|---|
| Docker VM (Debian 12) | `api` (web app + API, port 8090) and `worker` (forecast runs, backups, the map's precipitation frames every 10 min) |
| Home Assistant VM | The Cloudflared app, which already runs the tunnel for `ha.` and `dash.` |
| Cloudflare | DNS, the tunnel edge, the Access login |
| `./data` on the Docker VM | The database, the raw-response cache, backups, `precip/` (map frames and snow totals, ~2 MB), `tiles/` (cached map tiles and label fonts; unused ones pruned nightly) and `osm/` (ski runs, lifts and peaks from OpenStreetMap, refreshed weekly) |

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
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | From step 10 (push alerts; leave empty to keep alerts off) |

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
docker compose run --rm worker snowwatch avalanche refresh
```
```bash
docker compose run --rm worker snowwatch pull
```

`init` creates the database and adds the six starting locations. `lookups
refresh` loads the ski-area catalog, the SNOTEL station list and the avalanche
zones that the Manage page uses (the worker refreshes them weekly). `avalanche
refresh` fetches today's avalanche forecasts; the worker checks again after every
run and at 13:45, 15:45 and 17:45 UTC, when the centers publish. `pull` fetches
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

### 10. Push alerts (optional)

Snow Watch can send a phone or desktop notification when a powder day or a storm
first shows up in the forecast (and, if someone picks it, avalanche danger High
or Extreme). It uses the browser's own push system, so nobody needs an extra
app, and it needs the HTTPS site from steps 5–6.

1. Create the keys (once):
   ```bash
   docker compose run --rm worker snowwatch push keys
   ```
   It prints two lines, `VAPID_PUBLIC_KEY=…` and `VAPID_PRIVATE_KEY=…`.
2. Paste both lines into `.env`. Keep the private key secret, and don't change the
   keys later: that would silently cut off every phone that subscribed.
3. Restart:
   ```bash
   docker compose up -d
   ```
4. On each phone or computer:
   - **iPhone or iPad** (iOS 16.4 or newer): open `https://snow.andrewlaurin.com`
     in Safari → Share → **Add to Home Screen**. Open Snow Watch **from the Home
     Screen icon**, then More → Alerts → **Turn on alerts** → Allow → **Send a
     test**.
   - **Android:** in Chrome, More → Alerts → **Turn on alerts** → Allow → **Send a
     test**. Installing the app (⋮ → Install app) is optional.
   - **Desktop:** the same from Chrome, Edge or Firefox.
5. Pick which alerts and which locations, then **Save**. Friends can do the same
   on their own phones once they can sign in.

If the test doesn't arrive, see Troubleshooting.

## After updating to M6

If the mini PC was set up before M6 (flags, snow stations, scorecard, map,
webcams, push alerts), do this once after the timer deploys it:

1. Load the BC snow-pillow stations (and refresh the other lookups):
   ```bash
   docker compose run --rm worker snowwatch lookups refresh
   ```
2. Give Whistler, Revelstoke and Sunshine their nearest snow station (it only
   fills in locations that have none, so your other edits are kept):
   ```bash
   docker compose run --rm worker snowwatch locations stations
   ```
   It prints what it picked: Callaghan Creek, Mount Revelstoke (snow water only;
   that station has no depth sensor) and Floe Lake.
3. Fetch avalanche forecasts and a fresh forecast now instead of waiting for the
   next run:
   ```bash
   docker compose run --rm worker snowwatch avalanche refresh
   ```
   ```bash
   docker compose run --rm worker snowwatch pull
   ```
4. Push alerts: step 10.
5. Check More → **Status**: every source should show a recent success.

---

## Everyday tasks

**Add a friend:** Zero Trust → Access → the `Snow Watch` app's policy (or the
`snow-viewers` group) → add their email. They sign in with a one-time PIN sent
to that address.

**Map precipitation:** the worker redraws the frames every 10 minutes, starting
when it starts; the first build takes about a minute and a half. If the Map says
precipitation is unavailable, check the worker's log for `precipitation frames`, or
build them now:
```bash
docker compose run --rm worker snowwatch precip
```
The frames cover a box around your locations, so adding a location elsewhere moves
the box at the next pass.

**Map ski runs, lifts and peaks:** the worker fetches them from OpenStreetMap
(Overpass) at start, then weekly, or after six hours if it got nothing. If the map
shows no runs, check the worker's log for `overpass` or `ski map data`, or fetch
them now; it prints how many runs, lifts and peaks it saved:
```bash
docker compose run --rm worker snowwatch ski-map
```
Reload the Map page afterwards.

If the worker's log shows `NumPy was built with baseline optimizations ... X86_V2`,
the VM's virtual CPU type hides the processor's features. The project pins NumPy
below 2.4 so this can't happen, but setting the Docker VM's CPU type to `host` (in
Proxmox: VM → Hardware → Processors → Type) is still worth doing: it also speeds up
the forecast runs.

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

**Webcams:** More → Manage locations → **Edit** a location → **+ Add a webcam**.
Give it a name and the webcam's **page link** (what opens when tapped). If the
resort publishes a still image that updates (a link ending in `.jpg` that you can
open on its own), paste it as the **image link** and the location page shows a
thumbnail. Leave the image empty when there isn't one.

**Raw or snow-ratio depth:** after about a week of runs, open a location with a
snow station → **Observed** → **Forecast scorecard**. It compares the forecast
made the evening before with what the station measured. The two "Consensus" rows
are the two depth methods: model depth (the default) and snow-ratio depth. If
snow-ratio has the smaller mean error at most locations for a couple of weeks,
switch the default in `config/forecast.yaml`:
```yaml
depth_method: slr
```
then commit it to `main` (the timer deploys it). Switch back with `raw`.

**Push alerts for a friend:** they turn them on themselves (step 10, on their own
phone). Nothing to do on the mini PC.

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
| More → Alerts says "Push alerts aren't set up on the server yet" | The two `VAPID_…` lines are missing from `.env`, or the containers weren't restarted (`docker compose up -d`) |
| iPhone: no "Turn on alerts" button, only "Add to Home Screen" | Open Snow Watch from the Home Screen icon, not from Safari; iOS only allows push there (iOS 16.4+) |
| "Notifications are blocked for this site" | Allow notifications for the site in the browser's settings (iPhone: Settings → Notifications → Snow Watch), reload, try again |
| "Send a test" says the push service refused it | Turn alerts off and on again on that device. If it keeps failing, check the worker log: `docker compose logs worker \| grep push` |
| Status page shows a source in red | It hasn't succeeded for a day. The Last error column says why; most fix themselves on the next run |
| Observed tab: "No snow station is set" | Run `docker compose run --rm worker snowwatch locations stations` (after `lookups refresh`), or pick one when adding a location |
