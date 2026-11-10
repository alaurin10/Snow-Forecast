# Deploying Snow Watch

Snow Watch runs as two Docker containers on any Linux machine with about 1.5 GB of
free memory and a few GB of disk. It needs outbound internet access (weather
services) and, to be reached from outside your network, HTTPS in front of it: a
reverse proxy (Caddy, nginx, Traefik) or a tunnel (Cloudflare Tunnel, Tailscale
Funnel). Snow Watch needs no login service of its own.

[`deploy-notes-home.md`](deploy-notes-home.md) is one complete example: a mini PC
at home behind Cloudflare Tunnel.

## 1. Get the code and settings

```bash
git clone https://github.com/alaurin10/Snow-Forecast.git /opt/snow-forecast
```
```bash
cd /opt/snow-forecast && cp .env.example .env && mkdir -p data
```

Edit `.env` (every setting is explained in the file):

| Setting | What to put |
|---|---|
| `NWS_CONTACT` | An email or URL. The US National Weather Service asks API users for one; it is sent only to them |
| `OWNER_PASSWORD` | A long password (12+ characters) for Manage locations. Leave empty to manage locations from the command line only |
| `PUBLIC_URL` | The site's address, e.g. `https://snow.example.com` |
| `TRUSTED_PROXY` | `1` if a reverse proxy or Cloudflare sits in front (so rate limits see real visitor addresses) |
| `CONTACT_EMAIL` | An email for push services (needed only for push alerts) |

The containers run as uid 1000. If that isn't your user, run
`sudo chown 1000:1000 data`.

## 2. Start it

```bash
GIT_COMMIT=$(git rev-parse --short HEAD) docker compose up -d --build
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

`init` creates the database and adds six starting locations
(`config/seed-locations.yaml`). `lookups refresh` loads the ski-area list, snow
stations and avalanche zones that Manage uses. `pull` fetches the first forecasts
(a few minutes: it pauses 20 s between locations). After that the worker runs by
itself at 03:30, 09:30, 15:30 and 21:30 UTC.

Check it: `curl -s http://localhost:8090/api/health` should say `"status":"ok"`,
and `http://<host>:8090` shows the app.

## 3. Put HTTPS in front

Point your proxy or tunnel at `http://<host>:8090`. With Caddy, for example:

```
snow.example.com {
	reverse_proxy localhost:8090
}
```

Then set `PUBLIC_URL` and `TRUSTED_PROXY=1` in `.env` and run
`docker compose up -d`.

In production (`ENV=prod`, which `docker-compose.yml` sets) the owner cookie is
HTTPS-only, so sign in through the HTTPS address, not `http://<host>:8090`.

## 4. Optional extras

**Push alerts** (powder days, storms, avalanche danger 4+, through the browser's
own push service; no app to install):

```bash
docker compose run --rm worker snowwatch push keys
```

Paste the two printed lines into `.env` and run `docker compose up -d`. Never
change the keys afterwards: that silently cuts off every subscribed device.
Then, on each device: More → Alerts → Turn on alerts. On iPhone and iPad (iOS 16.4
or newer), add the site to the Home Screen first and open it from there.

**Monitoring:**
- Point an uptime checker at `/api/health`. It answers 503 when there is no
  forecast or the last good run is more than 12 hours old, so it catches both
  "down" and "stuck".
- Optionally create two [Healthchecks.io](https://healthchecks.io) checks (forecast
  runs: period 6 h; backups: period 1 day) and put their ping URLs in `.env` as
  `HEALTHCHECKS_RUN_URL` and `HEALTHCHECKS_BACKUP_URL`.
- `docker compose ps` shows both services' health (the worker's is its heartbeat).

**Automatic updates:** `deploy/deploy.sh` fetches `main` and rebuilds when app
files changed. To run it every 5 minutes:

```bash
sudo cp deploy/snowwatch-deploy.service deploy/snowwatch-deploy.timer /etc/systemd/system/
```
```bash
sudo sed -i "s/REPLACE_WITH_YOUR_USER/$USER/" /etc/systemd/system/snowwatch-deploy.service
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now snowwatch-deploy.timer
```

Keep that checkout free of local edits (it only fast-forwards). Watch it with
`journalctl -u snowwatch-deploy -f`.

## Everyday tasks

**Manage locations:** More → Manage locations, then sign in with the owner
password. Search the ski-area list for a resort, or drop a trailhead and a high
point on the map for a tour; the app fills in elevations, timezone, snow station
and avalanche zone for you to check. The first forecast appears a minute or two
after saving. From the command line instead:

```bash
docker compose run --rm worker snowwatch locations export /data/locations.yaml
```
```bash
docker compose run --rm worker snowwatch locations import /data/locations.yaml
```

**Change the owner password:** edit `.env`, run `docker compose up -d`, then end
the existing sessions:

```bash
docker compose run --rm worker snowwatch owner logout-all
```

**Webcams:** Manage → Edit a location → Add a webcam. The page link opens when
tapped; an optional `https://` image link that updates shows a thumbnail.

**Snow depth method:** after a couple of weeks, open a location with a snow
station → Observed → Forecast scorecard. If the temperature-based depth is closer
at most locations, set `depth_method: slr` in `config/forecast.yaml`.

**Logs:** `docker compose logs -f worker` and `docker compose logs -f api` (one
JSON object per line).

**A forecast in the terminal:** `docker compose run --rm worker snowwatch show crystal`

## Backups and restore

Every night at 10:00 UTC the worker writes `data/backups/snowwatch-YYYYMMDD.db`
and `data/backups/locations-YYYYMMDD.yaml`, keeping 14 of each. Copy `data/backups`
off the machine too. Only the location list and the forecast history are
irreplaceable; forecasts regenerate at the next run.

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

## Rolling back an update

```bash
git log --oneline -5
```
```bash
sudo systemctl stop snowwatch-deploy.timer && git checkout <good-commit> && docker compose up -d --build
```

When the fix is on `main`: `git checkout main && sudo systemctl start snowwatch-deploy.timer`.

If the update applied a database migration (the worker logs "applied database
migrations" when it starts), an
older version may not run on the newer database: restore the backup from before
the update as well (see above).

## Troubleshooting

| Symptom | What to check |
|---|---|
| "The forecast hasn't updated for N hours" | `docker compose ps` (is the worker healthy?) and `docker compose logs worker` |
| `rate limited` in the logs | Open-Meteo's per-minute limit; the worker waits and retries. Fine unless it happens every run |
| Owner sign-in doesn't stick | Sign in through the HTTPS address. If a proxy rewrites the Host header, set `PUBLIC_URL` |
| "Too many wrong passwords" | Wait (the lockout doubles each time, up to an hour) or restart the api container |
| Manage says it's turned off | `OWNER_PASSWORD` is empty or shorter than 12 characters; check `docker compose logs api` |
| Alerts: "aren't set up on the server" | The two `VAPID_…` lines are missing from `.env`, or the containers weren't restarted |
| iPhone: no "Turn on alerts" button | Open Snow Watch from the Home Screen icon, not from Safari (iOS 16.4+) |
| "Send a test" says the push service refused it | Turn alerts off and on again on that device |
| A source shows red on Status | It hasn't succeeded for a day; its last error says why. Most recover at the next run |
| Map: no precipitation | The worker draws the frames every 10 minutes; `docker compose run --rm worker snowwatch precip` builds them now |
| Map: no ski runs | `docker compose run --rm worker snowwatch ski-map` |
| Observed: "No snow station is set" | `docker compose run --rm worker snowwatch locations stations` (after `lookups refresh`) |
| Disk filling up | `docker image prune -f`; lower `TILES_MAX_MB` |
| Worker logs `NumPy ... X86_V2` | Give the VM the host's CPU type (NumPy is pinned below 2.4 to avoid this, but it also speeds up runs) |
