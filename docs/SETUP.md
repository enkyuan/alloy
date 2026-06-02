# AgentKit Local Setup

## Structure

```
.
├── packages/
│   ├── sdk/          # the `agentkit` SDK (Python)
│   ├── serve/        # `agentkit-serve` — FastAPI + workers (path-depends on ../sdk)
│   └── ts/           # `@agentkit/sdk` — TypeScript SDK
└── docker/           # Docker Compose (Postgres, Redis, Supabase)
```

## FastAPI Backend Setup

The reference service is the `agentkit-serve` distribution. Run these from
`packages/serve/`; it pulls in the `agentkit` SDK via a path dependency
(`../sdk`).

### 1. Install Poetry dependencies

```bash
cd packages/serve
poetry install
```

### 2. Set up environment

```bash
cp ../docker/.env.example .env
# Edit .env with your database credentials and API keys
```

### 3. Run migrations

```bash
poetry run alembic upgrade head
```

### 4. Start development server

```bash
poetry run uvicorn agentkit_serve.server.app:app --reload --host 0.0.0.0 --port 8080
```

API docs: `http://localhost:8080/api/v1/docs`

## Docker Stack

From the repository root:

```bash
cd docker
cp .env.example .env   # if present; configure credentials
docker compose up -d
```

Services use the `agentkit` Compose project name (`agentkit-sdk`, `agentkit-worker`, `agentkit-bus-worker`).

## Running Tests

```bash
# Core SDK tests (from packages/sdk/ — no database needed)
cd packages/sdk && poetry run pytest tests/

# Reference service tests (from packages/serve/ — DB tests need Postgres)
cd packages/serve && poetry run pytest tests/
```

## Quick Start

```bash
# Terminal 1: infrastructure + API (from docker/)
cd docker && docker compose up -d

# Terminal 2: API server (from packages/serve/)
cd packages/serve && poetry run uvicorn agentkit_serve.server.app:app --reload --host 0.0.0.0 --port 8080
```
