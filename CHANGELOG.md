# Changelog

All notable changes to AgentKit are documented here.

## [Unreleased] — SDK Remediation Pass

### TypeScript SDK (`agentkit/ts`) — Beta Candidate

#### Breaking fixes
- **`AgentBuilder` now wires a scoped `ToolPlanner`** so tools registered via `.integration()` are both visible to the model and executable. Previously, `AgentBuilder` registered tools in a local `ToolRegistry` but `AgentRuntime` fell back to the global `executeTool`, causing "Unknown tool" errors for builder-only integrations.
- **`AgentRuntime` delegates all tool execution to `ToolPlanner`** instead of inlining a parallel scatter-gather. This unifies policy enforcement and approval events through a single code path.

#### New features
- `AgentRuntimeOptions` gains `planner`, `toolExecutor`, and `approvalHandler` fields so any level of customisation is possible without subclassing.
- `AgentBuilder` gains `.approvalHandler()` for wiring approval callbacks end-to-end into the runtime.
- `ToolPlanner.executeSingle` now enforces the allow/deny policy (`isAllowed`) **before** the approval gate, matching Python behaviour. Direct planner users get full policy enforcement, not only approval gating.
- New deny-list and allow-list tests added to `tests/tools.planner.test.ts`.
- New E2E builder regression test: a builder-created runtime executes a scoped integration tool through `runTurn` and asserts `TOOL_CALL_COMPLETED`.
- New policy-via-`runTurn` tests: deny, approval-approve, and builder-deny paths.

#### Documentation
- README rewritten: `AgentBuilder` is now the primary quick-start path; global `registerTool` is described as advanced. Export table is regenerated from `src/index.ts`. Python vs TS parity matrix added. "Real LLM providers not yet ported" note removed (OpenAI and Anthropic are exported).
- `ToolRegistry` doc example updated to show `ToolPlanner` as the correct usage pattern.

#### CI
- Added `.github/workflows/ts-sdk.yml`: uses `oven-sh/setup-bun`, runs `bun install`, `typecheck`, and `test` on every push/PR to `agentkit/ts/**`.

---

### Python SDK (`agentkit/sdk`) — Pre-Beta

#### Fixes
- `agentkit/core/config.py`: Added `overload` stubs for the PEP 562 `settings` lazy attribute so type checkers resolve `from agentkit.core.config import settings` as `Settings` rather than `Any`.
- `agentkit/infra/realtime/redis.py`: Replaced the module-level `import redis.asyncio as redis` with a lazy `_get_redis_module()` helper, guarded behind a try/except with a clear `ImportError` message. This prevents import-time failures when the optional `realtime` extra is not installed.
- `redis.py` `close_redis_client` return type annotated as `-> None`; uses `.aclose()` (redis-py 4+ API) consistently.

#### New tests
- `tests/test_agent_builder.py`: Full coverage of `AgentBuilder` — construction, integration registration, decorator-pattern tool wiring, end-to-end `run_turn` with scoped registry, deny policy blocking.
- `tests/test_tool_planner.py`: Covers lifecycle events, error path, auto-generated call ID, deny/allow policy, approval approved/rejected/fail-safe, low-risk skip, and scatter-gather concurrency.
- `tests/test_providers_anthropic.py`: Unit tests for `AnthropicProvider` — import/registration, `_split_messages`, `_parse_tool_use` (dict and namespace blocks, None input), `generate()` with mocked client, `generate_stream()` text chunks and tool-use reassembly.
- `tests/test_infra_redis.py`: Tests for `RedisKeys` versioned naming scheme, `RedisConfig` constants, `get_redis_client` singleton with fakeredis patching, missing-redis error handling, and `close_redis_client` singleton reset.

#### CI
- Added `.github/workflows/sdk-tests.yml`: uses `snok/install-poetry`, runs `poetry install`, `pyrefly check`, and `pytest -q` on every push/PR to `agentkit/sdk/**`.

---

## Status notes

| Package | Status | Notes |
|---|---|---|
| `@agentkit/sdk` (TS) | Beta candidate | Core agent loop, tools, policy, OpenAI/Anthropic providers + OpenRouter/Kimi/Gemini factories (OpenAI-compatible), CI green. Deferred: RAG, voice, Redis, CLI. |
| `agentkit` (Python) | Pre-beta | Suitable for internal embedded agents. Static checks pass on hardened paths. Multi-process platform (Redis, voice workers) not production-hardened. |
