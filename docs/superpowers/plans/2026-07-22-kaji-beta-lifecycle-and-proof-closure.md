# Kaji Beta Lifecycle and Proof Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Every implementation task requires a fresh implementer, a spec-compliance review, a code-quality review, and a GitButler checkpoint before its dependent task starts.

**Goal:** Remove the cross-SDK session-generation corruption defect, align beta evidence with the approved arm64 macOS scope, and add the missing exact-artifact GitHub proof boundary before Kaji collects protected beta evidence.

**Architecture:** Capacity never deletes a retained session implicitly. A session ID becomes reusable only through an explicit, store-scoped purge fence that closes old subscriptions, removes event history, clears every runtime owner's caches, and releases settled idempotency state. Release proof reuses the existing one-artifact-set fan-out: installed packages produce closed macOS-bound evidence, while calibration, live credentials, signing, provenance, publication, and registry verification remain protected operator actions.

**Tech Stack:** Python 3.11-3.14, asyncio, Pydantic 2, pytest, Ruff, ty, uv; TypeScript 5.7/current 6.x, Node 22/24, Bun, Zod 4, Vitest, oxfmt; JSON Schema Draft 2020-12; GitHub Actions; ast-grep 0.44.1; GitButler.

## Global Constraints

- The beta evidence claim is arm64 macOS only. Every human receipt records `os: "macos"`, `architecture: "arm64"`, and the exact `sw_vers -productVersion` value. Linux-capable runtime code remains supported but is not part of the beta claim.
- The embedded/process-local architecture remains the beta boundary. Do not add distributed coordination, a hosted control plane, or a second runtime abstraction.
- Silent event-store eviction is forbidden. Capacity exhaustion raises `EventStoreCapacityError` until the host explicitly purges a settled session.
- Purge is destructive and fail-closed: capability and busy-state preflight happens before mutation; once event history is deleted, a later host-ledger cleanup failure is reported and retried, never hidden or rolled back fictionally.
- Physical deletion requires the exact opaque authorization issued by the active store/session purge lease. A global `purging` boolean is not authorization: concurrent direct callers must still fail while the legitimate runtime awaits the store lane.
- Python shields the irreversible phase from caller cancellation. Once physical deletion may have committed, subscription-independent cache and settled-ledger cleanup runs to completion before cancellation is re-raised.
- Raw store purge is unavailable while the store has any live listener for that session, even when no runtime owner exists. Standalone journal/committer callers must close their iterator first; runtime purge closes every supported iterator before it reaches the store.
- Physical deletion creates a store/session `cleanup_pending` tombstone before the purge lease can reopen. New turns, projections, runtime registration, and store-only purge remain blocked until a retry finishes every owner's settled-ledger cleanup and clears the tombstone.
- Existing subscribers belong to one retained session generation. Purge terminates them; a reused session requires a new cursor-0 subscription.
- Do not weaken tests, schemas, evidence binding, timeout/cancellation boundaries, package audits, or security gates to obtain green output.
- Do not raise the five-minute npm child timeout. Preserve the exact package smoke; improve only its closed, redacted failure classification.
- GitHub remains experimental until its exact-artifact two-runtime private-repository proof and cleanup pass. Gmail remains deferred until the approved GitHub live gate, Google Desktop OAuth/restricted-scope test accounts, and real arm64 macOS Keychain spike pass.
- Echo remains the only stable integration. Do not change `kaji/contracts/beta-core-v1.json` integration promotion markers in this work.
- Generated evidence and artifacts remain untracked under `.artifacts/`. Never commit provider keys, OAuth material, participant receipts, package archives, benchmark samples, or publication credentials.
- Use GitButler for all version-control inspection and writes. Preserve the user-owned `AGENTS.md` change and all unrelated applied branches.
- Work belongs on `feat/beta-release`. Because the current workspace contains relevant commits above the pushed target, do not move, squash, or rewrite those shared commits without explicit user authorization. If a checkpoint cannot be assigned to `feat/beta-release` without changing another branch's ownership, stop at that checkpoint and request the GitButler topology decision.
- Do not push, tag, publish, create a release, or alter repository rulesets/environments/runners in this implementation. Those actions require separate authorization and/or operator access.

---

## Confirmed Causal Baseline

The 2026-07-22 investigation classified every recent report before this plan was written.

Git baseline: remote and local target `feat/beta-release` both resolved to `090f5a8f3e046c1f277830d40daa3c673b7c048b` during the audit; the GitButler workspace also contained relevant applied commits above that target. Re-read GitButler status before every checkpoint and never infer ownership from the composite workspace HEAD.

| Report | Classification | Current evidence and treatment |
|---|---|---|
| Reused closed sessions return empty turns | Current product defect, P0 | Both SDKs silently evict a closed log while independent projectors, subscribers, and idempotency entries retain the old generation. Fix in Tasks 1-4. |
| Python `ty` reported 71, 5, or 279 diagnostics | Stale/closed report | Canonical `uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise` and `cd kaji && .venv/bin/ty check --output-format concise` both pass. Non-project invocations analyze the wrong workspace. No type-repair task. |
| npm package smoke timed out | Environmental/infrastructure blocker plus narrow tooling defect | The failure occurs at registry-backed `npm:package-install` before package execution; the same tarball later passed npm and Bun. Keep behavior/timeout, add redacted `failedPhase` and `failureKind` in Task 8. |
| TypeScript installed-proof v5 is rejected by release normalizers | Current test/tooling defect | `smoke_package.mts` emits schema v5/15 scenarios plus closed recovery/observability fields; four rehearsal/publish normalizers, the retained-evidence validator, and fixtures still require v4/14. Align consumers in Task 8; never downgrade the producer. |
| GitHub Actions PR failures | Environmental/infrastructure blocker | Jobs had no runner, no steps, and a spending-limit annotation. Source jobs did not fail. No test weakening or CI workaround. |
| Workflow filename/display/job naming | Stale/closed report | Five workflow display names and 30 job names are locked by tests. Preserve the protected check identity `beta release gate`; Task 8 changes receipt normalization only. |
| GitHub/Gmail integration plan | GitHub shared/offline work complete; Gmail externally gated | GitHub registry, ABI, client/tools, OAuth/Keychain primitives, structural rules, parity, idempotency, observability, and quick benchmark landed. Gmail runtime/ABI/live proof did not. Task 9 adds narrow GitHub exact-artifact comment proof only; Gmail stays held. |
| TTHW requires macOS plus Linux | Current release-contract defect | Approved claim is arm64 macOS only, but schema/validator/docs encode mixed OS and omit architecture/version. Fix in Task 6. |
| Protected performance targets Linux/x64 | Current workflow/release-contract defect | Benchmark, rehearsal, and publish performance jobs contradict the approved platform. Fix source labels and runtime fingerprint enforcement in Task 7. |
| Three format-check failures | Current test/tooling defect | Ruff would reformat two Python test files; oxfmt would reformat one TypeScript test. Mechanical closure in Task 0. |
| Baseline/full benchmark/30-minute soak/keyed providers/TTHW | Missing protected/external evidence | Keep as operator evidence in Task 10. Do not fabricate local receipts. |
| Signed tag/provenance/publication/registry bytes | Missing protected/external evidence | Existing protected workflows retain the source-level path; immutable actions remain separately authorized Task 10 work. |
| Required status check | Environmental/configuration blocker | Repository ruleset currently has no required Kaji context. Operator must require exact context `beta release gate` after hosted capacity returns. |

### Causal code pointers

| Boundary | Current code that proves the gap |
|---|---|
| Python silent eviction | `kaji/src/kaji/infra/events/store/inmem.py:150-161` deletes a closed retained session and IDs during admission; `runtime/agents/runtime.py:471-675` owns an independent projector generation. |
| TypeScript unsafe purge/eviction | `kaji/ts/src/events/store.ts:341-384` directly deletes listeners/history and silently evicts; `runtime/runtime.ts:90-234,688-720` fences only runtime-owned work and always reopens after post-delete cleanup. |
| Subscriber/outbox generation | `kaji/src/kaji/infra/events/journal.py:49-327,386-700` and `kaji/ts/src/events/committer.ts:216-554` keep delivery state outside store history; split pending entries have no generation identity. |
| Ledger generation | Python `runtime/tools/idempotency.py:105,343-352` releases only completed entries; TypeScript `tools/idempotency.ts:26-35,167-175` has settled cleanup but no post-delete tombstone protects it. |
| Broken release guide | `docs/kaji/tthw-evidence.md:92,107,171` uses the wrong provider alias twice and one stale Python terminal assertion; `kaji/tests/test_docs_sync.py:73-91` passes because it checks literals, not execution. |
| CLI contract drift | `docs/kaji/cli.md:34-38` and `apps/docs/content/cli.mdx:76-79` omit exits 3-6; `kaji/ts/src/cli/add.ts:35-76,150-153` returns 1/stdout for malformed usage. |
| Misleading expected failure | `kaji/ts/src/tools/execution.ts:501-508` logs every handler rejection as internal even when it is an already-normalized `ToolExecutionError`. |
| Protected platform drift | `.github/workflows/kaji.benchmark.yml:81,132,179`, `kaji.rehearsal.yml:80-86`, and `kaji.publish.yml:152-158` select Linux/x64 and trust a configured `IMAGE_DIGEST`. |
| Package evidence drift | `kaji/ts/scripts/smoke_package.mts:90-221,1046-1116` emits v5/15 plus recovery/observability, while `validate_release_evidence.py:164-293` and rehearsal/publish normalizers still require v4/14. |
| Premature package success | `kaji/ts/scripts/smoke_package.mts:1678-1725,1854-1870,2664-2695` emits pass before top-level workspace cleanup. |

## What Already Exists

- The TypeScript runtime already has owner registration, busy fencing, cache clearing, explicit runtime purge, and settled-ledger cleanup. Tasks 1-3 move the lifecycle primitive to the event boundary, fence public store operations, close the direct-store bypass, and port the model to Python. They also correct two gaps in the current TypeScript design: a post-delete ledger failure currently reopens the generation, and split delivery can retain old-generation outbox work.
- Both event stores already serialize per-session mutation lanes and track listeners/ID indexes. Task 1 removes only implicit admission-time deletion and reuses those lanes for physical purge.
- `installed_release_runtime.py`, `verify_release_artifacts.py`, `release_smoke.py`, and `smoke_package.mts` already prove installed wheel/sdist/npm identities. Tasks 5, 8, and 9 extend/reuse them instead of creating another package loader.
- `beta_release_check.py`, `run_beta_benchmarks.py`, `run_beta_soak.py`, `live_provider_proof.py`, `validate_tthw_evidence.py`, and the current rehearsal/publish workflows already define the one-artifact-set release flow. This plan aligns their platform and evidence contracts; it does not replace them with a second candidate pipeline.
- The canonical integration manifest/ABI synchronizers, offline gate, 42 ast-grep rules, 67 parity scenarios, GitHub registry/client/tools, fixed-origin requester, OAuth/Keychain primitives, idempotency tests, observability tests, and quick integration benchmark are already green. Task 9 adds only the missing installed-artifact live-proof/cleanup boundary.
- Installed wheel/tarball mock quickstarts and the no-credential GitHub recovery tuple work. The checked-in TTHW Echo guide does not: it calls `echo.say` instead of the registered `echo_say` alias in both SDKs, and its Python expected text is stale. Task 5 makes release-critical snippets executable instead of treating prose sync as proof.

## NOT in Scope

- A second two-clone candidate-bundle/readiness system is deferred. The existing protected one-artifact-set fan-out, tag verification, SBOM/provenance, publication, and byte-verification workflow remains authoritative; adding a parallel release architecture is not required to close the confirmed beta defects.
- Gmail runtime, ABI, registry bundle, MIME/send tools, and live proof remain deferred behind the approved GitHub-live, Google Desktop OAuth/restricted-scope test-user, and arm64 macOS Keychain stop/go prerequisites.
- GitHub promotion to beta is not performed. Task 9 supplies the proof machinery; only real exact-artifact private-repository proof and cleanup can authorize a later marker change.
- Benchmark calibration, full benchmark, 30-minute soak, four keyed provider cells, five-user TTHW, signed tag, SBOM/provenance generation, publication, and registry byte verification are operator evidence, not local implementation substitutes.
- An installed-artifact integration microbenchmark is deferred. The current benchmark driver intentionally uses source/test seams that are not public package exports; packaging those internals would expand the SDK. The existing source quick benchmark remains a regression gate, while Task 9 proves installed GitHub semantics.
- Required status-check configuration, Actions billing, runner registration, repository environments, and secrets are repository/operator configuration and are not mutated here.
- Distributed session coordination, durable purge across processes, encrypted host storage, exactly-once external effects, and cross-platform performance claims remain outside the embedded arm64 macOS beta boundary.

## Lifecycle State and Failure Flow

```text
new turn / append
  -> store-scoped operation fence
  -> session coordinator + projector
  -> append-only retained log
  -> release operation fence

new session at capacity
  -> EventStoreCapacityError
  -> host drains named session
  -> runtime.purge_session / runtime.purgeSession
       -> acquire store-scoped purge fence
       -> preflight every shared runtime owner and delivery/ledger capability
       -> reject queued turn / active projection / provider quarantine / running tool
       -> terminate old-generation subscribers
       -> issue one opaque physical-purge authorization
       -> require zero raw listeners; delete events + ID index
       -> clear every owner's projectors/locks/collectors/diagnostics/quarantine
       -> delete completed + unknown idempotency entries
       -> clear cleanup_pending only after every ledger succeeds
       -> release fence
  -> reused ID starts at sequence 1 with session.created

direct store purge while a runtime is registered
  -> SessionPurgeBusyError / explicit runtime-purge-required error

direct store purge with a standalone live subscription
  -> SessionPurgeBusyError; iterator stays valid; caller closes it and retries

ledger failure after physical deletion
  -> cleanup_pending tombstone remains
  -> every session operation rejects
  -> runtime purge retry skips deletion and retries owner cleanup
  -> tombstone clears only on convergence
  -> no mutation
```

Add the compact fence/order diagram as an inline comment in the new shared lifecycle module. The docs carry the user-facing version; runtime/store files should link to the shared helper rather than duplicate the full diagram.

### Smallest discriminating lifecycle repro

Run from the repository root before Task 1. Both commands currently print empty text, zero returned events, and no `session.created` for the reused session.

```bash
uv run --project kaji python - <<'PY'
import asyncio
from kaji.infra.events.schemas import SessionClosed
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents import AgentBuilder
from kaji.runtime.providers.mock import MockProvider

async def main() -> None:
    store = InMemoryEventStore(max_sessions=2)
    runtime = AgentBuilder().provider(MockProvider(reply="ok")).build(store=store)
    for session_id in ("a", "b"):
        await runtime.turn("first", session_id=session_id)
        await runtime.append_event(SessionClosed(session_id=session_id))
    await runtime.history("a")
    await runtime.turn("first", session_id="c")
    result = await runtime.turn("second", session_id="b")
    print(result.text, len(result.events), [event.type.value for event in await runtime.history("b")])

asyncio.run(main())
PY

cd kaji/ts
bun - <<'TS'
import { AgentBuilder, EventType, InMemoryEventStore, KajiEvent } from "./src/index.ts";
import { MockProvider } from "./src/testing.ts";

const store = new InMemoryEventStore({ maxSessions: 2 });
const runtime = new AgentBuilder().provider(new MockProvider({ reply: "ok" })).build({ store });
for (const sessionId of ["a", "b"]) {
  await runtime.turn("first", { sessionId });
  await runtime.appendEvent(KajiEvent.parse({ type: EventType.SESSION_CLOSED, session_id: sessionId }));
}
await runtime.history("a");
await runtime.turn("first", { sessionId: "c" });
const result = await runtime.turn("second", { sessionId: "b" });
console.log(result.text, result.events.length, (await runtime.history("b")).map((event) => event.type));
TS
```

Expected RED before implementation: the third session is admitted by silently deleting `b`; reuse is corrupted.

Expected GREEN after Task 4: the attempt to admit `c` raises `EventStoreCapacityError`; after `await runtime.purge_session("b")` / `await runtime.purgeSession("b")`, reuse of `b` begins with `session.created` at sequence 1 and returns `ok`.

## File Responsibility Map

| File or group | Responsibility |
|---|---|
| `kaji/src/kaji/infra/events/store/{base,inmem}.py`, `kaji/ts/src/events/{protocols,store}.ts` | Fail-closed retained-session capacity, public store-operation fencing, and explicit store purge capability. |
| `kaji/src/kaji/infra/events/session_lifecycle.py`, `kaji/ts/src/events/session-lifecycle.ts` | Store-scoped runtime-owner registry, operation/purge authorization fences, and direct-store bypass prevention. |
| `kaji/src/kaji/runtime/agents/runtime.py`, `kaji/ts/src/runtime/runtime.ts` | Runtime owner callbacks, busy preflight, cache cleanup, and the only supported purge entry point while runtimes are registered. |
| `kaji/src/kaji/infra/events/journal.py`, `kaji/ts/src/events/committer.ts` | Terminate old-generation subscribers; reject split/outbox delivery as purge-unsafe. |
| `kaji/src/kaji/runtime/tools/{execution,idempotency}.py`, TypeScript equivalents | Detect active session work and release completed/unknown state without deleting running claims. |
| `kaji/contracts/{beta-core-v1,feature-tiers-v1}.json` plus package copies | Machine-readable cross-SDK lifecycle contract and public-surface parity. |
| TTHW/Getting Started/CLI docs plus executable-snippet and CLI tests | A no-key first success, runnable Echo guide, and cross-SDK exit-code contract. |
| `kaji/contracts/release/tthw-*`, composer/validator/tests/docs | Exact-commit, exact-artifact five-user arm64 macOS evidence contract. |
| `benchmark_platform.py`, `beta_benchmark_gate.py`, `validate_release_evidence.py`, performance workflows | Enforce protected Darwin/arm64/macOS-version/bootstrap-manifest provenance. |
| `smoke_package.mts`, command helper, package tests, and rehearsal/publish workflows | Closed, redacted package-smoke failure phase/kind, including terminal cleanup. |
| `github-proof-v1.schema.json`, `live_github_proof.py`, `github_proof_cleanup.py` | Installed-artifact GitHub comment proof with separate private cleanup state; no Gmail implementation. |
| `.github/workflows/kaji.rehearsal.yml`, `.github/workflows/kaji.publish.yml` | Existing one-artifact-set protected evidence and publication chain; only platform/fingerprint alignment changes here. |

## Dependency Order

1. Task 0 is mechanical and independent.
2. Tasks 1-3 are one atomic runtime lane. Do not checkpoint or expose a partially coordinated purge between them.
3. Task 4 freezes the lifecycle contract only after the full runtime lane is green.
4. Task 5 closes executable DevEx contracts before collecting human evidence.
5. Tasks 6-8 are release-contract hardening; Tasks 6 and 7 may proceed in parallel after Task 5.
6. Task 9 depends on Tasks 4, 7, 8, and the existing installed-runtime harness.
7. Task 10 is final QA/operator handoff and begins only from a clean, reviewed, exact commit.

## Engineering Test Coverage Map

```text
CODE PATHS                                                   OPERATOR / DEVELOPER FLOWS
[+] retained-session admission                              [+] bounded in-memory host
  +-- [*** PLANNED] existing session below event cap          +-- [*** PLANNED] close -> capacity error -> purge -> reuse
  +-- [*** PLANNED] new session below session cap              +-- [*** PLANNED] direct store purge rejected with runtime
  +-- [*** PLANNED] new session at cap -> typed error           +-- [*** PLANNED] cursor reset and fresh subscription
  +-- [*** PLANNED] invalid/absent/retained store purge
[+] store-scoped purge fence                                [+] shared-runtime teardown
  +-- [*** PLANNED] every public store op is fenced             +-- [*** PLANNED] every owner cache cleared
  +-- [*** PLANNED] register/operate while purging -> busy      +-- [*** PLANNED] every operation blocked during tombstone
  +-- [*** PLANNED] concurrent direct purge lacks lease         +-- [*** PLANNED] cancellation cannot strand stale caches
  +-- [*** PLANNED] standalone live listener blocks raw purge    +-- [*** PLANNED] ledger failure blocks reuse until retry
  +-- [*** PLANNED] queued turn/projection/quarantine -> busy   +-- [*** PLANNED] running tool blocks destructive work
  +-- [*** PLANNED] unsupported store/delivery/ledger           +-- [*** PLANNED] host-ledger failure is visible/retryable
  +-- [*** PLANNED] one subscriber close rejects -> no delete   +-- [*** PLANNED] old iterator ends; new iterator sees seq 1
  +-- [*** PLANNED] store delete then ledger reject             +-- [*** PLANNED] split outbox can never cross generations
[+] executable DevEx contracts                             [+] first-run developer path
  +-- [*** PLANNED] Python + TS TTHW snippets execute           +-- [*** PLANNED] no-key mock first, provider second
  +-- [*** PLANNED] documented CLI exits 0-6                    +-- [*** PLANNED] malformed usage exits 2 in both SDKs
  +-- [*** PLANNED] expected GitHub auth is not "internal"      +-- [*** PLANNED] recovery tuple stays redacted and closed
[+] macOS evidence validation                              [+] release operator
  +-- [*** PLANNED] candidate/artifact-bound 5 users            +-- [*** PLANNED] Python/npm/Bun participant coverage
  +-- [*** PLANNED] Linux/x64/missing/empty/stale reject        +-- [*** PLANNED] actionable wrong-runner failure
  +-- [*** PLANNED] Darwin/arm64/version/manifest checks        +-- [*** PLANNED] no protected claim from local-unpinned run
[+] package smoke failure receipt                          [+] install troubleshooting
  +-- [*** PLANNED] timeout/exit/output/start/cleanup kinds     +-- [*** PLANNED] identify registry timeout without leakage
  +-- [*** PLANNED] unknown/setup failure normalization         +-- [*** PLANNED] same exact tarball rerun, no timeout increase
[+] GitHub exact-artifact proof                           [+] experimental integration promotion gate
  +-- [*** PLANNED] wrong commit/hash/source path reject         +-- [*** PLANNED] approval reject touches no transport
  +-- [*** PLANNED] Python + TypeScript installed cells          +-- [*** PLANNED] read -> approved write -> readback -> cleanup
  +-- [*** PLANNED] ambiguous mutation never auto-retries        +-- [*** PLANNED] any live/cleanup failure keeps experimental
  +-- [*** PLANNED] canary/token/content/oversize reject

QUALITY: all changed branches have behavior + edge + failure assertions planned.
E2E: installed-artifact DevEx and live GitHub proof are end-to-end boundaries.
EVAL: none; no prompts, model policies, or tool descriptions change.
```

Legend: `***` = behavior, edge, and error coverage. The P0 lifecycle cases are regression tests and cannot be removed or converted to source-shape assertions.

## Production Failure Modes

| Codepath | Realistic failure | Test | Error/recovery visible to host |
|---|---|---|---|
| Capacity admission | All retained slots are full | Store tests in both SDKs | Typed `EventStoreCapacityError` names explicit purge recovery; no deletion. |
| Purge fence | A queued turn or direct store operation starts between drain and purge | Runtime/store concurrency tests | `SESSION_PURGE_BUSY`; host can re-drain/fence and retry. |
| Physical authorization | A direct store caller races the legitimate purge while its store await is pending | Opaque-lease concurrency tests in both SDKs | Direct caller is rejected; only the lease holder may delete the generation. |
| Python cancellation | Caller cancellation arrives after store deletion begins | Cancellation-injection runtime test | Irreversible cleanup finishes, then cancellation is re-raised; no stale cache generation survives. |
| Shared owners | A sibling runtime retains an old projector | Shared-store regression tests | All owners clear; reuse begins at sequence 1. |
| Subscriber teardown | One delivery wrapper refuses to close | Multi-owner close-failure tests | Purge rejects before event deletion; host repairs delivery and retries. |
| Standalone subscriber | Store-only purge is attempted while an iterator is blocked | Store/journal integration tests | Purge rejects without deleting or orphaning the iterator; close then retry succeeds. |
| Tool ledger | A handler is running or outcome is unknown | Busy and settled-ledger tests | Running blocks; settled unknown is cleared only by explicit purge. |
| Split delivery | A pending outbox event survives a purge and publishes into a reused sequence | Unsupported-capability regression tests | Purge rejects `event_delivery` before deletion; split delivery is not purge-capable in beta. |
| Host ledger cleanup | External cleanup rejects after event deletion | Post-delete ledger-failure and concurrent-operation tests | Error is surfaced as irreversible/retryable; a strongly retained `cleanup_pending` target blocks turn/store/subscribe/register until recovery succeeds. |
| TTHW guide | A copied Echo snippet uses the manifest name rather than the registered alias | Extracted-snippet installed tests | Docs gate fails until both snippets return the documented mock output. |
| TTHW | A Linux/x64/stale/foreign-artifact receipt is submitted | Schema/composer hostile fixtures | JSON pointer identifies invalid evidence; protected gate remains blocked. |
| Benchmark | Runner labels or digest assertion lie about the host | Runtime fingerprint/file-hash tests | Protected gate rejects non-Darwin/non-arm64/bad version/symlinked or mismatched bootstrap manifest. |
| npm smoke | Registry install hangs | Injected timeout receipt test | `failedPhase=npm:package-install`, `failureKind=timeout`; no child output leaked. |
| GitHub proof | Comment mutation outcome is ambiguous or cleanup fails | Orchestrator/private-state cleanup hostile fixtures | Bounded reconciliation touches only the designated private issue; no automatic mutation retry; integration stays experimental. |

No planned path has an untested, unhandled, silent failure.

## Parallelization Strategy

| Lane | Modules | Depends on |
|---|---|---|
| A: lifecycle | `kaji/src/kaji/{infra/events,runtime}`, `kaji/ts/src/{events,runtime,tools}` | - |
| B: formatting | Python/TypeScript release tests | - |
| C: executable DevEx | TTHW/Getting Started/CLI docs and tests | A contract checkpoint |
| D: macOS contracts | `kaji/contracts/release`, TTHW scripts/tests/docs | C executable guide |
| E: performance/smoke | benchmark scripts, workflows, release tests, package smoke | A before installed-artifact final gate |
| F: GitHub proof | release contracts/scripts/tests/docs | A + E installed-runtime identity |
| G: final QA | all Kaji gates and installed artifacts | A-F |

Implementation runs A sequentially because store, runtime, delivery, and ledger changes share one lifecycle state and are committed atomically. B may run immediately. C follows the lifecycle docs checkpoint. After C, D and the package-smoke portion of E may run in parallel; workflow/contract synchronization is serialized through one owner. F waits for the settled runtime and installed-runtime identity. G runs after every lane joins. Agents share one working directory, so no lane may concurrently format or synchronize the same contract/workflow files.

## Implementation Tasks from Engineering Review

- [ ] **T1 (P1)** - lifecycle - Remove implicit eviction and enforce one coordinated purge generation boundary.
  - Surfaced by: architecture review - direct store deletion and independent caches can corrupt reused sessions.
  - Files: event stores, shared lifecycle modules, runtimes, delivery, idempotency, mirrored tests.
  - Verify: Tasks 1-4 focused gates plus full parity/contract checks.
- [ ] **T2 (P1)** - release platform - Bind TTHW and protected performance evidence to arm64 macOS at schema, runtime, and workflow boundaries.
  - Surfaced by: architecture review - current Linux/x64 evidence contradicts the approved beta claim.
  - Files: TTHW contracts/scripts/docs/tests, benchmark scripts, three workflows, release-security tests.
  - Verify: Tasks 6-7 commands.
- [ ] **T3 (P2)** - release diagnostics - Preserve closed package-smoke phase/kind without changing behavior or timeouts.
  - Surfaced by: code-quality review - console-only phase collapses environmental and product failures in retained receipts.
  - Files: `smoke_package.mts` and compatibility receipt tests/normalizers.
  - Verify: Task 8 commands.
- [ ] **T4 (P1)** - integration evidence - Add installed-artifact GitHub proof and cleanup while keeping Gmail and promotion gated.
  - Surfaced by: architecture review - offline/package coverage cannot prove real fixed-origin remote behavior.
  - Files: one closed release schema, two scripts, focused tests, docs/matrix.
  - Verify: Task 9 deterministic suite; live run remains protected operator evidence.
- [ ] **T5 (P2)** - quality - Format the three failing release test files and run the full local/DevEx/Ponytail gates.
  - Surfaced by: code-quality/test review - canonical format gate is currently red on test-only files.
  - Files: three formatter-owned files plus no generated evidence.
  - Verify: Tasks 0 and 10 commands.
- [ ] **T6 (P1)** - DevEx contract - Make the release-critical TTHW and Getting Started snippets executable and align CLI/error contracts.
  - Surfaced by: empirical DevEx review - both installed SDKs reject the documented `echo.say` tool, Python expected output is stale, CLI exits drift, and the prose-only docs gate misses all of it.
  - Files: public docs, snippet runner/tests, TypeScript CLI parse boundary, integration error diagnostic tests.
  - Verify: Task 5 commands plus the repeated installed-artifact DevEx scenario in Task 10.

---

### Task 0: Close the Mechanical Format Gate

**Files:**

- Modify mechanically: `kaji/tests/test_release_task15.py`
- Modify mechanically: `kaji/tests/test_ts_handoff.py`
- Modify mechanically: `kaji/ts/tests/release-security.test.ts`

**Interfaces:**

- Consumes: current Ruff and oxfmt configuration.
- Produces: byte-format compliance only; no assertion, fixture, workflow, or runtime semantics change.

- [ ] **Step 1: Capture the three-file RED baseline.**

```bash
uv run --project kaji --no-sync ruff format --check kaji/src kaji/tests
cd kaji/ts && bun run format:check
```

Expected: Ruff identifies exactly two test files; oxfmt identifies exactly one test file.

- [ ] **Step 2: Apply only the configured formatters.**

```bash
uv run --project kaji --no-sync ruff format kaji/tests/test_release_task15.py kaji/tests/test_ts_handoff.py
cd kaji/ts && bunx oxfmt --write tests/release-security.test.ts
```

- [ ] **Step 3: Prove semantics and formatting.**

```bash
uv run --project kaji --no-sync pytest -q kaji/tests/test_release_task15.py kaji/tests/test_ts_handoff.py --no-cov
cd kaji/ts && bun run test tests/release-security.test.ts && bun run format:check
```

Expected: focused tests pass and both format checks exit 0.

- [ ] **Step 4: GitButler checkpoint.**

Commit only the three formatter-owned hunks to `feat/beta-release` with:

```text
style(kaji): normalize release gate fixtures
```

---

### Task 1: Replace Silent Session Eviction with Fail-Closed Capacity

**Files:**

- Modify: `kaji/src/kaji/infra/events/store/inmem.py`
- Modify: `kaji/ts/src/events/store.ts`
- Test: `kaji/tests/test_events_store.py`
- Test: `kaji/ts/tests/store.test.ts`

**Interfaces:**

- Consumes: `EventStoreCapacityError` and session-scoped store lanes.
- Produces: fail-closed admission only; capacity never deletes history implicitly. This is the first slice of one atomic Tasks 1-3 lifecycle checkpoint; do not commit or expose the intermediate TypeScript raw-purge behavior.

- [ ] **Step 1: Replace the old LRU tests with RED lifecycle tests.**

Python test body:

```python
@pytest.mark.asyncio
async def test_closed_session_requires_explicit_purge_before_capacity_reuse() -> None:
    store = InMemoryEventStore(max_sessions=1)
    await store.append(UserMessage(session_id="old", content="one"))
    await store.append(SessionClosed(session_id="old"))
    await store.get_events("old")

    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="new", content="two"))

    assert [event.sequence for event in await store.get_events("old")] == [1, 2]
    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="new", content="two"))
```

TypeScript test body:

```ts
it("requires explicit purge before reusing retained session capacity", async () => {
  const store = new InMemoryEventStore({ maxSessions: 1 });
  await store.append(userMessage("old", "one", 1));
  await store.append(KajiEvent.parse({ type: EventType.SESSION_CLOSED, session_id: "old" }));
  await store.getEvents("old");

  await expect(store.append(userMessage("new", "two", 2))).rejects.toBeInstanceOf(
    EventStoreCapacityError,
  );
  expect((await store.getEvents("old")).map((event) => event.sequence)).toEqual([1, 2]);
  await expect(store.append(userMessage("new", "two", 2))).rejects.toBeInstanceOf(
    EventStoreCapacityError,
  );
});
```

- [ ] **Step 2: Run RED tests.**

```bash
uv run --project kaji --no-sync pytest -q kaji/tests/test_events_store.py -k "explicit_purge or capacity" --no-cov
cd kaji/ts && bun run test tests/store.test.ts -t "explicit purge"
```

Expected: Python lacks `purge_session`; both old implementations admit `new` by deleting `old`.

- [ ] **Step 3: Implement fail-closed admission.**

Python `_insert_reserved()` must use:

```python
if is_new_session:
    async with self._metadata_lock:
        if len(self._events) >= self.max_sessions:
            raise EventStoreCapacityError(
                draft.session_id,
                f"all {self.max_sessions} session slots are retained; purge one explicitly",
            )
        self._events[draft.session_id] = bucket
```

Delete `_evict_closed_session()` and all read-driven `move_to_end()` calls. Do not add a partial Python purge in this task; Tasks 2-3 add it with listener checks, opaque authorization, and the cleanup-pending fence before one atomic checkpoint.

TypeScript `admitSession()` becomes:

```ts
private admitSession(sessionId: string): void {
  if (this.sessions.size < this.maxSessions) return;
  throw new EventStoreCapacityError(
    sessionId,
    `Cannot admit session ${sessionId}; ${this.maxSessions} session slots are retained; purge one explicitly`,
  );
}
```

Remove `SessionLog.closed`, `SessionLog.lastAccess`, `clock`, and read-driven access mutation. Leave the existing TypeScript `purgeSession()` behavior untouched until Task 2 hardens it.

- [ ] **Step 4: Run GREEN store tests.**

```bash
uv run --project kaji --no-sync pytest -q kaji/tests/test_events_store.py --no-cov
cd kaji/ts && bun run test tests/store.test.ts
```

- [ ] **Step 5: Hold the lifecycle lane open.**

Do not checkpoint yet. Tasks 2-3 complete the public operation fence, authorized physical delete, delivery shutdown, cleanup tombstone, and ledger release. Review and commit the lifecycle lane only after Task 3 is green.

---

### Task 2: Add a Cross-SDK Store Fence and Authorized Physical Purge

**Files:**

- Modify: `kaji/src/kaji/infra/events/store/{base,inmem,__init__}.py`
- Modify: `kaji/src/kaji/infra/events/{__init__,errors}.py`
- Create: `kaji/src/kaji/infra/events/session_lifecycle.py`
- Modify: `kaji/ts/src/events/{protocols,store,errors}.ts`
- Create: `kaji/ts/src/events/session-lifecycle.ts`
- Modify: `kaji/src/kaji/runtime/agents/runtime.py`
- Modify: `kaji/src/kaji/runtime/agents/__init__.py`
- Modify: `kaji/src/kaji/__init__.py`
- Modify: `kaji/ts/src/runtime/{runtime,errors}.ts`
- Test: `kaji/tests/test_events_store.py`
- Test: `kaji/tests/test_runtime_turn.py`
- Test: `kaji/ts/tests/store.test.ts`
- Test: `kaji/ts/tests/runtime-turn.test.ts`

**Interfaces:**

The public capability remains the ordinary one-argument protocol already expected by custom stores:

```python
@runtime_checkable
class PurgeableEventStore(EventStore, Protocol):
    async def purge_session(self, session_id: str) -> bool: ...

def supports_session_purge(store: EventStore) -> TypeGuard[PurgeableEventStore]: ...
```

Runtime-coordinated deletion uses a separate internal capability, never a widened public signature:

```python
class CoordinatedPurgeableEventStore(Protocol):
    async def _purge_session_authorized(
        self, session_id: str, authorization: SessionPurgeAuthorization
    ) -> bool: ...
```

TypeScript uses a module-private/non-barrel-exported `unique symbol` method for the same internal capability. A custom store implementing only `purgeSession(sessionId)` remains valid for store-only use; `AgentRuntime.purgeSession()` rejects it with `component="event_store"` because it cannot prove coordinated deletion.

`SessionPurgeUnsupportedError.component` is the closed union `event_store | event_delivery | tool_idempotency_ledger`. `SessionPurgeBusyError.code` remains `SESSION_PURGE_BUSY`. Errors and authorization live at the neutral event boundary; event modules never import the runtime package.

- [ ] **Step 1: Add RED operation and authorization races.**

In both SDKs, hold each public store operation in the session lane and race purge against it: append, event read, last-event read, transaction, and listener/subscription registration. Purge must reject or wait according to the existing nonblocking contract without deleting the active generation. Also test:

- direct store purge with a registered runtime rejects before mutation;
- while legitimate runtime purge is paused in the physical store lane, a direct caller cannot borrow the global `purging` state;
- an internal authorization is identity-scoped to one store, session, active lease, and one physical deletion;
- a public one-argument custom store is supported for direct teardown but rejected by runtime purge as `event_store`.

- [ ] **Step 2: Build one event-layer lifecycle registry.**

Move the existing TypeScript owner/fence state out of `runtime.ts` and port it to Python. Use a weak store registry during ordinary operation. Each session state contains:

```text
active_operations
quarantined_providers
purging
active_authorization
cleanup_pending
cleanup_targets
```

The public operations are:

```python
def register_runtime_owner(store: EventStore, owner: StoreRuntimeOwner) -> Callable[[], None]: ...
def register_purge_blocker(
    store: EventStore, blocker: StorePurgeBlocker
) -> Callable[[], None]: ...

@contextmanager
def store_session_operation(store: EventStore, session_id: str) -> Iterator[None]: ...

@contextmanager
def authorized_session_teardown(
    store: EventStore, session_id: str, authorization: SessionPurgeAuthorization
) -> Iterator[None]: ...

@contextmanager
def store_session_purge(store: EventStore, session_id: str) -> Iterator[StoreSessionPurgeLease]: ...

def assert_physical_purge_authorized(
    store: EventStore, session_id: str, authorization: SessionPurgeAuthorization
) -> None: ...

def mark_physical_purge_committed(lease: StoreSessionPurgeLease) -> None: ...
def finish_session_cleanup(lease: StoreSessionPurgeLease) -> None: ...
```

Ordinary runtime owners and delivery blockers are weak. A blocker reports one closed unsupported component without becoming a cache-cleanup owner. Once `mark_physical_purge_committed()` runs, copy all cleanup owners into `cleanup_targets` as strong references and set `cleanup_pending` synchronously before the physical store method returns. This tombstone outlives the initiating runtime/caller. Owner/blocker registration, new turns, all public store reads/writes/transactions, new subscriptions, and store-only purge reject while it exists. A recovery purge obtains the retained cleanup targets, skips physical deletion, retries cache/ledger convergence, and alone may call `finish_session_cleanup()`. `authorized_session_teardown()` is the only operation admitted while `purging`; it accepts the same opaque lease solely so supported delivery can detach listeners before physical deletion. It cannot append/read/delete events or be called by public transaction APIs.

- [ ] **Step 3: Fence the in-memory stores, not just runtimes.**

Wrap every session-specific public store path in `store_session_operation()`. `InMemoryEventStore.purge_session(session_id)` acquires a store-only purge lease, requires no registered runtime owners and no live raw listener, invokes the internal authorized method, marks the physical commit, and immediately finishes cleanup because it has no runtime targets. The internal method validates the exact lease object in the session lane, deletes events/ID indexes, marks the tombstone in the same critical section, and returns. It never accepts `authorization=None` and never checks only a boolean.

- [ ] **Step 4: Coordinate runtime purge and cancellation.**

Runtime purge first requires the internal guarded store capability, captures all shared owners, validates delivery and ledger support, checks runtime/tool/provider activity, and closes supported subscriptions. Only then may it invoke the internal physical method. After physical commit it clears all owner caches synchronously, releases settled ledgers asynchronously, and clears the tombstone only when all owners converge.

Python puts only the irreversible phase in a child task and survives repeated cancellation:

```python
commit = asyncio.create_task(self._finish_irreversible_purge(session_id, lease))
cancelled = False
while not commit.done():
    try:
        await asyncio.shield(commit)
    except asyncio.CancelledError:
        cancelled = True
result = commit.result()  # convergence failure outranks cancellation
if cancelled:
    raise asyncio.CancelledError
return result
```

TypeScript uses the same lease/tombstone order without a cancellation shim because promises have no ambient task-cancellation injection.

- [ ] **Step 5: Add post-delete recovery RED/GREEN tests.**

Inject a ledger rejection after physical deletion. Assert the events are gone but `turn`, `append`, `getEvents`, `subscribe`, owner registration, and direct purge all return the busy/tombstone error. Drop external references to one owner and force GC where supported; the cleanup target must remain retained. A second runtime purge skips deletion, retries the idempotent cache/ledger work, clears the tombstone, and permits reuse beginning at sequence 1. Inject cancellation after deletion and prove the same convergence completes before `CancelledError` is re-raised.

- [ ] **Step 6: Run the focused store/runtime gates.**

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_events_store.py \
  kaji/tests/test_runtime_turn.py -k "purge or capacity or cleanup_pending or operation" --no-cov
cd kaji/ts && bun run test \
  tests/store.test.ts \
  tests/runtime-turn.test.ts -t "purge|capacity|cleanup pending|operation"
```

Do not checkpoint yet; delivery and idempotency in Task 3 are part of this same generation boundary.

---

### Task 3: Close Subscriber, Outbox, and Idempotency Generations

**Files:**

- Modify: `kaji/src/kaji/infra/events/journal.py`
- Modify: `kaji/ts/src/events/committer.ts`
- Modify: `kaji/src/kaji/runtime/tools/{idempotency,execution}.py`
- Modify: `kaji/ts/src/tools/{idempotency,execution}.ts`
- Modify: lifecycle/runtime files from Task 2 as required by the final owner capability
- Test: `kaji/tests/test_events_journal.py`
- Test: `kaji/ts/tests/event-delivery.test.ts`
- Test: `kaji/tests/test_runtime_faults.py`
- Test: `kaji/ts/tests/runtime-faults.test.ts`

**Interfaces:**

- Stable in-memory delivery exposes an internal owner hook `close_session_subscriptions(session_id, authorization)` / `closeSessionSubscriptions(sessionId, authorization)` and completes pending iterators normally. The opaque token is not added to the public store protocol.
- Split journal/committer delivery is explicitly purge-unsupported for beta. Each built-in split wrapper registers a weak store-level `event_delivery` purge blocker for its lifetime, so both runtime purge and direct underlying-store purge reject; pending/retrying outbox work is never discarded or published into a reused session generation.
- Python ledger adds `release_settled(session_id) -> int`; both SDKs delete `completed` and `unknown`, never `running`.
- Tool execution exposes a session-busy predicate over active handler, setup, approval, and ambiguous-result ownership.

- [ ] **Step 1: Add subscriber-generation RED tests.**

Open a cursor-0 subscription, consume the old generation, and block on the next event. Runtime purge must wake and normally finish that iterator, remove the raw listener, and permit a new cursor-0 iterator to observe `session.created` at sequence 1. A raw store purge with a standalone live listener must reject without deleting anything; explicitly close the iterator, retry, and pass.

- [ ] **Step 2: Prove split delivery is fail-closed.**

Queue an old-generation event in each split journal/committer outbox and pause publication. Runtime purge and direct underlying-store purge must reject with `SessionPurgeUnsupportedError(component="event_delivery")` before store deletion. Closing/disposal unregisters the weak blocker; until then, resume delivery and prove no old event was lost or published under a reused sequence. Do not add a cross-generation outbox reconciliation protocol in this beta task.

- [ ] **Step 3: Add idempotency RED tests.**

Use a fixed tool-call ID. Execute once, close/purge/reuse, and require a second handler execution. Unknown outcomes clear on explicit purge; running/setup/approval claims block purge and leave history/cache intact. A settled-ledger failure after deletion must keep the Task 2 tombstone until retry succeeds.

- [ ] **Step 4: Implement supported delivery and settled-ledger cleanup.**

The in-memory journal/committer retains subscription handles by session. Closure uses Task 2's internal authorized teardown lane to remove the listener even though ordinary `sessionTransaction` is fenced, clears queued old-generation backlog, wakes a pending reader, and completes iteration. Physical purge must independently assert that the raw listener count is zero; this catches standalone/unregistered committers and fails without orphaning their pending iterator. Attempt every owner closure with `gather(..., return_exceptions=True)` / `Promise.allSettled`; if any fails, surface the first deterministic error only after every owner was asked, and do not physically delete.

Python ledger implementation remains narrow:

```python
async def release_settled(self, session_id: str) -> int:
    async with self._lock:
        keys = [
            key
            for key, entry in self._entries.items()
            if entry.session_id == session_id and entry.state != "running"
        ]
        for key in keys:
            self._entries.pop(key, None)
        return len(keys)
```

- [ ] **Step 5: Run the atomic lifecycle GREEN suite.**

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_events_store.py \
  kaji/tests/test_events_journal.py \
  kaji/tests/test_runtime_faults.py \
  kaji/tests/test_runtime_turn.py --no-cov
cd kaji/ts && bun run test \
  tests/store.test.ts \
  tests/event-delivery.test.ts \
  tests/runtime-faults.test.ts \
  tests/runtime-turn.test.ts
```

- [ ] **Step 6: Independent lifecycle review, then one GitButler checkpoint.**

Review Tasks 1-3 together for public-signature compatibility, complete operation fencing, cycle-free imports, cancellation, strong tombstone retention, and no split-outbox generation crossing. Commit the coherent lane only after that review:

```text
fix(kaji): enforce coordinated session generations
```

---

### Task 4: Freeze the Cross-SDK Lifecycle Contract and Documentation

**Files:**

- Modify: `kaji/contracts/beta-core-v1.json`
- Modify: `kaji/contracts/feature-tiers-v1.json`
- Synchronize: `kaji/src/kaji/contracts/**`
- Synchronize: `kaji/ts/contracts/**`
- Modify: `docs/kaji/production-beta.md`
- Modify: `docs/kaji/concurrency-and-ordering.md`
- Modify: `docs/kaji/api-parity.md`
- Modify: `kaji/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `kaji/tests/test_stability_contract.py`
- Modify: `kaji/ts/tests/docs-contract.test.ts`
- Modify: `kaji/ts/tests/schema-parity.test.ts`

**Interfaces:**

- Produces lifecycle contract fields:

```json
{
  "inMemorySessionAdmission": "fail_closed_until_explicit_purge",
  "purgedSessionReuse": "fresh_sequence",
  "purgeClosesExistingSubscribers": true,
  "purgeFencesDirectStoreOperations": true,
  "postDeleteCleanup": "tombstone_until_converged",
  "splitDeliveryPurge": "unsupported"
}
```

- Promotes Python purge types/helpers/errors to the same stable tier already used by TypeScript. Accounting remains TypeScript-only; purge does not.

- [ ] **Step 1: Add RED contract assertions.**

Require byte-synchronized contract copies, exact lifecycle field values, and Python stable exports for `PurgeableEventStore`, `SessionPurgeBusyError`, `SessionPurgeUnsupportedError`, and `supports_session_purge`.

- [ ] **Step 2: Update canonical contracts and synchronize copies.**

```bash
uv run --project kaji --no-sync python kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync python kaji/scripts/check_beta_contract.py
```

- [ ] **Step 3: Replace TypeScript-only purge documentation.**

Document the identical lifecycle order in Python and TypeScript, the explicit capacity error/recovery, old-subscriber termination, cursor reset to 0 after purge, shared-store owner semantics, public one-argument store capability versus internal coordinated capability, unsupported custom/split-delivery components, every fenced direct store operation, and irreversible host-ledger cleanup/tombstone recovery. Keep TypeScript-only accounting in its own subsection.

- [ ] **Step 4: Run contract/docs GREEN gates.**

```bash
uv run --project kaji --no-sync pytest -q kaji/tests/test_stability_contract.py --no-cov
cd kaji/ts && bun run test tests/docs-contract.test.ts tests/schema-parity.test.ts
uv run --project kaji --no-sync python kaji/scripts/check_sdk_parity.py
```

- [ ] **Step 5: GitButler checkpoint.**

```text
docs(kaji): define explicit purge parity
```

---

### Task 5: Make Release-Critical Guides and CLI Contracts Executable

**Files:**

- Modify: `docs/kaji/tthw-evidence.md`
- Modify: `apps/docs/content/getting-started.mdx`
- Modify: `docs/kaji/cli.md`
- Modify: `apps/docs/content/cli.mdx`
- Modify: `kaji/scripts/smoke_install.py`
- Modify: `kaji/tests/test_tthw_composer.py`
- Modify: `kaji/tests/test_production_beta_docs.py`
- Modify: `kaji/src/kaji/cli/add.py`
- Modify: `kaji/tests/cli/test_add.py`
- Modify: `kaji/ts/scripts/smoke_package.mts`
- Modify: `kaji/ts/src/cli/{add,index}.ts`
- Modify: `kaji/ts/src/tools/execution.ts`
- Modify: `kaji/ts/tests/{cli-add,cli-dispatch,docs-contract,integration-failures}.test.ts`

**Interfaces:**

- Public first success is credential-free: install the base SDK, run one deterministic mock turn, then opt into a real provider/key.
- The TTHW Echo blocks use the copied bundle's registered alias `echo_say`, and Python expects `mock response`.
- CLI exits are closed and shared: `0` success/current/help, `1` runtime/validation/copy failure, `2` malformed usage, `3` absent, `4` outdated, `5` modified, `6` demoted.
- Known `ToolExecutionError` failures are represented by the durable event/ledger/metrics/trace and do not produce an `internal error` log. Only untyped/unexpected exceptions use the existing redacted internal diagnostic; the integration recovery tuple is unchanged.

- [ ] **Step 1: Add RED extracted-snippet tests.**

Mark the two TTHW Echo blocks with stable HTML sentinels. Extend `test_tthw_composer.py` and `docs-contract.test.ts` to extract exactly one bounded block per language, copy the current Echo fixture into a temporary directory, and execute it. The RED source blocks fail with `UnclassifiedToolRiskError` / `UnknownToolError`; changing only the temporary tool name to `echo_say` makes them pass, while Python still fails its stale text assertion.

Then extend the existing exact-artifact paths, `smoke_install.py` and `smoke_package.mts`, to run those same marked blocks after their existing installed Echo bundle setup. Reuse their bounded process, environment, and no-network controls; do not create a second docs runner.

- [ ] **Step 2: Correct the TTHW blocks and expected output.**

Change both scripted calls and prompts from `echo.say` to the registered provider alias `echo_say`. Change Python `assert result.text == "mock"` and the preceding prose to `mock response`. Keep lifecycle-event and result assertions intact.

- [ ] **Step 3: Put a no-key mock run before provider setup.**

Restructure `apps/docs/content/getting-started.mdx` so the base package install and a marker-delimited mock `AgentBuilder` turn produce visible output before any API-key/export step. The next step introduces the real provider extras/client and key, then the existing tool example. `test_production_beta_docs.py` requires the mock block to precede the first key/live-provider construction, and the two existing exact package smokes execute the marked no-key behavior rather than merely grepping it.

- [ ] **Step 4: Align CLI exit behavior and reference docs.**

Add RED tests for `add([])`, missing `--out` value, unknown flag, and incompatible `--check --force`; every malformed form returns `2`, performs no write, and sends usage to stderr. Route Python and TypeScript `add` validation/copy/runtime diagnostics to stderr while keeping requested `--check` status JSON/text on stdout. Add `err` to TypeScript `AddOptions`, thread it through the dispatcher, and replace the conditional parse fallback with `if (args === undefined) return 2`. Document codes `3-6` in both CLI references as `add --check` classifications, not generic failures.

- [ ] **Step 5: Make expected integration failures accurately redacted.**

In `ToolExecutionController`, skip `logRedactedFailure` for an existing `ToolExecutionError`; do not import integration modules into tools or inspect messages/details. Add a test using `IntegrationAuthRequiredError("github_token_missing")` that asserts:

- stderr has no `internal error`, token, tool args, arbitrary cause text, or duplicate operational line;
- the durable failure still carries `INTEGRATION_AUTH_REQUIRED`, `github_token_missing`, `CONFIGURE_GITHUB_TOKEN`, and the fixed docs URL.

Pair it with an arbitrary `Error` test that preserves the current redacted internal diagnostic.

- [ ] **Step 6: Run GREEN documentation and CLI gates.**

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_tthw_composer.py \
  kaji/tests/test_production_beta_docs.py \
  kaji/tests/cli/test_add.py -k "docs or example or tthw or stream or usage" --no-cov
cd apps/docs && bun run check:sdk-sync
cd ../../kaji/ts && bun run test \
  tests/cli-add.test.ts \
  tests/cli-dispatch.test.ts \
  tests/docs-contract.test.ts \
  tests/integration-failures.test.ts
```

- [ ] **Step 7: Independent review and GitButler checkpoint.**

Review the exact extracted blocks, no-network execution, exit-code compatibility, import direction, and redaction. Then commit:

```text
fix(kaji): make beta guides executable
```

---

### Task 6: Bind Five-User TTHW Evidence to arm64 macOS

**Files:**

- Modify: `kaji/contracts/release/tthw-evidence-v1.schema.json`
- Modify: `kaji/contracts/release/tthw-participant.template.json`
- Synchronize: `kaji/src/kaji/contracts/release/tthw-*`
- Synchronize: `kaji/ts/contracts/release/tthw-*`
- Modify: `kaji/scripts/validate_tthw_evidence.py`
- Modify: `kaji/scripts/compose_tthw_evidence.py`
- Modify: `kaji/tests/test_tthw_evidence.py`
- Modify: `kaji/tests/test_tthw_composer.py`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `docs/kaji/tthw-evidence.md`
- Modify: `docs/kaji/releasing.md`
- Modify: `docs/kaji/testing.md`
- Modify: `kaji/RELEASE_MATRIX.md`

**Interfaces:**

- Each `humanRun` requires:

```json
{
  "commit": "40-hex",
  "releaseManifestSha256": "64-hex",
  "artifact": {
    "name": "kaji_sdk-0.2.0b1-py3-none-any.whl",
    "package": "python",
    "version": "0.2.0b1",
    "sha256": "64-hex"
  },
  "os": "macos",
  "architecture": "arm64",
  "platformVersion": "15.5"
}
```

`platformVersion` is captured from `sw_vers -productVersion` and matches `^[0-9]+(?:\.[0-9]+){1,2}$`; the schema does not hard-code one macOS release. Python participants bind to the selected wheel; npm/Bun participants bind to the one npm tarball. The aggregate still binds all three release artifacts.

- [ ] **Step 1: Make all-macOS evidence the RED fixture.**

Update the valid fixture to five distinct arm64 macOS participants spanning Python, npm, and Bun. Before implementation, the validator must reject it for missing Linux. Add hostile cases for Linux, x86_64, missing `architecture`, malformed/missing `platformVersion`, stale commit, foreign release-manifest hash, wrong artifact name/package/version/hash, and a Python receipt bound only to the sdist it did not install.

- [ ] **Step 2: Close the schema.**

In `$defs.humanRun`, require the candidate/artifact fields plus `os`, `architecture`, and `platformVersion`; use:

```json
"os": { "const": "macos" },
"architecture": { "const": "arm64" },
"platformVersion": { "type": "string", "pattern": "^[0-9]+(?:\\.[0-9]+){1,2}$" }
```

The validator replaces mixed-OS coverage with:

```python
if any(run["os"] != "macos" or run["architecture"] != "arm64" for run in runs):
    fail("/humanRuns", "every beta TTHW run must use arm64 macOS")
```

Preserve five distinct pseudonyms and collective Python/npm/Bun path coverage. In `compose_tthw_evidence.py`, compute the expected commit, manifest hash, and canonical artifact rows before accepting any participant. Compare every receipt to those exact values and its path-selected artifact; never inject current candidate identity around a stale receipt.

- [ ] **Step 3: Update template, central evidence fixture, and docs.**

The operator guide instructs each participant to copy candidate fields from a generated participant template and record:

```bash
uname -m
sw_vers -productVersion
```

All five assignments are arm64 macOS. The composer rejects reuse of a receipt from another commit/artifact even if its timings and assertions otherwise pass. General runtime support statements remain unchanged.

- [ ] **Step 4: Synchronize and verify.**

```bash
uv run --project kaji --no-sync python kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_tthw_evidence.py \
  kaji/tests/test_tthw_composer.py \
  kaji/tests/test_release_task15.py -k "tthw or contract" --no-cov
uv run --project kaji --no-sync python kaji/scripts/check_beta_contract.py
```

- [ ] **Step 5: GitButler checkpoint.**

```text
fix(kaji): bind TTHW evidence to arm64 macOS
```

---

### Task 7: Enforce arm64 macOS Protected Performance

**Files:**

- Modify: `.github/workflows/kaji.benchmark.yml`
- Modify: `.github/workflows/kaji.rehearsal.yml`
- Modify: `.github/workflows/kaji.publish.yml`
- Create: `kaji/scripts/benchmark_platform.py`
- Modify: `kaji/scripts/beta_benchmark_gate.py`
- Modify: `kaji/scripts/validate_release_evidence.py`
- Modify: `kaji/tests/test_beta_release_check.py`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `kaji/ts/tests/release-security.test.ts`

**Interfaces:**

- Protected performance jobs use exactly:

```yaml
runs-on: [self-hosted, macOS, ARM64, kaji-benchmark]
```

- `benchmark_platform.py` owns the one protected-runner parser/validator used by the beta benchmark and retained-evidence validator. Protected/calibration runtime validation requires `platform.system() == "Darwin"`, `platform.machine().lower() == "arm64"`, numeric `platform.mac_ver()[0]`, and `KAJI_BENCHMARK_PINNED_RUNNER=1`.
- `KAJI_BENCHMARK_RUNNER_MANIFEST` names a reviewed local bootstrap-manifest file. The helper rejects missing, non-regular, symlinked, or larger-than-64-KiB files, hashes the bytes, and compares them to `KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256=64-hex`. This is measured provenance; do not retain a field named `imageDigest` for a value supplied only by configuration.
- The retained runner shape is closed:

```json
{
  "os": "Darwin",
  "arch": "arm64",
  "platformVersion": "15.5",
  "bootstrapManifestSha256": "64-hex"
}
```

- [ ] **Step 1: Add RED platform and artifact-identity tests.**

Require Linux, x64, empty/malformed macOS version, local-unpinned, missing/symlinked/oversized bootstrap manifest, configured/hash mismatch, and old `imageDigest`-only evidence to fail. Require the workflow selectors above and require rehearsal/publish normalization to assert fingerprint OS, architecture, version, and bootstrap-manifest hash.

- [ ] **Step 2: Enforce platform in Python gates.**

Use one helper from `benchmark_platform.py`; do not duplicate platform/file validation in workflows or evidence validators:

```python
def require_protected_macos_arm64(*, protected: bool, calibrating: bool) -> None:
    if not (protected or calibrating):
        return
    if os.environ.get("KAJI_BENCHMARK_PINNED_RUNNER") != "1":
        raise BenchmarkError("protected evidence requires the pinned runner")
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise BenchmarkError("protected evidence requires arm64 macOS")
    version = platform.mac_ver()[0]
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version) is None:
        raise BenchmarkError("protected evidence requires a numeric macOS version")
    verify_bootstrap_manifest_from_environment()
```

- [ ] **Step 3: Update workflow labels and central evidence validation.**

All benchmark/soak/calibration jobs use the macOS labels and receive the manifest path/hash variables. Inline `jq` consumes the fingerprint produced by Python instead of reimplementing host detection; `validate_release_evidence.py` rejects non-Darwin/non-arm64/bad-version/bad-bootstrap fingerprints and requires benchmark, soak, baseline, and normalized workflow evidence to agree exactly.

- [ ] **Step 4: Run GREEN gates.**

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_beta_release_check.py \
  kaji/tests/test_release_task15.py -k "benchmark or performance or runner" --no-cov
cd kaji/ts && bun run test tests/release-security.test.ts
```

Do not run protected calibration and do not edit `kaji/benchmarks/beta-baseline.json` in this task.

- [ ] **Step 5: Independent review and GitButler checkpoint.**

Review that the fingerprint measures the manifest file and macOS version, no host path is retained, and no source benchmark is misrepresented as an installed-package benchmark. Then commit:

```text
fix(kaji): enforce macOS beta performance proof
```

---

### Task 8: Retain Closed Package-Smoke Failure Diagnostics

**Files:**

- Modify: `kaji/ts/scripts/command.ts`
- Modify: `kaji/ts/scripts/smoke_package.mts`
- Modify: `.github/workflows/kaji.rehearsal.yml`
- Modify: `.github/workflows/kaji.publish.yml`
- Modify: `kaji/scripts/validate_release_evidence.py`
- Modify: `kaji/ts/tests/smoke-command.test.ts`
- Modify: `kaji/ts/tests/package-contract.test.ts`
- Modify: `kaji/ts/tests/release-security.test.ts`
- Modify: `kaji/tests/test_release_task15.py`

**Interfaces:**

- Failed package receipts add:

```ts
type SmokeFailureKind =
  | "unsupported_host"
  | "start"
  | "exit"
  | "timeout"
  | "output_limit"
  | "cleanup"
  | "capture"
  | "shutting_down"
  | "unknown";

interface FailedSmokeReceipt {
  conclusion: "failed";
  failureCode: "artifact_identity_failed" | "node_smoke_failed";
  failedPhase: SmokePhase | null;
  failureKind: SmokeFailureKind;
}
```

No command arguments, child output, registry body, environment values, tokens, or filesystem secrets enter the receipt.

The installed GitHub package proof remains schema v5 with 15 scenarios, `githubFailureRecovery`, and `githubObservabilitySinksVerified`. Every rehearsal/publish normalizer and `validate_release_evidence.py` accepts that exact shape and rejects v4/14 or missing new fields; the producer is never downgraded to match stale consumers.

- [ ] **Step 1: Add RED failure classification tests.**

Inject every live command error: `UnsupportedReleaseHostError`, `CommandStartError`, `CommandExitError`, `CommandTimeoutError`, `CommandOutputLimitError`, `CommandCleanupError`, `CommandCaptureError`, `CommandShuttingDownError`, base `CommandError`, and an unknown error. Assert exact closed kind/phase and absence of canary argv/output/token strings. Preserve `PACKAGE_TIMEOUT_MS = 300_000`.

- [ ] **Step 2: Close every package phase.**

Replace `handoff:${string}` with a finite `HandoffPhase` union containing exactly these suffixes:

```text
npm-install, bun-install, typescript57-version, typescriptCurrent-version,
typescript57-esm, typescript57-cjs, typescriptCurrent-esm, typescriptCurrent-cjs,
npm-github-proof, bun-github-proof, archive-list, archive-types, archive-extract,
policy-before-token, node-version, npm-version, node-esm, node-commonjs
```

Add `workspace:cleanup` to the ordinary phase union. Tests must reject arbitrary handoff labels while keeping all 18 real callers typed.

- [ ] **Step 3: Attach phase/kind without changing execution.**

Map the command classes by identity, never by exception message. Wrap errors from `runCommand()` in a typed error carrying only `phase` and the closed kind. Preserve packages, audits, install arguments, bounded output, child-tree termination, and timeout.

- [ ] **Step 4: Emit success only after workspace cleanup.**

Change ordinary, artifact-contract handoff, and Node handoff functions to return a pending success document rather than writing it. Remove the temporary workspace first; only then emit/atomically retain `conclusion="passed"`. Injected cleanup failure must make ordinary mode emit a closed failed receipt with `failedPhase="workspace:cleanup"` and `failureKind="cleanup"`; trusted handoff must emit no passed receipt and exit nonzero so its workflow-owned terminal normalizer records failure.

- [ ] **Step 5: Upgrade all retained-evidence consumers to exact v5.**

Update both initial/final compatibility normalizers in each of `kaji.rehearsal.yml` and `kaji.publish.yml`, the Python central validator, and the shared fixture to require schema v5, 15 scenarios, the exact closed GitHub recovery tuple, and `githubObservabilitySinksVerified: true`. Add RED cases for v4, missing either new field, npm/Bun disagreement, and extra fields. The four workflow normalizers must preserve valid `failedPhase`/`failureKind`, use `null`/`unknown` only when package execution never began, and reject unrecognized values.

- [ ] **Step 6: Run GREEN gates and exact discriminator.**

```bash
cd kaji/ts && bun run test \
  tests/smoke-command.test.ts \
  tests/package-contract.test.ts \
  tests/release-security.test.ts
uv run --project kaji --no-sync pytest -q kaji/tests/test_release_task15.py -k "compat or package" --no-cov
```

Re-run the exact v5 validator discriminator: exact v5 returns true; the previous v4 fixture returns false.

- [ ] **Step 7: Independent review and GitButler checkpoint.**

Review all live consumers (`ts.test`, benchmark/rehearsal/publish callers, trusted handoff, and `beta_release_check.py`) for unchanged script identity and success-after-cleanup semantics. Then commit:

```text
fix(kaji): close package smoke evidence
```

---

### Task 9: Add the Exact-Artifact GitHub Live-Proof Boundary

**Files:**

- Create: `kaji/contracts/release/github-proof-v1.schema.json`
- Synchronize: `kaji/src/kaji/contracts/release/github-proof-v1.schema.json`
- Synchronize: `kaji/ts/contracts/release/github-proof-v1.schema.json`
- Modify: `kaji/scripts/check_beta_contract.py`
- Create: `kaji/scripts/live_github_proof.py`
- Create: `kaji/scripts/github_proof_cleanup.py`
- Create: `kaji/scripts/installed_github_live.py`
- Create: `kaji/ts/scripts/installed-github-live.mts`
- Create: `kaji/tests/test_live_github_proof.py`
- Create: `kaji/tests/test_github_proof_cleanup.py`
- Modify: `kaji/tests/test_release_smoke.py`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `docs/kaji/integration-manifests.md`
- Modify: `kaji/RELEASE_MATRIX.md`

**Interfaces:**

- `live_github_proof.py --artifacts-dir PATH --expected-commit SHA --python-compat PATH --typescript-compat PATH --fixture PATH --state PATH --output PATH` executes one Python and one TypeScript installed-artifact cell.
- `github_proof_cleanup.py --state PATH --expected-commit SHA` is an idempotent interruption-recovery command.
- The credential comes only from `KAJI_GITHUB_PROOF_TOKEN`; it is allowlisted into child/control calls and never accepted in argv/files.
- The operator supplies one pre-existing private repository issue. Kaji adds and deletes uniquely marked comments; it never creates an issue because GitHub issues cannot be safely removed.
- The retained schema is closed and contains no repository, issue/comment ID, marker, body, token, URL, query, path, user content, or free text.

```json
{
  "schemaVersion": "1.0.0",
  "commit": "40-hex",
  "releaseManifestSha256": "64-hex",
  "cells": [
    {
      "runtime": "python",
      "artifactSha256": "64-hex",
      "packageProofSha256": "64-hex",
      "conclusion": "passed"
    },
    {
      "runtime": "typescript",
      "artifactSha256": "64-hex",
      "packageProofSha256": "64-hex",
      "conclusion": "passed"
    }
  ],
  "approvalRejectedBeforeTransport": true,
  "readPassed": true,
  "approvedCommentPassed": true,
  "controlReadbackPassed": true,
  "ambiguousMutationRetried": false,
  "cleanup": { "required": true, "conclusion": "passed" },
  "redacted": true
}
```

- [ ] **Step 1: Add RED public-evidence and private-state tests.**

Reject missing/extra/stale cells, source-checkout import paths, wrong commit/hash, a downgraded package proof, missing credentials, failed cleanup, oversized documents, symlinks, permissive private-file modes, token/content/handle canaries, and any non-GitHub provider field. Assert no retained field can carry the private fixture or state data.

- [ ] **Step 2: Bind the existing offline/package safety proof.**

Before any live call, validate one canonical Python and TypeScript compatibility receipt against the exact Task 8 shapes and candidate artifacts. Require the package evidence to prove approval rejection before credential/transport access, `github_mutation_unknown` preservation, zero automatic mutation retries, the closed no-credential recovery tuple, and observability sinks. Persist only each receipt's SHA-256. Do not reproduce ambiguous live faults against GitHub.

- [ ] **Step 3: Create private atomic cleanup intent before dispatch.**

The fixture and state are regular, non-symlink, at-most-64-KiB, owner-only (`mode & 0o077 == 0`) JSON files under `.artifacts/`. The fixture contains only the designated `owner/repository` and existing issue number. Before each mutation, atomically/fsync write that cell's unique marker and state transition:

```text
planned -> dispatched -> identified -> cleanup_required -> cleaned
                         \-> failed
```

Repository, issue, marker, comment ID, and reconciliation status may exist only in this private state. State writes happen before dispatch and immediately after an ID is learned, so process interruption is recoverable.

- [ ] **Step 4: Execute the narrow installed live path.**

Reuse `installed_release_runtime`, the process runner, and the closed child-environment pattern from `live_provider_proof.py`; do not add source fallback or package private benchmark seams. For each installed SDK:

1. copy/load the packaged GitHub bundle from that exact artifact;
2. read the designated existing issue through `github_get_issue`;
3. approve exactly one `github_add_comment` call carrying the unique benign marker;
4. write the returned comment ID into private state;
5. use a separate fixed-origin control client to GET that exact comment and verify the marker;
6. never invoke `create_issue` and never retry the mutation.

Child output is a bounded private channel consumed into state, not retained evidence. Any pre-dispatch failure leaves no resource; any dispatched/unknown result requires reconciliation.

- [ ] **Step 5: Implement deterministic, idempotent cleanup.**

Cleanup verifies the state commit/manifest before network access. With a comment ID, GET then DELETE exactly that comment and verify absence. Without an ID after `dispatched`, enumerate a bounded number of comments only on the designated issue, match only the exact marker, delete zero or one match, and fail closed on duplicates, pagination/cap ambiguity, origin drift, timeout, or verification failure. Re-running a cleaned state is a no-op success. The parent invokes cleanup in `finally`; a public `passed` receipt is written atomically only after both cells are `cleaned`.

- [ ] **Step 6: Synchronize contracts and document the promotion hold.**

```bash
uv run --project kaji --no-sync python kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync python kaji/scripts/check_beta_contract.py
```

Documentation says GitHub remains experimental until both installed cells and cleanup pass on the exact candidate. Gmail remains at `GMAIL_RUNTIME_NOT_IN_REVIEWED_CHECKPOINT` and receives no runtime/ABI/schema in this task.

- [ ] **Step 7: Run deterministic GREEN tests without credentials.**

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_live_github_proof.py \
  kaji/tests/test_github_proof_cleanup.py \
  kaji/tests/test_release_smoke.py \
  kaji/tests/test_release_task15.py -k "github or proof or cleanup" --no-cov
uv run --project kaji --no-sync python kaji/scripts/check_integration_abi.py
```

Live proof is not run locally without credentials and is not claimed.

- [ ] **Step 8: Independent security/scope review and GitButler checkpoint.**

Review fixed-origin enforcement, approval order, private-file modes, atomic state transitions, cleanup idempotence, absence of issue creation, exact package-proof binding, and retained-schema redaction. Then commit:

```text
test(kaji): add exact-artifact GitHub proof
```

---

### Task 10: Run Full Local QA, Then Hand Off Protected Operator Evidence

**Files:**

- No tracked implementation files.
- Generated local receipts only under `.artifacts/`; never commit them.

**Interfaces:**

- Consumes the settled source tree and exact candidate artifacts.
- Produces either verified local engineering readiness or a precise list of environmental/protected blockers. It does not produce a beta tag/publication claim.

- [ ] **Step 1: Run all static, structural, contract, and behavior gates.**

```bash
uv run --project kaji --no-sync ruff format --check kaji/src kaji/tests
uv run --project kaji --no-sync ruff check kaji/src kaji/tests
uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise
uv run --project kaji --no-sync pytest kaji

cd kaji/ts
bun run format:check
bun run lint
bun run typecheck
bun run build
bun run test:coverage
cd ../..

uv run --project kaji --no-sync python kaji/scripts/check_beta_contract.py
uv run --project kaji --no-sync python kaji/scripts/sync_integration_contracts.py --check
uv run --project kaji --no-sync python kaji/scripts/check_integration_abi.py
uv run --project kaji --no-sync python kaji/scripts/check_sdk_parity.py
bun run audit:ast-grep
uv run --project kaji --no-sync python kaji/scripts/integration_benchmark.py --mode quick
cd apps/docs && bun run check:sdk-sync
```

Expected: no failures. The integration benchmark is identified as a source regression gate only. Keyed/live/protected gates remain explicitly skipped unless their exact prerequisites are supplied.

- [ ] **Step 2: Build and smoke exact installed artifacts.**

Run the canonical release rehearsal with the required tool paths and retain its receipt. If npm install times out, preserve `failedPhase`/`failureKind`, run the registry discriminator, and rerun the same exact tarball once; classify infrastructure separately rather than increasing the timeout.

```bash
PATH="/opt/homebrew/bin:$PATH" uv run --project kaji --no-sync python kaji/scripts/beta_release_check.py --release
npm ping --registry=https://registry.npmjs.org/
```

- [ ] **Step 3: Repeat empirical DevEx scenarios.**

From fresh temporary directories and only the frozen wheel/tarball:

1. Python install -> `kaji init` -> no-key deterministic turn -> Echo tool.
2. npm install -> TypeScript init -> no-key deterministic turn -> Echo tool.
3. Bun install -> same TypeScript flow.
4. Fill one-session capacity -> observe actionable capacity error -> explicit purge -> fresh sequence-1 reuse.
5. Attempt GitHub without credentials -> closed auth-required recovery, no transport.
6. Verify expected GitHub auth failure produces no TypeScript `internal error` line and retains the closed recovery tuple.
7. Run malformed `kaji add` forms -> stderr/exit 2; run `--check` states -> stdout/exits 3-6.
8. Execute the exact marker-delimited Getting Started and TTHW Echo blocks from the checked-in docs.

Record timings and friction locally; do not present them as the five-user cohort.

- [ ] **Step 4: Obtain independent code and simplification reviews.**

Review each meaningful checkpoint against this plan, then run Ponytail over the full diff. Remove dead compatibility code, duplicate lifecycle state, redundant evidence paths, and speculative abstractions only when tests prove identical behavior.

- [ ] **Step 5: Verify GitButler ownership and create the final local checkpoint.**

Use `but diff` and assign only this plan's changes to `feat/beta-release`. Preserve `AGENTS.md` and unrelated branch work. If GitButler would restack/rewrite another shared branch, stop and request the user-owned topology decision. Do not push.

- [ ] **Step 6: Hand off the exact protected/operator sequence.**

The operator performs these steps only after the source commit is clean and reviewed:

1. Restore Actions billing/minutes and protect the candidate environment.
2. Configure the required status context exactly as `beta release gate`.
3. Register a reviewed self-hosted arm64 macOS benchmark runner with labels `self-hosted`, `macOS`, `ARM64`, `kaji-benchmark`; set `KAJI_BENCHMARK_RUNNER_MANIFEST` to the reviewed local manifest and `KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256` to its exact 64-hex digest.
4. Build the frozen artifacts and run protected calibration:

   ```bash
   export KAJI_BENCHMARK_RUNNER_MANIFEST=/absolute/path/to/reviewed-runner.json
   export KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256=<64-hex>
   KAJI_BENCHMARK_CALIBRATION=1 \
   KAJI_BENCHMARK_PINNED_RUNNER=1 \
   uv run --project kaji --no-sync python kaji/scripts/run_beta_benchmarks.py \
     --calibrate --protected --artifacts-dir .artifacts/kaji-release
   ```

5. Human-review and checkpoint only the accepted `kaji/benchmarks/beta-baseline.json`, then freeze the new candidate and rerun affected evidence.
6. Run the full protected benchmark and 30-minute soak from the frozen artifacts:

   ```bash
   uv run --project kaji --no-sync python kaji/scripts/run_beta_benchmarks.py \
     --full --protected --artifacts-dir .artifacts/kaji-release
   uv run --project kaji --no-sync python kaji/scripts/run_beta_soak.py \
     --minutes 30 --protected --artifacts-dir .artifacts/kaji-release
   ```

7. Run Python/TypeScript x OpenAI/Anthropic keyed provider cells with installed artifacts and bounded provider-specific child environments.
8. Generate candidate-bound participant templates, collect exactly five fresh arm64 macOS TTHW participants across Python/npm/Bun, and compose/validate their redacted receipts against the same commit, release-manifest hash, and selected artifact hashes.
9. Run the GitHub Python/TypeScript exact-artifact proof against one designated existing private issue, then run/verify cleanup from its private owner-only state. Keep GitHub experimental on any failure or residue:

   ```bash
   KAJI_GITHUB_PROOF_TOKEN=<fine-grained-token> \
   uv run --project kaji --no-sync python kaji/scripts/live_github_proof.py \
     --artifacts-dir .artifacts/kaji-release \
     --expected-commit <40-hex> \
     --python-compat .artifacts/kaji-evidence/python-compat.json \
     --typescript-compat .artifacts/kaji-evidence/typescript-compat.json \
     --fixture .artifacts/private/github-fixture.json \
     --state .artifacts/private/github-proof-state.json \
     --output .artifacts/kaji-evidence/github-proof.json
   ```
10. Only after GitHub passes, evaluate the Gmail stop/go: Google Desktop OAuth project, restricted scopes/test users, and real Keychain save/load/delete/locked/missing/corrupt/cancel/timeout/no-leak spike. A failed prerequisite keeps Gmail deferred.
11. Complete the existing protected rehearsal and review that every retained receipt names the same candidate commit, release-manifest hash, and applicable artifact hashes.
12. Request separate authorization to create/push the signed tag and to publish.
13. Let the publish workflow attach SBOM/provenance/attestations, publish selected bytes, and download/byte-verify PyPI and npm. Never substitute a local claim.

## Completion Criteria

- Both SDKs reject retained-session capacity exhaustion without deleting history.
- Explicit purge is cross-SDK, store-operation fenced, opaque-lease authorized, shared-owner aware, subscription terminating, idempotency clearing, cleanup-tombstoned, and sequence-1 reusable; split delivery blocks purge rather than crossing generations.
- Lifecycle public exports/contracts/docs are synchronized and tested.
- Getting Started and TTHW Echo examples execute from exact installed artifacts; CLI exit/stream behavior is identical and documented.
- TTHW receipts bind each participant to the exact commit/manifest/selected artifact, and protected performance is arm64 macOS-only with a measured version/bootstrap-manifest fingerprint.
- Package-smoke failures identify a closed phase/kind without leaking child details or changing timeouts; success is emitted only after cleanup; exact v5 package proof survives every normalizer/validator.
- Exact-artifact GitHub comment proof/cleanup exists with separate private state and handle-free retained evidence; Gmail remains deferred.
- The existing protected one-artifact-set rehearsal/publication path remains single-source and every consumer verifies the same commit, manifest, and artifact hashes.
- Full local gates and installed-artifact smokes pass, or any remaining failure is classified as an environmental blocker with its exact phase.
- No beta, provider, provenance, publication, or registry claim is made without the corresponding protected evidence.

## Engineering Review Summary

- Scope challenge: scope reduced to confirmed beta defects and the approved GitHub comment proof; installed integration microbenchmark, Gmail, distributed purge, and protected operator actions remain deferred.
- Architecture review: 6 issues found and folded into the opaque lease, public store fence, cleanup tombstone, split-delivery blocker, private proof state, and measured runner manifest.
- Code-quality review: 3 issues found and folded into public/internal protocol separation, finite smoke classifications, and reuse of existing installed/runtime proof machinery.
- Test review: combined code/user-flow diagram produced; 4 uncovered regressions gained mandatory RED/GREEN coverage.
- Performance review: 1 issue found; source regression benchmark remains source-only and protected proof gains an honest arm64 macOS fingerprint.
- DevEx review: empirical score 6.0/10; five tested defects are assigned to Task 5 and the repeat run in Task 10. Human TTHW remains unmeasured.
- Failure modes: 0 silent, untested critical gaps remain in the reviewed plan.
- Outside voice: independent Codex subagent ran; Claude CLI reported unauthenticated at review time. Eleven findings were reproduced before incorporation.
- Parallelization: 7 lanes; lifecycle is sequential/atomic, while formatting and later release-contract lanes may run in parallel within the conflict rules above.
- TODOS.md: 0 additions. Deferred work is already captured with prerequisites in `NOT in Scope`; no vague backlog item was created.
- Lake score: 14/14 complete recommendations selected under the user's standing preference for recommended choices.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 fresh | — | No review within the current 7-day window |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | ISSUES FOLDED | 11 reproduced plan findings; 11 incorporated |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAN | 14 issues, 0 critical gaps, 0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | Not applicable to SDK/runtime/release tooling |
| DX Review | `/devex-review` | Developer experience gaps | 1 | ISSUES FOLDED | score 6.0/10, TTHW unmeasured, 5 tested/3 inferred dimensions |

**CODEX:** Listener orphaning, split-generation outbox, tombstone recovery, candidate-bound human evidence, v5 normalizer drift, and private GitHub cleanup state were added before implementation.

**VERDICT:** ENG CLEARED — the reviewed plan is ready to implement; protected/external evidence remains explicitly unclaimed.

NO UNRESOLVED DECISIONS
