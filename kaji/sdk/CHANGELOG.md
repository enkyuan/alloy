# Changelog

All notable changes to the `kaji` Python SDK are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

---

## [Unreleased] — pre-beta hardening

### Added

- **`test_agent_builder.py`** — unit and E2E tests for `AgentBuilder`: fluent
  API, scoped registry isolation, policy wiring, and the regression test that
  builder-registered integration tools are executable (not just listed).
- **`test_tool_planner.py`** — unit tests for `ToolPlanner` covering allow/deny
  policy, approval gate (approved / rejected / no-handler fail-safe), and
  scatter-gather concurrency.
- **`test_providers_anthropic.py`** — mocked unit tests for `AnthropicProvider`
  mirroring the OpenAI test structure: loading, API key guard, `_split_messages`,
  `_parse_tool_use`, `generate()`, and streaming tool reassembly.
- **`test_redis_realtime.py`** — unit tests for Redis helpers (`get_redis_client`,
  `close_redis_client`, `RedisKeys`, `RedisConfig`) using `fakeredis`; skipped
  when `fakeredis` is not installed.
- **CI workflow** — `.github/workflows/sdk-tests.yml` added (runs pyrefly +
  pytest on every push/PR touching `kaji/sdk/`).

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
