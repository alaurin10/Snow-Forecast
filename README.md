# Snow-Forecast

Snow Watch: a self-hosted, OpenSnow-style snow forecast dashboard for ski resorts and backcountry zones, running on a home mini PC and shared at `snow.andrewlaurin.com` through Cloudflare Tunnel and Access.

- [`docs/PLAN.md`](docs/PLAN.md): the build plan (design, data sources, analysis, deployment, milestones).
- [`docs/SOURCES.md`](docs/SOURCES.md): the latest live check of every data source.
- [`docs/SPEC-draft.md`](docs/SPEC-draft.md) and [`docs/reference/`](docs/reference/): the original draft spec and the working prototype.

## Layout

| Path | What |
|---|---|
| `backend/` | Python 3.12 package `snowwatch`: pipeline, analysis, SQLite store, FastAPI app, CLI |
| `frontend/` | SvelteKit single-page app (static build served by the API) |
| `config/forecast.yaml` | Models, ensembles, thresholds and schedule |
| `config/seed-locations.yaml` | The six starting locations |

## Development

Needs [uv](https://docs.astral.sh/uv/) and Node 22+ (npm 11; Node 24 ships it).

```bash
cd backend
uv sync
uv run snowwatch init            # create data/snowwatch.db and seed the locations
uv run snowwatch locations list
uv run snowwatch budget          # estimated daily Open-Meteo usage
uv run uvicorn snowwatch.api.app:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173, proxies /api to :8000
```

Checks (the same as CI):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy snowwatch && uv run pytest
cd frontend && npm run lint && npm run check && npm test && npm run build
```

Copy `.env.example` to `.env` (repo root) and set `NWS_CONTACT` to your email.

## See it in a browser

Build the frontend once, then one process serves both the app and the API:

```bash
cd frontend && npm install && npm run build
cd ../backend && uv run snowwatch init && uv run snowwatch pull
uv run uvicorn snowwatch.api.app:app --port 8000
```

Open http://localhost:8000. For frontend work, `npm run dev` in `frontend/` (http://localhost:5173) proxies `/api` to the backend on port 8000.

`node frontend/scripts/screenshots.mjs` captures every page at phone, tablet and desktop widths in light and dark, and fails if a page scrolls sideways or the API errors.

After changing a response model in `backend/snowwatch/api/models.py` or `doc.py`, regenerate the frontend types (CI checks they match):

```bash
cd backend && uv run snowwatch schema --out ../frontend/src/lib/api-schema.json
cd ../frontend && npm run types
```

## Commands

Run from `backend/` with `uv run snowwatch …`:

| Command | What it does |
|---|---|
| `init` | Create or migrate the database and seed the locations |
| `pull [--only ID …] [--ensembles]` | Fetch, analyse and store forecasts now |
| `show ID [--band base\|mid\|summit]` | Print a location's latest forecast as a table (in, °F, ft) |
| `worker [--run-now]` | The scheduler: runs at 03:30/09:30/15:30/21:30 UTC, the job queue, nightly backups |
| `rebuild [--from FOLDER]` | Rebuild snapshots with no API calls, from the raw cache or saved fixtures |
| `backup` | Write a database backup and a `locations.yaml` copy now |
| `locations list\|import\|export`, `budget` | Manage the list; estimated Open-Meteo usage |
| `check-sources --write ../docs/SOURCES.md` | Probe every upstream source and rewrite the report |
| `schema --out FILE` | Write the API's JSON Schema (source of the frontend types) |
| `capture-fixtures` | Save today's real responses to `backend/tests/fixtures/live-YYYYMMDD/` |

Try it offline: `uv run snowwatch init && uv run snowwatch rebuild --from tests/fixtures/live-20261104 && uv run snowwatch show whistler`.

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0), NWS, NRCS SNOTEL, avalanche.org and Avalanche Canada. Ski areas from [OpenSkiMap](https://openskimap.org/) (© OpenStreetMap contributors, ODbL).
