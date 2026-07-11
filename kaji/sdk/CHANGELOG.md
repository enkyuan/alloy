# Changelog

All notable changes to the `kaji` Python SDK are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

---

## [0.2.0b1] - unreleased pre-beta build

- Added bounded durable tool arguments, fail-closed package verification, and
  reproducible wheel/sdist release gates for shared contract version `1.0.0`.
- Promotion remains blocked pending same-commit protected runtime-matrix,
  provider, benchmark, soak, signing, provenance, and publication evidence.

## [Unreleased] — pre-beta hardening

### Added

- **Public exports** — the lazy map in `kaji/__init__.py` now surfaces 18
  additional names so consumers can import them directly from the top level
  instead of digging into subpackages:
  - Knowledge: `Chunk`, `Document`, `DocumentRAG`, `VectorStore`, `InMemoryVectorStore`.
  - Pluggable infra: `SessionStore`, `InMemorySessionStore`, `SessionRecord`,
    `HistoryStore`, `InMemoryHistoryStore`.
  - Tool retrieval: `Embedder`, `EmbeddingCache`, `ToolRetriever`.
  - Neutral tool payload translators: `build_tools_payload`, `spec_to_neutral`,
    `to_openai`, `to_anthropic`, `to_gemini`.
  The parity table in `kaji/sdk/README.md` lists Document RAG and the tool
  retriever as implemented Python extensions, while the release matrix keeps
  them experimental and outside the beta support promise. Imports remain lazy: `import kaji`
  performs no eager submodule loads.
- **`tests/integration/test_gemini_provider.py`** and
  **`tests/integration/test_kimi_provider.py`** — opt-in live integration tests
  matching the existing OpenAI/Anthropic pattern. Skipped when `GEMINI_API_KEY`
  (resp. `OPENROUTER_API_KEY`) is absent; conftest extended to dispatch.
- **`test_agent_builder.py`** — unit and E2E tests for `AgentBuilder`: fluent
  API, scoped registry isolation, policy wiring, and the regression test that
  builder-registered integration tools are executable (not just listed).
- **`test_tool_planner.py`** — unit tests for `ToolPlanner` covering allow/deny
  policy, approval gate (approved / rejected / no-handler fail-safe), and
  bounded batch execution.
- **`test_providers_anthropic.py`** — mocked unit tests for `AnthropicProvider`
  mirroring the OpenAI test structure: loading, API key guard, `_split_messages`,
  `_parse_tool_use`, `generate()`, and streaming tool reassembly.
- **`test_redis_realtime.py`** — unit tests for Redis helpers (`get_redis_client`,
  `close_redis_client`, `RedisKeys`, `RedisConfig`) using `fakeredis`; skipped
  when `fakeredis` is not installed.
- **Python CI gates** - the repository Python workflows run Ruff, ty, pytest,
  contract synchronization, and clean-install artifact checks for SDK changes.

### Changed

- **`kaji/core/config.py`** — Added `from __future__ import annotations`,
  `TYPE_CHECKING` guard with `settings: Settings` annotation, and `@overload`
  stubs for `__getattr__` so type checkers resolve `from kaji.core.config
  import settings` as `Settings` instead of `Any`.
- **`kaji/README.md`** — Status updated from "pre-release" to "pre-beta"
  with explicit scope on what is and isn't production-hardened.

### Fixed

- `kaji/infra/realtime/redis.py` — redis.asyncio import is already lazy
  (uses `_get_redis_module()`); added `TYPE_CHECKING` guard and updated module
  docstring to document the `kaji[realtime]` install requirement.

---

## [0.1.0] — initial SDK release

- Event-sourced runtime (`AgentRuntime`, `ToolPlanner`, `AgentBuilder`).
- Tool registry with scoped `ToolRegistry` and global helpers.
- `ToolPolicy` with allow/deny lists and approval gates.
- Providers: mock, OpenAI, Anthropic, Kimi/OpenRouter, Gemini.
- Text modality adapter and session management.
- Optional: Redis realtime backbone, voice/TTS adapters.
- CLI scaffold (`kaji` entry point).
