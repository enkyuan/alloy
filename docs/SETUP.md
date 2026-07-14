# Kaji Local Setup

## Structure

```
.
├── kaji/
│   ├── sdk/             # the `kaji` SDK (Python)
│   ├── serve/           # `kaji-serve` -- REST + Soniox STT (path-depends on ../sdk)
│   └── ts/              # `@kaji/sdk` -- TypeScript SDK
└── docker/
    ├── kaji/        # Postgres and Supabase for kaji-serve
    └── ryo/        # docker stack for the ryo product
```

## FastAPI Backend Setup

The reference service is the `kaji-serve` distribution. Run these from
`kaji/serve/`; it pulls in the `kaji` SDK via a path dependency
(`../sdk`).

### 1. Install dependencies with uv

```bash
cd kaji/serve
uv sync
```

### 2. Set up environment

```bash
cp ../../docker/kaji/.env.example .env
# Edit .env with your database credentials and API keys
```

### 3. Run migrations

```bash
uv run alembic upgrade head
```

### 4. Start development server

```bash
uv run uvicorn kaji_serve.server.app:app --reload --host 0.0.0.0 --port 8080
```

API docs: `http://localhost:8080/api/v1/docs`

## Docker Stack

From the repository root:

```bash
cd docker/kaji
cp .env.example .env   # configure credentials
docker compose up -d
```

Compose uses the `kaji` project name and starts the `kaji-serve` API plus its
Postgres/Supabase dependencies. It does not host an agent runtime or background
tool worker.

## Running Tests

```bash
# Core SDK tests (from kaji/sdk/ -- no database needed)
cd kaji/sdk && uv run pytest tests/

# Reference service tests (from kaji/serve/ -- DB tests need Postgres)
cd kaji/serve && uv run pytest tests/
```

## Quick Start

```bash
# Option 1: infrastructure + API (from docker/kaji/)
cd docker/kaji && docker compose up -d

# Option 2: API server directly (from kaji/serve/; requires its dependencies)
cd kaji/serve && uv run uvicorn kaji_serve.server.app:app --reload --host 0.0.0.0 --port 8080
```
