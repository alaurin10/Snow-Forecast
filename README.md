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

Copy `.env.example` to `.env` to set `NWS_CONTACT` and the other settings.

## Data tools

- `uv run snowwatch check-sources --write ../docs/SOURCES.md`: probe every upstream source and rewrite the report.
- `uv run snowwatch capture-fixtures`: save today's real responses for the seed locations to `backend/tests/fixtures/live-YYYYMMDD/` for tests.

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0), NWS, NRCS SNOTEL, avalanche.org and Avalanche Canada. Ski areas from [OpenSkiMap](https://openskimap.org/) (© OpenStreetMap contributors, ODbL).
