# ryo

ryo lets businesses deploy ai agents that take orders, answer questions, and collect payments via any modality. merchants embed an agent on their platform; consumers pay through it using a saved payment method. stripe settles funds directly to the merchant's connected account -- ryo never holds money.

the agent runtime is provided by kaji. see [`kaji/README.md`](../kaji/README.md) for how the runtime works.

## what it does

**the payment flow** (what happens when a customer interacts with an agent):

```
      customer types / speaks (any channel)
                        │
                        ▼
   ┌───────────────────────────────────────────────┐
   │  agent  (embedded on merchant site or app)    │
   │  kaji AgentRuntime  (tool-using loop,         │
   │  any modality: chat widget, Twilio, Vapi, SMS)│
   └────────────────────┬──────────────────────────┘
                        │  calls request_payment tool
                        ▼
   ┌──────────────────────────────────────────────────┐
<<<<<<<< HEAD:ryo/README.md
   │  @ryo/api  (merchant plane)                      │
========
   │  @ryo/api  (merchant plane)                 │
>>>>>>>> origin/main:docs/RYO.md
   │  creates payment session + Stripe PaymentIntent  │
   │  writes ledger row, fires payment.initiated      │
   └────────────────────┬─────────────────────────────┘
                        │
                        ▼
   ┌───────────────────────────────────────────────┐
   │  Stripe hosted checkout / Payment Element     │
   │  consumer authenticates via Stripe Link       │
   │  stripe_customer_id created or reused         │
   └────────────────────┬──────────────────────────┘
                        │  Stripe webhook callback
                        ▼
   ┌───────────────────────────────────────────────┐
<<<<<<<< HEAD:ryo/README.md
   │  @ryo/api                                     │
========
   │  @ryo/api                                │
>>>>>>>> origin/main:docs/RYO.md
   │  updates ledger · fires merchant webhook      │
   │  writes consumer transaction row              │
   └───────────┬────────────────────┬──────────────┘
               │                    │
               ▼                    ▼
         merchant backend       consumer app
         receives signed        sees updated
         push event             transaction feed
```

<<<<<<<< HEAD:ryo/README.md
ryo does not own any voice or STT/TTS infrastructure. merchants choose their modality (Twilio, Vapi, Bland, etc.) and point it at a kaji endpoint. ryo owns only the tool surface and payment session lifecycle.
========
ryo does not own any voice or STT/TTS infrastructure. merchants choose their modality (Twilio, Vapi, Bland, etc.) and point it at an kaji endpoint. ryo owns only the tool surface and payment session lifecycle.
>>>>>>>> origin/main:docs/RYO.md

---

## api/

rest control plane for agents, wallets, payment configs, sessions, and webhooks. written in go; backed by postgres and redis.

**stack:** go 1.25, chi router, pgx/v5, redis, goose migrations, structured slog.

### routes

| method | path | description |
| ------ | ---- | ----------- |
| get | `/health` | liveness check |
| post | `/v1/agents` | create an agent |
| get | `/v1/agents` | list agents for the org |
| get | `/v1/agents/{id}` | get an agent |
| patch | `/v1/agents/{id}` | update agent config |
| delete | `/v1/agents/{id}` | delete an agent |
| get | `/v1/agents/{id}/embed` | get embed snippet (widget or webhook url) |
| post | `/v1/wallets` | create a wallet (stripe connect onboarding) |
| get | `/v1/wallets` | get the org wallet |
| get | `/v1/wallets/balance` | get live balance |
| get | `/v1/wallets/transactions` | list transactions |
| post | `/v1/payments` | create a payment config for an agent |
| get | `/v1/payments/{agent_id}` | get payment config |
| patch | `/v1/payments/{id}` | update payment config |
| get | `/v1/payments/providers` | list supported providers + fields |
| post | `/v1/sessions` | create a payment session (called by kaji tool) |
| post | `/v1/webhooks` | register a merchant webhook url |
| get | `/v1/webhooks` | list registered webhooks |
| delete | `/v1/webhooks/{id}` | remove a webhook |
| post | `/stripe/webhook` | stripe event callback (internal) |

all routes under `/v1/` require a `bearer` jwt signed with `jwt_secret`. the token must carry `sub` (user id) and `orgid` claims.

### data model

| table | purpose |
| ----- | ------- |
| `users` | auth identities |
| `orgs` + `org_members` | multi-tenant grouping |
| `agents` | configured agent (business type, tools, embed token, embed type) |
| `wallets` | merchant receiving account (stripe connect) |
| `payment_configs` | provider + collection method bound to an agent |
| `sessions` + `session_events` | runtime conversation + event log |
| `webhooks` | merchant webhook registrations (url, secret, event filter) |
| `webhook_deliveries` | append-only delivery log; doubles as the durable delivery queue |

### payment providers

| provider | collection methods |
| -------- | ------------------ |
| stripe | `card_on_file`, `one_time_link` |
| square | `card_on_file`, `one_time_link` |

stripe is the primary provider at launch. square retained for merchants who need it.

### webhook events

| event | fired when |
| ----- | ---------- |
| `payment.initiated` | session created, PaymentIntent opened |
| `payment.completed` | stripe confirms payment succeeded |
| `payment.failed` | stripe confirms payment failed |
| `session.started` | agent session begins |
| `session.ended` | agent session ends |

each delivery is signed with `X-Ryo-Signature: sha256=<hmac>`. retry schedule: immediate -> +30s -> +5min. dead after 3 failures. delivery latency is typically 1-3 seconds with the postgres-backed queue.

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
| -------- | ------- | ------- |
| `port` | `8090` | http listen port |
| `database_url` | required | postgres dsn |
| `redis_url` | `redis://localhost:6379` | redis connection |
| `jwt_secret` | required | hmac secret for bearer tokens |
| `stripe_secret_key` | required | stripe api key |
| `stripe_webhook_secret` | required | stripe webhook signing secret |
| `studio_origin` | `http://localhost:3000` | cors allowed origin (studio) |

```bash
make build    # compile to bin/api
make test     # go test ./...
make lint     # golangci-lint
```

---

## consumer/

rest service for consumer identity, wallet management, and transaction history. written in go; backed by postgres.

**stack:** go 1.25, chi router, pgx/v5, goose migrations, structured slog.

### routes

| method | path | description |
| ------ | ---- | ----------- |
| post | `/v1/auth/signup` | create consumer account |
| post | `/v1/auth/login` | issue jwt |
| get | `/v1/wallet` | stripe customer status + saved payment methods |
| post | `/v1/wallet/setup` | initiate stripe SetupIntent (save a payment method) |
| get | `/v1/transactions` | paginated transaction history |
| get | `/v1/activity` | plain-language activity feed |

all routes under `/v1/` (except auth) require a bearer jwt with `sub` (consumer id) and `role: consumer` claims issued by this service.

### data model

| table | purpose |
| ----- | ------- |
| `consumers` | consumer identity + stripe_customer_id |
| `consumer_transactions` | append-only ledger with plain-language labels |

`plain_label` is a human-readable string written server-side at settlement time. format: `"Agent at {merchant_name} {action} - ${amount}"`. the consumer app reads and displays it directly -- no client-side formatting.

**environment variables:**

| variable | default | purpose |
| -------- | ------- | ------- |
| `port` | `8091` | http listen port |
| `database_url` | required | postgres dsn |
| `jwt_secret` | required | hmac secret for consumer tokens |
| `stripe_secret_key` | required | stripe api key |

---

## web/

studio -- the merchant-facing dashboard for managing agents, wallets, payment configs, and webhook registrations.

**stack:** react 19, typescript, vite, tanstack router + query + form, tailwind css v4, shadcn/ui, better-auth, zod.

### routes

| path | description |
| ---- | ----------- |
| `/` | landing / redirect to dashboard or login |
| `/login` | email + password sign-in |
| `/signup` | account creation |
| `/dashboard` | agent list and org overview |
| `/webhooks` | register and inspect webhook deliveries |

### development

```bash
cd apps/web
bun install
bun dev   # default port 5173
```

**environment variables** (copy from `.env.example`):

| variable | purpose |
| -------- | ------- |
| `vite_api_url` | base url for `@ryo/api` |
| `vite_auth_url` | base url for `@ryo/auth` |

```bash
bun run build      # production build
bun run typecheck  # tsc --noemit
bun run lint       # eslint
```

---

## consumer app/

ios app for consumers to manage their wallet and view transaction history.

**stack:** swift, swiftui, stripe ios sdk.

### screens

| screen | description |
| ------ | ----------- |
| wallet | payment method status, add/remove via stripe payment element |
| transactions | paginated list -- amount, merchant, status |
| activity | plain-language feed of agent actions |

payment method management is fully delegated to stripe's hosted ui (payment element / stripe link). no card numbers touch the app or the consumer service.

---

## auth/

auth service wrapping better-auth with a jwt plugin. bun runtime, port 8080. handles merchant/studio identities only. consumer identities are issued by the consumer service.
