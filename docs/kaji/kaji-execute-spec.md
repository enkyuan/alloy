# Kaji.execute, Product-Shape Refactor Spec (A0–A2)

Status: **Draft, composed for `plan-eng-review`, corrected against verified ground truth**
Source of truth: supersedes the investigation open-questions in `.pi/tasks/session-78914-78914/b88c4f867.output` (completed research brief) and the v0.3 implementation slices in `docs/kaji/v0.3-plan.md`.

> This spec was reviewed by an eng-manager plan review (the gstack `plan-eng-review` workflow is not installed as a CLI in this environment, so its methodology was run via the available `review` subagent against the live code). All P0–P2 findings from that pass are incorporated below and cited by ID. The most material corrections: `Kaji.execute` must route through `ToolPlanner.executeBatch()` (the `ToolExecutionController` alone skips `ToolPolicy` + approval → a fail-closed violation); the `executeBatch` input is `sessionId + turnContext.principalId + signal` (the planner assembles the full `ToolExecutionContext` internally); `KajiBackend` and `TypedApprovalHandler` are the real type names and import paths.

## 0. Scope

**In scope.**
- Add `Kaji.execute({ capability, input, principal })` as the stable core product entry point for one-shot, non-con conversational capability execution through the **existing** execution envelope.
- Reclassify `AgentBuilder`/`AgentRuntime` as compatibility surface (not removed, not renamed, preserved full backward compatibility).
- Extend `features.json` with a second classification axis (`role`) so stability (`tier`) and product role are not conflated.
- Ship with tests; no production behavior of legacy paths may regress.

**Out of scope.**
- No second execution path (`Kaji.execute` routes through `ToolExecutionController` + `ToolPlanner` + `ToolRegistry`).
- No TypeScript `TaskRuntime`/`TaskHandle`/`TaskSnapshot` implementation in this slice.
- No MCP, no A2A, no graph/workflow DSL, no new provider, no package rename, no Ryo code in core.
- No PyPI publication (remains deferred).

## 1. Verified current state (ground truth)

| Area | State | Location |
|------|-------|----------|
| Entry point | No `Kaji` class, namespace, or `Kaji.execute`. Consumers use `AgentBuilder.build()` → `AgentRuntime` | `kaji/packages/ts/src/runtime/{builder,runtime}.ts` |
| Execution envelope | `ToolExecutionController` (permit pool, idempotency claim, deadline races, result snapshot), but **policy + approval are NOT here** | `kaji/packages/ts/src/tools/execution.ts:226` |
| Policy + approval locus | `ToolPlanner.preflight()`, `ToolPolicy.isAllowedAny()` (policy.ts:711), `requiresApproval()` (policy.ts:78), approval decision handling (planner.ts:783-918) | `kaji/packages/ts/src/tools/{policy,planner}.ts` |
| Capability adapter | `Capability` compiles to `ToolSpec` + handler and `register(registry)`; `ToolPolicy` applies by capability `name`; unknown risk fails closed | `kaji/packages/ts/src/capabilities/definition.ts:33-46` |
| `CapabilityResult<T>` / `capabilityResult()` / `isCapabilityResult()` | `{value?, artifacts}`, symbol-branded; `capabilityResult(value?, artifacts?)` is **positional** | `kaji/packages/ts/src/capabilities/result.ts:7,13,39` |
| `ArtifactRef` / `artifact()` | `artifact(id, type, uri, options?)` is **positional**; validated (namespaced type, URI scheme, durable-JSON metadata) | `kaji/packages/ts/src/artifacts/types.ts:44`; exported from `index.ts` |
| `AgentBuilder` / `AgentRuntime` | Root exports; classified `stable` | `index.ts` (~`@/runtime/builder`, `@/runtime/runtime`); `features.json` top-level `stable` array, `agent-builder` + `runtime-turn-loop` |
| `features.json` structure | `cliCommands.{python,typescript}`, `packageSubpaths.typescript.*`, `publicExports.typescript.{stable,experimental,deprecated}` (symbol-name **arrays**), and top-level `stable`/`experimental`/`deprecated` arrays of `{id, surface}` objects. **No `role` field anywhere; no `compatibility` tier; `deprecated` empty.** | `kaji/contracts/tiers/v1/features.json` |
| Backends | `InMemoryBackend` (root export) = `{store, journal: EventCommitter, coordinator, idempotencyLedger}`; `KajiPostgresBackend` at `@irogane/kaji/postgres` (`./postgres` subpath). `KajiBackend` interface = `{store, journal, idempotencyLedger, coordinator}`, **not** currently re-exported from root | `kaji/packages/ts/src/backends/{base,in-memory,postgres}.ts`; `package.json` `./postgres` |
| `public-declarations.test.ts` | Asserts root export set == flat union of `publicExports.typescript.{stable,experimental,deprecated}` (a flat array-equality check, **no `role` column**); also maintains a `forbidden` list (incl. `Task*` symbols) that must NOT appear in the `.d.ts` | `kaji/packages/ts/tests/contracts/public-declarations.test.ts:59,164-189` |
| `schema-parity.test.ts` | "pins core defaults byte-for-byte and preserves the TypeScript export projection" (line 45); projects Python `Task*` OUT of TS (line 108-113, via `legacyPythonTaskSymbols`) | `kaji/packages/ts/tests/contracts/schema-parity.test.ts` |
| `projection.py` | `PYTHON_LEGACY_EXPORTS = {TaskHandle, TaskRuntime, TaskSnapshot, TaskState, TaskCompleted}` (line 29); at line 67 filters those names out of the stable export set | `kaji/tooling/contracts/projection.py` |
| Python `Task*` | Present in `kaji.tasks`; projected OUT of TS parity; de-promoted to legacy/experimental for this slice |, |

## 2. Resolved decisions (the five open contract questions)

### Q1, `Kaji.execute` signature & invocation model, DECIDED
**Static, stateless, dependency-injectable. No `new`, no persistent engine instance.** All collaborators are supplied via the parameter object so a one-shot call needs no prior wiring:

```ts
interface KajiExecuteArgs {
  capability: Capability;               // from @/capabilities/definition
  input: Record<string, unknown>;       // capability arguments
  principal: string;                     // non-empty caller identity (only string principals)
  backend?: KajiBackend;                // defaults to new InMemoryBackend()
  policy?: ToolPolicy;
  approvalHandler?: TypedApprovalHandler;
  cancellationToken?: CancellationToken;
  sessionId?: string;                   // optional: enables same-session retry deduplication
  metadata?: Record<string, unknown>;
}
```

- `backend` defaults to `new InMemoryBackend()` (prototype/local path). Production callers pass `PostgresBackend` (`@irogane/kaji/postgres`).
- `principal` is a non-empty string, normalized via `normalizePrincipalId` (`@/runtime/context`). Structured principal objects are not accepted: the resolved product decision exposes only `principalId: string`, and identity data must not be copied into metadata.
- `policy`/`approvalHandler` optional; if omitted → fail-closed (`ToolExecutionController` rejects unknown risk before execution).
- **`Kaji.execute` returns `CapabilityResult<T>`**, see Q2.

*Rationale:* minimal onboarding (no journal internals needed), single execution path (reuse the `ToolPlanner` + `ToolExecutionController` stack that `AgentBuilder.build()` already constructs at builder.ts:153-208), no stateful engine to misconfigure. Matches the brief's `Kaji.execute({ capability, input, principal })`.

### Q2, Return type, DECIDED: `CapabilityResult<T>`
`Kaji.execute` resolves to a `CapabilityResult<T>` (`{ value?, artifacts }`) reusing the existing `capabilityResult()` factory + `isCapabilityResult()` guard.
- Artifacts are first-class to Kaji (`ArtifactEmitted` event); a raw-`T` return (Option A) would hide artifacts and contradict one-shot durable execution.
- The existing stack already produces this shape: the planner returns `ToolCallResult[]`; for a completed call `result` is the raw handler return, and `isCapabilityResult(result)` distinguishes a full result from plain JSON (`capabilityResult(result)` wraps the latter). `ArtifactEmitted` is emitted by `ToolPlanner.executePrepared()` (planner.ts:1057-1070) from the controller outcome's `artifacts`; `Kaji.execute` does **not** emit events itself.
- Dropped `KajiExecuteResult` (a redundant new wrapper), `Kaji.execute` returns `CapabilityResult<T>` directly, avoiding the unconstrained-generic mismatch called out in review P1-7.

### Q3, Approval lifecycle during `Kaji.execute`, DECIDED: inline, fail-closed reject
Approval is handled by the **existing** `ToolPlanner` approval path (planner.ts:783-918), invoked synchronously inline through `executeBatch`:
- A capability whose `risk` triggers `policy.requiresApproval(name, risk)`:
  - if no `approvalHandler` is supplied → the planner produces a terminal failure with `error_code: "APPROVAL_UNAVAILABLE"` and **does not execute**;
  - if the handler denies → `error_code: "APPROVAL_REJECTED"` and **does not execute**;
  - in both cases `Kaji.execute` **rejects** by throwing a `ToolExecutionError` carrying the `error_code` (no invented `ApprovalDeniedError`/`ExecutionRequiresApproval`, review P0-5). This is the single, existing approval contract; no second journal.
- `approvalCommitter` is wired to `backend.journal` (requirement called out in P1-5).

### Q4, `features.json` classification, DECIDED (per product direction)
**Do not invent a `compatibility` stability tier.** Introduce a second axis, `role`, on feature entries, distinct from `tier` (which encodes the semver promise):

```jsonc
// features.json, added to the top-level stable/experimental feature objects (already {id, surface}):
{ "id": "kaji-execute",  "surface": "Kaji.execute one-shot entry point", "role": "core" }
{ "id": "agent-builder", "surface": "Agent builder",                      "role": "compatibility" }
{ "id": "runtime-turn-loop", "surface": "Runtime turn loop",             "role": "compatibility" }
// publicExports.typescript.stable: add "Kaji", "kajiExecute", "KajiExecuteArgs", "KajiBackend"
```

- `AgentBuilder`/`AgentRuntime` keep `tier: "stable"` (signatures never change; existing tests pass unchanged); annotated `role: "compatibility"`.
- `Kaji`/`kajiExecute` → `tier: "stable"`, `role: "core"`.
- `public-declarations.test.ts` keeps its flat-array export-name assertion **unchanged**, and gains a **separate** `it("classifies features by role")` test asserting `kaji-execute`=core, `agent-builder`/`runtime-turn-loop`=compatibility, and that any *declared* `role ∈ {"core","compatibility"}` (review P1-1, no fake "column").
- `docs/kaji/api-parity.md` regenerated by the existing generator to list `Kaji`/`kajiExecute`/`KajiExecuteArgs` under stable core exports; `AgentBuilder`/`AgentRuntime` annotated "compatibility surface".

**Open decision logged (review P1-2):** v0.3 rule 5 (Python/TS semantics must match for anything `stable`) has no Python `Kaji.execute` in this slice. Per the product decision (Q4) and the npm-beta-first direction (NEXT.md), `kaji-execute` ships `stable`/`core` on TypeScript; Python parity is an explicit follow-up epic and the v0.4 release gate (see §5). This overrides the review's "demote to experimental" suggestion, user direction wins; the parity gap is tracked, not silently reclassified.

### Q5, Scaffold & quickstart, DECIDED
- `kaji init` (CLI) **continues** to scaffold `AgentBuilder` for the conversational-agent on-ramp (matches docs §8 / README "Build an agent").
- Add a **new template** `kaji init --template capability` scaffolding a `Kaji.execute`-driven capability (matches README "Expose a product capability").
- `docs.test.ts` snippet extraction extended with marker `docs-test:kaji-execute-capability:typescript` (review P2-2); existing AgentBuilder snippets untouched.

## 3. API surface (TypeScript), routes through the existing `ToolPlanner` + `ToolExecutionController` stack

`Kaji.execute` does **not** call a controller method directly. `ToolExecutionController.execute()` only handles idempotency claims, permit pooling, and deadline races, it does **not** apply `ToolPolicy` or invoke any approval handler (review P0-4). Those live in `ToolPlanner`, so `Kaji.execute` composes the same `ToolRegistry` + `ToolExecutionController` + `ToolPlanner` triple that `AgentBuilder.build()` does (builder.ts:153-189) and dispatches one capability through `ToolPlanner.executeBatch()`:

```ts
// NEW: kaji/packages/ts/src/kaji.ts
import { ToolRegistry, type ToolSpec } from "@/tools/registry";
import { ToolPlanner, type ToolCallInstruction, bindEmitterToCommitter } from "@/tools/planner";
import { ToolExecutionController, type ToolExecutionError } from "@/tools/execution";
import { systemIdFactory, systemClock, systemTimerScheduler } from "@/internal/uuid";
import { InMemoryBackend } from "@/backends/in-memory";
import type { KajiBackend } from "@/backends/base";
import {
  normalizePrincipalId,
  MissingToolIdentityError,
} from "@/runtime/context";
import { isCapabilityResult, type CapabilityResult } from "@/capabilities/result";
import { capabilityResult } from "@/capabilities/result";
import type { ToolPolicy } from "@/tools/policy";
import type { TypedApprovalHandler } from "@/runtime/approval/types";
import type { CancellationToken } from "@/runtime/cancellation";
import type { Capability } from "@/capabilities/definition";

interface KajiExecuteArgs {
  capability: Capability;
  input: Record<string, unknown>;
  principal: string;                     // non-empty caller identity (only string principals)
  backend?: KajiBackend;
  policy?: ToolPolicy;
  approvalHandler?: TypedApprovalHandler;
  cancellationToken?: CancellationToken;
  /** Same-session retries of one capability deduplicate to a single
   *  execution through the stable `kaji:<capability>` tool identity;
   *  changed input in the same session conflicts instead of re-running. */
  sessionId?: string;
  metadata?: Record<string, unknown>;
}

export const Kaji: { execute: typeof execute } = {
  execute,
} as const;
export { execute as kajiExecute };

async function execute<T = unknown>(args: KajiExecuteArgs): Promise<CapabilityResult<T>> {
  const backend = args.backend ?? new InMemoryBackend();
  const idFactory = systemIdFactory;

  // (1) Same registry + capability registration path as AgentBuilder.build().
  const registry = new ToolRegistry();
  args.capability.register(registry);                                // definition.ts:41, registers ToolSpec+handler
  const specs = new Map(registry.listSpecs({ enabledOnly: false }).map((s: ToolSpec) => [s.name, s]));

  // (2) Same controller+planner composition. Policy + approval live ONLY in the planner.
  // NOTE: executionController cannot be combined with idempotencyLedger/executionLimits (planner.ts:393).
  const executionController = new ToolExecutionController({
    ledger: backend.idempotencyLedger,
  });
  const planner = new ToolPlanner({
    executor: (name, argv, context) => registry.execute(name, argv, context),
    policy: args.policy,
    approvalHandler: args.approvalHandler,
    specs,
    executionController,
    approvalCommitter: backend.journal,                             // required for event-backed approval (review P1-5)
    idFactory,
    clock: systemClock,
    timerScheduler: systemTimerScheduler,
  });

  // (3) Emit through the same committer as approvals: journal first, then acknowledge.
  const emit = bindEmitterToCommitter(
    (event) => backend.journal.commit(event),
    backend.journal,
  );

  // (4) executeBatch builds the full ToolExecutionContext (principalId, sessionId,
  //     turnId, requestId, traceId, toolCallId, idempotencyKey, signal, metadata)
  //     internally; it throws MissingToolIdentityError if principalId is absent (fail-closed).
  const sessionId = args.sessionId ?? idFactory.next("session");
  const signal = args.cancellationToken?.signal ?? new AbortController().signal;
  const results = await planner.executeBatch(
    sessionId,
    [{ name: args.capability.spec.name, arguments: args.input }],   // ToolCallInstruction
    emit,
    /* turnId */ idFactory.next("turn"),
    { principalId: normalizePrincipalId(args.principal), metadata: args.metadata ?? {} },
    signal,
  );

  // (5) Single-call result. ToolCallResult = {id,name,result}
  //     | {id,name,error,error_code?,retryable?,outcome?,"not_started"|"failed"|"unknown",...} (planner.ts:77-90).
  const [call] = results;
  if ("result" in call) {
    return isCapabilityResult(call.result)
      ? (call.result as CapabilityResult<T>)
      : capabilityResult(call.result);                               // plain JSON → wrap; positional (result.ts:13)
  }
  // Failure variant: translate to the existing ToolExecutionError (review P0-5: reuse, don't fabricate).
  throw toolExecutionErrorFromResult(call);
}

function toolExecutionErrorFromResult(
  r: { error: string; error_code?: string; retryable?: boolean; outcome?: "not_started" | "failed" | "unknown" },
): ToolExecutionError {
  // Constructor arity is (message, error_code, retryable, outcome, recovery?), errors.ts:37-41.
  return new ToolExecutionError(
    r.error,
    r.error_code ?? "TOOL_EXECUTION_ERROR",
    r.retryable ?? false,
    r.outcome ?? "failed",
  );
}
```

**Exports added to `index.ts`** (and to `publicExports.typescript.stable` in `features.json`): `Kaji`, `kajiExecute`, `KajiExecuteArgs` (type), and `KajiBackend` (re-exported from `@/backends/base`, previously not a root export).

**Error surface (no invented types):** reuse `MissingToolIdentityError` (missing principal, context.ts:105), `ToolExecutionError` with the existing `error_code` taxonomy including `APPROVAL_UNAVAILABLE` / `APPROVAL_REJECTED` (planner.ts:790-791, 818-823). Unknown-risk capabilities fail closed at `Capability`/`ToolPolicy` registration before any execution.

## 4. Implementation plan (slices), grounded, no second path

### Slice 0, Contract & type freeze (no runtime)
1. `kaji/contracts/tiers/v1/features.json`:
   - Add `kaji-execute` feature object `{"id":"kaji-execute","surface":"Kaji.execute one-shot entry point","role":"core"}` to the top-level `stable` array.
   - Add `"role":"compatibility"` to `agent-builder` and `runtime-turn-loop`.
   - Add `"Kaji","kajiExecute","KajiExecuteArgs","KajiBackend"` to `publicExports.typescript.stable`.
   - Regenerate `kaji/packages/ts/contracts/tiers/v1/features.json` via `projection.py` (role is not a legacy export; projection preserves unknown fields, projection.py:67 only strips `PYTHON_LEGACY_EXPORTS`).
2. `kaji/packages/ts/src/backends/base.ts`: already exports `KajiBackend` (base.ts:7); re-export from `index.ts`: `export { type KajiBackend } from "@/backends/base";` (review P0-2).
3. `kaji/packages/ts/tests/contracts/public-declarations.test.ts`: add a separate `it("classifies features by role")` test (asserting `kaji-execute`→core, `agent-builder`/`runtime-turn-loop`→compatibility, and that any *declared* `role ∈ {core,compatibility}`). Leave the existing flat-array export assertion unchanged.
4. `kaji/tooling/contracts/check.py`: add `check_feature_roles()` validating `role ∈ {core,compatibility}` when declared on any feature, and enforcing `kaji-execute`=core / `agent-builder`=compatibility / `runtime-turn-loop`=compatibility; wire into `check_contracts()`.
5. `docs/kaji/api-parity.md`: regenerate the `public-exports:typescript` fragment to include the new exports; annotate `AgentBuilder`/`AgentRuntime` as compatibility surface.

**Gate:** `yarn test:contracts` + `kaji/tooling/contracts` green; `check.py` passes.

### Slice 1, `Kaji.execute` surface (reuses `ToolPlanner` + `ToolExecutionController`)
1. New module `kaji/packages/ts/src/kaji.ts` implementing `execute()` per §3 (composes `ToolRegistry` + `ToolExecutionController` + `ToolPlanner`, dispatches one call via `executeBatch`, no second path).
2. Add to `index.ts`: `export { Kaji, kajiExecute, type KajiExecuteArgs } from "@/kaji";` plus the `KajiBackend` re-export.
3. `public-declarations.test.ts`: the existing export-set assertion now requires `Kaji`, `kajiExecute`, `KajiExecuteArgs`, `KajiBackend` to appear in `index.d.ts` (they're in `features.json` stable from Slice 0), validates they ship as stable exports.

**Acceptance tests (Slice 1):**
1. capability returning a plain value → `CapabilityResult` with `value`, **no** `ArtifactEmitted` observed in journal.
2. capability returning `capabilityResult(value, [artifact(...)])` → `ARTIFACT_EMITTED` emitted (planner.ts:1057-1070), ids unique, duplicates rejected by idempotency ledger.
3. unknown `risk` → rejected at registration (`UnclassifiedToolRiskError` / `ToolSchemaValidationError.invalidRisk`), fail-closed before execution.
4. missing/empty `principal` → `MissingToolIdentityError`, no execution.
5. `ToolPolicy` deny → failure result (`error_code: "TOOL_NOT_ALLOWED"`-class), no execution.
6. approval required, no handler → result `error_code: "APPROVAL_UNAVAILABLE"`, `Kaji.execute` throws `ToolExecutionError`.
7. approval required, handler denies → `error_code: "APPROVAL_REJECTED"`, throws `ToolExecutionError`.
8. `principal.id` flows into `ToolExecutionContext.principalId` (executeBatch builds it from `turnContext.principalId`).
9. idempotency: a same-session retry of one capability uses the stable `kaji:<capability>` call identity, so the recorded result is returned without re-running the hook; changed input in the same session is a conflict, and distinct sessions run independently (verified RED/GREEN in the adapter-cut task).
10. `kaji init --template capability` end-to-end (docs.test.ts smoke).

**Gate:** legacy `tests/runtime/*` + `tests/integration/*` unchanged & green; `tests/contracts` green; no second execution path.

### Slice 2, CLI + docs (Q5)
1. `kaji/packages/ts/src/cli/init.ts`: add `--template capability` (default `AgentBuilder` template unchanged). The capability template emits a declared `capability()` + a `Kaji.execute()` call site.
2. `docs/kaji/README.md` + `docs/kaji/api-parity.md`: add "Expose a product capability" section with a snippet marked `docs-test:kaji-execute-capability:typescript`.
3. `kaji/packages/ts/tests/contracts/docs.test.ts`: extract + `bun`-run that snippet marker.

**Gate:** docs + CLI smoke green; `api-parity.md` fragment already regenerated in Slice 0.

## 5. Cross-SDK & parity implications
- `Kaji.execute` is **TypeScript-first** for this release: the npm `@irogane/kaji` beta is the sole publication target; Python remains source-install (NEXT.md). No Python `Kaji.execute` is added here (review P1-2).
- Per the v0.3 rule 5 tension (review P1-2): `kaji-execute` ships `stable`/`core` on TypeScript (product decision), with Python parity as an explicit **follow-up epic + v0.4 release gate**, recorded as a tracked gap, not a regression. The npm-beta-first direction (NEXT.md) is the governing rationale.
- Python `Task*` stays as-is (legacy/projection-filtered; projection.py:29). `api-parity.md` will annotate `Task*` as legacy/experimental cross-SDK status, **not** stable.
- `CapabilityResult`/`ArtifactRef`/`ArtifactEmitted`/`ToolSpec` are already shared-schema between SDKs (contracts/parity/v1), `Kaji.execute` reuses them, so the one-shot semantics are portable by construction once Python lands.

## 6. Backward compatibility
- `AgentBuilder`/`AgentRuntime` signatures unchanged; still root exports; still `stable` tier (only `role: "compatibility"` added as metadata, no behavioral change; `public-declarations.test.ts` flat-array assertion unaffected).
- Existing `tests/runtime/`, `tests/integration/`, CLI snapshot tests: unchanged and green.
- `principal` structured-vs-string normalized at the boundary; existing `executeTool`/direct registry API untouched.
- Adding `role` to `features.json` is additive; `projection.py` ignores unknown keys (only strips legacy exports).

## 7. Risks & review findings (from the `plan-eng-review` pass)
| ID | Severity | Finding | Resolution in this spec |
|----|----------|---------|--------------------------|
| P0-1 | BLOCKER | §3 fabricated `controller.executeCapability()` | Rewritten to `planner.executeBatch()` (§3, §4.2) |
| P0-2 | BLOCKER | `@/tools/types` doesn't exist; `ApprovalHandler`/`KajiBackend` not exported | Corrected imports (`@/tools/policy`, `@/runtime/approval/types`, `@/backends/base`); `KajiBackend` re-exported (§3, Slice 0) |
| P0-3 | BLOCKER | Under-specified `ToolExecutionContext` (6/8 fields) | `executeBatch` assembles context internally from `sessionId + turnContext.principalId + signal` (planner.ts:429-470); fail-closed via `MissingToolIdentityError` |
| P0-4 | BLOCKER | Routing through controller alone bypasses `ToolPolicy` + approval | `Kaji.execute` composes `ToolPlanner` (the only policy/approval locus), §3 |
| P0-5 | BLOCKER | Fabricated error types | Reuse `ToolExecutionError`/`MissingToolIdentityError` + `APPROVAL_*` codes |
| P0-6 | BLOCKER | Misattributed `ArtifactEmitted` to controller | Emission is in `ToolPlanner.executePrepared()` (planner.ts:1057-1070); controller only returns `outcome.artifacts` |
| P0-7 | BLOCKER | Object-form `capabilityResult()`/`artifact()` calls | Positional signatures used (`result.ts:13`, `types.ts:44`) |
| P1-1 | significant | "role column" claim is wrong | Separate `it("classifies features by role")` test, not a column |
| P1-2 | significant | Stable feature w/o Python twin vs v0.3 rule 5 | Retained `stable/core` (product decision); Python parity → v0.4 gate (§5) |
| P1-3 | significant | `policy.requireApprovalFor` is a data field, not a trigger | Trigger is `ToolPolicy.requiresApproval(name, risk)` |
| P1-4 | significant | Denial surfaces as a result error, not a thrown error | `Kaji.execute` inspects `ToolCallResult` error variant and throws `ToolExecutionError` (§3 step 5) |
| P1-5 | significant | `approvalCommitter` not wired → approval unavailable | `approvalCommitter: backend.journal` (§3 step 2) |
| P1-6 | significant | `tier` redundant on feature objects | `role` is the only added field; `tier` implied by array position |
| P1-7 | significant | `KajiExecuteResult<T>` generic mismatch | Dropped; returns `CapabilityResult<T>` directly |
| P1-8 | significant | Idempotency key derivation unspecified | `idempotencyKey = sessionId:toolCallId`; `sessionId` injectable (§3 step 4, test 9) |
| P2-1 | medium | Return-path extraction incomplete | `results[0].result` → `isCapabilityResult` ? return : `capabilityResult(result)` (§3 step 5) |
| P2-2 | medium | `kaji init --template capability` test marker undefined | Marker `docs-test:kaji-execute-capability:typescript` (§2.5, Slice 2) |
| P2-3 | medium | `api-parity.md` regen unspecified | Regenerator derives from `publicExports.typescript` (Slice 0.5; Slice 2.3) |

## 8. Appendix, resolved open questions (verbatim, answered)
1. **Signature / instantiation:** static `Kaji.execute(args)` namespace; deps inline (`backend`/`policy`/`approvalHandler`); `principal` normalized to `principalId`. See §2.1, §3.
2. **Return type:** `CapabilityResult<T>` (reuses `capabilityResult`/`isCapabilityResult`). See §2.2, §3 step 5.
3. **Approval:** `ToolPlanner`-routed (fail-closed); `APPROVAL_UNAVAILABLE`/`APPROVAL_REJECTED` → `ToolExecutionError`. See §2.3, §3, P0-4/P1-5.
4. **Classification:** `role` axis (`core`/`compatibility`) on feature objects, no third tier; `kaji-execute` = `stable`/`core`. See §2.4, Slice 0.
5. **Scaffold:** keep `AgentBuilder` for conversational `kaji init`; add `--template capability`. See §2.5, Slice 2.
