# Kaji Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for parallelizable tasks, or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Move `kaji/` from "good pre-beta SDK + reference service" to a publishable embedded-agent SDK with an honest, stable public contract and a clearly quarantined reference-service runtime.

**Architecture:** Keep the SDK centered on `AgentBuilder -> ToolRegistry -> ToolPlanner -> AgentRuntime -> EventStore/EventBus -> ModelProvider`. Keep `kaji-serve` as a reference service, not a second public runtime.

**Tech Stack:** Python 3.11+, Pydantic 2, FastAPI, Redis, TaskIQ, SQLAlchemy, TypeScript, Zod 4, Vitest, ast-grep.

**Audit Basis:** Reviewed 385 tracked `kaji` files (246 Python, 105 TypeScript), ran ast-grep structural queries, inspected SDK/runtime/provider/events/session/realtime/service/TS surfaces, and ran focused tests:

- `kaji/sdk`: 60 focused remediation tests passed.
- `kaji/ts`: 38 focused remediation tests passed.
- `kaji/serve`: 21 focused remediation tests passed, 3 skipped.
- Repo ast-grep config now parses and reports 110 advisory findings:
  83 `python-broad-exception`, 27 `ts-generic-error`.

## What Already Exists

- Python SDK core: event schemas, in-memory event store/bus, replay, session manager, AgentBuilder, AgentRuntime, ToolRegistry, ToolPlanner, ToolPolicy, integrations, RAG/retriever primitives, provider adapters, CLI scaffold.
- TypeScript SDK core: event/store/bus/replay, AgentBuilder, AgentRuntime, ToolRegistry, ToolPlanner, ToolPolicy, OpenAI/Anthropic providers, provider factories for OpenRouter/Kimi/Gemini, CLI scaffold, registry commands.
- Reference service: FastAPI routes, auth, Gemini text/chat/stream routes, STT WebSocket, Redis stream/pubsub handoff, TaskIQ tool workers, Postgres session index.
- Tests: strong SDK package-boundary tests, quickstarts, replay/planner/provider tests, TS runtime/provider tests, serve no-DB route tests.

## NOT In Scope

- No new third-party integrations beyond proving a small catalog contract.
- No behavior rewrite of product flows while doing cleanup, except explicitly called out terminal/error contract fixes.
- No production durability promise for `kaji-serve` until persistent event replay and load testing are complete.

## Key Findings To Fix

- Cross-SDK wire drift: TS has `provider.rate_limited`; Python does not, despite docs claiming event strings are identical.
- Runtime terminal gap: Python and TS SDK loops can exhaust max tool iterations with no terminal event or final text.
- Provider parity gap: Python OpenAI non-streaming bad tool JSON becomes `{}`; TS returns a parse-error sentinel. Python Anthropic ignores explicit constructor options. OpenAI/Anthropic error classification lags Kimi/Gemini.
- Architecture tax: `kaji-serve` still has a legacy node/messaging runtime used by workers, parallel to SDK `AgentRuntime`.
- Catalog/doc drift: `docs/MVP.md` claims TS CLI/catalog gaps that no longer match the tree, and docs-sync tests do not cover this file.
- Structural guard gap: ast-grep rules exist but the configured scan is broken and not yet CI-grade.
- Publish hygiene: ignored caches and `__pycache__` artifacts exist locally under `kaji/sdk` and `kaji/serve`.

---

## Task 1: Make Structural Audit Checks Runnable

- [x] Fix `tools/ast-grep/rules/python-broad-exception.yml` so `sg scan --config sgconfig.yml kaji` parses under `@ast-grep/cli`.
- [x] Use a valid AST-shaped rule for Python broad exception clauses.
- [x] Keep `python-service-import-in-sdk` as an error rule for SDK boundaries.
- [x] Add a documented command in the root/package developer checks for ast-grep.
- [x] Add a small CI-ready smoke check that fails if the ast-grep config cannot parse.

**Verify:**

```bash
bunx -p @ast-grep/cli sg scan --config sgconfig.yml kaji
```

---

## Task 2: Restore Python/TS Event Contract Parity

- [x] Decide and implement one public wire contract for provider rate-limit observability.
- [x] Recommended: remove the TS-only `PROVIDER_RATE_LIMITED` event unless a runtime path emits it today.
- [x] Update these files consistently:
  - `kaji/ts/src/events/types.ts`
  - `kaji/ts/src/events/schemas.ts`
  - `kaji/ts/src/index.ts`
  - `kaji/ts/src/cli/_replay_render.ts`
  - `kaji/README.md`
- [x] Add a cross-SDK parity test that compares Python `EventType` values to TS `EventType` values.
- [x] If the product wants rate-limit events, add the event to both SDKs instead, plus emitters and replay rendering. Not selected: the implemented wire contract removes the un-emitted TS-only event and keeps rate-limit observability in typed provider errors.

**Verify:**

```bash
cd kaji/sdk && .venv/bin/python -m pytest tests/test_events_schemas.py tests/test_docs_sync.py -q
cd kaji/ts && bun run test tests/events.test.ts tests/cli.replay.test.ts
```

---

## Task 3: Add Explicit Max-Iteration Terminal Semantics

- [x] Add a cross-SDK event such as `agent.turn.exhausted` with fields:
  - `max_iterations`
  - `pending_tool_calls`
  - optional `reason`
- [x] Emit it in Python `AgentRuntime.run_turn` when the loop exits because tool calls continue through `max_iterations`.
- [x] Emit it in TS `AgentRuntime.runTurn` with the same wire shape.
- [x] Keep the current invariant: do not emit empty `agent.message.completed`.
- [x] Update `TurnResult` docs to explain `text == ""` with an exhaustion event.
- [x] Add tests proving exhaustion is observable in both SDKs.

**Files:**

- `kaji/sdk/src/infra/events/types.py`
- `kaji/sdk/src/infra/events/schemas.py`
- `kaji/sdk/src/runtime/agents/runtime.py`
- `kaji/sdk/tests/test_agents_runtime.py`
- `kaji/ts/src/events/types.ts`
- `kaji/ts/src/events/schemas.ts`
- `kaji/ts/src/runtime/runtime.ts`
- `kaji/ts/tests/runtime.test.ts`

**Verify:**

```bash
cd kaji/sdk && .venv/bin/python -m pytest tests/test_agents_runtime.py tests/test_events_schemas.py -q
cd kaji/ts && bun run test tests/runtime.test.ts tests/events.test.ts
```

---

## Task 4: Normalize Provider Error And Tool-Argument Semantics

- [x] Change Python OpenAI non-streaming `_parse_tool_calls` to return `{"__parse_error": ...}` for malformed JSON, matching TS and Python streaming.
- [x] Add Python OpenAI tests proving malformed tool args fail closed through `ToolPlanner`.
- [x] Make Python `AnthropicProvider` accept explicit `api_key` and `model` constructor options, matching OpenAI/Kimi/Gemini.
- [x] Add shared provider error classification helpers for OpenAI/Anthropic so 401/403/429/5xx/network errors map to typed service errors.
- [x] Reuse that helper in Kimi/Gemini where possible to reduce duplicate classification logic.
- [x] For Kimi, consider an injectable/reused `httpx.AsyncClient` or closeable client owner to avoid per-request connection setup in high-throughput use. Deferred: this changes lifecycle ownership and should be a separate performance task.

**Verify:**

```bash
cd kaji/sdk && .venv/bin/python -m pytest tests/test_providers.py tests/test_providers_openai.py tests/test_providers_anthropic.py tests/test_tool_planner.py -q
cd kaji/ts && bun run test tests/providers.openai.test.ts tests/providers.anthropic.test.ts tests/providers.args.test.ts
```

---

## Task 5: Quarantine Or Collapse The Legacy Serve Runtime

- [x] Treat `kaji_serve.runtime.messaging` and `kaji_serve.runtime.nodes` as service-internal legacy compatibility, not public runtime.
- [x] Move or alias them under an explicit internal/legacy namespace, or add package-level warnings/docs that they are not SDK surface.
- [x] Map every import from:
  - `kaji/serve/src/workers/main.py`
  - `kaji/serve/src/runtime/workflows/queue.py`
  - tests under `kaji/serve/tests`
- [x] Remove stale TODOs that are no longer actionable; convert real issues into tests or tracked plan items.
- [x] Design the next step to collapse `AgentReasoningNode` onto SDK `AgentRuntime` while keeping voice/STT edges in `kaji-serve`. Next step: migrate `workers/main.py` to construct SDK `AgentRuntime` behind the existing Redis/voice worker edges, then delete the compatibility nodes once worker tests cover parity.

**Verify:**

```bash
cd kaji/serve && .venv/bin/python -m pytest tests/test_agents_node_infra_free.py tests/test_workers_tts_publish.py -q
```

---

## Task 6: Fix Catalog And MVP Documentation Drift

- [x] Update `docs/MVP.md` to match the current tree:
  - TS CLI scaffold exists.
  - Python registry currently ships echo, not GitHub/Gmail/GCal.
  - TS registry currently ships echo/http/fs/web/sqlite.
  - Python top-level exports include non-MVP RAG/retriever primitives.
- [x] Decide whether top-level Python RAG/retriever exports are intentional. If yes, update MVP wording. If no, move them behind submodule imports in a separate breaking-change plan.
- [x] Extend docs-sync tests to include `docs/MVP.md` or add a dedicated MVP-contract sync test.
- [x] Add catalog parity expectations that make the current asymmetry deliberate rather than accidental.

**Verify:**

```bash
cd kaji/sdk && .venv/bin/python -m pytest tests/test_docs_sync.py tests/test_integrations_registry.py tests/test_package_boundaries.py -q
cd kaji/ts && bun run test tests/cli.add.test.ts tests/cli.list_integrations.test.ts tests/validate-manifests.test.ts
```

---

## Task 7: Tighten Reference-Service Publishability

- [x] Replace `raise Exception("Soniox API key is not configured.")` with a typed configuration error.
- [x] Keep no-DB tests default-fast; mark Postgres tests with `@pytest.mark.db`.
- [x] Make `/sessions` construction clearer by injecting the session index directly rather than creating an unused `InMemoryEventStore`.
- [x] Keep Gemini-specific HTTP routes clearly labeled as convenience routes, not the generic agent API.
- [x] Add a README section that says what `kaji-serve` can do today and what it cannot do without persistent `EventStore` wiring.

**Verify:**

```bash
cd kaji/serve && .venv/bin/python -m pytest tests/test_api_health.py tests/test_api_providers.py tests/test_api_tools.py tests/test_api_auth.py -q
```

---

## Task 8: Clean Local Generated Artifacts Before Release

- [x] Remove local ignored caches under `kaji/sdk` and `kaji/serve`:
  - `__pycache__/`
  - `*.pyc`
  - `.pytest_cache/`
  - `.ruff_cache/`
- [x] Confirm no generated artifacts are tracked.
- [x] Add or verify cleanup command documentation for maintainers.

**Verify:**

```bash
git ls-files kaji | rg '(__pycache__|\.pyc$|\.pytest_cache|\.ruff_cache|logs/)'
find kaji -path '*/__pycache__' -o -name '*.pyc' -o -path '*/.pytest_cache/*' -o -path '*/.ruff_cache/*'
```

---

## Recommended Order

- [x] First: Task 1, Task 2, Task 4. These are contract/safety fixes with small blast radius.
- [x] Second: Task 3 and Task 6. These make runtime behavior and product docs honest.
- [x] Third: Task 5 and Task 7. These reduce architectural debt in the reference service.
- [x] Last: Task 8. Do this immediately before packaging or committing release work.

## Acceptance Criteria

- [x] `sg scan --config sgconfig.yml kaji` runs successfully.
- [x] Python and TS event type sets either match exactly or have a documented, tested exception.
- [x] Malformed model tool arguments never execute as `{}` in either SDK.
- [x] Max-iteration exhaustion produces a replayable terminal event in both SDKs.
- [x] `docs/MVP.md`, package READMEs, and actual catalog/package exports agree.
- [x] `kaji-serve` legacy runtime surfaces are clearly internal or replaced.
- [x] Focused SDK, TS, and serve tests pass.
