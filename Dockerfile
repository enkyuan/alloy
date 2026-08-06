# syntax=docker/dockerfile:1.7

# --- Stage 1: build deps and editable install via uv ---------------------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ARG BUILD_COMMIT=unknown
LABEL build.commit="${BUILD_COMMIT}"

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/kaji/packages/serve/.venv

WORKDIR /app

# System deps that some Python packages (psycopg2-binary, etc.) need to import.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the monorepo. kaji-serve is a uv workspace member; the workspace root
# (pyproject.toml + uv.lock) plus the kaji-sdk member must all be present.
COPY . .

# Install. Frozen = lockfile must already exist and resolve; no remote re-resolution.
# --no-dev = skip the [dependency-groups].dev group; the image is for runtime.
# Run from the workspace root and select the serve member by name.
RUN uv sync --frozen --no-dev --package kaji-serve

# --- Stage 2: slim runtime ----------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/kaji/packages/serve/.venv/bin:${PATH}"

# Runtime system deps (psql client for entrypoint waits, curl for healthcheck).
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring in the synced venv plus the source tree.
COPY --from=builder /app /app

# Fail at build time if either package is unimportable. Catches stale image
# layers built before the monorepo restructure.
RUN python -c "import kaji; import kaji_serve"

# Non-root user.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "kaji_serve.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
