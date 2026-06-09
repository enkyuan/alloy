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

### 5. Anthropic provider (MISSING)
No way to talk to Claude. Most visible provider gap.
- New `agentkit/sdk/agentkit/runtime/providers/anthropic.py` — streaming + tool use.
- Add `anthropic` dep in `agentkit/sdk/pyproject.toml`, `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` to config.
- Self-register in `registry.py`.

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

### 14. General document / knowledge RAG (DONE — retrieval capability; runtime auto-injection deferred)
- `agentkit/sdk/agentkit/knowledge/` — `Document`/`Chunk` types, deterministic `chunk_text`, `VectorStore` protocol + `InMemoryVectorStore` (cosine, dimension-guarded), `DocumentRAG` (ingest + retrieve). Infra-free by default; reuses the tool retriever's `Embedder` protocol.
- Exported from the public API; runnable quickstart in the SDK README.
- DEFERRED: auto-injecting retrieved chunks into the `AgentRuntime` prompt (when to retrieve, how to ground) — a memory-injection design owns that. `DocumentRAG.retrieve()` returns chunks; wiring into the loop is caller code today.

### 15. Multi-agent / swarm handoff (MISSING — stub)
- `agentkit/sdk/agentkit/runtime/agents/router.py:13` — `determine_handoff` unconditionally returns `None`. Implement routing or drop the surface.

### 16. Durable session persistence (DONE — SessionStore interface + in-memory impl; durable backend deferred to serve)
- `agentkit/sdk/agentkit/runtime/sessions/store.py` — `SessionStore` protocol + `SessionRecord` + `InMemorySessionStore` (a cross-session index, distinct from the per-session `EventStore`).
- `SessionManager` takes an optional `SessionStore`; `list_active` returns recorded sessions when configured, `[]` otherwise. `record_session` + round-trip test exercise the path.
- Exported from the public API; runnable quickstart in the SDK README.
- DEFERRED: the durable (Postgres) backend lives in `agentkit-serve` and implements this same protocol. Auto-recording from inside `AgentRuntime` is not wired (the runtime has no `user_id`); callers record via `SessionManager.record_session`.

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
- `agentkit/sdk/agentkit/modalities/voice/stt/soniox_gateway.py:52` — `enable_endpoint_detection=False` hardcoded.

### 22. Durable chat persistence (PARTIAL)
- Postgres `Conversation` / `Message` models and migrations exist but nothing writes to them. History lives only in Redis, trimmed to `AGENT_HISTORY_LIMIT`.
- `agentkit/serve/agentkit_serve/server/v1/sessions.py:10` — `/sessions` backed by in-memory store, lost on restart.

### 23. Reconcile the two auth paths (PARTIAL)
- HTTP validates Bearer tokens locally via HS256 (`agentkit/serve/agentkit_serve/server/deps.py`).
- STT WebSocket validates remotely against Supabase (`agentkit/sdk/agentkit/modalities/voice/stt/handler.py:209`).
- Pick one canonical token model for REST and socket.

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

### 29. agentkit CLI / scaffold `init` (MISSING)
The docs landing page advertises a CLI tab, but there is no `agentkit` CLI yet. Today onboarding is `pip install agentkit` / `bun add @agentkit/sdk` plus hand-wiring `lib/agent.ts` and a route handler. A scaffold command would collapse that into one step.
- New `agentkit init` (and TS equivalent) that scaffolds `lib/agent.ts` (runtime + provider + tool registry + in-memory bus), a framework-appropriate API route handler, and `.env` keys (`AGENTKIT_API_KEY`, provider key).
- Pattern reference: better-auth's CLI — one root binary with `init` / `generate` / `secret` subcommands, package-manager-tabbed install. agentkit has no schema/migration step, so `init` is the primary command.
- Until this lands, the landing-page CLI tab shows the real install command, and the MCP tab (`npx agentkit mcp`) is likewise aspirational.
- The CLI tab currently shows a single `pip install agentkit` command. Once the CLI ships, it should show two tabs: Python (`pip install agentkit` / `agentkit init`) and TypeScript (`bun add @agentkit/sdk` / `npx agentkit init`). Update `hero-readme.tsx` `InstallBlock` at that point.
