# Kaji SDK Production-Beta Gap-Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to execute this plan one task at a time. Shared contracts, fixtures, and their Python/TypeScript consumers must land in the same checkpoint. Use GitButler for every version-control operation.

**Goal:** Close the remaining correctness, contract, performance, release-proof, and developer-experience gaps that prevent the Python `kaji` and TypeScript `@kaji/sdk` packages from carrying a production-beta label.

**Architecture:** Keep the implemented `AgentBuilder -> AgentRuntime -> provider -> ToolPlanner -> ToolExecutionController -> EventJournal/EventCommitter` architecture. Harden its boundaries instead of replacing it: one closed cross-SDK event contract, JSON-safe durable values, one effective turn deadline, session-scoped commit lanes, an incremental context index, bounded/coalesced provider output, executable integration manifests, and release gates that operate correctly from a clean checkout.

**Tech Stack:** Python 3.11+, asyncio, Pydantic 2, `jsonschema` Draft 2020-12, pytest, Ruff, ty, uv; TypeScript 5.7 through current 6.x, Node 22/24, Zod 4, Ajv 2020, Vitest, tsup, Bun; ast-grep 0.44.1; GitHub Actions; GitButler.

**Status:** Reviewed plan only. Do not start implementation until the review report at the end of this file is CLEAR.

**Supersedes:** This is the remaining-work delta to `docs/superpowers/plans/2026-07-10-kaji-sdk-production-beta.md`; it does not reopen completed work from that plan.

---

## 1. Release Outcome and Scope

The first beta may be named only after the exact release commit proves all of the following:

- Python package `0.2.0b1` and TypeScript package `0.2.0-beta.1` implement the same stable-core semantics.
- Durable events accepted by canonical JSON Schema, Python, and TypeScript have identical accept/reject behavior, including the I-JSON safe-integer boundary.
- A tool or workflow result cannot poison persistence or replay.
- One configured work deadline covers queue wait, provider opening/streaming, approval, and tool work for the built-in adapters and any custom provider that honors the cancellation contract; caller return is bounded by that deadline plus the explicit 5-second cancellation grace.
- Unrelated sessions do not contend on a process-global event commit lock.
- Repeated tool iterations do not rescan all retained history.
- Provider text, streamed tool arguments, total response bytes, and tool-call count are bounded and do not create quadratic string growth or unbounded durable delta writes.
- Stable integration manifests describe and match the executable tool ABI.
- A clean release rehearsal builds TypeScript artifacts before tests that consume them and all child processes have outer time limits.
- The pinned performance runner has a calibrated baseline, full benchmark, and 30-minute soak for the exact commit.
- Python 3.11/3.14, Node 22/24, the declared TypeScript compiler range, keyed OpenAI and Anthropic proofs in both SDKs, signed tag, SBOM/provenance, registry publication, and byte-exact verification all succeed on that commit.

### Stable beta surface

Reuse the machine-readable tier contract at `kaji/contracts/feature-tiers-v1.json:4-39`:

- agent builder and runtime turn loop;
- cancellation and sessions;
- in-memory event store/journal and replay;
- tool registry, planner, policy, approvals, and execution controller;
- OpenAI and Anthropic adapters;
- Echo integration;
- the packaged CLI commands explicitly marked stable in the command matrix: no-key `init`, Echo `add`/`list`, and TypeScript event `replay`; every other shipped subcommand is explicitly experimental until promoted.

### NOT in scope

- Python Redis event/history backends, voice/TTS, RAG/retrieval, native Gemini/Kimi, and retriever selection remain experimental.
- TypeScript HTTP, Web, filesystem, and SQLite integrations remain experimental even after their manifests become ABI-verifiable.
- Distributed session serialization, exactly-once external side effects, durable snapshots, and unbounded cross-process replay remain deferred by `kaji/contracts/feature-tiers-v1.json:40-60`.
- No new UI, server, hosted control plane, billing, or end-user application is introduced.
- No new third-party runtime dependency is required for the stable core; existing stdlib/runtime primitives and current dependencies are sufficient.
- Delta coalescing does not promise token-preserving event boundaries. Consumers may rely on ordered concatenated text, not vendor chunk boundaries.
- In-process custom providers are cooperative by contract. If one ignores cancellation beyond the configured grace period, Kaji returns a typed contract violation, quarantines that session behind the still-owned lease, and requires a successful `drain_providers()` / `drainProviders()` before another turn is safe. Closing the runtime prevents new turns but cannot force-kill hostile in-process code; an operation that never settles requires process restart or out-of-process isolation. Killable isolation for untrusted providers remains out of scope.
- Serialized events produced before this beta are not a compatibility promise. A migration preflight validates them against the frozen beta `1.0` contract; incompatible rows fail with `EVENT_SCHEMA_INCOMPATIBLE` and are never silently rewritten.

## 2. Current Evidence and Remaining Gaps

The existing implementation is strong enough to harden rather than rewrite:

- Python: 936 tests passed, 6 skipped, approximately 83% coverage.
- TypeScript: 844 tests passed, 6 skipped after building first.
- Cross-SDK parity: all 59 scenarios passed.
- Structural audit: all 8 existing rule fixtures and the full ast-grep scan passed.
- Integration schema copies are byte-identical and current manifest/index validation is closed.

The remaining blockers are concrete:

| Priority | Gap | Current evidence | Beta consequence |
|---|---|---|---|
| P0 | Event contract drift | Canonical IDs are UUID-only and schemas allow extras (`kaji/contracts/events/new-kaji-event-v1.schema.json:8,191`); Python accepts opaque IDs but forbids extras (`kaji/sdk/src/infra/events/schemas.py:78-90`); TypeScript also accepts empty base IDs (`kaji/ts/src/events/schemas.ts:39-50`) | A payload can be valid in one boundary and invalid in another |
| P0 | Python durable-result poisoning | `ToolCallCompleted.result` and `WorkflowCompleted.result` are `Any` (`kaji/sdk/src/infra/events/schemas.py:195-200,274-277`), are stored at `kaji/sdk/src/infra/events/store/inmem.py:87-93`, then canonicalized during replay | One non-JSON tool result can permanently break session projection |
| P0 | Turn deadline stops at tools | Python waits at `kaji/sdk/src/runtime/agents/runtime.py:569` and streams at `kaji/sdk/src/runtime/agents/runtime.py:896-910` without a runtime deadline; TypeScript queues at `kaji/ts/src/runtime/runtime.ts:518-526` and streams at `kaji/ts/src/runtime/runtime.ts:701-713` using only the caller token | A stalled provider can hold a session lease indefinitely |
| P0 | Clean release order is wrong | `kaji/scripts/beta_release_check.py:205-221,328-349` runs artifact-consuming TypeScript tests before build | A fresh checkout fails while a dirty checkout passes |
| P1 | Global event commit serialization | Python journal uses one `_lock` at `kaji/sdk/src/infra/events/journal.py:128-169`; TypeScript committers use one `SerialExecutor` at `kaji/ts/src/events/committer.ts:180-218,273-353` | Unrelated sessions contend under fan-out |
| P1 | Full context scan per tool iteration | Python calls `_turn_groups(state.messages)` at `kaji/sdk/src/runtime/agents/context.py:135-177`; TypeScript calls `turnGroups(messages)` at `kaji/ts/src/runtime/context.ts:345-380`, both inside provider loops | Work grows with retained history multiplied by tool iterations |
| P1 | Streaming amplification | Python uses `full_response += chunk.delta` and commits each delta (`kaji/sdk/src/runtime/agents/runtime.py:896-903`); TypeScript does the same (`kaji/ts/src/runtime/runtime.ts:701-709`) | High-rate streams create avoidable CPU, memory, and event writes |
| P1 | Integration ABI is descriptive only | Manifest tools contain name, description, and risk (`kaji/contracts/integrations/manifest.schema.json:75-93`); `kaji/ts/scripts/check_integration_sources.ts:18-30` checks files/header only | Catalog metadata can drift from executable schemas/settings |
| P1 | Performance proof cannot pass | `kaji/benchmarks/beta-baseline.json:2-20` is explicitly uncalibrated and the full gate rejects it at `kaji/scripts/beta_benchmark_gate.py:211-224` | No defensible regression threshold exists |
| P1 | CI path coverage is incomplete | Python paths at `.github/workflows/python.test.yml:6-16` and TS paths at `.github/workflows/ts.test.yml:6-22` exclude shared contracts/scripts/docs | Contract-only drift can merge without both suites |
| P2 | Installed-package smoke can hang | `kaji/ts/scripts/smoke_package.mts:20-31` calls `execFileSync` without `timeout` or `maxBuffer` | A network or child-process stall can consume the entire job |

### ast-grep structural evidence

The current `bun run audit:ast-grep` passes, but bespoke structural queries found the remaining hot paths:

```text
result: Any
  kaji/sdk/src/infra/events/schemas.py:200
  kaji/sdk/src/infra/events/schemas.py:277

async for ... self.provider.generate_stream(...)
  kaji/sdk/src/runtime/agents/runtime.py:896

for await (... this.provider.generateStream(...))
  kaji/ts/src/runtime/runtime.ts:701

execFileSync(...)
  kaji/ts/scripts/smoke_package.mts:26

build_context(...) in the provider iteration
  kaji/sdk/src/runtime/agents/runtime.py:861

buildContext(...) in the provider iteration
  kaji/ts/src/runtime/runtime.ts:673
```

Turn these observations into permanent rules in Task 9.

## 3. Approved Design Decisions

These decisions resolve the ambiguities exposed by the audit and review passes:

1. **Opaque non-empty IDs are canonical.** The public `IdFactory` seam and deterministic tests intentionally return strings such as `event-13-1`; forcing UUIDs would be a needless breaking restriction. Canonical JSON Schema will use `type: string, minLength: 1`.
2. **The event union is closed and exhaustive.** Canonical schemas will define every event variant under `$defs`, select through `oneOf`, and end with `unevaluatedProperties: false`. Drafts forbid `sequence`; stored events require a positive sequence.
3. **Durable numbers use the I-JSON interoperable range.** Integers, including integral floats, must be between `-(2^53 - 1)` and `2^53 - 1`; other numbers must be finite. This intentionally replaces the pre-beta “exactly representable IEEE-754 integer” policy because standard JSON Schema, Python, and TypeScript can enforce the safe range identically.
4. **Durable values are validated before side-effect bookkeeping.** Tool and workflow results are canonicalized and size-checked before the idempotency ledger is marked complete and before a success event is constructed. The internal boundary uses `INVALID_DURABLE_VALUE` plus a closed subject; tool planning maps it to the public `INVALID_TOOL_RESULT` failure code.
5. **Deadline and cancellation are distinct and phase-aware.** Caller cancellation emits `cancellation.completed`; deadline expiry raises a typed `TurnTimeoutError(phase, retryable, outcome)` and records `agent.turn.failed` with `error_code: TURN_TIMEOUT`. Queue and pre-execution approval timeouts are `not_started` and retryable; active tool timeouts are `unknown` and non-retryable. A cooperative provider is cancelled and joined before release. A non-cooperative provider raises `PROVIDER_CANCELLATION_CONTRACT_VIOLATION` after a bounded grace period and leaves the session quarantined behind a background lease owner.
6. **One runtime default bounds all turns.** Add a 120,000 ms default work timeout and 5,000 ms cancellation grace to the beta contract and effective limits. A caller-supplied earlier absolute deadline may tighten the work deadline; it may not silently extend the configured maximum. The API documents maximum caller-return latency as work deadline plus grace. TypeScript renames the absolute epoch field to `deadlineAtMs`; duration fields always end in `TimeoutMs`.
7. **The event store owns session lanes.** The in-memory store exposes one non-nesting, store-identity-scoped session transaction used by direct store calls and every journal/committer over that store. Sequence assignment, backlog/live subscription attachment, ID reservation, and fanout remain atomic per session. Cross-session order is deliberately unspecified.
8. **One projector owns context indexing without copying payloads.** Cold replay is O(history) once; each committed event updates both session state and a compact turn-boundary/character-count index that references the existing projected messages. The public arbitrary-array context helper remains for external callers and tests.
9. **Provider streams are bounded and coalesced.** Accumulate text and argument fragments in arrays; enforce 256 KiB text, 64 KiB per tool argument object, 512 KiB total provider-response bytes, and 64 tool calls; emit durable deltas in at most 4 KiB chunks and flush at terminal/tool/cancel/failure boundaries. An injected clock/scheduler covers any latency flush without real sleeps in tests.
10. **Integration manifests carry executable tool metadata.** `parameters`, `parallel_safe`, and `timeout_ms` mirror stable `ToolSpec` fields. Exact executable comparison is mandatory only for stable Echo; experimental entries receive structural/schema validation and move executable parity to their promotion gate.
11. **Performance changes land before calibration.** Never calibrate a baseline around known global-lock, full-scan, stream-amplification, or duplicated-context behavior.
12. **Beta is an evidence state, not a version string.** Local success remains “offline rehearsal”; protected credentials, signing, provenance, human TTHW evidence, and publication are separate operator gates.

## 4. Target System Design

```text
Caller + TurnContext
        |
        v
EffectiveTurnScope (configured timeout ∩ caller deadline ∩ cancellation)
        |
        v
SessionTurnCoordinator[session_id] ---- queue timeout/cancel ----> typed terminal
        |
        v
AgentRuntime provider iteration
        |                    |
        |                    +--> ContextIndex.suffix(window) -- O(kept context)
        |
        +--> ProviderDeadlineScope --> OpenAI/Anthropic AbortSignal/task cancellation
        |          |
        |          +--> ResponseBudget(text + tool args) --> DeltaAccumulator
        |          |                                      --> bounded durable AgentMessageDelta
        |          +--> cancellation grace --> joined OR quarantined session
        |
        +--> ToolPlanner --> ToolExecutionController --> durable_json_snapshot(result)
        |                                              |
        |                                              +--> idempotency ledger
        v
InMemoryEventStore session transaction (one owner per store identity)
        |
        +--> locked append/get/sequence + ID reservation
        +--> bounded subscribers
        +--> SessionProjector.apply(event) --> state + ContextIndex
```

### Turn deadline state machine

```text
created -> queued -> acquired -> provider_opening -> provider_streaming
                  -> tools/approval -> completed

Any non-terminal state -- caller token --> cancelling -> cancellation.completed
Any non-terminal state -- deadline -----> timing_out(phase) -> agent.turn.failed(TURN_TIMEOUT)
Any active provider state -- timeout ---> abort/cancel -> bounded grace
                                                | joined -> release session lane
                                                + ignored -> quarantine + contract violation

Invalid transitions:
  completed -> cancellation/timeout        prevented by sealed TurnScope
  timeout -> release while provider active prevented by owned-operation join/background owner
  cancellation + timeout -> two terminals  prevented by first-winner terminal latch;
                                         explicit caller cancellation wins ties
```

### Durable result flow

```text
handler result
  -> canonical JSON validation
       nil/null: accepted
       empty object/list/string: accepted
       cycle/class/function/NaN/Infinity/integer outside I-JSON safe range/surrogate:
         INVALID_DURABLE_VALUE(subject=tool_result) -> INVALID_TOOL_RESULT
  -> serialized byte cap
       <= 64 KiB: detached immutable snapshot
       > 64 KiB: INVALID_TOOL_RESULT
  -> idempotency ledger complete(snapshot)
  -> ToolCallCompleted(snapshot)
  -> closed event validation
  -> session lane append + fanout
  -> replay canonicalization (cannot newly fail)
```

### Session-scoped commit state

```text
absent -> store.session_transaction(session_id) -> reserved(event_id) -> stored -> fanned_out
             |                       |                    |
             | duplicate same body  | append error       +--> subscriber overflow (typed)
             | waits for owner       +--> reservation removed
             + duplicate conflict --> EVENT_ID_CONFLICT

Public store methods acquire the transaction; journals call only locked primitives inside it.
Nested acquisition is forbidden and tested. Lane cleanup occurs only when holder count == 0
and waiter count == 0; two journals sharing one store therefore share one coordinator.
```

## 5. Delivery Order and Parallel Lanes

```text
Task 1 shared event contract
  -> Task 2 durable result safety
       -> Task 3 turn/provider deadline + phase/quarantine semantics
       -> Task 6 session-scoped commit lanes -> Task 7 context index

Task 4 clean release ordering/timeouts ───────────────┐
Task 5 executable integration ABI ───────────────────┤ can run after Task 1
Tasks 3 + 7 -> Task 8 provider stream accumulation ─┘
                       |
                       v
Task 9 benchmarks + ast-grep guards
  -> Task 10 CI/release evidence
  -> Task 11 docs, migrations, and DX proof
  -> Task 12 protected operator release
```

Parallel implementation after Task 1:

- Shared event lane seed: Task 2 lands durable-store validation first; then split into Lane A and Lane D.
- Lane A: Task 3 (`runtime/`, providers, event results).
- Lane B: Task 4 (`kaji/scripts`, package smoke, gate tests).
- Lane C: Task 5 (integration contracts/registry).
- Lane D: Task 6 -> Task 7 (event concurrency then projector/context), starting only after Task 2.
- Join Lanes A and D at Task 8 because the context index and bounded stream accumulator both alter the provider loop; land Task 8 only after Tasks 3 and 7, then merge all lanes before Task 9 so benchmark baselines measure the final architecture.

Conflict flags:

- Tasks 2, 3, and 8 all touch runtime event emission and must remain sequential.
- Tasks 2 and 6 both change event-store boundaries and must remain sequential; Task 6 builds its lane API on Task 2's validated append path.
- Tasks 6 and 7 both touch projectors/journals and must remain sequential.
- Tasks 7 and 8 both touch the runtime provider loop and must remain sequential even though their data structures are independent.
- Every shared-contract edit must include both SDK consumers; never split one contract version across branches.

## 6. Implementation Tasks

### Task 1: Close the Cross-SDK Event Wire Contract

**Priority:** P0  
**Human estimate:** 1.5-2 days  
**Agent estimate:** 2-3 hours  
**Blocks:** Tasks 2, 3, 5, 6, 7

**Files:**

- Modify `kaji/contracts/events/new-kaji-event-v1.schema.json`.
- Modify `kaji/contracts/events/stored-kaji-event-v1.schema.json`.
- Modify `kaji/contracts/events/conformance.json` so every runtime event variant has one valid stored fixture.
- Create `kaji/contracts/events/conformance-invalid.json`.
- Modify `kaji/contracts/beta-core-v1.json` with event/result/output limits and default turn timeout.
- Modify `kaji/contracts/feature-tiers-v1.json` to classify every packaged CLI command as stable or experimental.
- Modify `kaji/contracts/errors/error-codes.json` with `INVALID_DURABLE_VALUE`, `INVALID_TOOL_RESULT`, `EVENT_PAYLOAD_TOO_LARGE`, `PROVIDER_OUTPUT_LIMIT`, `PROVIDER_CANCELLATION_CONTRACT_VIOLATION`, `EVENT_SCHEMA_INCOMPATIBLE`, and `TURN_TIMEOUT`.
- Modify `kaji/scripts/check_beta_contract.py` to validate positive and negative event fixtures and exact `EventType` coverage.
- Create `kaji/scripts/check_event_migration.py` as a read-only JSONL preflight for pre-beta logs.
- Modify `kaji/scripts/sync_beta_contracts.py` only if contract-copy discovery must change.
- Modify `kaji/sdk/src/infra/events/json.py` and `kaji/sdk/src/infra/events/schemas.py`.
- Modify `kaji/ts/src/events/json.ts` and `kaji/ts/src/events/schemas.ts`.
- Modify `kaji/sdk/tests/test_events_schemas.py`, `kaji/sdk/tests/test_beta_contract.py`, `kaji/sdk/tests/test_cross_sdk_fixtures.py`, `kaji/sdk/tests/test_events_replay.py`, and `kaji/sdk/tests/test_production_beta_docs.py`.
- Modify `kaji/ts/tests/events.test.ts`, `kaji/ts/tests/beta-contract.test.ts`, `kaji/ts/tests/cross-sdk-fixtures.test.ts`, `kaji/ts/tests/schema-parity.test.ts`, and `kaji/ts/tests/replay.test.ts`.
- Create `kaji/ts/tests/event-contract-conformance.test.ts`.

**Step 1: Write failing contract fixtures.**

`kaji/contracts/events/conformance-invalid.json` must contain at least:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "cases": [
    { "name": "missing-event-id", "kind": "new", "event": { "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s" }, "path": "/id" },
    { "name": "missing-version", "kind": "new", "event": { "id": "e", "type": "session.created", "timestamp": 0, "session_id": "s" }, "path": "/version" },
    { "name": "missing-timestamp", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "session_id": "s" }, "path": "/timestamp" },
    { "name": "missing-session-id", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0 }, "path": "/session_id" },
    { "name": "missing-event-type", "kind": "new", "event": { "id": "e", "version": "1.0", "timestamp": 0, "session_id": "s" }, "path": "/type" },
    { "name": "empty-event-id", "kind": "new", "event": { "id": "", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s" }, "path": "/id" },
    { "name": "empty-session-id", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "" }, "path": "/session_id" },
    { "name": "empty-present-turn-id", "kind": "new", "event": { "id": "e", "type": "agent.reasoning.started", "version": "1.0", "timestamp": 0, "session_id": "s", "turn_id": "" }, "path": "/turn_id" },
    { "name": "unknown-event-type", "kind": "new", "event": { "id": "e", "type": "unknown", "version": "1.0", "timestamp": 0, "session_id": "s" }, "path": "/type" },
    { "name": "extra-field", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s", "extra": true }, "path": "/extra" },
    { "name": "draft-has-sequence", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s", "sequence": 1 }, "path": "/sequence" },
    { "name": "stored-missing-sequence", "kind": "stored", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s" }, "path": "/sequence" },
    { "name": "unsafe-integral-number", "kind": "new", "event": { "id": "e", "type": "session.created", "version": "1.0", "timestamp": 0, "session_id": "s", "metadata": { "n": 9007199254740992 } }, "path": "/metadata/n" }
  ]
}
```

Add `validate_new_event_python` / `validate_stored_event_python` and TypeScript equivalents that compose canonical raw-document validation, union validation, draft/stored sequence enforcement, and durable JSON validation. Feed every fixture's untouched mapping through canonical JSON Schema and those explicit validators before Pydantic or Zod can apply constructor defaults, asserting identical acceptance and normalized JSON Pointer. Missing `id`, `version`, or `timestamp` is therefore invalid on the wire even though the host-language constructors may generate those fields for newly authored in-process events. Do not treat the Python `NewKajiEvent` alias or `StoredKajiEvent` protocol as runtime validators.

**Step 2: Run the tests and confirm the current mismatch.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_events_schemas.py kaji/sdk/tests/test_beta_contract.py kaji/sdk/tests/test_cross_sdk_fixtures.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/event-contract-conformance.test.ts tests/events.test.ts tests/beta-contract.test.ts tests/schema-parity.test.ts)
```

Expected before implementation: the canonical schemas reject valid opaque IDs that both runtimes intentionally accept, while TypeScript accepts empty base IDs and the conditional schemas admit fields outside the selected event variant. The implementation resolves this by freezing opaque non-empty IDs everywhere; non-UUID syntax is not an invalid case.

**Step 3: Replace conditional schemas with an exhaustive union.**

Use shared `$defs` for base fields, JSON values, token usage, and each of the 25 event variants:

```json
{
  "$defs": {
    "nonEmptyId": { "type": "string", "minLength": 1 },
    "jsonNumber": {
      "oneOf": [
        { "type": "integer", "minimum": -9007199254740991, "maximum": 9007199254740991 },
        { "type": "number", "not": { "type": "integer" } }
      ]
    },
    "jsonValue": {
      "oneOf": [
        { "type": "null" }, { "type": "boolean" }, { "$ref": "#/$defs/jsonNumber" },
        { "type": "string" },
        { "type": "array", "items": { "$ref": "#/$defs/jsonValue" } },
        { "type": "object", "additionalProperties": { "$ref": "#/$defs/jsonValue" } }
      ]
    },
    "sessionCreated": {
      "allOf": [
        { "$ref": "#/$defs/base" },
        { "type": "object", "properties": { "type": { "const": "session.created" } }, "required": ["type"] }
      ],
      "unevaluatedProperties": false
    }
  },
  "oneOf": [
    { "$ref": "#/$defs/sessionCreated" }
  ]
}
```

The real `oneOf` must list every `EventType`; the sample is intentionally abbreviated.

Remove `format: "uuid"` from both canonical event schemas. UUID remains the default generated value, but the wire contract intentionally accepts any non-empty string supplied through the public `IdFactory`. Duplicate IDs remain a store conflict, not a schema-format error.

**Step 4: Align runtime base validators.**

Python:

```python
class BaseEvent(BaseModel):
    id: str = Field(default_factory=_next_event_id, min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str | None = Field(default=None, min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
```

TypeScript:

```ts
const nonEmptyId = z.string().min(1);
const baseShape = {
  id: nonEmptyId.default(() => defaultUuid()),
  session_id: nonEmptyId,
  turn_id: nonEmptyId.optional(),
  metadata: durableJsonObject.default(() => ({})),
  // version and timestamp unchanged
};
```

Use a Unicode-code-point length helper for all 200-character error/reason limits so Python and TypeScript do not diverge on surrogate pairs.

Keep construction and wire ingestion as distinct paths. Public constructors may retain the defaults above; serialized replay, migration, import, and any raw-mapping append path must first validate the untouched document against the canonical new/stored schema and only then construct the runtime model. Add regression tests proving Python `SessionCreated(session_id="s")` and TypeScript `SessionCreated.parse({ type: EventType.SESSION_CREATED, session_id: "s" })` receive generated fields, while the raw JSON object `{ "type": "session.created", "session_id": "s" }` is rejected at `/id` before any default is applied.

Update both canonical JSON encoders so any mathematically integral number outside `Number.MAX_SAFE_INTEGER` is rejected, including Python floats. Replace the pre-beta replay cases that accepted `2**53` with boundary cases for `2**53 - 1`, `2**53`, `-(2**53 - 1)`, `-(2**53)`, large non-integral finite values, and exponent notation. This is an intentional pre-beta wire tightening and must appear in the migration guide.

**Step 5: Define pre-beta log compatibility explicitly.**

Keep wire version `1.0` because this is its first frozen beta definition. `kaji/scripts/check_event_migration.py` reads without mutation, reports every incompatible JSONL line and normalized pointer, and exits non-zero. Runtime/store validation maps an incompatible pre-beta row to `EVENT_SCHEMA_INCOMPATIBLE`; conforming rows may continue to replay, but no compatibility is promised for rows that fail the frozen contract. Never silently coerce IDs, numbers, fields, or sequence values.

**Step 6: Sync package copies and prove exact parity.**

```bash
uv run --project kaji/sdk python kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji/sdk python kaji/scripts/check_beta_contract.py
uv run --project kaji/sdk python kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji/sdk python kaji/scripts/check_sdk_parity.py
```

Expected: all valid/invalid fixtures agree across three validators; parity remains 59/59 or increases only by intentional new scenarios.

**Step 7: Checkpoint with GitButler.**

```bash
but diff
but commit enkang/kaji-beta-gap-closure -c -m "fix(kaji): close the shared event contract" --changes <task-1-change-ids>
```

**Rollback:** Revert this checkpoint as one unit; never revert only one runtime or only generated contract copies.

### Task 2: Reject Non-JSON and Oversized Durable Results Before Persistence

**Priority:** P0  
**Depends on:** Task 1
**Blocks:** Tasks 3 and 6

**Files:**

- Modify `kaji/sdk/src/infra/events/json.py`.
- Modify `kaji/sdk/src/infra/events/schemas.py`.
- Modify `kaji/sdk/src/infra/events/store/base.py` and `kaji/sdk/src/infra/events/store/inmem.py` so whole-event validation occurs before persistence.
- Modify `kaji/sdk/src/runtime/tools/execution.py` around `ledger.complete()` at lines 937-956.
- Modify `kaji/sdk/src/runtime/agents/planner.py` around terminal creation at lines 997-1045.
- Modify `kaji/ts/src/events/json.ts`.
- Modify `kaji/ts/src/events/schemas.ts`.
- Modify `kaji/ts/src/events/store.ts` so whole-event validation occurs before persistence.
- Modify `kaji/ts/src/tools/execution.ts` before its ledger completion at the current `ledger.complete` call.
- Modify `kaji/ts/src/tools/planner.ts:997-1012`.
- Modify `kaji/contracts/beta-core-v1.json`, `kaji/contracts/events/new-kaji-event-v1.schema.json`, and `kaji/contracts/events/stored-kaji-event-v1.schema.json` with `maxDurableToolResultBytes: 65536` and `maxDurableEventBytes: 1048576`.
- Modify `kaji/sdk/tests/test_event_payload_limits.py`, `kaji/sdk/tests/test_events_schemas.py`, `kaji/sdk/tests/test_events_store.py`, `kaji/sdk/tests/test_events_replay.py`, and `kaji/sdk/tests/test_runtime_faults.py`.
- Modify `kaji/ts/tests/event-json.test.ts`, `kaji/ts/tests/event-payload-limits.test.ts`, `kaji/ts/tests/events.test.ts`, `kaji/ts/tests/store.test.ts`, `kaji/ts/tests/replay.test.ts`, and `kaji/ts/tests/runtime-faults.test.ts`.

**Step 1: Add the poisoning regression tests.**

Python representative test:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [object(), {"x": object()}, float("nan"), 2**53])
async def test_non_json_tool_result_becomes_tool_failure_without_poisoning(bad):
    runtime, store = runtime_with_tool_result(bad)
    result = await runtime.turn("call it", context=principal_context())
    projector = SessionProjector("session")
    await projector.sync(store)  # regression: must not raise during replay
    history = await store.get_events("session")
    assert not any(e.type == EventType.TOOL_CALL_COMPLETED for e in history)
    assert exactly_one_tool_failure(history, "INVALID_TOOL_RESULT", outcome="unknown")
    assert result.events[-1].type in {EventType.AGENT_MESSAGE_COMPLETED, EventType.AGENT_TURN_EXHAUSTED}
```

TypeScript must cover functions, symbols, `BigInt`, `Date`, `Map`, cycles, non-finite numbers, sparse arrays, accessors, and oversized UTF-8 payloads.

Add parallel cases for invalid/oversized workflow results, metadata, memory documents, pending tool calls, and whole-event payloads. Assert `INVALID_DURABLE_VALUE.subject` is one of the closed values `tool_result`, `workflow_result`, `event_metadata`, `memory_document`, `pending_tool_call`, or `event`, and that no success event or poisoned row is persisted.

**Step 2: Add one cross-SDK snapshot primitive.**

Python:

```python
JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

def durable_json_snapshot(value: object, *, subject: str, max_bytes: int) -> JsonValue:
    encoded = canonical_json(value, subject=subject)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise DurableJsonLimitError(subject, max_bytes)
    return cast(JsonValue, json.loads(encoded))
```

TypeScript:

```ts
export function durableJsonSnapshot(
  value: unknown,
  subject: string,
  maxBytes: number,
): DeepReadonly<JsonValue> {
  const encoded = canonicalJsonValue(value, subject);
  if (new TextEncoder().encode(encoded).byteLength > maxBytes) {
    throw new DurableJsonLimitError(subject, maxBytes);
  }
  return cloneAndFreezeJson(JSON.parse(encoded) as JsonValue);
}
```

Use this primitive for tool results, workflow results, event metadata, memory documents, pending tool calls, and the whole event payload at the durable boundary. Do not silently stringify unsupported values.

**Step 3: Snapshot before the ledger is completed.**

```python
snapshot = durable_json_snapshot(
    completed.result,
    subject="tool_result",
    max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
)
await self.ledger.complete(claim, snapshot)
return _ToolExecutionOutcome(result=snapshot)
```

If snapshotting fails, record an unknown-outcome tombstone with internal `INVALID_DURABLE_VALUE(subject=tool_result)` because the handler already ran and may have produced an external effect. Return the existing `_ToolExecutionOutcome(failure=...)`; the planner emits `ToolCallFailed(error_code="INVALID_TOOL_RESULT", outcome="unknown", retryable=false)` and may continue the provider loop exactly as it does for other tool failures. Do not make `runtime.turn()` raise a new plumbing exception and never mark the idempotency claim complete with a value that cannot be replayed.

**Step 4: Run targeted proof.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_event_payload_limits.py kaji/sdk/tests/test_events_store.py kaji/sdk/tests/test_events_replay.py kaji/sdk/tests/test_runtime_faults.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/event-json.test.ts tests/event-payload-limits.test.ts tests/store.test.ts tests/replay.test.ts tests/runtime-faults.test.ts)
```

Expected: invalid values fail before `ToolCallCompleted`; subsequent projection and turns remain healthy.

**Step 5: Checkpoint.**

```bash
but diff
but commit enkang/kaji-beta-gap-closure -m "fix(kaji): make durable event values JSON safe" --changes <task-2-change-ids>
```

### Task 3: Enforce One End-to-End Turn Deadline

**Priority:** P0  
**Depends on:** Tasks 1-2

**Files:**

- Create `kaji/sdk/src/runtime/agents/limits.py` with `TurnExecutionLimits` and `TurnTimeoutError`.
- Modify `kaji/sdk/src/runtime/agents/builder.py`, `kaji/sdk/src/runtime/agents/runtime.py`, `kaji/sdk/src/runtime/agents/coordinator.py`, and `kaji/sdk/src/runtime/agents/planner.py`.
- Modify `kaji/sdk/src/runtime/context.py` only to resolve/configure effective deadlines; preserve the existing public absolute-deadline field as a tightening override.
- Modify `kaji/sdk/src/runtime/providers/openai.py` and `kaji/sdk/src/runtime/providers/anthropic.py` to accept explicit request timeout configuration.
- Modify `kaji/sdk/src/runtime/tools/execution.py` so the outer deadline tightens, but never extends, the existing tool deadline.
- Modify `kaji/sdk/src/runtime/agents/__init__.py` and `kaji/sdk/src/__init__.py` public exports plus `EffectiveRuntimeLimits`.
- Modify `kaji/ts/src/runtime/cancellation.ts`, `kaji/ts/src/runtime/session-turn-coordinator.ts`, `kaji/ts/src/runtime/runtime.ts`, `kaji/ts/src/runtime/context.ts`, and `kaji/ts/src/runtime/builder.ts`.
- Modify `kaji/ts/src/providers/openai.ts` and `kaji/ts/src/providers/anthropic.ts` with explicit request timeout options.
- Modify `kaji/ts/src/tools/execution.ts` so the outer deadline tightens, but never extends, the existing tool deadline.
- Modify `kaji/ts/src/index.ts` public exports plus `EffectiveRuntimeLimits`.
- Modify `kaji/contracts/parity/scenarios.json`, `kaji/contracts/parity/expected-normalized.json`, and `kaji/scripts/check_sdk_parity.py` with deterministic queue-timeout, provider-open-timeout, mid-stream-timeout, and cancellation-winning-a-tie scenarios.
- Modify `kaji/sdk/tests/test_runtime_concurrency.py`, `kaji/sdk/tests/test_providers_cancel.py`, `kaji/sdk/tests/test_effective_runtime_limits.py`, `kaji/sdk/tests/test_runtime_faults.py`, `kaji/sdk/tests/test_stability_contract.py`, `kaji/sdk/tests/test_tool_execution_limits.py`, and `kaji/sdk/tests/test_approval_lifecycle.py`.
- Modify `kaji/ts/tests/cancellation.test.ts`, `kaji/ts/tests/runtime-concurrency.test.ts`, `kaji/ts/tests/runtime-faults.test.ts`, `kaji/ts/tests/effective-runtime-limits.test.ts`, `kaji/ts/tests/tool-execution-limits.test.ts`, `kaji/ts/tests/openai-provider.test.ts`, `kaji/ts/tests/anthropic-provider.test.ts`, `kaji/ts/tests/approval-handler.test.ts`, and `kaji/ts/tests/approval-lifecycle.test.ts`.

**Step 1: Define the shared effective limits.**

```json
{
  "runtime": {
    "turnTimeoutMs": 120000,
    "providerCancellationGraceMs": 5000,
    "providerTextMaxBytes": 262144,
    "providerToolArgumentsMaxBytes": 65536,
    "providerResponseMaxBytes": 524288,
    "providerToolCallsMax": 64
  }
}
```

Python API shape:

```python
@dataclass(frozen=True, slots=True)
class TurnExecutionLimits:
    timeout_seconds: float = 120.0
    provider_cancellation_grace_seconds: float = 5.0
    provider_text_max_bytes: int = 262_144
    provider_tool_arguments_max_bytes: int = 65_536
    provider_response_max_bytes: int = 524_288
    provider_tool_calls_max: int = 64

class TurnTimeoutError(TimeoutError):
    code = "TURN_TIMEOUT"

    def __init__(self, *, phase: TurnPhase, retryable: bool, outcome: Outcome):
        self.phase = phase
        self.retryable = retryable
        self.outcome = outcome
        super().__init__(f"Turn deadline exceeded during {phase.value}")
```

TypeScript mirrors this as `TurnExecutionLimits` with millisecond fields and a `TurnTimeoutError` carrying the same code/retryability/outcome.

Timeout classification is constructed from the state-machine phase, never from one class-wide default:

| Phase | Outcome | Retryable | Reason |
|---|---|---:|---|
| `queue` | `not_started` | yes | no provider/tool work began |
| `provider_open` before dispatch | `not_started` | yes | request was not handed off |
| `provider_open` after dispatch / `provider_stream` | `unknown` | yes, manual | duplicate provider cost/output is possible, but no tool side effect has begun |
| `approval` before a decision | `not_started` | yes | handler has not begun |
| active `tool` | `unknown` | no | the external effect may have happened |
| cancellation contract violation | `unknown` | no | provider is still active and session is quarantined |

**Step 2: Write deterministic deadline tests before implementation.**

Required cases in both SDKs:

1. deadline expires while queued behind the same session;
2. deadline expires before the provider yields its first chunk;
3. deadline expires after one chunk and before stream completion;
4. caller cancellation and deadline fire on the same clock tick; cancellation wins;
5. provider error before the deadline remains the original provider error;
6. a timed-out turn records exactly one `agent.turn.failed` terminal;
7. queued turn two acquires the lane after a cooperative turn one fully cancels/joins;
8. coordinator entry/waiter counts and deadline timers/listeners return to zero;
9. approval timeout before decision is `not_started`/retryable and emits one terminal;
10. cooperative tool timeout after handler start is `unknown`/non-retryable and preserves the execution ledger semantics;
11. a non-cooperative tool retains the existing execution-controller drain semantics;
12. a provider that ignores cancellation beyond the grace period raises `PROVIDER_CANCELLATION_CONTRACT_VIOLATION`, transfers the lease to a tracked background owner, rejects later same-session turns as quarantined, and becomes reusable only after `drain_providers()` / `drainProviders()` succeeds; closing rejects every new turn but does not claim to kill the operation;
13. wall-clock jumps do not move the resolved monotonic deadline.

Use injected clocks/timers and barriers; do not use wall-clock sleeps.

**Step 3: Resolve one absolute deadline before queueing.**

```python
effective_deadline = min(
    now_monotonic + self.turn_limits.timeout_seconds,
    context.deadline_monotonic or math.inf,
)
async with self._turn_scope(session_id, token, deadline=effective_deadline):
    ...
```

The coordinator waits for whichever occurs first: lease grant, caller cancellation, or remaining-deadline expiry. Its waiter cleanup remains FIFO and leak-free.

TypeScript replaces the ambiguous public `TurnContext.deadlineMs` with `deadlineAtMs` (absolute Unix epoch milliseconds) and adds `deadlineAfter(timeoutMs, clock)` for call sites that want a duration. Builder/runtime limits keep `turnTimeoutMs` as a duration. Convert `deadlineAtMs` exactly once to the injected monotonic clock before queueing; reject both legacy and new fields together during the pre-beta migration window and remove the legacy field before the release tag.

**Step 4: Own provider cancellation through a disposable scope.**

Python code shape:

```python
async with ProviderDeadlineScope(parent=token, deadline=deadline, clock=clock) as scope:
    async for chunk in scope.consume(
        self.provider.generate_stream(messages, tools, cancellation_token=scope.token)
    ):
        ...
```

TypeScript code shape:

```ts
const scope = createDeadlineCancellationScope(token, deadlineMs, this.clock);
try {
  for await (const chunk of scope.consume(
    this.provider.generateStream(messages, tools, {
      cancellationToken: scope.token,
      metricsSink: this.metrics,
    }),
  )) {
    // existing bounded processing
  }
} finally {
  scope.dispose();
}
```

Do not use a non-disposable `AbortSignal.timeout()`. The scope must clear its timer, remove the parent listener, and call/await the provider iterator's `return`/`aclose`. Give cooperative shutdown a configured 5-second grace. If it settles, release normally. If it does not, transfer the lease and provider task to a runtime-owned quarantine record, return the typed contract violation to the caller, reject new turns for that session, and expose bounded `drain_providers()` / `drainProviders()` plus a close operation that rejects all future turns. A failed drain remains visible and requires process restart or an external killable boundary. Never pretend an in-process coroutine or promise can be force-killed.

**Step 5: Emit distinct timeout semantics.**

Extend `AgentTurnFailed` with optional `error_code`, `phase`, `retryable`, and `outcome`. Deadline expiry emits a redaction-safe public error plus phase-specific `TURN_TIMEOUT`; caller cancellation continues to emit `CancellationCompleted` only. Provider quarantine emits `PROVIDER_CANCELLATION_CONTRACT_VIOLATION`, not `TURN_TIMEOUT`.

**Step 6: Prove providers forward cancellation.**

Both stable adapters already forward TypeScript signals (`kaji/ts/src/providers/openai.ts:163,213`; `kaji/ts/src/providers/anthropic.ts:209,256`). Add explicit request-timeout constructor options and tests that the runtime-linked signal reaches the vendor mock. Python adapters must configure SDK request timeouts and have the runtime cancel their iterator/task instead of relying only on polling at `kaji/sdk/src/runtime/providers/openai.py:301-323` and `kaji/sdk/src/runtime/providers/anthropic.py:249-275`. Custom providers must document and pass the same cancellation-contract suite before being presented as production-safe.

**Step 7: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_runtime_concurrency.py kaji/sdk/tests/test_providers_cancel.py kaji/sdk/tests/test_effective_runtime_limits.py kaji/sdk/tests/test_runtime_faults.py kaji/sdk/tests/test_stability_contract.py kaji/sdk/tests/test_tool_execution_limits.py kaji/sdk/tests/test_approval_lifecycle.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/cancellation.test.ts tests/runtime-concurrency.test.ts tests/runtime-faults.test.ts tests/effective-runtime-limits.test.ts tests/tool-execution-limits.test.ts tests/approval-handler.test.ts tests/approval-lifecycle.test.ts tests/openai-provider.test.ts tests/anthropic-provider.test.ts)
uv run --project kaji/sdk python kaji/scripts/check_sdk_parity.py
but diff
but commit enkang/kaji-beta-gap-closure -m "fix(kaji): enforce turn deadlines through providers" --changes <task-3-change-ids>
```

### Task 4: Make the Release Rehearsal Correct From a Clean Checkout

**Priority:** P0  
**Independent after:** Task 1

**Files:**

- Create `kaji/scripts/process_runner.py` as the single bounded Python child-process primitive for Kaji release tooling.
- Modify `kaji/scripts/beta_release_check.py`, `kaji/scripts/check_sdk_parity.py`, `kaji/scripts/attach_release_assets.py`, and `kaji/scripts/verify_published_packages.py`.
- Modify `kaji/scripts/run_beta_benchmarks.py`, `kaji/scripts/beta_benchmark_gate.py`, `kaji/scripts/run_beta_soak.py`, `kaji/scripts/verify_openai_loop.py`, `kaji/scripts/live_provider_proof.py`, and `kaji/scripts/verify_package_metadata.py`.
- Create `kaji/sdk/scripts/_repo_process.py` as a path-only adapter to the repository helper; modify `kaji/sdk/scripts/release_smoke.py`, `kaji/sdk/scripts/check_types.py`, `kaji/sdk/scripts/test_archive_verifier.py`, and their focused tests to use it.
- Create `kaji/sdk/tests/test_process_runner.py` and modify `kaji/sdk/tests/test_beta_release_check.py`, `kaji/sdk/tests/test_cross_sdk_fixtures.py`, `kaji/sdk/tests/test_release_smoke.py`, `kaji/sdk/tests/test_release_task15.py`, `kaji/sdk/tests/test_live_gate.py`, and the benchmark/soak gate tests.
- Create `kaji/ts/scripts/command.ts`.
- Modify `kaji/ts/scripts/smoke_package.mts`.
- Create `kaji/ts/tests/smoke-command.test.ts`.
- Modify `.github/workflows/ts.test.yml`, `.github/workflows/kaji.beta.yml`, and `.github/workflows/kaji.beta-publish.yml` with job-level timeouts where missing.

**Step 1: Write order and timeout regression tests.**

```python
def test_typescript_build_precedes_every_artifact_consumer() -> None:
    common = gate_labels(common_gates())
    release = gate_labels(release_gates())
    assert common.index("TypeScript build") < common.index("TypeScript unit tests")
    assert release.index("TypeScript build (release)") < release.index("TypeScript tests (release)")
    assert release.index("TypeScript build (release)") < release.index("TypeScript package smoke (release)")
```

Also run the wrapper from a test-created checkout/worktree where `kaji/ts/dist` is absent. Do not add a global `pretest` hook; focused Vitest runs must remain fast.

**Step 2: Make gate order data-driven.**

```python
TS_COMMON_GATES = (
    Gate("TypeScript typecheck", TYPESCRIPT, ("bun", "run", "typecheck")),
    Gate("TypeScript build", TYPESCRIPT, ("bun", "run", "build")),
    Gate("TypeScript unit tests", TYPESCRIPT, ("bun", "run", "test")),
    Gate("TypeScript package smoke", TYPESCRIPT, ("bun", "run", "package:smoke")),
)
```

Release order: format/lint/typechecks/registry checks -> build -> tests/quickstart -> package smoke -> publint -> attw -> dependency audits.

**Step 3: Bound every Python release child process.**

`kaji/scripts/process_runner.py` owns validated per-command budgets, timeout classification, bounded stdout/stderr capture, process-group termination, and redacted diagnostics. Commands that do not need captured output inherit the parent streams. Captured commands drain stdout and stderr concurrently in bounded chunks; exceeding either cap terminates the process group and raises `CommandOutputLimitError`. Timeout handling sends terminate, waits through a short grace period, then kills and reaps the entire process group before raising `CommandTimeoutError`.

Root release scripts import the sibling module directly. Because the SDK-local scripts are also direct entrypoints and `kaji/scripts` is not an installed package, `_repo_process.py` performs the one tested repository-relative path insertion and re-exports `run_checked`/budget/error types. It contains no execution logic; tests assert all SDK-local callers resolve the root module so the process runner cannot fork into two implementations.

```python
@dataclass(frozen=True)
class CommandBudget:
    timeout_seconds: float
    max_output_bytes: int = 1_048_576
    terminate_grace_seconds: float = 2.0


def run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    budget: CommandBudget,
    capture: bool = False,
    env: Mapping[str, str] | None = None,
) -> CompletedCommand:
    """Run, bound, terminate/reap on failure, and never echo secret arguments."""
```

Use named budgets instead of ad hoc literals: metadata probes 30 seconds; local lint/type/build/test commands 10 minutes; package install/audit 15 minutes; benchmark child samples 10 minutes; provider proofs 5 minutes; soak duration plus 2 minutes. `run_beta_soak.py` must terminate and reap both children if either child times out or fails. No release script may call bare `subprocess.run(...)` or `Popen.wait()` directly after this task.

**Step 4: Bound all installed-package TypeScript child commands.**

```ts
export async function runCommand(options: CommandOptions): Promise<CompletedCommand> {
  const child = spawn(options.command, options.args, {
    cwd: options.cwd,
    env: options.env,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  return await collectBoundedChild(child, options);
}
```

`collectBoundedChild` drains stdout and stderr concurrently, counts UTF-8 bytes before concatenation, and owns a timeout state machine: signal the detached POSIX process group with `SIGTERM`, wait a short grace period, then signal the group with `SIGKILL` and await the child close event. A direct-child `execFileSync` timeout is insufficient because descendants can survive. Kaji release tooling is supported on the declared macOS/Linux operator hosts; fail fast with `UnsupportedReleaseHostError` rather than claiming process-tree cleanup on Windows. Convert `smoke_package.mts` to an async entrypoint and route every child through this helper.

Use separate validated budgets: local node/tsc commands 60 seconds; package install/audit 300 seconds; outer GitHub jobs 15-60 minutes. Normalize timeout errors without echoing secret-bearing command arguments.

**Step 5: Prove timeout, output-cap, and cleanup behavior.**

Add a fake child executable/fixture that can hang, ignore termination, fork a hanging descendant, flood stdout, flood stderr, or exit non-zero. Tests must prove typed classification, bounded captured bytes, descendant/process-group cleanup, and that a failed soak child cannot leave its sibling running. These tests use sub-second injected budgets and never sleep for production timeout values.

Python's standard `subprocess.run(timeout=...)` kills and waits on expiry, while direct `Popen.wait()` requires explicit cleanup and pipe handling; Node's asynchronous `spawn` exposes the child lifecycle needed for bounded drains and explicit process-group termination. Keep those guarantees centralized rather than relying on GitHub Actions' six-hour default job timeout.

Primary references: [Python subprocess timeouts](https://docs.python.org/3/library/subprocess.html#subprocess.run), [Node `child_process.spawn`](https://nodejs.org/api/child_process.html#child_processspawncommand-args-options), and [GitHub Actions job timeouts](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes).

**Step 6: Verify from no `dist`.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_beta_release_check.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/smoke-command.test.ts)
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py --release
```

Expected: TypeScript full suite reports 844+ passed from a clean checkout; the wrapper ends with the offline-rehearsal disclaimer, not a beta-readiness claim.

**Step 7: Checkpoint.**

```bash
but diff
but commit enkang/kaji-beta-gap-closure -m "fix(kaji): make release rehearsal clean-checkout safe" --changes <task-4-change-ids>
```

### Task 5: Make Integration Manifests Executable Tool ABI Contracts

**Priority:** P1  
**Depends on:** Task 1 shared JSON and error vocabulary

**Files:**

- Modify `kaji/contracts/integrations/manifest.schema.json`.
- Modify `kaji/contracts/integrations/conformance-valid.json` and `kaji/contracts/integrations/conformance-invalid.json`.
- Create `kaji/contracts/integrations/echo-tool-abi-v1.json` as the sole reviewed Echo namespace/tool-ABI authoring document.
- Modify `kaji/scripts/check_beta_contract.py` and `kaji/scripts/sync_integration_contracts.py`.
- Create `kaji/scripts/check_integration_abi.py` as the canonical author/release entrypoint.
- Modify `kaji/sdk/src/integrations/__init__.py` and `kaji/sdk/src/integrations/validation.py`.
- Modify generated copies `kaji/sdk/src/integrations/registry/schema.json` and `kaji/ts/registry/schema.json` only through `kaji/scripts/sync_integration_contracts.py --write`.
- Modify `kaji/sdk/src/integrations/registry/echo/manifest.json`, `kaji/sdk/src/integrations/registry/echo/echo.py`, and the generated `kaji/sdk/src/integrations/registry/echo/echo.ts` only as required for exact metadata parity.
- Modify `kaji/ts/src/integrations/registry-loader.ts`.
- Create `kaji/ts/scripts/integration-abi.ts` and modify `kaji/ts/scripts/check_integration_sources.ts`.
- Modify `kaji/ts/registry/_template/manifest.json`, `kaji/ts/registry/echo/manifest.json`, `kaji/ts/registry/fs/manifest.json`, `kaji/ts/registry/http/manifest.json`, `kaji/ts/registry/sqlite/manifest.json`, and `kaji/ts/registry/web/manifest.json`; modify only `kaji/ts/registry/echo/index.ts` for executable parity.
- Modify `kaji/sdk/tests/test_manifest_registry.py`, `kaji/sdk/tests/test_echo_registry.py`, and `kaji/sdk/tests/test_integrations.py`.
- Modify `kaji/ts/tests/manifest-validate.test.ts`, `kaji/ts/tests/echo-registry.test.ts`, `kaji/ts/tests/fs-registry.test.ts`, `kaji/ts/tests/http-registry.test.ts`, `kaji/ts/tests/sqlite-registry.test.ts`, and `kaji/ts/tests/web-registry.test.ts`; create `kaji/ts/tests/integration-abi.test.ts` for Echo only.

**Step 1: Extend the canonical manifest tool shape.**

```json
{
  "required": ["name", "description", "parameters", "risk", "parallel_safe"],
  "additionalProperties": false,
  "properties": {
    "name": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
    "description": { "type": "string", "minLength": 1 },
    "parameters": { "type": "object" },
    "risk": { "enum": ["read", "write", "external_effect", "destructive", "admin"] },
    "parallel_safe": { "type": "boolean" },
    "timeout_ms": { "type": "integer", "minimum": 1 }
  }
}
```

The manifest schema validates `parameters` as an object without a remote meta-schema `$ref`. After manifest validation, call `Draft202012Validator.check_schema` / Ajv `validateSchema` for every tool parameter schema. Validation must remain offline and accept the same Draft 2020-12 subset in both SDKs.

Make `parallel_safe` explicit rather than relying on Python’s false default and TypeScript’s absent default. `timeout_ms` remains optional because the runtime default is authoritative.

Update Python's parsed public shape so validation does not immediately discard the new ABI fields:

```python
@dataclass(frozen=True)
class ManifestTool:
    name: str
    description: str
    parameters: Mapping[str, object]
    risk: ToolRisk
    parallel_safe: bool
    timeout_ms: int | None = None
```

`load_manifest()` must copy/freeze the validated parameter mapping and require `risk`/`parallel_safe`; its focused tests assert every field survives loading. TypeScript's `IntegrationManifestDocument` and registry loader must expose the same values without a duplicate hand-written risk union.

**Step 2: Add Echo source-to-manifest mismatch fixtures.**

Tests must reject:

- manifest tool missing from runtime exports;
- runtime export missing from the manifest;
- duplicate normalized tool name;
- description or risk drift;
- parameter schema drift after canonical key sorting;
- `parallel_safe` or `timeout_ms` drift;
- invalid Draft 2020-12 parameter schema;
- side effects during metadata loading.

**Step 3: Compare normalized Echo executable specs without running tools.**

```ts
interface ManifestToolAbi {
  name: string;
  description: string;
  parameters: JSONSchema;
  risk: ToolRisk;
  parallel_safe: boolean;
  timeout_ms?: number;
}

export function compareManifestAbi(
  manifest: IntegrationManifestDocument,
  specs: readonly ToolSpec[],
): void {
  const declared = normalizeManifestTools(manifest.tools);
  const executable = normalizeToolSpecs(specs);
  if (!structurallyEqualJson(declared, executable)) {
    throw new IntegrationAbiMismatchError(firstMismatchPointer(declared, executable));
  }
}
```

Python Echo metadata may be obtained from its decorated handlers/Integration instance through existing public inspection APIs. TypeScript Echo must expose a side-effect-free `tools`/spec list or a private metadata-only loader; do not execute handlers or perform I/O during validation.

`kaji/contracts/integrations/echo-tool-abi-v1.json` is authoritative only for the Echo namespace and normalized tool array. `sync_integration_contracts.py --write` copies that array into both package manifests while preserving their package-specific `files`, extras, and peer dependencies. Neither language implementation generates the ABI contract.

There is one TypeScript executable authoring source: `kaji/ts/registry/echo/index.ts`. The sync command copies it byte-for-byte to the Python package's bundled `echo/echo.ts`, preserving the existing Python `kaji add echo` cross-language output without maintaining a second implementation. `--check` fails if the distribution copy drifts. `check_integration_abi.py --explain` compares the canonical ABI document with the Python `echo.py` specs and the TypeScript `index.ts` specs; the exact-copy check transitively covers the bundled `echo.ts`. It also proves both manifest tool arrays equal the canonical array, prints the first normalized JSON Pointer and redacted expected/actual values, and never rewrites executable source automatically.

**Step 4: Keep promotion separate from validation.**

Structural manifest and parameter-schema validation runs for every catalog entry. `kaji/ts/registry/index.json` continues to mark HTTP, Web, filesystem, and SQLite experimental. Only Echo loads executable metadata and compares every shipped stable source to the canonical ABI on the beta critical path. Exact source-to-manifest parity for an experimental entry is a future promotion gate, not a beta blocker.

**Step 5: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_manifest_registry.py kaji/sdk/tests/test_echo_registry.py kaji/sdk/tests/test_integrations.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/integration-abi.test.ts tests/manifest-validate.test.ts tests/echo-registry.test.ts tests/fs-registry.test.ts tests/http-registry.test.ts tests/sqlite-registry.test.ts tests/web-registry.test.ts)
(cd kaji/ts && bun run validate:registry && bun run check:integrations && bun run typecheck:registry)
uv run --project kaji/sdk python kaji/scripts/sync_integration_contracts.py --write
uv run --project kaji/sdk python kaji/scripts/sync_integration_contracts.py --check
uv run --project kaji/sdk python kaji/scripts/check_integration_abi.py --explain
but diff
but commit enkang/kaji-beta-gap-closure -m "feat(kaji): verify integration manifests against tool ABI" --changes <task-5-change-ids>
```

### Task 6: Replace Global Event Locks With Session-Scoped Commit Lanes

**Priority:** P1  
**Depends on:** Tasks 1-2

**Files:**

- Create `kaji/sdk/src/infra/events/lanes.py`.
- Modify `kaji/sdk/src/infra/events/store/base.py`, `kaji/sdk/src/infra/events/store/inmem.py`, and `kaji/sdk/src/infra/events/journal.py`.
- Modify `kaji/sdk/tests/test_events_store.py`, `kaji/sdk/tests/test_events_journal.py`, `kaji/sdk/tests/test_runtime_concurrency.py`, and `kaji/sdk/tests/test_runtime_complexity.py`.
- Create `kaji/ts/src/internal/keyed-serial.ts`.
- Modify `kaji/ts/src/events/store.ts` and `kaji/ts/src/events/committer.ts`.
- Modify `kaji/ts/tests/event-delivery.test.ts`, `kaji/ts/tests/event-ordering.test.ts`, `kaji/ts/tests/store.test.ts`, `kaji/ts/tests/runtime-concurrency.test.ts`, and `kaji/ts/tests/runtime-complexity.test.ts`.
- Modify both runtime benchmark files in Task 9, not in this checkpoint.

**Step 1: Add deterministic cross-session blocking tests.**

Use a barrier-backed store:

```text
append(session A) enters store and blocks
append(session B) starts

EXPECTED:
  B stores and returns before A is released
  A sequence remains contiguous within A
  B sequence remains contiguous within B
```

Also test:

- same-session concurrent commits remain FIFO;
- direct store append racing a journal commit uses the same lane;
- two journals/committers sharing one store preserve sequence and backlog/live attachment without gaps;
- attempted nested transaction acquisition fails immediately in tests rather than deadlocking;
- subscription attachment during a commit sees every event exactly once;
- concurrent same-ID/same-body commits coalesce to one insert and one fanout;
- concurrent same-ID/different-body commits yield `EVENT_ID_CONFLICT`;
- closed-session LRU eviction never removes an active/locked lane;
- lane maps return to zero after success, append error, cancellation, overflow, and subscriber close;
- split-committer pending capacity cannot be exceeded by simultaneous reservations.

**Step 2: Implement a ref-counted keyed lane pool owned by the store.**

Python shape:

```python
@dataclass(slots=True)
class _Lane:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0

class SessionLanePool:
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        lane = await self._retain(session_id)
        try:
            async with lane.lock:
                yield
        finally:
            await self._release(session_id, lane)
```

TypeScript shape:

```ts
export class KeyedSerialExecutor {
  private readonly tails = new Map<string, Promise<void>>();

  async run<T>(key: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.tails.get(key) ?? Promise.resolve();
    const gate = deferred<void>();
    const tail = previous.then(() => gate.promise);
    this.tails.set(key, tail);
    await previous;
    try { return await operation(); }
    finally {
      gate.resolve();
      if (this.tails.get(key) === tail) this.tails.delete(key);
    }
  }
}
```

`InMemoryEventStore` owns exactly one pool for its lifetime. Do not construct a pool in `EventJournal`/`EventCommitter`; that would break coordination between direct store calls or two wrappers over the same store.

**Step 3: Expose one non-nesting session transaction.**

Python shape:

```python
class InMemorySessionTransaction:
    def append_locked(self, event: NewKajiEvent) -> AppendResult: ...
    def get_events_locked(self, *, after_sequence: int = 0, limit: int | None = None) -> list[StoredKajiEvent]: ...
    def last_sequence_locked(self) -> int: ...

@asynccontextmanager
async def session_transaction(self, session_id: str) -> AsyncIterator[InMemorySessionTransaction]:
    async with self._lanes.hold(session_id):
        yield InMemorySessionTransaction(self, session_id)
```

Public `append`, `get_events`, and `last_sequence` acquire `session_transaction` and call locked primitives. Journal/committer operations acquire it once and call only locked primitives. Add a task-local/async-context guard that raises an internal `NestedEventTransactionError` on recursive acquisition. The TypeScript store exposes the same internal transaction capability; committers detect it structurally. A custom `EventStore` without that capability keeps the current correctness-preserving global serializer and is not entitled to the cross-session performance guarantee.

**Step 4: Preserve global ID dedup without a global slow-path lock.**

Keep a short metadata lock/reservation map keyed by event ID. The reservation owner performs its session append; duplicates await the owner and compare canonical draft payloads. Never hold the metadata lock while awaiting store I/O or subscriber work.

**Step 5: Keep backlog/live attachment atomic per session.**

`open_subscription(session_id)` must read backlog through the locked transaction primitive and register the live subscriber while holding the same store-owned session transaction used for commits. This preserves the no-gap handshake currently protected by the global locks at `kaji/sdk/src/infra/events/journal.py:200-225` and `kaji/ts/src/events/committer.ts:241-261` without recursive acquisition.

For `SplitEventCommitter`, reserve pending capacity synchronously before persistence, then convert the reservation to a pending outbox item only on publish failure. A capacity failure must happen before persistence.

**Step 6: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_events_store.py kaji/sdk/tests/test_events_journal.py kaji/sdk/tests/test_runtime_concurrency.py kaji/sdk/tests/test_runtime_complexity.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/event-delivery.test.ts tests/event-ordering.test.ts tests/store.test.ts tests/runtime-concurrency.test.ts tests/runtime-complexity.test.ts)
but diff
but commit enkang/kaji-beta-gap-closure -m "perf(kaji): isolate event commits by session" --changes <task-6-change-ids>
```

**Rollback:** Revert the lane checkpoint and return to global serialization; contract fixtures and result validation remain valid independently.

### Task 7: Maintain Provider Context Incrementally

**Priority:** P1  
**Depends on:** Tasks 1 and 6

**Files:**

- Create `kaji/sdk/src/runtime/sessions/context_index.py`.
- Modify `kaji/sdk/src/infra/events/replay.py`, `kaji/sdk/src/runtime/sessions/projector.py`, `kaji/sdk/src/runtime/agents/context.py`, and `kaji/sdk/src/runtime/agents/runtime.py`.
- Modify `kaji/sdk/tests/test_context_window.py`, `kaji/sdk/tests/test_agents_context.py`, `kaji/sdk/tests/test_events_replay.py`, and `kaji/sdk/tests/test_runtime_complexity.py`.
- Create `kaji/ts/src/sessions/context-index.ts`.
- Modify `kaji/ts/src/sessions/replay.ts`, `kaji/ts/src/sessions/projector.ts`, `kaji/ts/src/runtime/context.ts`, and `kaji/ts/src/runtime/runtime.ts`.
- Modify `kaji/ts/tests/context-window.test.ts`, `kaji/ts/tests/replay.test.ts`, and `kaji/ts/tests/runtime-complexity.test.ts`.

**Step 1: Preserve the full-scan implementation as a differential oracle.**

Before changing runtime behavior, rename/private-wrap the current algorithms as `build_context_from_messages` and `buildContextFromMessages`. Tests may use them as oracles, but the runtime provider loop must stop calling them.

Generate deterministic histories containing:

- user/assistant text turns;
- assistant tool batches with parallel results;
- tool failures and approval terminals;
- empty assistant tool-only messages;
- transcript-final voice inputs;
- exact character-limit boundaries and Unicode;
- malformed orphan/duplicate/pending tool call IDs.

For every prefix, indexed output and error behavior must match the oracle byte-for-byte.

**Step 2: Add an index updated only by event projection.**

```python
@dataclass(slots=True)
class ContextTurn:
    message_start: int
    message_end: int
    characters: int
    pending_tool_call_ids: set[str]

class ContextIndex:
    def apply(self, event: StoredKajiEvent) -> None: ...
    def suffix(self, window: ContextWindow) -> ContextBuildResult: ...
```

TypeScript mirrors this state in projection-owned private metadata rather than allowing multiple mutation paths. `SessionProjector.apply` must be the sole codepath that advances the event cursor, session state, and context index. The index stores integer boundaries, character counts, and call IDs only; it references `SessionState.messages` by range and must not duplicate message dicts/objects, text, tool arguments, or results.

**Step 3: Make complexity proportional to kept context.**

Cold replay may scan 10,000 events once. Each later event update is O(1) amortized. Selecting a 32-turn/100,000-character suffix is O(kept turns/messages), independent of dropped history and tool-iteration count.

Required operation-count assertion:

```text
history: 10,000 events
provider/tool iterations: 5
expected full-history index builds: 1
expected later events applied: only newly committed events
expected copied message payload bytes in index: 0
expected index entries: <= retained turn count + 1
forbidden: 5 scans of the 10,000-event prefix
```

Do not use elapsed time as the only proof; retain deterministic counters and add the benchmark in Task 9. Before calibration, enforce zero copied payload bytes and a 64 MiB maximum incremental RSS increase for the index-enabled 10,000-event fixture relative to the same projected state with the index disabled. Treat a breach as a design failure, not a baseline to normalize.

**Step 4: Keep public arbitrary-array helpers.**

`build_messages(state/messages)` remains available for callers that provide an arbitrary detached collection. Add a projector-specific `build_projected_context` path for runtime use rather than weakening the public API.

**Step 5: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_context_window.py kaji/sdk/tests/test_agents_context.py kaji/sdk/tests/test_events_replay.py kaji/sdk/tests/test_runtime_complexity.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/context-window.test.ts tests/replay.test.ts tests/runtime-complexity.test.ts)
but diff
but commit enkang/kaji-beta-gap-closure -m "perf(kaji): index provider context during projection" --changes <task-7-change-ids>
```

### Task 8: Bound Provider Output and Coalesce Durable Deltas

**Priority:** P1  
**Depends on:** Tasks 2-3 and Task 7

**Files:**

- Create `kaji/sdk/src/runtime/agents/stream.py`.
- Modify `kaji/sdk/src/runtime/agents/runtime.py` and `kaji/sdk/src/runtime/agents/limits.py`.
- Modify `kaji/sdk/src/runtime/providers/base.py`, `kaji/sdk/src/runtime/providers/types.py`, `kaji/sdk/src/runtime/providers/openai.py`, and `kaji/sdk/src/runtime/providers/anthropic.py`.
- Modify `kaji/sdk/tests/test_runtime_turn.py`, `kaji/sdk/tests/test_event_payload_limits.py`, `kaji/sdk/tests/test_runtime_complexity.py`, and `kaji/sdk/tests/test_effective_runtime_limits.py`; create `kaji/sdk/tests/test_provider_stream_limits.py` with mocked OpenAI and Anthropic streams.
- Create `kaji/ts/src/runtime/delta-accumulator.ts`.
- Modify `kaji/ts/src/runtime/runtime.ts`, `kaji/ts/src/runtime/builder.ts`, and `kaji/ts/src/providers/base.ts`.
- Modify `kaji/ts/src/providers/openai.ts` and `kaji/ts/src/providers/anthropic.ts`.
- Modify `kaji/ts/tests/runtime-turn.test.ts`, `kaji/ts/tests/event-payload-limits.test.ts`, `kaji/ts/tests/runtime-complexity.test.ts`, `kaji/ts/tests/effective-runtime-limits.test.ts`, `kaji/ts/tests/openai-provider.test.ts`, and `kaji/ts/tests/anthropic-provider.test.ts`.

**Step 1: Add output-boundary and exact-text tests.**

Required cases:

- 10,000 one-character deltas produce exact concatenated text with a bounded event count;
- one multibyte delta ending exactly at 256 KiB succeeds;
- one byte over fails with `PROVIDER_OUTPUT_LIMIT` before `AgentMessageCompleted`;
- 64 tool calls succeed; 65 fail before tool execution;
- one tool's arguments at exactly 64 KiB succeed; one byte over aborts before JSON parse/finalization;
- 10,000 fragmented tool-argument deltas are accumulated linearly with an exact 512 KiB total-response cap;
- text plus tool-argument fragments share the total-response budget, so neither path can hide bytes from the other;
- a delta flush occurs before tool execution, completion, cancellation, timeout, and failure;
- a provider emitting empty deltas does not create empty durable events;
- no partial `AgentMessageCompleted` appears after limit failure;
- subscribers may observe the bounded prefix, and the terminal failure makes that partial state explicit.

**Step 2: Replace repeated string concatenation.**

Python:

```python
parts: list[str] = []
output_bytes = 0
for chunk in stream:
    if chunk.delta:
        delta_bytes = len(chunk.delta.encode("utf-8"))
        if output_bytes + delta_bytes > limits.provider_text_max_bytes:
            raise ProviderOutputLimitError(...)
        parts.append(chunk.delta)
        output_bytes += delta_bytes
full_response = "".join(parts)
```

TypeScript uses `const parts: string[] = []` and `parts.join("")` with `TextEncoder` byte accounting.

Add `ProviderResponseLimits` to `kaji/sdk/src/runtime/providers/types.py` / the Python provider protocol and to TypeScript `ModelProviderOptions`. Thread the effective values from the runtime into every provider call. The stable OpenAI and Anthropic adapters must use per-call argument-part arrays plus incremental UTF-8 counters at their current fragment assembly sites:

- `kaji/sdk/src/runtime/providers/openai.py:140-160`;
- `kaji/sdk/src/runtime/providers/anthropic.py:296-315`;
- `kaji/ts/src/providers/openai.ts:221-250`;
- `kaji/ts/src/providers/anthropic.ts:264-276`.

Abort and close the vendor stream before parsing/finalizing a tool call that breaches `providerToolArgumentsMaxBytes: 65536` or the combined `providerResponseMaxBytes: 524288`. The runtime remains a second boundary for custom providers that yield already-finalized calls.

**Step 3: Coalesce durable delta writes behind one accumulator.**

```ts
class DeltaAccumulator {
  push(delta: string): readonly string[]; // returns size-triggered flushes
  flush(): string | undefined;
  get totalBytes(): number;
}
```

Use a 4 KiB durable chunk threshold. If an optional latency flush is retained, it must use the injected runtime scheduler and a disposable timer; size/boundary flushes remain deterministic. Never split a Unicode scalar or emit more than the event payload cap.

**Step 4: Preserve observable semantics.**

The ordered concatenation of every `AgentMessageDelta.delta` for an iteration must equal `AgentMessageCompleted.content`. Document that vendor chunk boundaries are not stable API. Keep every delta durable for beta, but at bounded batch granularity; a later ephemeral-stream transport remains out of scope.

**Step 5: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_runtime_turn.py kaji/sdk/tests/test_event_payload_limits.py kaji/sdk/tests/test_runtime_complexity.py kaji/sdk/tests/test_effective_runtime_limits.py kaji/sdk/tests/test_provider_stream_limits.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/runtime-turn.test.ts tests/event-payload-limits.test.ts tests/runtime-complexity.test.ts tests/effective-runtime-limits.test.ts tests/openai-provider.test.ts tests/anthropic-provider.test.ts)
but diff
but commit enkang/kaji-beta-gap-closure -m "perf(kaji): bound and coalesce provider streams" --changes <task-8-change-ids>
```

### Task 9: Expand Benchmarks and Structural Regression Guards

**Priority:** P1  
**Depends on:** Tasks 1-8

**Files:**

- Modify `kaji/sdk/benchmarks/runtime_benchmark.py`.
- Modify `kaji/ts/benchmarks/runtime-benchmark.ts`.
- Modify `kaji/scripts/beta_benchmark_gate.py`.
- Modify `kaji/benchmarks/beta-budgets.json`.
- Do not modify `kaji/benchmarks/beta-baseline.json` locally; calibration is Task 12.
- Add rules under `tools/ast-grep/rules/` and fixtures under `tools/ast-grep/rule-tests/`.
- Add missing fixtures for the five existing untested rules.
- Modify `kaji/sdk/tests/test_beta_release_check.py` and `.github/workflows/ast-grep.yml`.

**Step 1: Add four worst-case benchmarks to both runtimes.**

Extend the case list beyond the current four at `kaji/sdk/benchmarks/runtime_benchmark.py:30` and `kaji/ts/benchmarks/runtime-benchmark.ts:22`:

```text
context10kIterations5
  preseed 10,000 events, execute five provider/tool iterations
  assert one cold context index build and bounded suffix work

crossSessionCommit100
  block one session's append, commit 99 other sessions
  assert overlap, contiguous per-session sequence, zero lane leaks

streamDeltas10k
  provider yields 10,000 one-character deltas
  assert exact text, output cap, bounded delta-event count, zero timer/task leaks

toolArgDeltas10k
  provider yields 10,000 fragments for one tool argument payload
  assert linear fragment accounting, exact parse at the limit, one-byte-over rejection,
  and zero parser/provider-task leaks
```

Every sample reports duration, peak RSS, semantic counters, and leak counters. Keep child-process isolation, deterministic seeds, warmups, and five measured full-mode samples.

**Step 2: Add absolute semantic budgets before timing budgets.**

```json
{
  "context10kIterations5": {
    "maxFullHistoryScans": 1,
    "maxProviderIterations": 5,
    "maxCopiedPayloadBytes": 0,
    "maxIndexEntriesPerRetainedTurn": 1.01,
    "maxIncrementalRssBytes": 67108864
  },
  "crossSessionCommit100": {
    "minOverlappingSessions": 2,
    "maxLaneEntriesAfter": 0
  },
  "streamDeltas10k": {
    "maxDeltaEvents": 16,
    "expectedCharacters": 10000,
    "maxProviderTextBytes": 262144,
    "maxProviderResponseBytes": 524288
  },
  "toolArgDeltas10k": {
    "maxArgumentBytes": 65536,
    "maxResponseBytes": 524288,
    "maxFragmentJoins": 1
  }
}
```

Set timing/RSS budgets only after protected calibration. Quick mode still enforces semantic caps without comparing timing to an uncalibrated machine.

**Step 3: Add structural guards.**

New rule IDs and intent:

```text
python-events-no-untyped-durable-result
  forbid `result: Any` in BaseEvent subclasses

ts-events-no-unknown-durable-result
  forbid `result: z.unknown()` in durable event schemas

python-runtime-provider-stream-requires-deadline-scope
  forbid direct `self.provider.generate_stream(...)` iteration in runtime.py

ts-runtime-provider-stream-requires-deadline-scope
  forbid direct `this.provider.generateStream(...)` iteration in runtime.ts

python-runtime-no-full-context-build-in-provider-loop
ts-runtime-no-full-context-build-in-provider-loop
  forbid the arbitrary-array/full-scan helpers inside the iteration loop

python-runtime-no-stream-string-concatenation
ts-runtime-no-stream-string-concatenation
  forbid `response += delta` / `content += chunk.delta` in stream loops

python-provider-no-tool-argument-string-concatenation
ts-provider-no-tool-argument-string-concatenation
  forbid repeated `+=` assembly at OpenAI/Anthropic argument-fragment sites

ts-event-committer-no-global-serial-executor
  forbid a process-global SerialExecutor field in event committers

python-release-no-unbounded-subprocess-run
  forbid direct `subprocess.run(...)` in Kaji release scripts after migration to `process_runner.run_checked`

python-release-no-bare-popen-wait
  forbid `Popen.wait()` without a timeout and the centralized terminate/kill/reap path

ts-release-command-runner-only
  forbid direct `execFileSync`, `spawnSync`, `execFile`, or `spawn` calls in Kaji TypeScript release scripts outside `kaji/ts/scripts/command.ts`
```

Example rule shape:

```yaml
id: ts-runtime-no-stream-string-concatenation
language: TypeScript
severity: error
message: Accumulate provider text in the bounded DeltaAccumulator.
files:
  - "kaji/ts/src/runtime/runtime.ts"
rule:
  all:
    - pattern: $CONTENT += $DELTA
    - inside:
        stopBy: end
        kind: for_in_statement
```

Write at least two valid and two invalid snippets for every new rule. Also add rule-test files for current rules that have none:

- `no-generic-ts-cancelled-error`;
- `python-core-no-upward-imports`;
- `python-runtime-no-legacy-tooldefinition`;
- `python-sdk-no-service-imports`;
- `ts-no-provider-value-imports`.

**Step 4: Remove the hard-coded rule-test count.**

Replace `.github/workflows/ast-grep.yml:36-47`’s “8 passed” string assertion with a repository test that compares rule IDs to rule-test IDs and then accepts ast-grep’s reported total dynamically.

**Step 5: Verify and checkpoint.**

```bash
bun run audit:ast-grep
uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --quick
uv run --project kaji/sdk pytest kaji/sdk/tests/test_runtime_complexity.py kaji/sdk/tests/test_beta_release_check.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/runtime-complexity.test.ts)
but diff
but commit enkang/kaji-beta-gap-closure -m "test(kaji): guard beta performance invariants" --changes <task-9-change-ids>
```

### Task 10: Make Shared Contracts and Release Gates Mandatory in CI

**Priority:** P1  
**Depends on:** Task 9

**Files:**

- Create `.github/workflows/kaji.beta-pr.yml`.
- Modify `.github/workflows/python.test.yml` and `.github/workflows/ts.test.yml` path filters and pin every external action they run.
- Modify `.github/workflows/ast-grep.yml` and `.github/workflows/kaji.benchmark.yml` to pin third-party actions by full commit SHA.
- Audit and pin any remaining floating actions in `.github/workflows/kaji.beta.yml` and `.github/workflows/kaji.beta-publish.yml`.
- Modify `kaji/sdk/tests/test_release_security.py`, `kaji/sdk/tests/test_beta_release_check.py`, and `kaji/ts/tests/release-security.test.ts`.
- Modify `kaji/RELEASE_MATRIX.md` only to name the new protected PR gate; do not claim the pending protected evidence has passed.

**Step 1: Expand ordinary suite triggers.**

Both Python and TypeScript workflows must trigger on:

```yaml
- "kaji/contracts/**"
- "kaji/scripts/**"
- "kaji/benchmarks/**"
- "kaji/RELEASE_MATRIX.md"
- "docs/kaji/**"
- "tools/ast-grep/**"
- "sgconfig.yml"
- "package.json"
- "bun.lock"
- "kaji/sdk/uv.lock"
```

Keep their existing package-specific paths.

**Step 2: Add a shared beta PR gate.**

`.github/workflows/kaji.beta-pr.yml` runs once for any shared beta input and executes:

```text
check_beta_contract.py
sync_beta_contracts.py --check
sync_integration_contracts.py --check
check_integration_abi.py --explain
check_sdk_parity.py
bun run audit:ast-grep
run_beta_benchmarks.py --quick
```

Set explicit job timeouts and use frozen dependency installs. The gate must be suitable as a required branch-protection check.

**Step 3: Pin action supply-chain inputs.**

Replace floating `actions/checkout@v4`, `actions/setup-node@v4`, and `actions/upload-artifact@v4` in every Kaji-triggered Python, TypeScript, beta, ast-grep, and performance workflow with reviewed full SHAs plus comments naming the upstream release tag. Repository-local actions remain path-pinned.

**Step 4: Add workflow-contract tests.**

Tests parse YAML and assert:

- every shared beta path triggers both ordinary SDK suites or the shared beta gate;
- required commands are present once and in the intended order;
- every external action reference is a 40-character SHA;
- benchmark calibration cannot run on an unpinned runner;
- release/publish jobs carry explicit timeouts and minimal permissions.

**Step 5: Verify and checkpoint.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_release_security.py kaji/sdk/tests/test_beta_release_check.py --no-cov -q
(cd kaji/ts && bun run vitest run tests/release-security.test.ts)
bun run audit:ast-grep
but diff
but commit enkang/kaji-beta-gap-closure -m "ci(kaji): require shared beta contract gates" --changes <task-10-change-ids>
```

### Task 11: Align Documentation, Migration Guidance, and Developer Experience

**Priority:** P1  
**Depends on:** Tasks 1-10

**Files:**

- Create `docs/kaji/README.md`, `docs/kaji/testing.md`, `docs/kaji/api-parity.md`, and `docs/kaji/cli.md`.
- Modify `docs/kaji/production-beta.md`, `docs/kaji/releasing.md`, `docs/kaji/concurrency-and-ordering.md`, `docs/kaji/tool-contracts.md`, `docs/kaji/troubleshooting.md`, and `docs/kaji/migrating-to-beta.md`.
- Modify `kaji/sdk/README.md`, `kaji/ts/README.md`, `kaji/sdk/CHANGELOG.md`, `kaji/ts/CHANGELOG.md`, and `kaji/RELEASE_MATRIX.md`.
- Modify `kaji/sdk/src/cli/init.py`, `kaji/sdk/src/cli/templates.py`, and `kaji/sdk/src/cli/_main.py`.
- Modify `kaji/ts/src/cli/init.ts`, `kaji/ts/src/cli/index.ts`, and `kaji/ts/src/cli/render.ts`.
- Modify `kaji/sdk/tests/cli/test_init.py`, `kaji/sdk/tests/cli/test_main.py`, `kaji/sdk/tests/test_production_beta_docs.py`, `kaji/sdk/tests/test_docs_sync.py`, and `kaji/sdk/tests/test_release_smoke.py`.
- Modify `kaji/ts/tests/cli-init.test.ts`, `kaji/ts/tests/cli-dispatch.test.ts`, `kaji/ts/tests/cli-replay.test.ts`, `kaji/ts/tests/docs-contract.test.ts`, `kaji/ts/tests/package-contract.test.ts`, and `kaji/ts/tests/public-declarations.test.ts`.
- Modify `kaji/ts/package.json`, `kaji/ts/scripts/smoke_package.mts`, and `kaji/sdk/scripts/release_smoke.py`.
- Create `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, and `.github/ISSUE_TEMPLATE/kaji-sdk-bug.yml`.

### Developer perspective

**Primary persona card**

| Attribute | Detail |
|---|---|
| Role/context | Platform engineer evaluating an embedded agent runtime for a production service in either Python or TypeScript |
| Time tolerance | Five minutes to deterministic output; ten minutes to one real tool lifecycle; one workday to complete production evaluation |
| Trust threshold | Exact artifact proof, explicit stable/experimental tiers, replay-safe events, bounded work, actionable failures, and no hidden global bottleneck |
| Existing knowledge | Comfortable with async code, package managers, JSON Schema, provider keys, and CI; should not need Kaji source knowledge |
| Expected escape hatches | Tighten deadlines, inject deterministic clocks/providers, inspect effective limits/events, drain or dispose runtime, and run offline contract checks |

**First-person journey and empathy narrative:** “I arrive from the package page and first need to know what ‘production beta’ covers. I run one install command and expect a no-key scaffold that prints a deterministic reply, turn ID, and event sequence without editing environment files. Next I replace the mock with OpenAI or Anthropic, add the Echo tool, and expect the same lifecycle in either language. When something stalls or returns invalid data, the error must tell me the phase, whether work started, whether retry is safe, and whether the session is quarantined. Before adoption I need a side-by-side API map, a testing guide, a migration checker for old event logs, and exact commands that reproduce the release gates. I should never discover from source that the CLI pinned an old SDK, omitted a peer, hid a failure code, or used different deadline units.”

**Journey map and current confusion log**

| Stage | Required path | Current confusion to remove | Acceptance evidence |
|---|---|---|---|
| Discover | package README -> `docs/kaji/README.md` -> production-beta scope | CLI commands ship but are absent from the tier contract | stable/experimental command matrix is generated/tested |
| Install | one Python install or one npm/Bun command including Zod | TS scaffold pins `^0.1.0`, omits Zod, and silently selects OpenAI | exact wheel/tarball scaffold installs without a key |
| Hello | `kaji init` -> run generated project | current scaffolds require provider configuration and do not prove event IDs | output asserts text, turn ID, and positive sequence |
| Real use | choose provider -> add Echo -> run one tool loop | Python/TS builder, deadline, and error field mappings are scattered | side-by-side stable API table and keyed proofs |
| Debug | replay/log -> error code -> troubleshooting anchor | TS replay collapses `agent.turn.failed` to a bare label | human and JSON renderers preserve code/phase/outcome |
| Upgrade | read changelog -> preflight events -> update | pre-beta number/closed-object changes lack a concrete checker | read-only migration command and incompatibility report |

**Competitive benchmark:** Official quickstarts optimize for a short core call, but none of the cited pages publishes a defensible measured TTHW. Kaji should not claim a speed rank until measured; its intended wedge is a deterministic no-key path plus cross-SDK durable/safety parity.

| SDK | Install/setup shown | Credentials for primary path | Core shape | Starter/playground | Debug/trace path in quickstart | Published TTHW |
|---|---|---|---|---|---|---|
| OpenAI Agents Python | project/venv, install | API key | `Agent` + `Runner.run` | docs examples | run/trace concepts linked | not stated |
| OpenAI Agents JS | npm project, SDK + Zod | API key | `Agent` + `run` | docs examples | run/trace concepts linked | not stated |
| Vercel AI SDK | install provider + AI SDK | provider key | compact `generateText` | Playground/templates | provider/tool docs | not stated |
| LangChain Python/JS | install package/provider | provider key | `create_agent` / `createAgent`, tool, invoke | templates/docs | agent/tool docs | “minutes” language, no measurement |
| Kaji target | one install command, exact artifact | none for first run | `AgentBuilder` + deterministic provider; same event lifecycle | generated scaffold | stable code/phase/outcome + replay | baseline pending; target below |

References:

- `https://openai.github.io/openai-agents-python/quickstart/`
- `https://openai.github.io/openai-agents-js/guides/quickstart/`
- `https://ai-sdk.dev/docs/introduction`
- `https://docs.langchain.com/oss/python/langchain/quickstart`
- `https://docs.langchain.com/oss/javascript/langchain/quickstart`

**Magical moment:** From a clean temporary project, run one install command, invoke `kaji init`, and see deterministic text, a non-empty turn ID, and positive sequenced events. For TypeScript the one command installs `@kaji/sdk` plus its required Zod peer; it is not falsely described as “one package.” Then select OpenAI or Anthropic explicitly, add Echo, and see the same normalized lifecycle in either language. Every example executes from the exact wheel/tarball, never repository source.

**Step 1: Make the packaged scaffold truthful and no-key by default.**

- Python adds `mock` to the provider choices and makes it the non-interactive/default scaffold. TypeScript adds `--provider mock|openai|anthropic`, defaulting to `mock`.
- Freeze one stable grammar in both packages: `kaji init [path] --provider mock|openai|anthropic --yes --force`. TypeScript accepts its existing `--out <path>` as a deprecated alias for `[path]`, rejects supplying both forms, and prints one redaction-safe migration warning; remove the alias only in a future major release. Python and TypeScript help, usage errors, exit codes, non-interactive behavior, overwrite refusal, and written-file summaries must match semantically.
- Generated TypeScript reads the installed package version instead of embedding `^0.1.0`, includes supported Zod, and uses `@kaji/sdk/testing` `MockProvider` for the default. Keyed providers are an explicit second mode.
- Generated Python uses `kaji.get_provider("mock")` by default. Both generated programs print deterministic text, turn ID, and final sequence.
- The CLI command matrix classifies stable `init`, Echo `add`/`list`, and TypeScript `replay`; Python maintenance commands and any other command are marked experimental with no beta claim.
- The real-provider quickstarts remove manual cancellation timers, show the safe 120-second default, expose effective limits, and show Python `deadline_monotonic` versus TypeScript `deadlineAtMs`/`deadlineAfter()` without mixing duration and absolute units.

Add table-driven CLI contract tests that feed the same valid and invalid argument cases to both dispatchers: default path, explicit path, each stable provider, `--yes`, `--force`, unknown provider, missing option value, conflicting path/`--out`, existing-file refusal, and deprecated-alias warning. Installed-artifact smoke must run the canonical command under Python, npm, and Bun.

**Step 2: Make errors actionable in APIs and the CLI.**

| Error | Developer sees | Recovery |
|---|---|---|
| `INVALID_TOOL_RESULT` | tool name, durable-value pointer/subject, outcome `unknown`, 64 KiB limit | fix the return value; do not auto-retry an external-effect tool |
| `TURN_TIMEOUT` | phase, configured/effective limit, retryability, and outcome | queue/pre-approval may retry; active tool does not; provider stream retry is manual |
| `PROVIDER_CANCELLATION_CONTRACT_VIOLATION` | provider ignored cancellation grace; session quarantined | drain and replace provider; close runtime to reject new work; restart process if the operation never settles |
| `PROVIDER_OUTPUT_LIMIT` | text/tool-argument/total-response dimension and limit, no raw payload | reduce provider output/schema or choose a bounded model configuration |
| `INTEGRATION_ABI_MISMATCH` | exact pointer plus redacted expected/actual field and remediation command | update canonical manifest/runtime metadata, then rerun `check_integration_abi.py --explain` |

Update `docs/kaji/troubleshooting.md` with stable anchors. `kaji/ts/src/cli/render.ts` renders `error_code`, `phase`, `retryable`, `outcome`, and a short recovery hint for human replay while preserving the full stable fields in `--format json`. Define stdout for requested data, stderr for diagnostics, stable exit codes (`0` success, `1` validation/runtime failure, `2` usage), `--no-color`, and `--verbose` with redacted causes. Never print prompts, tool arguments, API keys, raw provider bodies, or arbitrary metadata.

**Step 3: Publish one findable, tested operating path.**

- `docs/kaji/README.md` is the versioned index: quickstart, stable API, testing, CLI, operations, migration, and experimental surfaces.
- `docs/kaji/api-parity.md` maps Python/TypeScript builders, contexts, effective limits, errors, snake_case wire fields, host-language field names, units, and stable exports; one side-by-side Echo lifecycle is executable.
- `docs/kaji/testing.md` covers deterministic providers, clocks/IDs, contract fixtures, tool failures, package-artifact testing, and the macOS/Linux release-operator requirement for tested POSIX process-group cleanup without narrowing the SDK runtime's separately declared platform support.
- `docs/kaji/cli.md` owns the command stability matrix, streams/exit codes, and scaffold modes.
- Tests derive the stable export/feature lists from `kaji/contracts/feature-tiers-v1.json` and fail on undocumented stable exports or examples using experimental/deprecated aliases.
- Update `docs/kaji/production-beta.md`, both package READMEs, and `kaji/RELEASE_MATRIX.md` so OpenAI and Anthropic are described consistently as declared-stable adapters whose keyed Python-and-TypeScript tool-loop proofs are mandatory release evidence. Remove every remaining “conditional,” optional-key, or provider-skip readiness path; local no-key quickstarts continue to use the mock provider, but a missing protected credential blocks release.

**Step 4: Update migration and compiler/package-manager support.**

Cover:

- opaque non-empty event IDs and closed event objects;
- the new I-JSON safe-integer policy and read-only `kaji/scripts/check_event_migration.py` preflight;
- new durable-result and whole-event limits;
- timeout vs cancellation vs provider-quarantine terminal semantics and TS `deadlineMs` -> `deadlineAtMs` rename;
- new manifest ABI fields;
- coalesced delta boundaries;
- deprecated pre-beta compatibility paths and their removal horizon.

Because the first beta has not shipped, freeze these as the first `1.0.0` contract rather than publishing a second contract version. Pre-beta persisted rows are unsupported unless the migration preflight accepts them. Changelogs must still call out every behavioral change.

Declare Node support separately from compiler support: Node 22/24 runtime; TypeScript declarations compile under minimum TypeScript 5.7 and current 6.x. Update the scaffold to current 6.x, add a pinned TypeScript 5.7 compiler alias/dev fixture, and compile the packed declarations/quickstart under both. Support npm and Bun for the TypeScript beta and smoke the generated project with each; do not imply pnpm/yarn support until tested.

**Step 5: Add minimum production-beta trust and feedback surfaces.**

- `SECURITY.md`: private vulnerability channel, supported beta versions, response expectations, and no public exploit details.
- `CONTRIBUTING.md` and `SUPPORT.md`: local checks, stable/experimental boundaries, support channel, and best-effort beta response expectations.
- Kaji issue form: SDK language/version, runtime/compiler/package manager, OS, minimal reproduction, error code, and redacted event excerpt.
- Assign an owner/date for a 30-day post-release DX review, monthly friction audit for the beta window, and docs feedback link. Installed smoke is evidence of mechanics, not a substitute for human feedback.

**Step 6: Keep runnable docs as release tests and measure TTHW honestly.**

```bash
uv run --project kaji/sdk pytest kaji/sdk/tests/test_production_beta_docs.py kaji/sdk/tests/test_docs_sync.py kaji/sdk/tests/test_release_smoke.py --no-cov -q
uv run --project kaji/sdk pytest kaji/sdk/tests/cli/test_init.py kaji/sdk/tests/cli/test_main.py --no-cov -q
(cd kaji/ts && bun run build && bun run vitest run tests/cli-init.test.ts tests/cli-dispatch.test.ts tests/cli-replay.test.ts tests/docs-contract.test.ts tests/package-contract.test.ts tests/public-declarations.test.ts)
(cd kaji/ts && bun scripts/smoke_package.mts)
```

The exact-artifact smoke must pack/install, run `kaji init`, install/compile the generated project, execute it, and assert deterministic text/turn/sequence output. Record automated cold setup-to-output and warm run time separately for Python, npm, and Bun.

Human TTHW is currently **unmeasured**, not “competitive.” Before the beta label, run five fresh-user artifact evaluations across macOS/Linux and Python/npm/Bun, recording per-step time, OS, package manager, confusion points, median, and maximum. Exit targets: median no-key TTHW <5 minutes, every run <10 minutes; median first Echo lifecycle <10 minutes, every run <20 minutes. Repeat the protocol 30 days after publication and compare regressions.

**Step 7: Checkpoint.**

```bash
but diff
but commit enkang/kaji-beta-gap-closure -m "docs(kaji): publish the production-beta operating path" --changes <task-11-change-ids>
```

### Task 12: Produce Protected Same-Commit Release Evidence

**Priority:** P0 release-operator gate  
**Depends on:** Tasks 1-11 complete and code-frozen

This task includes operational actions that cannot be proven by local source changes alone. Do not mark it complete from a developer laptop.

**Files and protected artifacts:**

- Modify `kaji/scripts/live_provider_proof.py`, `kaji/scripts/verify_published_packages.py`, `kaji/sdk/tests/test_live_gate.py`, and `kaji/sdk/tests/test_release_task15.py`.
- Modify `.github/workflows/kaji.beta.yml` and `.github/workflows/kaji.beta-publish.yml` for mandatory dual-provider evidence and partial-publication state retention.
- Modify `kaji/benchmarks/beta-baseline.json` only from the reviewed pinned-runner calibration candidate.
- Modify `kaji/RELEASE_MATRIX.md`, `docs/kaji/production-beta.md`, `docs/kaji/releasing.md`, `kaji/sdk/README.md`, and `kaji/ts/README.md` only after every protected row and registry byte check passes.
- Retain benchmark, soak, provider, TTHW, signature, SBOM/provenance, publication-state, and downloaded-byte evidence under the protected workflow/release; do not commit credentials or raw prompts.

**Step 1: Run the complete local checkpoint from a clean workspace.**

```bash
bun run audit:ast-grep
uv run --project kaji/sdk python kaji/scripts/check_beta_contract.py
uv run --project kaji/sdk python kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji/sdk python kaji/scripts/sync_integration_contracts.py --check
uv run --project kaji/sdk python kaji/scripts/check_integration_abi.py --explain
uv run --project kaji/sdk python kaji/scripts/check_sdk_parity.py
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py --release
uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --quick
```

Expected: zero diff after generated-copy checks; Python/TS full suites and installed artifacts pass; output explicitly says protected readiness is not claimed.

**Step 2: Calibrate the pinned runner after code freeze.**

1. Configure self-hosted labels `[self-hosted, linux, x64, kaji-benchmark]`.
2. Set `KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST` to an immutable image digest.
3. Dispatch `.github/workflows/kaji.benchmark.yml` with `job=calibrate`.
4. Review all five raw samples for all eight cases and both runtimes.
5. Copy only the generated candidate into `kaji/benchmarks/beta-baseline.json`.
6. Commit the calibrated baseline separately:

```bash
but diff
but commit enkang/kaji-beta-gap-closure -m "perf(kaji): calibrate beta benchmark baseline" --changes <baseline-change-id>
```

Never hand-edit medians or calibrate on `local-unpinned`.

**Step 3: Run protected performance and runtime matrices on that exact commit.**

- full benchmark with regression comparison;
- 30-minute soak, at least 10,000 turns, <=5% late-window heap growth;
- Python 3.11 and 3.14 artifact matrices;
- Node 22 and 24 artifact matrices;
- TypeScript 5.7 and current 6.x declaration/quickstart compilation from the packed tarball;
- npm and Bun generated-scaffold smoke;
- five fresh-user TTHW evaluations meeting the Task 11 median/maximum targets, with redacted artifacts retained;
- retain raw benchmark/soak artifacts with commit SHA, runner fingerprint, lock hash, and tool versions.

**Step 4: Run keyed provider proof.**

Configure the protected `kaji-beta` environment with required OpenAI and Anthropic credentials. Modify `kaji/scripts/live_provider_proof.py` and its tests so both providers are mandatory and each completes a real normalized tool loop in Python and TypeScript. A missing-key skip/failure proves hygiene only and is not readiness evidence for a stable adapter.

**Step 5: Create and verify the signed release tag.**

- tag the direct release commit with the protected, annotated, signed `kaji-v0.2.0-beta.1` tag;
- verify approved tagger identity and signature;
- ensure the tag commit equals every protected evidence artifact’s commit;
- do not move or recreate the tag after publication.

**Step 6: Publish with provenance and track partial-publication state.**

Run `.github/workflows/kaji.beta-publish.yml` through its protected environment approvals. Require:

- wheel, sdist, and npm tarball metadata/content verification;
- SBOM and provenance attestations;
- PyPI and npm trusted publication;
- exact downloaded registry bytes match built artifacts;
- each PyPI wheel/sdist is downloaded from its registry file URL, hashed locally, and verified with PyPI's Integrity API attestation rather than trusting metadata digests alone;
- the npm tarball is downloaded, hashed, and its provenance/signatures are verified with the current npm CLI;
- GitHub prerelease assets and checksums attached;
- publication status and provider/performance evidence attached to the same release.

The operator records one monotonic state in the release evidence:

```text
unpublished
  -> pypi_only | npm_only
  -> both_published
  -> byte_verified
```

`byte_verified` is the only success terminal state. Rename the workflow's current `complete` status to `byte_verified` and make the release-evidence job require that exact value; `both_published` without downloaded-byte and attestation verification is not release-ready.

Primary references: [PyPI attestation consumption](https://docs.pypi.org/attestations/consuming-attestations/), [npm provenance statements](https://docs.npmjs.com/generating-provenance-statements/), and [GitHub artifact-attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).

Publish cannot be atomic across registries. If only one registry succeeds, immediately mark the GitHub prerelease/status as a partial-publication incident, stop install recommendations, and attempt the other registry only from the same immutable artifacts/tag. If recovery cannot complete promptly, yank the PyPI release where policy permits and deprecate the npm version with an incident message; never delete evidence, move/recreate the tag, overwrite bytes, or reuse either version. Fix forward with the next beta version, publish both registries, and verify bytes before clearing the incident. A registry-byte mismatch after both publishes follows the same next-version recovery and security triage.

**Step 7: Update evidence, not claims.**

Only after the publication state is `byte_verified` and every row passes, update `kaji/RELEASE_MATRIX.md`, `docs/kaji/production-beta.md`, `docs/kaji/releasing.md`, and both package status banners from “pre-beta” to “production beta,” citing protected run/release URLs. The final documents must show required passing OpenAI and Anthropic rows for Python and TypeScript; neither provider may be marked conditional or skipped while it remains in the stable tier. If any protected row fails, preserve pre-beta language, fix forward, and rerun every affected same-commit gate.

## 7. Error and Rescue Registry

| Method/codepath | Failure | Typed error/code | Rescue action | Developer impact |
|---|---|---|---|---|
| canonical event validation | unknown type, extra field, empty ID, wrong sequence, unsafe integral number | schema/Pydantic/Zod validation or `EVENT_SCHEMA_INCOMPATIBLE` | reject before append with normalized pointer; migration checker never writes | exact contract location |
| durable JSON snapshot | class/function/cycle/NaN/out-of-range integral number/surrogate | `InvalidDurableValueError` / `INVALID_DURABLE_VALUE(subject)`; tool maps to `INVALID_TOOL_RESULT` | tool result tombstones unknown outcome; other subjects fail before success persistence | fix the named durable subject; session remains replayable |
| durable JSON snapshot | result/event exceeds cap | `DurableJsonLimitError` / `EVENT_PAYLOAD_TOO_LARGE` | reject before persistence | reduce payload or externalize data |
| session coordinator queue | deadline expires before acquisition | `TurnTimeoutError` / `TURN_TIMEOUT` | unlink waiter, emit terminal if turn started | retryable; no lane leak |
| provider open/stream | deadline or caller cancellation, cooperative provider | phase-aware `TurnTimeoutError` or `CancellationError` | abort iterator/task, join within grace, emit exactly one terminal | retry guidance comes from phase; next turn is safe after join |
| provider open/stream | provider ignores cancellation grace | `ProviderCancellationContractViolation` / `PROVIDER_CANCELLATION_CONTRACT_VIOLATION` | quarantine session; background owner retains lease until successful drain; close blocks new work | no next turn until drained; restart if hostile code never settles |
| provider output | text/tool-argument/total-response/tool-call cap exceeded | `ProviderOutputLimitError` / `PROVIDER_OUTPUT_LIMIT` | abort vendor stream, flush only already-bounded text, emit failure, skip tools/completion | explicit dimension/limit without payload leakage |
| session transaction | nested acquisition or append failure | `NestedEventTransactionError` or existing event errors | fail fast on nesting; remove reservation, release lane, preserve original error | no deadlock; retry according to persisted flag |
| event ID reservation | same ID, different payload | `EventIdConflictError` | reject duplicate; no second fanout | choose a unique/stable ID |
| subscriber fanout | queue overflow | `EventBufferOverflowError` | detach subscriber with cursor diagnostics | reconnect from last sequence |
| context index | malformed tool grouping | `ContextIntegrityError` | fail identically to full-scan oracle | repair/import valid event history |
| integration ABI check | metadata/schema mismatch | `IntegrationAbiMismatchError` | fail registry validation before copy/publish | exact pointer and expected field |
| release child command | timeout or output overflow | `CommandTimeoutError` or `CommandOutputLimitError` | terminate, kill after grace, reap the process group, clean temp dir, fail gate | actionable step/budget, no secret-bearing arguments |
| performance full gate | missing/wrong fingerprint baseline | runtime gate error | block release; recalibrate only on pinned runner | no misleading local baseline |
| protected provider/tag/publish | auth/signature/pre-publication failure | workflow failure | stop before registry mutation; preserve pre-beta state | operator fixes environment and reruns |
| registry publication | one registry succeeds or byte verification fails | partial-publication incident state | yank/deprecate where permitted; retain tag/evidence; next-version fix forward | package is not advertised as beta until both bytes verify |

No catch-all path may swallow a failure. Broad catches used solely to preserve an original exception must log redacted type/phase context and re-raise or return a typed terminal.

## 8. Failure Modes Registry

| Codepath | Failure mode | Rescued? | Test? | Developer sees | Logged/metric? |
|---|---|---:|---:|---|---:|
| event contract | canonical/runtime drift | Yes | differential fixtures | normalized pointer | contract gate |
| numeric contract | pre-beta exact-float policy leaks past safe range | Yes | boundary/exponent fixtures | normalized number pointer | contract gate |
| Python tool result | non-JSON result poisons replay | Yes | poisoning regression | `INVALID_TOOL_RESULT` | failure + unknown outcome |
| turn queue | timeout waiter remains linked | Yes | deterministic race test | `TURN_TIMEOUT` | queue wait/outcome |
| provider stream | SDK ignores abort | Yes, quarantine | hostile provider/drain test | provider contract violation; session blocked | provider status/quarantine count |
| provider tool arguments | fragments grow quadratically or exceed memory before finalization | Yes | 10k-fragment/one-byte-over tests | `PROVIDER_OUTPUT_LIMIT` | response byte/fragment counters |
| commit lanes | duplicate-ID reservation or nested store/journal transaction deadlocks | Yes | direct-store/two-journal/nesting tests | typed conflict or nesting failure | lane/reservation counters |
| subscription | commit between backlog and attach | Yes | barrier handshake test | no gap/duplicate | lag/overflow metrics |
| context index | index diverges from projection | Yes | generated differential test | integrity error before request | replay/context counters |
| stream batching | terminal overtakes buffered text | Yes | every boundary test | exact ordered prefix + terminal | delta/event counters |
| integration ABI | validator loads side-effectful module | Yes | no-I/O metadata-load test | ABI validation error | registry check |
| clean release | tests use stale `dist` | Yes | absent-dist regression | failing ordered gate | release step output |
| release child process | command hangs, ignores termination, floods stdout/stderr, or leaves a sibling alive | Yes | fake-child timeout/output/process-group tests | typed command phase and budget | release gate failure |
| generated CLI | stale SDK/TS/Zod versions or keyed default | Yes | exact-artifact npm/Bun/Python scaffold smoke | deterministic no-key output | install-step timings |
| benchmark | baseline calibrated before final perf changes | Process prevention | workflow/order test | release blocked | provenance metadata |
| registry publish | PyPI succeeds and npm fails, or downloaded bytes differ | Yes, incident/fix-forward | workflow state-machine test + operator drill | partial-publication status | release evidence |

No row remains simultaneously unrescued, untested, and silent.

## 9. Test Coverage Map

```text
SHARED CONTRACT
  closed event union
    + happy: every EventType, new + stored                [unit + differential]
    + invalid: IDs/type/extras/sequence/I-JSON numbers   [unit + contract]
    + pre-beta JSONL migration preflight                 [artifact]
    + package copies                                     [artifact]

DURABLE RESULT
  handler -> snapshot -> ledger -> event -> replay
    + JSON values/boundaries                              [unit]
    + cycles/classes/functions/nonfinite/unsafe integral numbers [hostile unit]
    + oversized UTF-8                                    [boundary]
    + tool/workflow/metadata/memory/event subjects       [unit + integration]
    + tool failure follows existing planner semantics    [integration]

TURN DEADLINE
  queue -> provider open -> stream -> approval -> tool
    + timeout at every phase                             [deterministic integration]
    + cancel/timeout race                                [concurrency]
    + queue/provider/approval/tool retry metadata        [unit + integration]
    + cooperative provider joins; next turn proceeds     [integration]
    + hostile provider quarantines until drain/dispose   [fault injection]

EVENT CONCURRENCY
  store-owned transaction + ID reservation + subscription
    + A blocked, B proceeds                              [barrier concurrency]
    + same-session FIFO                                  [ordering]
    + duplicate same/conflicting ID                      [race]
    + backlog/live no-gap                                [integration]
    + direct store + two journals + nested acquisition   [integration]

CONTEXT + STREAM
  10k history x 5 iterations                             [operation-count + benchmark]
  zero copied context payload + bounded RSS              [semantic + benchmark]
  10k deltas, exact text, bounded events                 [unit + benchmark]
  10k tool-argument fragments, bounded bytes/joins       [unit + benchmark]
  every flush/terminal boundary                          [unit]

INTEGRATION ABI
  schema-valid manifest                                  [contract]
  exact Echo runtime metadata in both SDKs               [integration]
  experimental manifests structural only                [contract]
  no side effects during Echo validation                 [fault test]

RELEASE
  absent dist -> build -> tests -> package               [regression + E2E]
  child hang/ignore-term/output flood/nonzero exit       [fault unit + integration]
  soak sibling cleanup after timeout/failure             [process integration]
  wheel/tarball imports and docs                         [artifact E2E]
  generated no-key CLI under Python/npm/Bun              [artifact E2E]
  TypeScript 5.7 + 6.x declarations                      [artifact matrix]
  five fresh-user TTHW runs                              [human gate]
  both providers x both SDKs                             [protected E2E]
  partial-publication recovery                           [workflow/operator drill]
  PyPI/npm download hash + attestation verification      [protected artifact E2E]
  protected benchmark/soak/tag/byte verification         [workflow E2E]
```

The “2am Friday” test is the clean `beta_release_check.py --release` plus quick benchmark and parity gate. The hostile QA tests are non-cooperative providers/tools, concurrent duplicate IDs, malformed durable values, and an absent `dist`. The chaos tests are journal publish failures, subscriber overflow, provider timeout mid-stream, and 30-minute soak.

## 10. Observability and Operations

Add only low-cardinality measurements:

- `kaji.turn.deadline_exceeded{phase}`;
- `kaji.provider.output_bytes{provider_family,dimension}` where `dimension` is closed to `text`, `tool_arguments`, or `total`;
- `kaji.provider.delta_events{provider_family}`;
- `kaji.provider.quarantined_sessions{provider_family}`;
- `kaji.provider.cancellation_grace_exceeded{provider_family}`;
- `kaji.event.commit_lane_wait_ms` without session labels;
- `kaji.event.commit_lanes_active`;
- `kaji.context.full_index_builds`, `kaji.context.index_updates`, and `kaji.context.copied_payload_bytes`;
- `kaji.integration.abi_mismatch{field}` with a closed field vocabulary.

Never label metrics with session, turn, request, trace, tool arguments, prompts, result values, API keys, URLs, or arbitrary JSON Pointers. Trace attributes may retain existing correlation IDs under the established redaction policy.

Day-one runbook decisions:

- rising deadline failures by provider phase -> inspect provider status/latency; do not increase default blindly;
- any quarantined session -> stop new work for that runtime, drain/dispose, replace or fix the provider, and never release the lease manually;
- lane count never returns toward active-session count -> capture task dump and disable per-session optimization by reverting Task 6;
- context differential test/metric mismatch -> stop release and revert Task 7;
- delta-event ratio regression -> inspect provider batching and Task 8 limits;
- Echo ABI mismatch -> block registry copy/publication and run `check_integration_abi.py --explain`; experimental structural failure blocks only that invalid catalog artifact;
- partial registry publication -> declare incident, stop install recommendations, preserve tag/artifacts, and follow yank/deprecate plus next-version recovery;
- benchmark fingerprint mismatch -> do not compare results; restore runner image or recalibrate after approval.

## 11. Deployment and Rollback Sequence

```text
merge code checkpoints
  -> full local release rehearsal
  -> protected PR gate
  -> freeze code
  -> calibrate pinned benchmark baseline
  -> commit baseline
  -> rerun full benchmark + soak + runtime/compiler/package-manager matrices
  -> complete five fresh-user TTHW runs
  -> keyed OpenAI + Anthropic proof in both SDKs
  -> signed annotated tag
  -> build + attest + publish while recording partial-publication state
  -> download and byte-verify registries
  -> update release evidence/status
```

Rollback before registry publication is a GitButler revert/move of the offending coherent checkpoint followed by full affected gates. After either registry publishes, do not mutate artifacts or move the tag; use the explicit partial-publication incident path and publish the next prerelease with a changelog/migration note if same-artifact completion fails. Contract/schema, runtime, and generated copies are atomic rollback units.

Reversibility rating: **4/5**. All source changes are reversible before publication; public package versions and signed tags are immutable one-way evidence.

## 12. Beta Exit Checklist

### Correctness and isolation

- [ ] Canonical/Python/TypeScript event acceptance is identical for all fixtures, including I-JSON number boundaries.
- [ ] Pre-beta JSONL migration preflight reports incompatible rows without mutation.
- [ ] No durable event contains an unvalidated JSON value or exceeds its cap.
- [ ] Deadline covers queue, provider, approval, and tools with exactly one phase-classified terminal for cooperative providers.
- [ ] A hostile provider quarantines only its session, reports a contract violation, and drains/disposes without a false lease release.
- [ ] Same-session FIFO and cross-session overlap are both proven through direct store calls and multiple journals sharing one store.
- [ ] Context selection is incremental and oracle-equivalent.
- [ ] Text, fragmented tool arguments, total response bytes, tool-call count, and durable event count are enforced.

### Feature and integration contracts

- [ ] Stable feature tiers still match both public packages.
- [ ] Every shipped CLI command is explicitly stable or experimental; stable commands pass exact-artifact tests.
- [ ] Echo manifest ABI matches Python and TypeScript executable tool specs.
- [ ] Experimental integrations validate without being promoted.
- [ ] Shared contract/package copies are byte-identical.
- [ ] Parity scenarios and golden snapshots pass.

### Performance and resilience

- [ ] Quick semantic benchmark passes on ordinary CI.
- [ ] Pinned full benchmark passes calibrated absolute/regression budgets.
- [ ] 30-minute protected soak meets turn and heap-growth thresholds.
- [ ] No coordinator, lane, reservation, provider watcher/quarantine after drain, timer, subscriber, or tool task leaks.

### Release and DX proof

- [ ] Clean offline rehearsal passes without preexisting artifacts.
- [ ] Python 3.11/3.14, Node 22/24, TypeScript 5.7/6.x, npm, and Bun installed-artifact matrices pass.
- [ ] Exact-artifact CLI scaffolds run no-key in Python/npm/Bun and print text, turn ID, and sequence.
- [ ] Five fresh-user runs meet the no-key and Echo TTHW median/maximum targets.
- [ ] Keyed OpenAI and Anthropic tool loops pass in both SDKs.
- [ ] Signed direct tag, SBOM, provenance, and attestations verify.
- [ ] Publication state is `byte_verified`; PyPI/npm downloads match built bytes and GitHub prerelease assets.
- [ ] Status banners change only after all exact-commit evidence exists.

## 13. What Already Exists and Is Reused

- `canonical_json` / `canonicalJsonValue` already define cross-SDK Unicode, key-order, cycle, and plain-object policy; Task 1 tightens only integral-number interoperability and Task 2 reuses the encoders for detached snapshots.
- `TurnContext`, cancellation tokens, tool deadlines, and abort-signal forwarding already exist; Task 3 connects them across the whole turn.
- `InMemoryTurnCoordinator` / `InMemorySessionTurnCoordinator` already prove keyed FIFO semantics; the event store reuses the keyed-lane principle while adding a non-nesting transaction boundary.
- `SessionProjector` already applies suffix events once; Task 7 extends that single projection point with context indexing.
- `ToolExecutionController` already bounds parallelism, timeout, cancellation, idempotency, and non-cooperative handlers; result snapshotting belongs at this existing boundary.
- Manifest and index schemas are already closed with auth conditionals and safe paths; Task 5 adds ABI fields, structural validation for all entries, and executable correspondence only for stable Echo.
- The parity harness, package-copy sync checks, release wrapper, benchmark/soak drivers, and publish workflows already exist; Tasks 9-12 close their evidence gaps.
- Both packages already ship CLIs, installed quickstarts, migration docs, changelogs, and troubleshooting tests; Task 11 classifies and hardens that existing public surface rather than inventing a second onboarding system.

## 14. Dream-State Delta

After this plan, the stable single-process core is production-beta credible: cross-language contracts are closed, durable state is replay-safe, turns and output are bounded, unrelated sessions scale independently, context work is incremental, artifacts are reproducibly tested, and the release is backed by protected evidence.

Still outside the 12-month ideal:

- durable/distributed session coordination and event storage;
- restart-safe idempotency and snapshots;
- a separately versioned ephemeral realtime delta transport;
- promotion evidence for non-Echo catalog integrations;
- wider ecosystem/community and real-world sample applications;
- post-publication measured developer activation and support feedback.

Those are future product lanes, not reasons to weaken this beta’s stable-core promise.

## 15. Review Refinements Applied

### Plan-tune profile

- scope appetite: 0.85 — complete, edge-case-covered plan;
- risk tolerance: 0.25 — careful fail-first verification;
- detail preference: 0.85 — explicit code shapes and tradeoffs;
- autonomy: 0.85 — recommended reversible decisions applied without repeated pauses;
- architecture care: 0.85 — correctness and system design take precedence over label speed.

### CEO review — HOLD SCOPE

Implementation alternatives considered:

1. **Minimal:** fix event drift, Python result poisoning, deadlines, and build order; defer performance/ABI. Rejected because it would label a bounded but knowingly non-optimal architecture as production beta.
2. **Complete stable core:** close correctness, performance, stable Echo ABI, CI, packaged CLI/DX, and protected release proof in one evidence-driven sequence. Selected.
3. **Maximal catalog:** also source-compare every experimental integration before beta. Rejected because structural validation is sufficient until each experimental entry enters its own promotion gate.

Scope remains the stable core; no new providers, integrations, hosted services, or UI were added. Existing packaged CLIs are now classified because shipping an unclassified public executable would itself be a beta gap. The complete option means fully hardening the named beta promise, not promoting experimental catalog entries.

Current review decisions reaffirmed the complete stable-core path and made three contract choices explicit: event IDs are non-empty opaque strings with UUID as the default generator; both declared-stable providers require keyed same-commit tool-loop proof in both SDKs; and one generic integration ABI verifier enforces executable parity only for stable Echo while experimental entries remain structural-only until promotion.

CEO section outcomes:

- Architecture: store-owned non-nesting transactions, reference-only context index, provider quarantine, and bounded text/argument accumulators added to the plan.
- Error/rescue: durable-subject, phase-aware timeout, provider-contract, ABI, child-process, partial-publication, and benchmark failures made typed and visible.
- Security: closed inputs, no new runtime dependencies, redacted diagnostics, action pinning, vulnerability reporting, signing/provenance retained.
- Data edge cases: nil/empty/invalid/oversized/concurrent paths have explicit tests.
- Code quality: reuse existing JSON, coordination, projector, and execution abstractions; no parallel replacement systems.
- Tests: differential, fault, concurrency, exact-artifact CLI, compiler/package-manager, human TTHW, benchmark, soak, and protected E2E layers mapped.
- Performance: measure semantic work as well as timing; calibrate only after architecture changes.
- Observability: bounded closed-label metrics and rollback signals specified.
- Deployment: same-commit evidence, partial-publication state, and immutable next-version recovery specified.
- Long-term trajectory: reversible in-process foundations retain seams for durable/distributed implementations.
- Design/UX: skipped; no end-user UI scope.

### Engineering review — FULL REVIEW

- Architecture decision: use one effective deadline, phase-specific outcomes, a quarantine owner for non-cooperative providers, one store-owned session transaction, and one projection mutation path; avoid duplicated state machines.
- Code-quality decision: add small private primitives (`durable_json_snapshot`, deadline scope, session transaction, context index, response budget, delta accumulator) at existing boundaries instead of a runtime rewrite.
- Test decision: require explicit new/stored validators, differential fixtures, direct-store/two-journal races, hostile provider/tool tests, and deterministic semantic counters where elapsed timing would be flaky.
- Performance decision: remove known global serialization, payload-copy/full-scan work, and text/tool-argument amplification before baseline calibration.
- Parallelization: four post-contract lanes, with runtime and event/projector overlaps kept sequential.
- Session ordering decision: the store owns keyed, non-nesting session transactions; per-journal locks and the global serializer are rejected because neither protects direct-store plus multi-journal access correctly.
- Deadline decision: one absolute deadline is resolved before queueing and propagated through providers/tools; non-cooperative providers retain a background lease and quarantine the session after bounded grace.
- Release-tooling decision: centralized Python and TypeScript command runners own deadlines, output caps, redaction, process-group termination, and cleanup; ast-grep forbids direct unbounded subprocess calls.
- Context/stream decision: the projector owns a differential-tested context index, while provider text/tool fragments use bounded linear accumulators and coalesced durable deltas.
- Performance-evidence decision: semantic budgets run in ordinary CI; timing/RSS calibration and the 30-minute soak run only on the pinned protected runner after code freeze.
- Wire-ingestion decision: raw serialized events validate required fields before Pydantic/Zod defaults; defaults remain constructor-only conveniences.
- Provider-loop sequencing decision: Task 8 joins completed deadline and context-index work; Tasks 7 and 8 cannot run in parallel against the same loop.
- Child-process decision: inventory every Python release caller and use asynchronous detached process groups for TypeScript so descendant cleanup is a tested guarantee, not a direct-child assumption.
- Echo-authority decision: one canonical Echo ABI document feeds both manifests, one TypeScript executable source feeds its distribution copy, and Python's public `ManifestTool` preserves every validated ABI field.

### Developer-experience review — DX POLISH

| Dimension | Current | Planned | Result |
|---|---:|---:|---|
| Getting started | 6/10 | 9/10 | exact-artifact no-key CLI with truthful package/peer versions |
| API/SDK consistency | 6/10 | 9/10 | tested parity map, explicit deadline units, classified CLI |
| Errors/debugging | 7/10 | 9/10 | problem/cause/fix plus CLI code/phase/outcome rendering |
| Documentation | 7/10 | 9/10 | indexed stable API, testing, CLI, migration, and troubleshooting paths |
| Upgrade path | 8/10 | 9/10 | pre-beta contract changes and deprecated paths explicit |
| Dev environment | 6/10 | 9/10 | clean artifact, compiler/npm/Bun matrices, bounded commands |
| Community/ecosystem | 4/10 | 7/10 | security, contributing, support, and structured issue intake |
| DX measurement | 5/10 | 8/10 | automated timings plus five-user pre/post-release protocol |

Unweighted DX score: **49/80 (6.1/10) -> 69/80 (8.6/10)** if every planned gate passes. Target median TTHW: **<5 minutes** no-key and **<10 minutes** first Echo lifecycle, with explicit maximums in Task 11. Competitive tier remains **unproven until measured**; safety/parity is the intended wedge rather than the shortest hello-world syntax.

The current DX pass retained the existing platform-engineer persona, no-key magical moment, measured TTHW targets, and DX POLISH mode. It added one cross-SDK contract: both `init` commands now share the same path/provider/non-interactive/overwrite grammar and behavior, with TypeScript's existing `--out` retained only as a tested deprecated alias. All other pass findings were already represented by the exact-artifact quickstart, actionable error table, indexed docs, migration preflight, compiler/package-manager matrix, trust documents, and pre/post-release measurement protocol.

### Independent outside-voice disposition

Three fresh read-only reviewers challenged the complete draft against CEO/parity, Python engineering, and TypeScript/DX evidence. Their initial verdicts were all `CONCERNS`; no concern was waived:

- Phase-wide retry metadata became phase-specific, with active-tool timeout non-retryable.
- The impossible force-cancellation promise became cooperative-provider grace plus tracked quarantine/drain/restart semantics.
- The numeric contract changed from pre-beta exact-IEEE integer handling to schema-enforceable I-JSON safe integers, with migration preflight.
- Stream budgets now cover fragmented tool arguments and cumulative response bytes inside both stable adapters.
- Event concurrency now has one store-owned, non-nesting transaction shared by direct calls and multiple journals.
- Invalid tool results preserve the existing planner failure flow; generic durable subjects and workflow/event tests cover other boundaries.
- Context indexing stores boundaries/counters only and has pre-calibration copy/RSS budgets.
- Anthropic live tool loops are mandatory in both SDKs because the adapter remains stable.
- Experimental integrations receive structural validation only; executable parity remains an Echo/stable gate.
- Partial PyPI/npm publication has an incident and immutable next-version recovery state machine.
- Both shipped CLIs are classified; the no-key scaffold, replay errors, compiler/package-manager support, API map, trust docs, and human TTHW gates are explicit.
- Raw-wire validation now precedes constructor defaults, provider-loop tasks are serialized at their shared edit point, every current release subprocess caller is named, and TypeScript cleanup covers descendants.
- Echo now has one contract authority and one TypeScript executable authority; both manifests, Python runtime metadata, TypeScript runtime metadata, and the bundled TypeScript copy are checked.

The installed Claude CLI was considered as an optional cross-model review. After the privacy boundary was made explicit, external repository-content transmission was declined, so no source or plan content was sent. This privacy choice did not replace or weaken the three completed repository-grounded reviews.

## 16. Implementation Discipline

- Use `subagent-driven-development`; one fresh implementer and spec/code review cycle per task.
- Start each task by adding its failing test or fixture and recording the expected failure.
- Keep shared contracts and both runtime consumers in one checkpoint.
- Use `apply_patch` for edits and GitButler for all version-control operations.
- Preserve unrelated dirty work and other agents’ branches.
- Never calibrate, tag, publish, or update beta-status language early.
- After each task, run the targeted commands before its GitButler checkpoint.
- After Task 11, run the full clean local checkpoint once; after the baseline commit, rerun every protected affected gate.
- If a benchmark-backed optimization changes public event semantics beyond ordered concatenated text, stop and write a separate reviewed contract migration.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---:|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 3 | CLEAR | HOLD_SCOPE; complete stable core selected; opaque IDs, mandatory dual-provider proof, and stable-only executable ABI enforcement frozen |
| Independent Review | fresh read-only reviewers | Adversarial second opinion | 3 | CLEAR | all parity, Python engineering, and TypeScript/DX concerns dispositioned above |
| Claude Review | `/claude` outside voice | Cross-model check | 0 | SKIPPED | installed CLI; user declined external repository-content transmission after privacy disclosure; no content sent |
| Eng Review | `/plan-eng-review` | Architecture and tests | 3 | CLEAR | raw-wire strictness, phase/quarantine semantics, task sequencing, store transactions, process-tree bounds, Echo authority, stream limits, and differential context proof folded in |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | SKIPPED | No UI scope |
| DX Review | `/plan-devex-review` | Developer experience | 3 | CLEAR | honest 6.1 -> 8.6 target; canonical cross-SDK CLI, packaged smoke, human TTHW, compiler/package-manager, trust, and feedback gates added |

**VERDICT:** CLEAR FOR IMPLEMENTATION. The plan closes every reviewed production-beta blocker without promoting experimental product scope. Protected operator evidence remains an implementation-time exit gate, not an unresolved design decision.

NO UNRESOLVED DECISIONS
