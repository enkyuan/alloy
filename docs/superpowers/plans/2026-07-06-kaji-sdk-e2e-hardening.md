# Kaji SDK E2E Trust Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task.

**Goal:** Make `kaji/sdk` and `kaji/ts` trustworthy pre-beta SDKs by fixing TS real-model tool-loop replay, aligning cross-SDK contracts, and tightening first-run/developer proof paths.

**Architecture:** Keep the current `AgentBuilder -> ToolRegistry -> ToolPlanner -> AgentRuntime -> ModelProvider` shape. Fix the missing TS assistant tool-call history path instead of rewriting runtime/provider architecture. Treat Python as the reference for event replay semantics where it already handles provider-required tool-call parents.

**Tech Stack:** Python/Pydantic/pytest/ruff/ty, TypeScript/Zod/Vitest/tsc, OpenAI + Anthropic provider adapters, JSON Schema integration manifests.

## Global Constraints

- Do not rewrite providers, service runtime, voice, RAG, or the integration catalog.
- Use `gpt-5.4-mini` as the default first live OpenAI model unless env overrides it.
- Live tests must skip cleanly without provider keys.
- Use GitButler for version-control inspection and commits per `AGENTS.md`.
- Sequential implementation is required until Task 1 lands, because later work depends on the replay/message contract.

---

## Task 1: Fix TS Assistant Tool-Call Replay And Provider Formatting

**Files:** `kaji/ts/src/providers/base.ts`, `kaji/ts/src/sessions/replay.ts`, `kaji/ts/src/runtime/context.ts`, `kaji/ts/src/providers/openai.ts`, `kaji/ts/src/providers/anthropic.ts`, and matching replay/provider tests.

**Interfaces:** Add `toolCalls?: ToolCall[]` to `ProviderMessage`; add `toolCalls?: MessageToolCall[]` to replay `Message`; preserve `tool_call_id` on tool-result messages.

- [ ] Write replay tests for `TOOL_CALL_REQUESTED` attaching to the previous assistant message and synthesizing an empty assistant message for tool-only output.
- [ ] Update replay to project `TOOL_CALL_REQUESTED` into assistant `toolCalls`.
- [ ] Update context building to pass assistant `toolCalls` through to providers.
- [ ] Update OpenAI formatting to emit assistant `tool_calls`.
- [ ] Update Anthropic formatting to emit assistant `tool_use` blocks.
- [ ] Run `cd kaji/ts && node_modules/.bin/vitest run tests/replay.test.ts tests/providers.openai.test.ts tests/providers.anthropic.test.ts tests/runtime.test.ts`.
- [ ] Run `cd kaji/ts && node_modules/.bin/tsc --noEmit`.

## Task 2: Add Cross-SDK Event Schema Parity For Usage And Cost

**Files:** `kaji/sdk/src/infra/events/schemas.py`, `kaji/sdk/tests/test_events_schemas.py`, shared fixtures under `kaji/fixtures/events/`, and `kaji/ts/tests/events.schema-parity.test.ts`.

**Interfaces:** Python must accept optional `tokens: { input: int, output: int }` and `cost_usd: float >= 0` on `AgentMessageCompleted` and `ToolCallCompleted`, while still rejecting unknown fields.

- [ ] Add shared JSON fixtures for usage-bearing agent and tool-completed events.
- [ ] Add Python `EventTokenUsage` model and optional usage/cost fields.
- [ ] Add Python tests that parse shared fixtures and reject negative values.
- [ ] Add TS schema parity tests that parse the same fixtures.
- [ ] Run Python event schema tests and `scripts/check_types.py`.
- [ ] Run TS event tests and `tsc --noEmit`.

## Task 3: Unify Integration Manifest Schema Contract

**Files:** `kaji/sdk/src/integrations/registry/schema.json`, `kaji/ts/registry/schema.json`, Python and TS registry/CLI validation code, and matching tests.

**Decision:** Both SDKs use one v0 manifest shape: `extras?: string[]`, `peerDeps?: Record<string, string>`, and `tools.minItems = 1`.

- [ ] Make the Python and TS JSON schemas normalized-equivalent.
- [ ] Add `peer_deps` to the Python `Manifest` dataclass.
- [ ] Let TS validation accept `extras` while ignoring Python-only install behavior.
- [ ] Add a Python schema-equivalence test.
- [ ] Run Python integration registry tests.
- [ ] Run TS integration and CLI add tests.

## Task 4: Align Realtime Bus Semantics And First-Run DX

**Files:** `kaji/ts/src/events/bus.ts`, `kaji/ts/tests/bus.test.ts`, `kaji/sdk/src/cli/templates.py`, `kaji/sdk/tests/cli/test_init.py`, SDK READMEs, and `docs/MVP.md`.

**Decisions:** TS in-memory bus subscribers receive backlog then live events. Python `kaji init` generates the high-level `agent.turn("Say hello.")` path.

- [ ] Add TS bus backlog replay behavior and tests.
- [ ] Update Python init template to use the high-level turn API.
- [ ] Update CLI init tests.
- [ ] Update docs to state live tests skip without keys and TS Gemini/Kimi are OpenAI-compatible factories.
- [ ] Run targeted TS bus/CLI tests.
- [ ] Run targeted Python CLI/docs/quickstart tests.

## Task 5: Package And Live-Proof Readiness Checks

**Files:** `kaji/ts/scripts/smoke-install.mts`, live OpenAI tool-loop tests, and SDK READMEs.

**Requirements:** TS smoke install verifies `@kaji/sdk`, `@kaji/sdk/testing`, `@kaji/sdk/openai`, and `@kaji/sdk/anthropic`. OpenAI live tool-loop remains the readiness signal for both SDKs.

- [ ] Extend TS smoke install subpath checks.
- [ ] Confirm no-key integration suites skip cleanly.
- [ ] Confirm keyed OpenAI tests assert requested/completed tool calls, final assistant message, and no turn exhaustion.
- [ ] Run full TS unit, integration no-key, and static checks.
- [ ] Run full Python non-integration, ty, and ruff checks.

## Acceptance Criteria

- TS replay reconstructs assistant tool-call parents like Python.
- OpenAI and Anthropic TS providers format replayed tool-use history correctly.
- Shared event usage/cost fixtures parse in both SDKs.
- Integration manifest schemas no longer drift under the same `$id`.
- Python quickstart scaffold uses the high-level turn API.
- No-key integration suites skip cleanly.
- Full unit/static checks pass for both SDKs.
- Keyed OpenAI live tool-loop passes in both SDKs with `gpt-5.4-mini`.
