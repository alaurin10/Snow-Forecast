# Contributing

## Setup

You need [uv](https://docs.astral.sh/uv/) and Node.js 24. The README's
"Development" section starts the API with fixture data and the app with live
reload; no weather API calls are needed.

## Checks

CI runs these; run them before pushing:

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy snowwatch && uv run pytest --cov
```
```bash
cd frontend && npm run lint && npm run check && npm test && npm run build && npm run e2e
```

`npm run e2e` starts the API on port 8019 with forecasts rebuilt from
`backend/tests/fixtures/` and runs the browser smoke tests.

After changing a response model (`backend/snowwatch/api/models.py`, `doc.py`),
regenerate the frontend types; CI fails if they're stale:

```bash
cd backend && uv run snowwatch schema --out ../frontend/src/lib/api-schema.json
```
```bash
cd frontend && npm run types
```

## Conventions

- **Units:** the API is metric only; the browser converts.
- **Charts:** one y-axis per chart; marks stay inside the plot (the chart tests
  check); everything works at 380 px wide.
- **Upstream data:** each source fails on its own and never breaks a run; a
  broken upstream yields "no data", never an invented value. Add a test with a
  canned response for every new source or failure path.
- **Safety:** never present anything as a judgement that terrain is safe;
  avalanche ratings are shown exactly as published and hidden once expired.
- **Database:** add a new numbered file in `backend/snowwatch/store/migrations/`;
  never edit one that has shipped.
- **Wording:** short, plain sentences in the app; no internal jargon.
- **Commits:** one logical change each, with a message that says why. Note
  user-visible changes in `CHANGELOG.md`.
