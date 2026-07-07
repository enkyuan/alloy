# Kaji SDK/TS Beta Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task. This plan was written for a narrow hardening pass after an e2e assessment of `kaji/sdk` and `kaji/ts`.

**Goal:** Move the stable Python and TypeScript SDK core closer to reliable beta by making the release gate repeatable, explicit, and fail-fast on missing prerequisites without changing runtime behavior or promoting experimental surfaces.

**Assessment:** The TypeScript SDK passes its intended local gates (`bun run test`, `bun run typecheck`, `bun run build`, and package smoke). Python stable-core verification passes through `uv` once the release wrapper exposes the local tool path and uses the platform certificate store. Existing docs and tests already distinguish the stable core from Python-only experimental surfaces, and the live OpenAI script already handles no-key skip/fail semantics.

**Architecture:** Keep the current `AgentBuilder -> ToolRegistry -> ToolPlanner -> AgentRuntime -> provider` architecture. Add one root release gate wrapper that orchestrates existing checks and reports missing toolchain dependencies plainly. Do not rewrite providers, event buses, replay, RAG, voice, Redis, or integration runtime.

**Tech Stack:** Bash, Python/pytest/ruff/ty/uv, TypeScript/Vitest/tsc/Bun/tsup, existing ast-grep rules, existing OpenAI live gate.

## Review Fold-In

- **Plan tune:** Avoid blocking questions because the stable release contract is already documented. Keep scope to the repeatability gap surfaced by the assessment.
- **CEO review:** Beta should mean "stable core verified end to end," not "all Python-only experimental adapters are production-ready." Keyed OpenAI spend remains separate until non-keyed gates are hardened.
- **Eng review:** Add a wrapper around existing gates instead of inventing a second release process. Fail clearly when required tools such as `uv` are missing. Keep docs and tests aligned with the wrapper.

## Global Constraints

- Do not change SDK runtime behavior.
- Do not promote Redis realtime/history, voice/TTS, DocumentRAG, native Gemini/Kimi, or tool retrieval into the beta promise.
- Do not require provider API keys for the default gate.
- Preserve `KAJI_REQUIRE_LIVE_KEYS=1` as the explicit failure-mode proof for missing live credentials.
- Keep ast-grep optional when the local CLI is absent; the repo already exposes `bun run audit:ast-grep` for environments that can resolve the package.
- Use GitButler for checkpoint commits if available. If `but` is unavailable, report that instead of using raw git write operations.

## Implementation Tasks

### Task 1: Add A Root Beta Gate Wrapper

**Files:** `kaji/scripts/beta-release-check.sh`

- [x] Run no-key live-gate skip hygiene.
- [x] Assert `KAJI_REQUIRE_LIVE_KEYS=1` fails loudly without `OPENAI_API_KEY`.
- [x] Run the ast-grep structural audit when `sg` is installed, otherwise emit an explicit skip.
- [x] Run TS unit tests, typecheck, build, and package smoke.
- [x] Fail clearly if `uv` is missing before Python release gates.
- [x] Include common local tool paths and `UV_SYSTEM_CERTS` so local Bun/uv installs work from restricted runners.
- [x] Run Python unit tests, ty, ruff, and wheel smoke when `uv` is available.
- [x] Keep keyed OpenAI proof opt-in through `KAJI_RUN_KEYED_LIVE=1`.

### Task 2: Pin The Wrapper In Tests

**Files:** `kaji/sdk/tests/test_beta_release_check.py`

- [x] Add a shell syntax check for the wrapper.
- [x] Assert the wrapper includes all Python and TS stable-core release gates.
- [x] Assert docs and release matrix reference the wrapper and keyed-live opt-in.

### Task 3: Update Release Documentation

**Files:** `kaji/RELEASE_MATRIX.md`, `kaji/sdk/README.md`, `kaji/ts/README.md`, `docs/MVP.md`, root `package.json`

- [x] Make `bash kaji/scripts/beta-release-check.sh` the default non-keyed gate.
- [x] Document that keyed OpenAI live proof remains required before claiming live readiness.
- [x] Add a root script alias for discoverability.

## Verification

- [x] Run TypeScript unit tests with the intended Vitest command.
- [x] Run TypeScript typecheck.
- [x] Run TypeScript build.
- [x] Run Python tests/typecheck/lint through `uv`.
- [x] Run Python wheel smoke through `uv build` and clean install.
- [x] Run the full non-keyed `bash kaji/scripts/beta-release-check.sh` wrapper.
- [ ] Run keyed OpenAI live proof after non-keyed gates pass and credentials are intentionally supplied.

## Remaining Beta Readiness Questions

- Keyed OpenAI live proof remains intentionally deferred until credentials are supplied.
- Experimental Python-only surfaces should remain outside the beta promise unless they get their own promotion plan and keyed or fixture-backed tests.
- The current keyed OpenAI proof is intentionally deferred per the assessment instruction to ignore API-key usage until the rest of the hardening is complete.
