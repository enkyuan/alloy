# @agentpay/api

REST API for Agentpay: agents, wallets, payment configs, and sessions. Written
in Go; backed by Postgres and Redis.

## What it does

Agentpay lets small businesses deploy AI agents that take orders, answer
questions, and collect payments. This service is the control plane: it stores
agent configuration, connects payment providers, and records session events.

**The payment flow** (what happens when a customer interacts with an agent):

```
   customer speaks or types
      │
      ▼
   ┌───────────────────────────────────────┐
   │  agent  (embedded on merchant site)   │
   │  STT → LLM → TTS  (agentkit runtime)  │
   └────────────────┬──────────────────────┘
                    │  calls request_payment tool
                    ▼
   ┌───────────────────────────────────────┐
   │  @agentpay/api  (this service)        │
   │  validates, creates payment session   │
   └────────────────┬──────────────────────┘
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
   ┌─────────────┐    ┌─────────────────┐
   │  Stripe /   │    │     Natural     │
   │  Square     │    │  (wallet-to-    │
   │  (card/link)│    │    wallet)      │
   └──────┬──────┘    └────────┬────────┘
          └─────────┬──────────┘
                    │  settlement
                    ▼
   ┌───────────────────────────────────────┐
   │  merchant wallet  (org account)       │
   │  status: pending → verifying → active │
   └───────────────────────────────────────┘
```

## Stack

Go 1.25, chi router, pgx/v5, Redis, goose migrations, structured slog.

## Routes

| Method | Path | Description |
| ------ | ---------------------------------------- | -------------------------------- |
| GET | `/health` | Liveness check |
| POST | `/v1/agents` | Create an agent |
| GET | `/v1/agents` | List agents for the org |
| GET | `/v1/agents/{id}` | Get an agent |
| PATCH | `/v1/agents/{id}` | Update name, prompt, voice flag |
| DELETE | `/v1/agents/{id}` | Delete an agent |
| GET | `/v1/agents/{id}/embed` | Get the embed snippet |
| POST | `/v1/wallets` | Create a wallet (auto KYB or BYO) |
| GET | `/v1/wallets` | Get the org wallet |
| GET | `/v1/wallets/balance` | Get live balance |
| GET | `/v1/wallets/transactions` | List transactions |
| POST | `/v1/payments` | Create a payment config for an agent |
| GET | `/v1/payments/{agent_id}` | Get payment config |
| PATCH | `/v1/payments/{id}` | Update payment config |
| GET | `/v1/payments/providers` | List supported providers + fields |

All routes under `/v1/` require a `Bearer` JWT signed with `JWT_SECRET`. The
token must carry `sub` (user ID) and `orgId` claims.

## Data model

Six tables, all scoped to an org:

| Table | Purpose |
| ----------------------------- | ------------------------------------------------------- |
| `users` | Auth identities |
| `orgs` + `org_members` | Multi-tenant grouping |
| `agents` | Configured agent (business type, tools, embed token) |
| `wallets` | Payment receiving account (Natural, Stripe Connect) |
| `payment_configs` | Provider + collection method bound to an agent |
| `sessions` + `session_events` | Runtime conversation + event log |

## Payment providers

| Provider | Collection methods |
| -------- | ------------------------------------------------- |
| Stripe | `card_on_file`, `one_time_link` |
| Natural | `phone_handoff`, `one_time_link`, `wallet` |
| Square | `card_on_file`, `one_time_link` |

## Development

**Prerequisites:** Go 1.25+, Docker (Postgres + Redis).

```bash
# Copy and fill in env
cp .env.example .env

# Download dependencies
go mod download

# Run migrations
go run ./cmd/migrate/main.go up

# Start the server (default port 8090)
go run ./cmd/api/main.go
```

### Environment variables

| Variable | Default | Purpose |
| ---------------- | --------------------- | ---------------------------------- |
| `PORT` | `8090` | HTTP listen port |
| `DATABASE_URL` | required | Postgres DSN (asyncpg format) |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `JWT_SECRET` | required | HMAC secret for Bearer tokens |
| `STUDIO_ORIGIN` | `http://localhost:3000` | CORS allowed origin (Studio) |

### Make targets

```bash
make build    # compile to bin/api
make test     # go test ./...
make lint     # golangci-lint
```
