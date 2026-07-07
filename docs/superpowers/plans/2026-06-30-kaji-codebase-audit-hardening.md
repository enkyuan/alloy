# Kaji Codebase Audit Hardening Plan

> **For agentic workers:** Implement task-by-task with checkbox tracking. Keep cleanup behavior-preserving unless a task is explicitly marked behavioral hardening.

**Goal:** Make `kaji/` publishable as a credible pre-beta embedded agent SDK plus honest reference service: one clear runtime story, provider errors that behave consistently, deterministic tests, and docs that match the shipped surface.

**Architecture:** Keep the Python and TypeScript SDK cores as the canonical agent runtime. Treat `kaji-serve` as a service adapter around that runtime, not a parallel product runtime. Quarantine or delete stale node-graph/service layers after usage is proven.

**Tech Stack:** Python SDK and service venvs, pytest, FastAPI, SQLAlchemy, Redis extras, TypeScript, Node/Bun tooling, Vitest, oxlint.

## Completion Notes

- Added `sgconfig.yml` and initial ast-grep rules. The local `sg` binary is still not installed, so the rules are ready but were not executable in this environment.
- Mapped the service graph runtime and found it is still live through `kaji_serve.workers.main`; it was marked as a service-internal compatibility layer instead of being moved or deleted.
- Split the Redis realtime helper surface into focused modules while preserving `kaji.infra.realtime.redis_events` compatibility exports.
- Normalized Kimi and Gemini provider construction/error behavior and added provider tests.
- Split no-DB and DB-backed service test clients so non-DB service tests no longer require local Postgres.
- Fixed TS lint warnings and docs parity for Kimi/Gemini TS factories.

## Current Audit Evidence

- `ast-grep` was requested, but `sg` was not installed and `npx @ast-grep/cli` failed on the local npm TLS chain. Structural review used Python AST scans, `rg`, `tsc`, `vitest`, and `oxlint`. Re-run ast-grep once the local toolchain is fixed.
- `kaji/ts`: `tsc --noEmit` passed; Vitest passed with 41 files passed, 4 skipped, 330 tests passed, 6 skipped.
- `kaji/ts`: `oxlint --deny-warnings` fails only on four `unicorn(no-useless-fallback-in-spread)` warnings in provider factory and HTTP registry code.
- `kaji/sdk`: focused SDK checks passed: `tests/test_public_api.py`, `tests/test_package_boundaries.py`, `tests/test_agents_runtime.py`, `tests/test_tool_planner.py` with 65 passed.
- `kaji/serve`: focused API checks currently fail because `tests/conftest.py` assumes a live Postgres database at `localhost:5432/kaji_test_db`.
- Strong existing boundary tests already prevent service-only SDK imports, third-party registry packages, and legacy `ToolDefinition` surfaces from re-entering the SDK.

## Review Synthesis

- **Code quality:** SDK code is mostly clean, scoped, and easy to follow. The biggest redundancy is in `kaji-serve`, where `runtime/nodes` and `runtime/messaging` duplicate parts of the SDK agent loop, tool execution, and event routing.
- **Features:** Present: event-sourced Python and TS runtimes, tool registry/planner/policy, OpenAI/Anthropic providers, Python Kimi/Gemini, TS OpenRouter/Kimi/Gemini factories, FastAPI reference service, voice STT path, Redis handoff helpers, Postgres session metadata.
- **Feature gaps:** Production durable event replay is not wired by default; TS lacks RAG/voice/realtime by design; service provider routes are still Gemini-specific; service tests require hidden local infrastructure.
- **Engineering:** Embedded SDK is usable now for internal/pre-beta agent work. The service stack is useful as a reference but not publishable as production infrastructure until the parallel runtime, durability, and test setup are cleaned up.
- **CEO lens:** The product story should be "simple embedded agent SDK first." Do not let old node-graph or voice-specific service internals define the customer-facing architecture.
- **Eng lens:** Preserve the current SDK contracts. Consolidate runtime ownership and provider error semantics before adding new capabilities.
- **DevEx lens:** A new engineer or customer should be able to run the default test path without discovering a silent Postgres requirement after 19 fixture errors.

## Global Constraints

- No swarm work, no new integrations, no product behavior changes during cleanup unless explicitly marked.
- Prefer deletion or quarantine of stale Milo/Hermes-era and node-graph artifacts over leaving them in the main tree.
- Keep provider errors in `kaji.runtime.providers.errors`; do not add a parallel `service_errors` module.
- Keep public voice-modality types/constants CamelCase when touching voice code.
- Use current test naming domains: `test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`.
- Do not edit generated/cache directories: `.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `logs`.

## Task 1: Restore Reproducible Structural Scanning

**Files:**
- Modify only if needed: repo tooling docs or package scripts.

- [ ] Add or document a repo-approved way to run ast-grep without relying on a broken global install.
- [ ] Capture rules for the checks used in this audit: broad catches, service imports in SDK, duplicate route handlers, legacy naming, TODO markers, and generic `throw new Error`.
- [ ] Verify with:

```bash
sg --version
sg scan kaji
```

## Task 2: Quarantine the Parallel Service Runtime

**Files:**
- Inspect: `kaji/serve/src/runtime/messaging/`
- Inspect: `kaji/serve/src/runtime/nodes/`
- Inspect: `kaji/serve/src/workers/main.py`
- Inspect: `kaji/serve/tests/`

- [ ] Build a usage map:

```bash
rg -n "Bridge|Bus|RouteBuilder|ReasoningNode|AgentReasoningNode" kaji/serve/src kaji/serve/tests
```

- [ ] Delete unused modules. If still used, move experimental graph pieces under an explicit internal/compat namespace and remove public exports.
- [ ] Keep `AgentReasoningNode` only if a worker still needs it. If kept, document it as a service adapter, not a second SDK runtime.
- [ ] Add focused tests around the active worker path before moving or deleting anything.
- [ ] Verify:

```bash
cd kaji/serve
./.venv/bin/python -m pytest tests/test_agents_* tests/test_workers_* -q
```

## Task 3: Split Redis Realtime Helpers Without Behavior Change

**Files:**
- Split from: `kaji/sdk/src/infra/realtime/redis_events.py`
- Add focused modules under: `kaji/sdk/src/infra/realtime/`
- Preserve compatibility exports from: `kaji/sdk/src/infra/realtime/redis_events.py`

- [ ] Move history key/helpers, outbox publishing, DLQ parsing/drain, stream runner, and tool-call dedup into separate modules.
- [ ] Keep the old `redis_events.py` import surface re-exporting the moved functions until all internal imports are updated.
- [ ] Add unit tests for DLQ parse/build, publish outbox fallback, and tool-call dedup keys.
- [ ] Keep `run_stream_with_dlq` behavior identical, but isolate its infinite loop behind injectable poll/sleep knobs for tests.
- [ ] Verify:

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_events_* tests/test_realtime_* -q
```

## Task 4: Normalize Provider Error Semantics

**Behavioral hardening:** provider transport/auth/rate-limit failures should become typed provider/service errors instead of leaking raw SDK or `httpx` exceptions.

**Files:**
- Modify: `kaji/sdk/src/runtime/providers/kimi.py`
- Modify: `kaji/sdk/src/runtime/providers/gemini.py`
- Modify/add tests: `kaji/sdk/tests/test_providers_*`

- [ ] Make `KimiProvider.__init__(**kwargs)` honor explicit `api_key`, `base_url`, and `model` overrides consistently with OpenAI.
- [ ] Map Kimi HTTP status and `httpx` transport failures to existing provider/service error types. Cover 401, 429, 5xx, timeout, and malformed JSON/stream chunks.
- [ ] Make `GeminiService(api_key=...)` use the supplied key, and raise `ProviderConfigError` instead of `ValueError` for missing config.
- [ ] Wrap Gemini generation failures into existing provider/service errors at the provider boundary.
- [ ] Keep all error classes in `kaji.runtime.providers.errors`.
- [ ] Verify:

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_providers_* -q
```

## Task 5: Make Serve Tests Deterministic

**Files:**
- Modify: `kaji/serve/tests/conftest.py`
- Modify tests that do not need DB to avoid the DB fixture.

- [ ] Split fixtures into a no-DB ASGI client and a DB-backed client.
- [ ] Mark DB-dependent tests explicitly.
- [ ] If Postgres is unavailable, skip DB-dependent tests with one clear message instead of continuing after a failed database setup.
- [ ] Keep fakeredis for Redis unless a test explicitly opts into real Redis.
- [ ] Verify:

```bash
cd kaji/serve
./.venv/bin/python -m pytest tests/test_api_health.py tests/test_api_tools.py -q
./.venv/bin/python -m pytest -m "not db" -q
```

## Task 6: Reconcile Docs With Shipped Features

**Files:**
- Modify: `kaji/README.md`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/serve/README.md`
- Modify: `kaji/ts/README.md`
- Modify/add: `kaji/sdk/tests/test_docs_sync.py`

- [ ] Update TS parity docs: `kimi()` and `gemini()` factories exist via OpenAI-compatible endpoints, so do not claim Kimi/Gemini are absent in TS.
- [ ] Keep service docs explicit: Postgres stores session-list metadata; durable event replay is not wired by default.
- [ ] Add doc sync assertions for referenced Kaji paths and parity rows that drift easily.
- [ ] Verify:

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_docs_sync.py -q
```

## Task 7: Small DRY and Lint Cleanup

**Files:**
- Modify: `kaji/ts/src/providers/factory.ts`
- Modify: `kaji/ts/registry/http/index.ts`
- Inspect: `kaji/serve/src/server/app.py`
- Inspect: `kaji/serve/src/server/v1/health.py`

- [ ] Remove useless fallback spreads flagged by oxlint.
- [ ] Consolidate duplicate root/health response construction if it is still duplicated, while preserving routes.
- [ ] Verify:

```bash
cd kaji/ts
PATH=/usr/local/bin:$PATH /usr/local/bin/node node_modules/oxlint/bin/oxlint --deny-warnings
PATH=/usr/local/bin:$PATH /usr/local/bin/node node_modules/vitest/vitest.mjs run --passWithNoTests
```

## Final Verification

Run:

```bash
cd kaji/sdk && ./.venv/bin/python -m pytest -q
cd ../ts && PATH=/usr/local/bin:$PATH /usr/local/bin/node node_modules/typescript/bin/tsc --noEmit
cd ../ts && PATH=/usr/local/bin:$PATH /usr/local/bin/node node_modules/vitest/vitest.mjs run --passWithNoTests
cd ../serve && ./.venv/bin/python -m pytest -q
```

If serve DB tests are skipped, report the exact skip reason and the command needed to run them with Postgres.

## Expected Outcome

Kaji remains behaviorally stable but becomes easier to trust: SDK boundaries stay clean, the reference service stops looking like a second product runtime, realtime code is testable, provider failures are typed and predictable, tests run without surprise infrastructure, and docs match what customers can actually use today.
