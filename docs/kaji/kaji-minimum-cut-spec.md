# Kaji Minimum-Cut Refactor, Research-Backed Spec for @Agent

**Status:** research (read-only `rg`) + implementation plan. **Not yet implemented.**
**Point-in-time snapshot:** as of this read. A concurrent `context-mode` agent
(PID 53573, `~/.pi/agent/npm/node_modules/context-mode/server.bundle.mjs`,
3 instances running) is live-editing `kaji/contracts/.../features.json`,
`packages/ts/src/index.ts`, `docs/kaji/api-parity.md`, and has created
`packages/ts/src/kaji.ts`. `git HEAD` is unchanged (`dd9cb6dd`); nothing is
committed. **Do not edit those shared files while the live agent runs** --
coordinate or serialize. This spec owns the *minimum-cut* deletion plan; @Agent
executes it.

> Research tooling note: `rg` (ripgrep 15.2.0) and `ast-grep` (`node_modules/.bin/sg`,
> `ast-grep`) are both available. The `bash` tool corrupts multi-line / heredoc /
> escaped-regex payloads (remaps `command`→`cmd`), so all queries below used
> **single-line `rg`** with absolute paths. @Agent may re-verify the critical
> `import type` (type-only) vs `import` (runtime) distinction with `sg query`
> `--lang ts` for AST assurance.

## 1. Decision table

| # | Surface | Decision | Why (core evidence) | Action for @Agent |
|---|---------|----------|---------------------|-------------------|
| 1 | `Capability` + `capability()` | **Keep, core** | `kaji.ts` imports `Capability`; `.register(registry)` drives `ToolCallInstruction.name`. | Nothing. |
| 2 | `Kaji` / `kajiExecute` / `KajiExecuteArgs` / `KajiBackend` | **Keep, core (stabilize)** | The one-shot entry point; `KajiBackend` re-exported from `index.ts:293` (this agent's Slice 0). | Ensure `index.ts:295-297` re-exports `Kaji, kajiExecute, KaziExecuteArgs`; keep in `features.json` TS stable. |
| 3 | principal / identity (`ToolExecutionContext`, `normalizePrincipalId`, `MissingToolIdentityError`, `CancellationToken`) | **Keep, core** | `kaji.ts` imports `assertAbortSignal`+`normalizePrincipalId` from `@/runtime/context`; `executeBatch` throws `MissingToolIdentityError` if `principalId` absent (fail-closed). | Nothing. |
| 4 | policy + approvals (`ToolPolicy`, `AutoApprovalHandler`, `TypedApprovalHandler`, `ApprovalDecision`, `approvalKey`, `cliApprovalHandler`) | **Keep, core** | `kaji.ts` passes `policy`/`approvalHandler`; planner is sole policy+approval enforcer (`planner.ts:711,726,783-918`). | Nothing. |
| 5 | idempotency (`ToolIdempotencyLedger`, `IdempotencyConflictError`, `IdFactory`/`UuidFactory`) | **Keep, core** | `kaji.ts` wires `backend.idempotencyLedger`→controller; deterministic `sessionId` ⇒ `idempotencyKey===sessionId:toolCallId`. | Nothing. **Note:** `postgres/idempotency.ts:4` runtime-imports `closedRecoveryFields` from `@/integrations/recovery` (relocate, see #13). |
| 6 | cancellation + deadlines (`CancellationToken`, `CancellationError`, `deadlineAfter`, `TurnDeadlineOutcome`) | **Keep, core** | Feature object `cancellation` role:core; fail-closed semantics preserved. | Nothing. |
| 7 | events / audit journal (`EventStore`, `EventCommitter`, `EventType`, `NewKajiEvent`, `StoredKajiEvent`, `BaseEvent`, `EventIdConflictError`, `applyEvent`) | **Keep, core** | `kaji.ts` wires `emit`→`backend.journal`; planner emits `ArtifactEmitted` etc. **TS `events/` has zero Task refs** (rg: no match) → Task-independent. | Nothing. |
| 8 | backends, in-memory (`InMemoryBackend`, `EventJournal`, `SessionTurnCoordinator`, …) | **Keep, core** | `kaji.ts` `new InMemoryBackend()`. No providers/integrations import in `backends/in-memory.ts` (rg: clean). | Nothing. |
| 9 | Postgres backend (`KajiPostgresBackend`/`PostgresBackend`) | **Keep, optional prod backend** | `backends/postgres/` subtree; runtime dep on `@/integrations/recovery::closedRecoveryFields`, must be satisfied by relocation. | After #13. |
| 10 | `AgentBuilder` (+ `AgentBuilderBuildOptions`, `AgentStrategy`) | **Delete from stable product** | Not in `kaji.ts` import set. Consumers only: `runtime/builder.ts:256`, `runtime/oneshot.ts`, `cli/init.ts:5`, `integrations/functional.ts` (`kaji.ts` mentions it only in a comment). | Remove export from `index.ts:256`; remove `AgentBuilder/AgentBuilderBuildOptions/AgentStrategy` from `features.json` TS stable; delete `runtime/builder.ts` (and its tests), see caveats. |
| 11 | `AgentRuntime` / model loop (+ `AgentRuntimeOptions`) | **Delete from stable product** | Not in `kaji.ts`. Consumers only: `runtime/{runtime,oneshot,builder}.ts` + `index.ts`. | Remove `index.ts:221` export; remove from `features.json` TS stable; delete `runtime/{runtime,oneshot}.ts` subtrees. |
| 12 | Model providers (`ModelProvider`, `OpenAIProvider`, `registerProvider`, `getProvider`, `providerFamily`, `normalizeProviderError`, `Provider*`, `withRetry`, `resolveProviderResponseLimits`, `openai` factory, `calculateCostUsd`/`lookupCost`) | **Delete adapters; KEEP type-only bridge types** | `kaji.ts` imports none. Core dep is **type-only only**: `@/runtime/context.ts:5 import type { ProviderMessage }`; `runtime/approval/{types:auto,handler}.ts:4/5/6 import type { ToolCall } from "@/providers/base"`. `backends/in-memory.ts` does **not** import providers (rg: clean). Feature object `openai-adapter` is currently `role:core` (agent-made), **reclassify**. | Delete `providers/{factory,anthropic,costs,registry,errors,args,openai/,response/,mock}.ts`; delete `packages/serve` provider wiring; reclassify `openai-adapter` feature → experimental/removed. **Relocate** bridge types `ProviderMessage`, `ToolCall`, `ProviderAPIError`/`ProviderError`*, `RetryOptions`, `withRetry`, `resolveProviderResponseLimits`, `ModelProviderOptions` (consumed type-only by `context.ts`/approval) to `@/messages` (or keep a slim `@/providers/base.ts`). @Agent: use `sg` to enumerate exact provider exports and consumers to avoid over- or under-deleting. |
| 13 | Integrations manifest system (`Integration`, `Integration*`, `GitHubIntegration`, `createGithubIntegration`, `inspectIntegration`, `formatIntegrationError`, `snapshotIntegrationResult`, `IntegrationManifest*`) | **Delete adapters; RELOCATE recovery primitives** | `kaji.ts` imports none. Core dep: **type-only** in `tools/planner.ts:45` (`IntegrationRecoveryReason`) and `tools/execution/errors.ts:4-6` (`IntegrationRecoveryFields`/`IntegrationRecoveryReason`); **runtime** in `backends/postgres/idempotency.ts:4` (`closedRecoveryFields` value) and `events/schemas.ts`. | Delete `providers`? no, delete integration adapter/manifest/auth/cli layers: `integrations/{base,public,origin,functional,errors,github,registry/loader,safe-fetch}.ts`; `auth/{keychain,oauth,source,index}.ts`; `cli/{add,connect,disconnect,integrate-copy,render,list}.ts`. **Relocate** `integrations/recovery.ts` → `@/recovery` (exports at `recovery.ts:6,41,164,170,176,202,212`); repoint `postgres/idempotency.ts`, `events/schemas.ts`, `tools/planner.ts`, `tools/execution/errors.ts`, `contracts/integration-recovery.ts`. Reclassify feature `echo-integration` (currently `role:core`) → removed. |
| 14 | Python `TaskRuntime` / `TaskHandle` / `TaskSnapshot` / `TaskState` / `TaskCompleted` / `TaskInvocation` | **Delete** | Not exported by TS `index.ts` (rg: no match) and absent from TS `events/` (TS has zero task refs). Python-only surface. | Delete `packages/py/src/tasks/{__init__,errors,handle,projector,types}.py`; remove exports at `py/__init__.py:118-123`; strip task event types from `py/src/events/{__init__,types,schemas}.py`; remove `contracts/tasks/v1/...`; drop from `features.json` `publicExports.python.stable` + `schema-parity.test.ts`/`check.py`. |
| 15 | Artifact abstraction (`ArtifactRef`, `ArtifactEmitted`, `artifact()`, `validateArtifactRef`) | **Keep, core** | `kaji.ts` returns `CapabilityResult<T>` whose `.artifacts: ArtifactRef[]`; planner emits `ArtifactEmitted` (`planner.ts:1050-1070`); controller extracts artifacts via `isCapabilityResult` (`execution.ts:540,557`); appears in `events/types,schemas,errors`. Execution output genuinely carries artifacts. | Nothing. **Do not delete.** |

## 2. Core-closure ground truth (what `Kaji.execute` actually imports)

`kaji/packages/ts/src/kaji.ts` (created by the concurrent agent; validated against prior spec) imports only:

```
backends/in-memory (InMemoryBackend), backends/base (KajiBackend)
capabilities/definition (Capability), capabilities/result (isCapabilityResult, capabilityResult, CapabilityResult)
internal/uuid (systemClock, systemIdFactory, systemTimerScheduler)
events/json (JsonValue)
tools/policy (ToolPolicy)
tools/planner (ToolPlanner, ToolCallResult, bindEmitterToCommitter)
tools/execution (ToolExecutionController)
tools/execution/errors (ToolExecutionError)
runtime/context (assertAbortSignal, normalizePrincipalId)
tools/registry (ToolRegistry)
runtime/approval/types (TypedApprovalHandler)
runtime/cancellation (CancellationToken)
```

**None** of these are provider/adapter/agent/task/integration modules, so the execution path is already clean of the surfaces slated for deletion. The only non-type-only ("value") references into the deletion scope from this closure are mediated through `backend.journal.commit`/`backend.idempotencyLedger` (backend seams), which is exactly the abstraction the cut must preserve.

## 3. Core dependency classification (the justification crux)

`rg` of the core closure against deletion surfaces proves the separations below. **Type-only imports (`import type`) are erasable and do NOT constitute a runtime dependency**, they are relocation, not coupling.

| Core file | Deletion surface | `import` form | Runtime? |
|-----------|------------------|---------------|----------|
| `tools/planner.ts:45` | `@/integrations/recovery` (`IntegrationRecoveryReason`) | `import type` | No (type) |
| `tools/execution/errors.ts:4-6` | `@/integrations/recovery` (`IntegrationRecoveryFields/Reason`) | `import type` | No (type) |
| `runtime/context.ts:5` | `@/providers/base` (`ProviderMessage`) | `import type` | No (type) |
| `runtime/approval/{types,auto,handler}.ts:4/5/6` | `@/providers/base` (`ToolCall`) | `import type` | No (type) |
| `backends/in-memory.ts` | providers / integrations |, | **No dependency** |
| `backends/postgres/idempotency.ts:4` | `@/integrations/recovery` (`closedRecoveryFields`) | `import` (value) | **Yes (runtime)** |
| `events/schemas.ts` | `@/integrations/recovery` |, | type/schema (no runtime value dep on manifests) |

**Conclusion:** removing providers and the integration *manifest system* breaks nothing in core at runtime, except `postgres/idempotency.ts` needs `closedRecoveryFields`. The prerequisite, therefore, is relocating `integrations/recovery.ts` to a core path (`@/recovery`) and repointing its 5 consumers (`postgres/idempotency.ts`, `events/schemas.ts`, `tools/planner.ts`, `tools/execution/errors.ts`, `contracts/integration-recovery.ts`); the manifest-side consumers (`integrations/public.ts`, `cli/connect.ts`, `cli/render.ts`) are deleted wholesale.

## 4. Implementation plan for @Agent (ordered, non-atomic)

**0. Concurrency gate.** Confirm the context-mode agent has finished the `kaji.ts` + `index.ts` + `features.json` + `api-parity.md` writes (or ask it to yield). @Agent must NOT edit those files concurrently (lost-update risk on `index.ts`).

**1. Relocate shared recovery primitives (enables #13).**
- Create `src/recovery.ts` (or `src/events/recovery.ts`) containing `integrations/recovery.ts` contents (exports at `recovery.ts:6,41,164,170,176,202,212`).
- Repoint imports: `backends/postgres/idempotency.ts:4`, `events/schemas.ts`, `tools/planner.ts:45`, `tools/execution/errors.ts:4-6`, `contracts/integration-recovery.ts` → `@/recovery`.

**2. Delete provider adapters + relocate bridge types (enables #12).**
- Delete `providers/{factory,anthropic,costs,registry,errors,args,openai,response,budget,mock}.ts`.
- Keep/relocate type-only bridge types (`ProviderMessage`, `ToolCall`, `ProviderAPIError`/`ProviderError`*, `RetryOptions`, `withRetry`, `resolveProviderResponseLimits`, `ModelProviderOptions`, `DEFAULT_PROVIDER_RESPONSE_LIMITS`) where `context.ts`/approval still type-import them. Use `sg` to enumerate consumers to avoid breaking `@/messages` or observability types still used elsewhere.
- Remove provider symbols (`ModelProvider`, `OpenAIProvider`, `registerProvider`, `getProvider`, `providerFamily`, `normalizeProviderError`, `openai`, `calculateCostUsd`, `lookupCost`, …) from `features.json` `publicExports.typescript.stable`.

**3. Delete integration manifest/auth/CLI + agent loop (enables #10, #11, #13-adapters).**
- Delete `integrations/{base,public,origin,functional,errors,github,registry/loader,safe-fetch}.ts`.
- Delete `auth/{keychain,oauth,source,index}.ts` + CLI `cli/{add,connect,disconnect,integrate-copy,render,list}.ts` (TS) and equivalents in `packages/serve`/`py` CLI.
- Delete `runtime/{runtime,builder,oneshot}.ts` subtrees (agent loop), see caveats re. `cli/init.ts` (creates an agent; will dangle).
- Remove `AgentBuilder`/`AgentRuntime`/`AgentStrategy`/`Integration*`/`Integration`-manifest symbols from `features.json` TS stable.

**4. Delete Python Task surface (enables #14).**
- Delete `packages/py/src/tasks/` + `contracts/tasks/v1/...`.
- Remove `TaskHandle/TaskRuntime/TaskSnapshot/TaskState/TaskCompleted/TaskInvocation` from `py/__init__.py` (lines 118-123) and strip task event types from `py/src/events/{__init__,types,schemas}.py` (rg-confirmed references).
- Update `schema-parity.test.ts` + `check.py check_parity` (task.* scenarios).

**5. Reclassify `features.json`.**
- Feature-object changes: `openai-adapter` (core→removed/experimental), `echo-integration` (core→removed), `agent-builder`+`runtime-turn-loop` (compatibility→removed, per the "no compatibility tier" rule, delete from stable, do not park).
- Keep as `role:core`: `cancellation`, `sessions`, `in-memory-event-store-journal`, `event-replay`, `tool-registry-planner-policy`, `kaji-execute`.

**6. Regenerate + verify.**
- Regenerate `docs/kaji/api-parity.md` TS fragment (must drop the deleted symbols; must keep `Kaji`/`KajiBackend`/`KajiExecuteArgs`/`kajiExecute` + core).
- Rebuild `dist/index.d.ts` (`bun run build` / `tsup`) so the freshness gate passes.
- Run `uv run python tooling/contracts/check.py --contracts-only` → must exit 0 (`feature_sets`, `check_feature_roles`, `check_public_exports`, `check_parity`).
- Run `bun run test` → `public-declarations` set-equality + role test must pass: `features.json` TS stable∪experimental∪deprecated ≡ `index.d.ts` exports.

## 5. Verification gates

- `check.py --contracts-only` exits 0.
- `public-declarations.test.ts`: (a) `classifies every built root export exactly once`, (b) `index.d.ts is younger than src/index.ts` (freshness), (c) role test holds.
- `schema-parity.test.ts` parity snapshots regenerated (`{id, snapshot}` envelopes).
- `rg`/`sg` post-check: **zero** `import` (value, not `import type`) of `@/providers`, `@/integrations`, `@/runtime/builder`, `@/runtime/oneshot`, `@/runtime/runtime`, or `github`/`gmail` symbols from **core execution dirs** (`tools/`, `backends/`, `capabilities/`, `runtime/context.ts`, `runtime/approval/`, `internal/`, `events/json.ts`). Only `@/recovery` and the relocated bridge types may remain.
- `Kaji.execute()` still type-checks and its acceptance path (capability→registry→controller+planner→executeBatch→CapabilityResult) is unchanged.

## 6. Caveats / HITL calls

- **`cli/init.ts`** scaffolds an *agent* ("create a new kaji package, create a new agent"). If `AgentBuilder` is deleted, `init.ts` dangles or must become `kaji init --template capability` (the spec's Slice 2). @Agent to confirm the new `init` shape with HITL before deleting `builder.ts`.
- **`features.json` is being mutated live** by the context-mode agent. The line numbers cited here are point-in-time (2026-09-13 ~03:2x). @Agent must `git diff` fresh before editing.
- **No compatibility tier** (per Q4 decision): removed surfaces are *deleted from stable exports*, not parked. Only do this if there is no meaningful installed base depending on them, confirm via `git log`/usage before finalizing `AgentBuilder`/`AgentRuntime` deletion.
- **Postgres backend** (`KajiPostgresBackend`) stays; keep `@irogane/kaji/postgres` subpath (package.json exports + `packageSubpaths.typescript`). `closedRecoveryFields` relocation must not change its public behavior.
- **`modalities/voice/tasks.py`** (`packages/py/src/modalities/voice/tasks.py`) is **not** the Task runtime, do not delete it (it matched `find -path '*task*'` by name only).
