# agentpay system design
_2026-06-04_

## overview

agentpay lets merchants deploy ai agents that handle transactions via any modality (chat widget, voice via Twilio/Vapi, SMS). consumers interact with those agents, and agentpay handles the payment session, ledger, and event delivery. stripe settles money directly to the merchant's connected account — agentpay never holds funds.

---

## architecture

three layers, two backends, two frontends.

```
┌─────────────────────────────────────────────────────────┐
│  merchant studio (apps/web)                             │
│  manage agents, wallets, payment configs, webhooks      │
└────────────────────┬────────────────────────────────────┘
                     │ REST + JWT
                     ▼
┌─────────────────────────────────────────────────────────┐
│  @agentpay/api  (Go, port 8090)  — merchant plane       │
│  agents · wallets · payment configs · webhook registry  │
│  payment sessions · webhook delivery · ledger           │
└────────┬───────────────────────────┬────────────────────┘
         │ Stripe API                │ agentkit AgentRuntime
         ▼                           ▼
┌──────────────┐           ┌─────────────────────────────┐
│  Stripe      │           │  agentkit tool loop         │
│  settlement  │           │  any modality (chat/voice/  │
│  customer    │           │  SMS via Twilio, Vapi, etc.) │
│  vault       │           │  request_payment tool       │
└──────────────┘           └─────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  consumer app (mobile/web)                              │
│  wallet view · transaction feed · plain-language log    │
└────────────────────┬────────────────────────────────────┘
                     │ REST + JWT
                     ▼
┌─────────────────────────────────────────────────────────┐
│  @agentpay/consumer  (Go, port 8091)  — consumer plane  │
│  consumer identity · Stripe customer delegation         │
│  transaction history · plain-language activity feed     │
└─────────────────────────────────────────────────────────┘
```

**key decisions:**
- agentpay owns the tool surface and payment session lifecycle, not any modality
- voice/SMS is the merchant's choice — they point Twilio/Vapi/Bland at an agentkit endpoint
- stripe holds all sensitive payment data; agentpay stores only `stripe_customer_id`
- the ledger is append-only postgres rows — plain-language labels written at settlement time
- the consumer app is a read surface: wallet status + transaction feed, nothing writable except payment method setup

---

## modality

agentpay does not own STT/TTS. the agent loop is:

```
merchant embed (JS widget or webhook endpoint)
    │
    ▼
agentkit AgentRuntime (tool-using loop, provider-neutral)
    │  registered tool: request_payment(amount, description)
    ▼
POST /v1/sessions  →  @agentpay/api
```

merchants choose their modality:
- **chat widget** — embed the JS snippet, agentkit handles the conversation in-browser
- **voice/SMS** — merchant points Twilio/Vapi flow at a webhook endpoint; agentkit handles tool calls over that channel

both paths hit the same agentpay API surface.

---

## payment flow

```
agentkit calls request_payment tool
    │
    ▼
POST /v1/sessions  →  creates Stripe PaymentIntent
    │  writes session row + plain_label to ledger (pending)
    │  fires webhook event: payment.initiated
    ▼
Stripe hosted checkout / Payment Element
    │  consumer authenticates via Stripe Link
    │  stripe_customer_id created or reused
    ▼
Stripe webhook → POST /stripe/webhook  →  @agentpay/api
    │  payment.succeeded / payment.failed
    │  updates ledger row status
    │  writes to consumer_transactions
    │  fires merchant webhook: payment.completed / payment.failed
    ▼
merchant backend receives signed push event
consumer app reads updated transaction feed
```

no money touches agentpay. stripe settles directly to the merchant's connected account.

---

## data model

### additions to @agentpay/api (existing schema)

```sql
-- agents
ALTER TABLE agents ADD COLUMN embed_type TEXT NOT NULL DEFAULT 'widget'
  CHECK (embed_type IN ('widget', 'webhook'));

-- sessions
ALTER TABLE sessions ADD COLUMN channel TEXT NOT NULL DEFAULT 'chat'
  CHECK (channel IN ('chat', 'voice', 'sms'));
ALTER TABLE sessions ADD COLUMN plain_summary TEXT;

-- webhook registry
CREATE TABLE webhooks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  url         TEXT NOT NULL,
  secret      TEXT NOT NULL,  -- HMAC-SHA256 signing key, never returned after creation
  events      TEXT[] NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- delivery log (doubles as the durable queue)
CREATE TABLE webhook_deliveries (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  webhook_id    UUID NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  event_type    TEXT NOT NULL,
  payload       JSONB NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'delivered', 'failed', 'dead')),
  attempts      INT NOT NULL DEFAULT 0,
  next_attempt  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_status   INT,           -- HTTP response code from last attempt
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_webhook_deliveries_pending
  ON webhook_deliveries (next_attempt)
  WHERE status = 'pending';
```

### @agentpay/consumer (new schema)

```sql
CREATE TABLE consumers (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email              TEXT NOT NULL UNIQUE,
  hashed_password    TEXT NOT NULL,
  stripe_customer_id TEXT,          -- null until first payment method setup
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- append-only, never updated after status transitions
CREATE TABLE consumer_transactions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consumer_id  UUID NOT NULL REFERENCES consumers(id),
  session_id   UUID NOT NULL,       -- references api.sessions.id (cross-service, not FK)
  amount       BIGINT NOT NULL,     -- cents
  currency     TEXT NOT NULL DEFAULT 'usd',
  status       TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
  plain_label  TEXT NOT NULL,       -- e.g. "Agent helped you order a coffee at Blue Bottle - $4.50"
  merchant_id  UUID NOT NULL,       -- org_id from api service
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_consumer_transactions_consumer
  ON consumer_transactions (consumer_id, created_at DESC);
```

---

## @agentpay/consumer routes

| method | path | description |
|--------|------|-------------|
| POST | `/v1/auth/signup` | create consumer account |
| POST | `/v1/auth/login` | issue JWT |
| GET | `/v1/wallet` | stripe customer status + saved payment methods |
| POST | `/v1/wallet/setup` | initiate Stripe SetupIntent (save a payment method) |
| GET | `/v1/transactions` | paginated transaction history |
| GET | `/v1/activity` | plain-language feed entries |

auth uses the same JWT pattern as the existing auth service (HS256, `sub` + `role: consumer` claims). consumer JWTs are issued by the consumer service, not the existing auth service, to keep the identity namespaces separate.

---

## webhook delivery

### registration

```
POST /v1/webhooks
{ "url": "https://merchant.com/hooks/agentpay", "events": ["payment.completed", "payment.failed"] }
```

secret is generated server-side, returned once on creation, never again.

### event catalog

| event | fired when |
|-------|-----------|
| `payment.initiated` | session created, PaymentIntent opened |
| `payment.completed` | Stripe confirms payment.succeeded |
| `payment.failed` | Stripe confirms payment failed |
| `session.started` | agent session begins |
| `session.ended` | agent session ends |

### delivery mechanism

postgres-backed durable queue using `webhook_deliveries`:

1. event fires → row inserted with `status: pending`, `next_attempt: now()`
2. background worker (goroutine on startup) polls `WHERE status = 'pending' AND next_attempt <= now()` every 2 seconds
3. HTTP POST to merchant URL with signed payload
4. on 2xx → `status: delivered`
5. on non-2xx or timeout → increment `attempts`, set `next_attempt` per retry schedule, `status: failed`
6. after 3 attempts → `status: dead` (visible in studio for manual inspection)

**retry schedule:** immediate → +30s → +5min. dead after 3 failures.

**signing:** each delivery includes `X-Agentpay-Signature: sha256=<hmac>` computed over the raw request body. merchants verify before processing.

**typical end-to-end latency:** 1-3 seconds (poll interval + HTTP round trip).

### optimization notes (future)

the following can reduce delivery latency to sub-second when needed:

- **redis queue** — replace the postgres poll loop with a Redis Stream (`XADD`/`XREADGROUP`). worker wakes instantly on new events instead of polling. delivery latency drops to ~100-200ms. add only when poll latency becomes a real merchant complaint — redis adds an operational dependency not worth it at launch volume.
- **notify/listen** — postgres `NOTIFY` on insert + `LISTEN` in the worker eliminates the poll interval with no new infrastructure. latency drops to ~200-500ms. simpler than redis and a good intermediate step before adding redis.
- **parallel workers** — fan out delivery goroutines per webhook rather than a single serial worker. relevant when merchant count grows large enough that one slow endpoint blocks others.
- **dead letter alerting** — emit a structured log or metric when a delivery hits `dead` status so ops catches silent merchant endpoint failures early.

---

## agentkit integration

the `request_payment` tool is registered with `AgentRuntime` at agent startup:

```go
// tool spec surfaced to agentkit
{
  "name": "request_payment",
  "description": "Request payment from the customer for a product or service",
  "parameters": {
    "amount":      { "type": "integer", "description": "Amount in cents" },
    "description": { "type": "string",  "description": "Plain-language description shown to customer" }
  }
}
```

when the agent calls the tool, agentkit executes it by hitting `POST /v1/sessions` on the agentpay API. the tool returns a checkout URL or status that the agent can relay to the customer.

---

## consumer app (mobile/web)

thin read surface. three screens:

1. **wallet** — payment method status, add/remove via Stripe Payment Element
2. **transactions** — paginated list, amount + merchant + status
3. **activity** — plain-language feed: `"Agent helped you order a coffee at Blue Bottle - $4.50"`, `"Payment to Acme Bakery failed - no charge made"`

activity labels are written server-side at settlement time. the app never generates them — it only reads. this keeps the consumer app dumb and fast.

auth: email + password, JWT issued by consumer service. stripe payment method management is delegated fully to Stripe's hosted UI (Payment Element / Stripe Link) — no card numbers ever touch the consumer app or consumer service.

---

## open questions / deferred

- consumer app platform: React Native (single codebase for mobile + web) vs separate web app vs PWA. decision can wait until spec is approved and implementation starts.
- plain_label generation: hardcoded template strings at launch vs LLM-generated summaries. start with templates, upgrade later.
- merchant connected account onboarding: Stripe Connect onboarding flow (standard vs express) needs a dedicated spec before implementation.
- rate limiting on webhook delivery: not scoped here, add before public launch.
