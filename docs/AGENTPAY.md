# agentpay

agentpay lets small businesses deploy ai agents that take orders, answer questions, and collect payments. this directory contains the api service and the studio web app.

the agent runtime is provided by agentkit. see [`docs/AGENTKIT.md`](AGENTKIT.md) for how the runtime works.

## what it does

**the payment flow** (what happens when a customer interacts with an agent):

```
   customer speaks or types
      │
      ▼
   ┌───────────────────────────────────────┐
   │  agent  (embedded on merchant site)   │
   │  stt → llm → tts  (agentkit runtime)  │
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
   │  stripe /   │    │     natural     │
   │  square     │    │  (wallet-to-    │
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

---

## api/

rest control plane for agents, wallets, payment configs, and sessions. written in go; backed by postgres and redis.

**stack:** go 1.25, chi router, pgx/v5, redis, goose migrations, structured slog.

### routes

| method | path | description |
| ------ | ---------------------------------------- | -------------------------------- |
| get | `/health` | liveness check |
| post | `/v1/agents` | create an agent |
| get | `/v1/agents` | list agents for the org |
| get | `/v1/agents/{id}` | get an agent |
| patch | `/v1/agents/{id}` | update name, prompt, voice flag |
| delete | `/v1/agents/{id}` | delete an agent |
| get | `/v1/agents/{id}/embed` | get the embed snippet |
| post | `/v1/wallets` | create a wallet (auto kyb or byo) |
| get | `/v1/wallets` | get the org wallet |
| get | `/v1/wallets/balance` | get live balance |
| get | `/v1/wallets/transactions` | list transactions |
| post | `/v1/payments` | create a payment config for an agent |
| get | `/v1/payments/{agent_id}` | get payment config |
| patch | `/v1/payments/{id}` | update payment config |
| get | `/v1/payments/providers` | list supported providers + fields |

all routes under `/v1/` require a `bearer` jwt signed with `jwt_secret`. the token must carry `sub` (user id) and `orgid` claims.

### data model

| table | purpose |
| ----------------------------- | ------------------------------------------------------- |
| `users` | auth identities |
| `orgs` + `org_members` | multi-tenant grouping |
| `agents` | configured agent (business type, tools, embed token) |
| `wallets` | payment receiving account (natural, stripe connect) |
| `payment_configs` | provider + collection method bound to an agent |
| `sessions` + `session_events` | runtime conversation + event log |

### payment providers

| provider | collection methods |
| -------- | ------------------------------------------------- |
| stripe | `card_on_file`, `one_time_link` |
| natural | `phone_handoff`, `one_time_link`, `wallet` |
| square | `card_on_file`, `one_time_link` |

### development

**prerequisites:** go 1.25+, docker (postgres + redis).

```bash
cp .env.example .env
go mod download
go run ./cmd/migrate/main.go up
go run ./cmd/api/main.go   # default port 8090
```

**environment variables:**

| variable | default | purpose |
| ---------------- | ----------------------- | ---------------------------------- |
| `port` | `8090` | http listen port |
| `database_url` | required | postgres dsn |
| `redis_url` | `redis://localhost:6379` | redis connection |
| `jwt_secret` | required | hmac secret for bearer tokens |
| `studio_origin` | `http://localhost:3000` | cors allowed origin (studio) |

```bash
make build    # compile to bin/api
make test     # go test ./...
make lint     # golangci-lint
```

---

## web/

studio — the merchant-facing dashboard for managing agents, wallets, and payment configs.

**stack:** react 19, typescript, vite, tanstack router + query + form, tailwind css v4, shadcn/ui (base ui primitives), better-auth, zod.

### routes

| path | description |
| ----------------------- | ------------------------------------------ |
| `/` | landing / redirect to dashboard or login |
| `/login` | email + password sign-in |
| `/signup` | account creation |
| `/dashboard` | agent list and org overview |

### development

```bash
cd apps/web
bun install
bun dev   # default port 5173
```

**environment variables** (copy from `.env.example`):

| variable | purpose |
| ------------------------- | --------------------------------------- |
| `vite_api_url` | base url for `@agentpay/api` |
| `vite_auth_url` | base url for `@agentpay/auth` |

```bash
bun run build      # production build
bun run typecheck  # tsc --noemit
bun run lint       # eslint
```

---

## auth/

auth service wrapping better-auth with a jwt plugin. bun runtime, port 8080.
