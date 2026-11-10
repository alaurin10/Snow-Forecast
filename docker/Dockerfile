# Snow Watch: one image for both services (api and worker).
# Built on the server by `docker compose up -d --build`; CI only checks that it builds.
# Base images are pinned by digest (Dependabot proposes updates).

# 1. Frontend: a static build of the SvelteKit app.
FROM node:26-alpine@sha256:8996bb5821d62a8fd9bb27c1cb07462f3fdce6e47d640c6a881ead0b064ce216 AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Runtime: Python 3.12 with the backend, the config and the built frontend.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.32

WORKDIR /app/backend
# Dependencies first, so code changes don't reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/snowwatch ./snowwatch
RUN uv sync --frozen --no-dev

COPY config /app/config
COPY --from=frontend /src/frontend/build /app/static

# Runs as uid 1000, the usual first user on a Linux host, so ./data stays yours.
RUN useradd --create-home --uid 1000 snow && mkdir -p /data && chown snow /data
USER snow

# The commit this image was built from, shown on the About page.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=$GIT_COMMIT \
    PATH=/app/backend/.venv/bin:$PATH \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    CONFIG_DIR=/app/config
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/livez', timeout=3)"]
CMD ["uvicorn", "--factory", "snowwatch.api.app:production_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
