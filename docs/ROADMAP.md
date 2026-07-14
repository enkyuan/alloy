# Roadmap

What remains before kaji and ryo are production-ready. Items are ordered by leverage and grouped into shared timeline blocks -- kaji SDK work and ryo product work are interleaved because ryo depends on kaji capabilities landing first.

Status legend: **DONE** / **PARTIAL** / **MISSING** reflects current state, not the issue itself.

---

## P0 -- Core agent loop, unblocked -- DONE

Completed 2026-05-31. `import kaji` -> run an agent -> call a tool works end-to-end with zero external services. 83 SDK tests pass.

### 1. Wire tools into `AgentRuntime` (DONE)

- `kaji/sdk/src/kaji/runtime/agents/runtime.py` -- `tools: List[ToolSpec]` constructor arg, provider-neutral payload surfaced to `generate_stream` each turn.
- Tests: `kaji/sdk/tests/test_agents_runtime.py`.

### 2. Register the mock provider (DONE)

- `kaji/sdk/src/kaji/runtime/providers/registry.py` -- loads mock in `_ensure_builtin_providers_loaded`.
- `kaji/sdk/src/kaji/runtime/providers/mock.py` -- self-registers, drives full tool loop with no network.

### 3. Export the agent loop from the public API (DONE)

- `kaji/sdk/src/kaji/__init__.py` -- `AgentRuntime`, `AgentStrategy`, `ToolPlanner`, `CancellationToken`, `ModelProvider`, `UserMessage`, `InMemoryEventBus` added to lazy map.

### 3b. In-memory `EventBus` (DONE)

- `kaji/sdk/src/kaji/infra/events/bus.py` -- `InMemoryEventBus` (per-session log + live fan-out). Redis `EventBus` unchanged.
- Tests: `kaji/sdk/tests/test_events_bus.py`.

---

## P1 -- Providers + ryo scaffold

### 4. OpenAI LLM provider (DONE)

- `kaji/sdk/src/kaji/runtime/providers/openai.py` -- `generate` + `generate_stream` with tool calls via async openai SDK. Kimi stays default.
- Tests: `kaji/sdk/tests/test_providers_openai.py`.

### 5. Anthropic provider (DONE)

- `kaji/sdk/src/kaji/runtime/providers/anthropic.py` -- Messages API provider with streaming + tool use.
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` config path exists.
- Unit and opt-in live integration tests: `kaji/sdk/tests/test_providers_errors.py`, `kaji/sdk/tests/integration/test_anthropic_provider.py`.

### 6. Fix Gemini streaming (DONE)

- `kaji/sdk/src/kaji/runtime/providers/gemini.py` -- `generate_stream` now has full history + tool calls parity with `generate`.
- Tests: `kaji/sdk/tests/test_providers_gemini_stream.py`.

### 7. Provider-neutral tool payloads (DONE)

- `kaji/sdk/src/kaji/runtime/tools/payload.py` -- flat neutral list, `to_gemini` / `to_openai` translators at provider boundaries.
- Tests: `kaji/sdk/tests/test_tools_payload.py`.

### 7b. Fix Kimi tool translation (DONE)

- `kaji/sdk/src/kaji/runtime/providers/kimi.py` -- translates via `to_openai` at the boundary.

### 8. ryo API scaffold (MISSING)

The `ryo/api` service has handlers and store stubs but no wired payment session lifecycle, no Stripe integration, and no webhook delivery.

- Wire `POST /v1/sessions` -- create Stripe PaymentIntent, write ledger row, fire `payment.initiated` webhook delivery row.
- Add `POST /stripe/webhook` handler -- verify Stripe signature, handle `payment_intent.succeeded` / `payment_intent.payment_failed`, update ledger, write consumer transaction row, fire merchant webhook.
- Add `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}` routes and store.
- Add `webhook_deliveries` migration and background delivery worker (postgres-backed queue, goroutine on startup, 2s poll, retry immediate -> +30s -> +5min, dead after 3 attempts).
- Add `embed_type` column to `agents`, `channel` + `plain_summary` to `sessions`.
- Env vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

### 9. ryo consumer service (MISSING)

New Go service at `ryo/consumer`, port 8091.

- Scaffold: chi router, pgx/v5, goose migrations, slog -- mirror `ryo/api` structure.
- Migrations: `consumers`, `consumer_transactions` tables.
- Routes: `POST /v1/auth/signup`, `POST /v1/auth/login`, `GET /v1/wallet`, `POST /v1/wallet/setup`, `GET /v1/transactions`, `GET /v1/activity`.
- JWT pattern: HS256, `sub` + `role: consumer` claims, issued by this service only.
- Stripe SetupIntent flow for saving payment methods (no card data stored).

---

## P2 -- Decouple building blocks + ryo tool integration

### 10. Decouple `ToolRetriever` from Gemini + Redis (DONE)

- `kaji/sdk/src/kaji/runtime/tools/retriever.py` -- pluggable `Embedder` + `EmbeddingCache` protocols. Defaults infra-free.
- `kaji/sdk/src/kaji/infra/realtime/embedding_cache.py` -- `RedisEmbeddingCache` opt-in.
- Tests: `kaji/sdk/tests/test_tools_retriever.py`.

### 11. Conversation history storage primitives (DONE)

- `kaji/sdk/src/kaji/runtime/agents/history.py` -- `HistoryStore` protocol + `InMemoryHistoryStore`.
- `kaji/sdk/src/kaji/infra/realtime/redis_history.py` -- `RedisHistoryStore` opt-in.
- Tests: `kaji/sdk/tests/test_agents_history.py`, `test_redis_history.py`.

### 11b. Project `TOOL_CALL_FAILED` into session state (DONE)

- `kaji/sdk/src/kaji/infra/events/replay.py` -- `TOOL_CALL_FAILED` branch appends `{role: tool, name, content: "Error: <error>"}`.
- Tests: `kaji/sdk/tests/test_events_replay.py`.

### 12. `request_payment` kaji tool (MISSING)

The bridge between kaji and ryo. Registers with `AgentRuntime`; when called, hits `POST /v1/sessions` on `@ryo/api` and returns a checkout URL to the agent.

- Tool spec: `{name: "request_payment", parameters: {amount: integer (cents), description: string}}`.
- Implementation in `kaji/sdk/src/kaji/tools/payment.py` (or equivalent) -- thin HTTP call to ryo API, configurable base URL via env.
- Needs `@ryo/api` session endpoint (item 8) live first.

---

## P3 -- Capabilities promised but absent

### 14. General document / knowledge RAG (DONE)

- `kaji/sdk/src/kaji/knowledge/` -- `Document`/`Chunk` types, deterministic `chunk_text`, `VectorStore` protocol + `InMemoryVectorStore` (cosine, dimension-guarded), `DocumentRAG` (ingest + retrieve). Infra-free by default; reuses the tool retriever's `Embedder` protocol.
- Exported from the public API; runnable quickstart in the SDK README.
- `AgentRuntime(rag=...)` retrieves from the latest user message and injects relevant chunks into the system prompt each turn.

### 15. Multi-agent / swarm handoff (MISSING)

- The previous no-op swarm router and swarm event stubs were removed. Add this only with a real routing/runtime design.

### 16. Durable session persistence (DONE -- SessionStore interface + serve Postgres backend)

- `kaji/sdk/src/kaji/runtime/sessions/store.py` -- `SessionStore` protocol + `SessionRecord` + `InMemorySessionStore` (a cross-session index, distinct from the per-session `EventStore`).
- `SessionManager` takes an optional `SessionStore`; `list_active` returns recorded sessions when configured, `[]` otherwise. `record_session` + round-trip test exercise the path.
- Exported from the public API; runnable quickstart in the SDK README.
- `kaji/serve/src/kaji_serve/server/session_store.py` -- `PostgresSessionStore` implements the same protocol over the existing `Conversation` table.
- Auto-recording from inside `AgentRuntime` is not wired (the runtime has no `user_id`); callers record via `SessionManager.record_session` or service routes.

### 17. ryo merchant studio -- webhooks UI (MISSING)

Studio (`apps/web`) has no webhook management screens.

- Add `/webhooks` route: register a URL, select events, view delivery history, inspect dead deliveries.
- Feeds from `GET /v1/webhooks` and delivery log in `webhook_deliveries`.

### 18. ryo iOS consumer app (MISSING)

Deferred until the consumer service API and studio web app are stable.
Swift/SwiftUI app, iOS-first.

- Three screens: wallet (Stripe Payment Element), transactions (paginated), activity (plain-language feed).
- Auth: email + password -> JWT from consumer service.
- Stripe iOS SDK for payment method management. No card data in app or consumer service.
- Reads `GET /v1/transactions` and `GET /v1/activity` from consumer service.
- Blocked on items 9 and 17.

### 19. ryo merchant onboarding -- Stripe Connect (MISSING)

Stripe Connect Standard onboarding for merchant wallets. Agentpay owns the UI, submits KYB/KYC fields to Stripe via API.

- Needs a dedicated spec before implementation. Deferred from the current design.

---

## Voice / `kaji-serve` -- reference service gaps

### 20. Barge-in / interruption (MISSING)

- The reference service is STT-only and has no hosted response or TTS path to interrupt.
- Barge-in belongs in a future hosted-runtime adapter, not the current service shell.
- The SDK-level DTMF lookahead buffer at `kaji/sdk/src/kaji/modalities/voice/utils/dtmf_lookahead_buffer.py` remains experimental.

### 21. Automatic turn / endpoint detection (MISSING)

- `kaji/sdk/src/kaji/modalities/voice/turn_detection.py` -- `resolve_turn_policy` has zero consumers.
- `kaji/serve/src/kaji_serve/modalities/voice/stt/soniox_gateway.py` -- endpoint detection is not yet wired through.

### 22. Durable chat persistence (PARTIAL)

- `/sessions` lists `Conversation` rows through `PostgresSessionStore`.
- The service has no hosted agent runtime or message-history writer. Applications
  embedding `AgentRuntime` must supply and own their persistent `EventStore`.

### 23. Reconcile the two auth paths (DONE)

- HTTP validates Bearer tokens locally via HS256 (`kaji/serve/src/kaji_serve/server/deps.py`).
- STT WebSocket auth now uses the same local JWT decode helper in `kaji/serve/src/kaji_serve/server/auth_utils.py`.

### 24. Remove dead code (DONE)

- The legacy node graph, bus worker, and TaskIQ worker surfaces were removed.
- `kaji-serve` now contains only its REST, persistence, auth, and Soniox STT edge.

---

## TypeScript SDK -- to make it drive an agent

### 25. Provider layer (DONE)

- `kaji/ts/src/providers/` -- `ModelProvider` interface (`base.ts`), `registry.ts` (`registerProvider`/`getProvider`/`clearProviders`), `MockProvider` (drives the full tool loop with no network). Mirrors `kaji/sdk/src/kaji/runtime/providers/base.py`.
- A real TS provider (OpenAI/Anthropic) is a clean follow-up; the interface is fixed so it has no design risk.

### 26. Agent runtime (DONE)

- `kaji/ts/src/runtime/runtime.ts` -- ports `AgentRuntime.run_turn`: replay -> build messages -> stream from provider -> emit events -> scatter-gather tools -> loop. Plus `CancellationToken` and `buildMessages`. Guards the final completion on truthy text (matches the Python reference).

### 27. Tool-loop glue (DONE)

- The loop in `runtime.ts` turns provider `tool_calls` into `executeTool` (`kaji/ts/src/tools/registry.ts`) calls and emits the full lifecycle (`ToolCallRequested -> Started -> Completed | Failed`), concurrently via `Promise.all`. The real `tool_call_id` is threaded through replay so a real provider can match results to requests.

### 28. Reconcile sync vs async `publish` (DONE -- publish stays async; runtime awaits it)

- `kaji/ts/src/events/bus.ts` -- `EventBus.publish` is `async` (resolved-Promise) with a doc comment locking the decision; the runtime does `await bus.publish(event)`, matching the Python `await self.bus.publish(...)`.

---

## Developer experience

### 29. kaji CLI / scaffold (DONE)

Both `@kaji/cli` (TypeScript) and `kaji` (Python) ship the same surface:
`init`, `gen`, `info`, `secret`, `upgrade`, `doctor`. The TS CLI additionally
ships `mcp` only as a status command; MCP server registration is deferred until
a real server command exists.

- TS: `bun add -D @kaji/cli` -> `npx kaji init --lang ts|python --provider openai|anthropic|kimi|gemini`
- Python: `pip install kaji-sdk` -> `kaji init --provider openai`
- Landing-page CLI tab: safe to show both `kaji init` flows, but not MCP setup commands.
