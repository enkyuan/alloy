# Roadmap

What remains before agentkit and agentpay are production-ready. Items are ordered by leverage and grouped into shared timeline blocks — agentkit SDK work and agentpay product work are interleaved because agentpay depends on agentkit capabilities landing first.

Status legend: **DONE** / **PARTIAL** / **MISSING** reflects current state, not the issue itself.

---

## P0 — Core agent loop, unblocked — DONE

Completed 2026-05-31. `import agentkit` -> run an agent -> call a tool works end-to-end with zero external services. 83 SDK tests pass.

### 1. Wire tools into `AgentRuntime` (DONE)
- `agentkit/sdk/agentkit/runtime/agents/runtime.py` — `tools: List[ToolSpec]` constructor arg, provider-neutral payload surfaced to `generate_stream` each turn.
- Tests: `agentkit/sdk/tests/test_agents_runtime.py`.

### 2. Register the mock provider (DONE)
- `agentkit/sdk/agentkit/runtime/providers/registry.py` — loads mock in `_ensure_builtin_providers_loaded`.
- `agentkit/sdk/agentkit/runtime/providers/mock.py` — self-registers, drives full tool loop with no network.

### 3. Export the agent loop from the public API (DONE)
- `agentkit/sdk/agentkit/__init__.py` — `AgentRuntime`, `AgentStrategy`, `ToolPlanner`, `CancellationToken`, `ModelProvider`, `UserMessage`, `InMemoryEventBus` added to lazy map.

### 3b. In-memory `EventBus` (DONE)
- `agentkit/sdk/agentkit/infra/events/bus.py` — `InMemoryEventBus` (per-session log + live fan-out). Redis `EventBus` unchanged.
- Tests: `agentkit/sdk/tests/test_events_bus.py`.

---

## P1 — Providers + agentpay scaffold

### 4. OpenAI LLM provider (DONE)
- `agentkit/sdk/agentkit/runtime/providers/openai.py` — `generate` + `generate_stream` with tool calls via async openai SDK. Kimi stays default.
- Tests: `agentkit/sdk/tests/test_providers_openai.py`.

### 5. Anthropic provider (DONE)
- `agentkit/sdk/agentkit/runtime/providers/anthropic.py` — Messages API provider with streaming + tool use.
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` config path exists.
- Unit and opt-in live integration tests: `agentkit/sdk/tests/test_providers_errors.py`, `agentkit/sdk/tests/integration/test_anthropic_provider.py`.

### 6. Fix Gemini streaming (DONE)
- `agentkit/sdk/agentkit/runtime/providers/gemini.py` — `generate_stream` now has full history + tool calls parity with `generate`.
- Tests: `agentkit/sdk/tests/test_providers_gemini_stream.py`.

### 7. Provider-neutral tool payloads (DONE)
- `agentkit/sdk/agentkit/runtime/tools/payload.py` — flat neutral list, `to_gemini` / `to_openai` translators at provider boundaries.
- Tests: `agentkit/sdk/tests/test_tools_payload.py`.

### 7b. Fix Kimi tool translation (DONE)
- `agentkit/sdk/agentkit/runtime/providers/kimi.py` — translates via `to_openai` at the boundary.

### 8. agentpay API scaffold (MISSING)
The `agentpay/api` service has handlers and store stubs but no wired payment session lifecycle, no Stripe integration, and no webhook delivery.
- Wire `POST /v1/sessions` — create Stripe PaymentIntent, write ledger row, fire `payment.initiated` webhook delivery row.
- Add `POST /stripe/webhook` handler — verify Stripe signature, handle `payment_intent.succeeded` / `payment_intent.payment_failed`, update ledger, write consumer transaction row, fire merchant webhook.
- Add `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}` routes and store.
- Add `webhook_deliveries` migration and background delivery worker (postgres-backed queue, goroutine on startup, 2s poll, retry immediate -> +30s -> +5min, dead after 3 attempts).
- Add `embed_type` column to `agents`, `channel` + `plain_summary` to `sessions`.
- Env vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

### 9. agentpay consumer service (MISSING)
New Go service at `agentpay/consumer`, port 8091.
- Scaffold: chi router, pgx/v5, goose migrations, slog — mirror `agentpay/api` structure.
- Migrations: `consumers`, `consumer_transactions` tables.
- Routes: `POST /v1/auth/signup`, `POST /v1/auth/login`, `GET /v1/wallet`, `POST /v1/wallet/setup`, `GET /v1/transactions`, `GET /v1/activity`.
- JWT pattern: HS256, `sub` + `role: consumer` claims, issued by this service only.
- Stripe SetupIntent flow for saving payment methods (no card data stored).

---

## P2 — Decouple building blocks + agentpay tool integration

### 10. Decouple `ToolRetriever` from Gemini + Redis (DONE)
- `agentkit/sdk/agentkit/runtime/tools/retriever.py` — pluggable `Embedder` + `EmbeddingCache` protocols. Defaults infra-free.
- `agentkit/sdk/agentkit/infra/realtime/embedding_cache.py` — `RedisEmbeddingCache` opt-in.
- Tests: `agentkit/sdk/tests/test_tools_retriever.py`.

### 11. In-memory fallback for `AgentReasoningNode` (DONE)
- `agentkit/sdk/agentkit/runtime/agents/history.py` — `HistoryStore` protocol + `InMemoryHistoryStore`.
- `agentkit/sdk/agentkit/infra/realtime/redis_history.py` — `RedisHistoryStore` opt-in.
- Tests: `agentkit/sdk/tests/test_agents_history.py`, `test_agents_node_infra_free.py`.

### 11b. Project `TOOL_CALL_FAILED` into session state (DONE)
- `agentkit/sdk/agentkit/infra/events/replay.py` — `TOOL_CALL_FAILED` branch appends `{role: tool, name, content: "Error: <error>"}`.
- Tests: `agentkit/sdk/tests/test_events_replay.py`.

### 12. `request_payment` agentkit tool (MISSING)
The bridge between agentkit and agentpay. Registers with `AgentRuntime`; when called, hits `POST /v1/sessions` on `@agentpay/api` and returns a checkout URL to the agent.
- Tool spec: `{name: "request_payment", parameters: {amount: integer (cents), description: string}}`.
- Implementation in `agentkit/sdk/agentkit/tools/payment.py` (or equivalent) — thin HTTP call to agentpay API, configurable base URL via env.
- Needs `@agentpay/api` session endpoint (item 8) live first.

---

## P3 — Capabilities promised but absent

### 14. General document / knowledge RAG (DONE)
- `agentkit/sdk/agentkit/knowledge/` — `Document`/`Chunk` types, deterministic `chunk_text`, `VectorStore` protocol + `InMemoryVectorStore` (cosine, dimension-guarded), `DocumentRAG` (ingest + retrieve). Infra-free by default; reuses the tool retriever's `Embedder` protocol.
- Exported from the public API; runnable quickstart in the SDK README.
- `AgentRuntime(rag=...)` retrieves from the latest user message and injects relevant chunks into the system prompt each turn.

### 15. Multi-agent / swarm handoff (MISSING)
- The previous no-op swarm router and swarm event stubs were removed. Add this only with a real routing/runtime design.

### 16. Durable session persistence (DONE — SessionStore interface + serve Postgres backend)
- `agentkit/sdk/agentkit/runtime/sessions/store.py` — `SessionStore` protocol + `SessionRecord` + `InMemorySessionStore` (a cross-session index, distinct from the per-session `EventStore`).
- `SessionManager` takes an optional `SessionStore`; `list_active` returns recorded sessions when configured, `[]` otherwise. `record_session` + round-trip test exercise the path.
- Exported from the public API; runnable quickstart in the SDK README.
- `agentkit/serve/agentkit_serve/server/session_store.py` — `PostgresSessionStore` implements the same protocol over the existing `Conversation` table.
- Auto-recording from inside `AgentRuntime` is not wired (the runtime has no `user_id`); callers record via `SessionManager.record_session` or service routes.

### 17. agentpay merchant studio — webhooks UI (MISSING)
Studio (`apps/web`) has no webhook management screens.
- Add `/webhooks` route: register a URL, select events, view delivery history, inspect dead deliveries.
- Feeds from `GET /v1/webhooks` and delivery log in `webhook_deliveries`.

### 18. agentpay iOS consumer app (MISSING)
Deferred until the consumer service API and studio web app are stable.
Swift/SwiftUI app, iOS-first.
- Three screens: wallet (Stripe Payment Element), transactions (paginated), activity (plain-language feed).
- Auth: email + password -> JWT from consumer service.
- Stripe iOS SDK for payment method management. No card data in app or consumer service.
- Reads `GET /v1/transactions` and `GET /v1/activity` from consumer service.
- Blocked on items 9 and 17.

### 19. agentpay merchant onboarding — Stripe Connect (MISSING)
Stripe Connect Standard onboarding for merchant wallets. Agentpay owns the UI, submits KYB/KYC fields to Stripe via API.
- Needs a dedicated spec before implementation. Deferred from the current design.

---

## Voice / `agentkit-serve` — reference service gaps

### 20. Barge-in / interruption (MISSING)
- No speech-activity events produced anywhere in the STT/voice/worker path.
- `_synthesize_and_publish` in `agentkit/serve/agentkit_serve/workers/main.py` streams TTS with no cancellation hook.
- DTMF lookahead buffer (`agentkit/sdk/agentkit/modalities/voice/utils/dtmf_lookahead_buffer.py`) is written but never fed.

### 21. Automatic turn / endpoint detection (MISSING)
- `agentkit/sdk/agentkit/modalities/voice/turn_detection.py` — `resolve_turn_policy` has zero consumers.
- `agentkit/serve/agentkit_serve/modalities/voice/stt/soniox_gateway.py` — endpoint detection is not yet wired through.

### 22. Durable chat persistence (PARTIAL)
- `/sessions` now lists `Conversation` rows through `PostgresSessionStore`.
- Message history still lives only in Redis, trimmed to `AGENT_HISTORY_LIMIT`; `Message` rows are not yet written by the service runtime.

### 23. Reconcile the two auth paths (DONE)
- HTTP validates Bearer tokens locally via HS256 (`agentkit/serve/agentkit_serve/server/deps.py`).
- STT WebSocket auth now uses the same local JWT decode helper in `agentkit/serve/agentkit_serve/server/auth_utils.py`.

### 24. Remove dead code (cleanup)
- `agentkit/serve/agentkit_serve/workers/tasks/memory.py` — empty, reserved for future use. Implement or delete.
- `agentkit/serve/agentkit_serve/workers/helpers/llm_response.py` and `response_text.py` — written but never imported.

---

## TypeScript SDK — to make it drive an agent

### 25. Provider layer (DONE)
- `agentkit/ts/src/providers/` — `ModelProvider` interface (`base.ts`), `registry.ts` (`registerProvider`/`getProvider`/`clearProviders`), `MockProvider` (drives the full tool loop with no network). Mirrors `agentkit/sdk/agentkit/runtime/providers/base.py`.
- A real TS provider (OpenAI/Anthropic) is a clean follow-up; the interface is fixed so it has no design risk.

### 26. Agent runtime (DONE)
- `agentkit/ts/src/runtime/runtime.ts` — ports `AgentRuntime.run_turn`: replay -> build messages -> stream from provider -> emit events -> scatter-gather tools -> loop. Plus `CancellationToken` and `buildMessages`. Guards the final completion on truthy text (matches the Python reference).

### 27. Tool-loop glue (DONE)
- The loop in `runtime.ts` turns provider `tool_calls` into `executeTool` (`agentkit/ts/src/tools/registry.ts`) calls and emits the full lifecycle (`ToolCallRequested -> Started -> Completed | Failed`), concurrently via `Promise.all`. The real `tool_call_id` is threaded through replay so a real provider can match results to requests.

### 28. Reconcile sync vs async `publish` (DONE — publish stays async; runtime awaits it)
- `agentkit/ts/src/events/bus.ts` — `EventBus.publish` is `async` (resolved-Promise) with a doc comment locking the decision; the runtime does `await bus.publish(event)`, matching the Python `await self.bus.publish(...)`.

---

## Developer experience

### 29. agentkit CLI / scaffold (DONE)

Both `@agentkit/cli` (TypeScript) and `agentkit` (Python) ship the same surface:
`init`, `gen`, `info`, `secret`, `upgrade`, `doctor`. The TS CLI additionally
ships `mcp` for registering an agentkit MCP server with the user's AI tool.

- TS: `bun add -D @agentkit/cli` -> `npx agentkit init --lang ts|python --provider openai|anthropic|kimi|gemini`
- Python: `pip install agentkit` -> `agentkit init --provider openai`
- Landing-page CLI tab: now safe to show both `agentkit init` flows.
