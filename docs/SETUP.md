# AgentKit Local Setup

## Structure

```
agentkit/
├── apps/
│   ├── api/          # FastAPI backend (AgentKit SDK)
│   └── desktop/      # Tauri desktop client
├── docker/           # Docker Compose (API, workers, Redis, Supabase)
└── packages/         # Shared workspace packages
```

## FastAPI Backend Setup

### 1. Navigate to API directory

```bash
cd apps/sdk
```

### 2. Install Poetry dependencies

```bash
poetry install
```

### 3. Set up environment

```bash
cp .env.example .env
# Edit .env with your database credentials and API keys
```

### 4. Run migrations

```bash
poetry run alembic upgrade head
```

### 5. Start development server

```bash
poetry run uvicorn sdk.main:app --reload --host 0.0.0.0 --port 8080
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

## Desktop App Setup

### Prerequisites

- [Bun](https://bun.sh)
- [Rust](https://rustup.rs) (for Tauri)

### 1. Install workspace dependencies

```bash
bun i
```

### 2. Start the desktop app

```bash
bun --filter @agentkit/desktop dev
```

### 3. Build the desktop app

```bash
bun --filter @agentkit/desktop build
```

Point the desktop client at your local API (`http://localhost:8080` by default).

## Running Tests

```bash
cd apps/sdk
poetry run pytest
```

## Quick Start

```bash
# Terminal 1: infrastructure + API (from docker/)
cd docker && docker compose up -d

# Terminal 2: desktop (from repo root)
bun --filter @agentkit/desktop dev
```
