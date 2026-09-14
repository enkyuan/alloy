# Kaji Production Beta Operating Contract

Kaji is in pre-beta release implementation. The stable core described here is
implemented and covered by local deterministic gates, but promotion is blocked
until the same release commit passes required keyed OpenAI tool loops in both
SDKs, floor/latest runtime, the three-replica paired A/B benchmark, a separate
30-minute soak, signed-tag, provenance, and publication checks. Do not describe
either package as production beta-ready before those artifacts are attached to
the release.

The shared machine contract is
[`kaji/contracts/beta-core-v1.json`](../../kaji/contracts/core/v1/beta.json).
The feature promise is generated and checked through
[`kaji/RELEASE_MATRIX.md`](../../kaji/RELEASE_MATRIX.md).

## First success

These examples use the deterministic mock provider so they run from the exact
installed wheel and npm tarball without credentials. Replace it with OpenAI
only after this local path works. Anthropic remains available as an opt-in
experimental/WIP adapter, not as a beta-supported path. Both examples
demonstrate the same four boundaries:

1. A text-only turn needs no principal because it cannot execute a tool.
2. A tool-enabled turn supplies an explicit principal and every tool declares risk.
3. A whole-turn deadline pairs the tool deadline with cooperative cancellation.
4. Results retain turn IDs in memory for event correlation; examples output only
   non-privileged text/accounting, and Kaji provider errors normalize to a
   redaction-safe shape.

### Python

<!-- installed-quickstart:python:start -->
```python
import asyncio
import time

import kaji


class EchoIntegration(kaji.Integration):
    namespace = "docs"

    @kaji.tool(
        description="Return a deterministic acknowledgement.",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )
    async def ping(self, context: kaji.ToolExecutionContext, args: dict) -> dict:
        return {"ok": True, "principal": context.principal_id}


async def main() -> None:
    text_runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock", reply="hello"))
        .build()
    )
    text = await text_runtime.turn("Say hello.")
    assert text.text == "hello"
    assert all(event.turn_id == text.turn_id for event in text.events)
    print(text.text)

    tool_runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock"))
        .integration(EchoIntegration())
        .build()
    )
    tool_result = await tool_runtime.turn(
        "Call ping.",
        context=kaji.TurnContext(
            principal_id="docs-user",
            deadline_monotonic=time.monotonic() + 30,
        ),
    )
    assert tool_result.tool_call_events

    normalized = kaji.normalize_provider_error(
        kaji.ProviderConfigError("safe public message", service="example")
    )
    print(normalized["code"], normalized["retryable"])


asyncio.run(main())
```
<!-- installed-quickstart:python:end -->

`deadline_monotonic` is an absolute value from `time.monotonic()`. An earlier
caller deadline tightens, but never extends, the configured 120-second
whole-turn default covering queue wait, provider open and streaming, approval,
and tool work. Cooperative provider shutdown may use the additional configured
cancellation grace.

Every provider call receives immutable `ProviderResponseLimits`: 256 KiB of
text, 64 KiB per tool-argument object, 512 KiB across text, arguments, tool
IDs, and names, and at most 64 tool calls. A breach raises
`ProviderOutputLimitError` with the closed dimension and configured limit,
records `PROVIDER_OUTPUT_LIMIT`, flushes only the already accepted text, and
never completes the assistant message or executes tools. Durable text deltas
are coalesced into nonempty chunks of at most 4 KiB. Their ordered
concatenation equals the completed message; vendor chunk boundaries are not a
stable API.

### TypeScript

<!-- installed-quickstart:typescript:start -->
```ts
import { EventType, InMemoryBackend, Kaji, capability, capabilityResult } from "@irogane/kaji";
import * as z from "zod";

const backend = new InMemoryBackend();
const ping = capability({
  name: "ping",
  description: "Return a deterministic acknowledgement.",
  input: z.object({}),
  risk: "read",
  execute: async (_args, context) =>
    capabilityResult({ ok: true, principal: context.principalId }),
});
const sessionId = "docs-quickstart";
const result = await Kaji.execute({
  capability: ping,
  input: {},
  principal: "docs-user",
  backend,
  sessionId,
});
const events = await backend.store.getEvents(sessionId);
const completed = events.find((event) => event.type === EventType.TOOL_CALL_COMPLETED);
if (completed === undefined) throw new Error("tool was not called");
if (events.some((event) => event.turn_id !== completed.turn_id)) {
  throw new Error("turn IDs did not propagate");
}
console.log(JSON.stringify(result.value));
```
<!-- installed-quickstart:typescript:end -->

`deadlineAtMs` is an absolute Unix epoch value; use `deadlineAfter()` when the
caller has a duration. It tightens the same configured whole-turn maximum as
Python. The runtime requests provider cancellation at expiry and allows the
configured grace for cooperative shutdown.

`normalize_provider_error()` and `normalizeProviderError()` accept Kaji
provider errors, not arbitrary vendor exceptions. Provider adapters convert
vendor failures before they cross the public boundary. The normalized object
contains only `type`, `code`, `service`, `action`, `status`, and `retryable`.

## Privileged journal and failure recovery

`TurnResult.events` and `history()` are a privileged full-fidelity journal in
both SDKs. Retained events can include prompts, provider-derived text and deltas,
tool arguments, tool results, arbitrary metadata, and correlation identifiers.
They are not redaction-safe and must not be logged, attached to exceptions, or
exported wholesale.

`MetricsSink` / `TraceSink` in TypeScript and their Python counterparts are
best-effort timing and correlation surfaces, not complete business or audit
records. Delivery failures do not change runtime behavior. Treat trace IDs as
access-controlled correlation data even though observability does not carry the
full journal payload.

Outcome shape matters:

| Outcome | Public result | Retained evidence |
| --- | --- | --- |
| Provider or timeout failure | Rejects with the original/typed error; no `TurnResult` | Accepted events plus `agent.turn.failed` when the secondary append succeeds. Timeout fields are structured; a generic provider failure has no durable recovery code. |
| Ordinary terminal tool failure | Usually continues to the next provider iteration and resolves | `tool.call.failed` with bounded public fields. Closed integration failures may include `reason_code`, `recovery_code`, and `doc_url`. |
| Mid-provider cooperative cancellation | Resolves with a cancellation result | `cancellation.completed`; no `agent.turn.failed`. An interrupted provider call is not successful-turn accounting. |
| Cancellation while queued | Rejects with `CancellationError` | `cancellation.completed`; no provider dispatch. |
| Failure-event append failure | Preserves the original operation error | The terminal event can be absent because the secondary journal append is best effort. |

For a failed turn, choose a preselected session ID. Preserve the caught error
separately, page until an empty page using the exclusive `afterSequence` cursor
(`after_sequence` in Python), reject a non-advancing cursor, and reduce to an
allowlist before export. Safe evidence includes only `sequence`, `turn_id`,
`type`, tool name/call ID, failure code/phase/retryability/outcome, and a closed
integration recovery tuple. Never include `content`, `delta`, `tool_args`,
`result`, arbitrary metadata, or the raw session ID by default. This is an
application pattern; the embedded SDK does not yet ship a public safe-journal
projection helper.
Always page until an empty page; a short page is not proof of exhaustion.

`close()` rejects future turn APIs but does not delete retained history, cancel
already-active work, or prevent paging. Default stores and coordination are
in-memory and process-local. The embedded beta ships no persistent event store
or distributed coordinator and does not release-certify host implementations;
their durability, deletion, and cross-process correctness are host
responsibilities.

## Cross-SDK session purge

Both SDKs use the same session lifecycle for the supported in-memory path.
Before disposal, stop ingress for the named session, drain tools and providers,
page and reduce required evidence, then call `purge_session(session_id)` in
Python or `purgeSession(sessionId)` in TypeScript. A live runtime may keep
serving other sessions. For whole-runtime shutdown, `close()` may run first to
reject new turn APIs; history, drains, and purge remain callable. A provider
quarantine or other owned work makes purge fail closed with
`SessionPurgeBusyError`.

The bounded in-memory store never evicts a retained session implicitly. When
every slot is occupied, admitting a new session raises
`EventStoreCapacityError` until the host explicitly purges one. Successful
purge normally terminates old subscribers, deletes the retained event and ID
indexes, clears every runtime owner's projection/diagnostic caches, and releases
settled idempotency entries. Reuse is a fresh generation: reset history and
subscription cursors to `0`; the next stored event starts at sequence `1`.

`PurgeableEventStore.purge_session(session_id)` and
`PurgeableEventStore.purgeSession(sessionId)` are the public one-argument store
capability, detected by `supports_session_purge()` / `supportsSessionPurge()`.
Runtime purge additionally requires the built-in internal coordinated
capability: its opaque, single-use authorization binds the store, session, and
active purge lease. A custom store that implements only the public capability
remains valid for store-only teardown, but runtime purge rejects it as
`SessionPurgeUnsupportedError(component="event_store")` before mutation.

The session fence covers direct append, event and last-sequence reads,
transactions, and subscription registration as well as runtime turns and new
shared-store owners. Stable in-memory delivery closes runtime-owned old
subscribers before physical deletion; a standalone raw listener must be closed
by its caller. Split delivery remains purge-unsupported because Kaji does
not reconcile an outbox across reused generations; unsupported custom delivery
or idempotency components also fail before deletion.

After physical deletion, `cleanup_pending` is a strong tombstone until every
shared runtime owner clears caches and host ledger cleanup converges. If cleanup
fails, deletion cannot be rolled back: all fenced operations keep failing
closed, and a later runtime purge retries cleanup without repeating physical
deletion. Kaji cannot promise VM string zeroization or delete copies held by
callers, providers, logs, observability backends, custom stores, or crash dumps.

### Removed TypeScript accounting

`TurnAccounting` was removed with the TypeScript capability cut. The retained
`Kaji.execute` surface returns a `CapabilityResult` without provider
accounting.

## Stable core

The beta promise is the shared stable core: cancellation, sessions,
same-session coordination, sequenced in-memory event history and replay, tool
schema/policy/execution, and the one-shot `Kaji.execute` capability surface.
The Python SDK additionally retains the agent builder, runtime turn loop, and
OpenAI adapter; the TypeScript capability cut removed those surfaces.
Anthropic, Gemini, Kimi, and OpenRouter adapters remain experimental/WIP,
opt-in, and outside the beta compatibility and publication-proof commitment.
RAG/retrieval may be implemented in Python but also remains experimental and
outside this promise. The Python `MockProvider` is the deterministic
local/test default for the Python runtime.

Echo is the only beta catalog entry. GitHub is experimental and requires
explicit opt-in in both SDKs. Python-only
Redis event/history, voice/TTS, RAG/retrieval, native Gemini/Kimi, and retriever
selection are also experimental.

## Default limits

These values come from contract version `1.0.0`; both SDKs must agree.
Inspect the resolved per-runtime values with `runtime.effective_limits()` in
Python or `runtime.effectiveLimits()` in TypeScript. They return immutable
`EffectiveRuntimeLimits` values after builder defaults and overrides are
applied.

Python override types are available from the agents package:

```python
from kaji.runtime.agents import AgentStrategy, ContextWindow, TurnExecutionLimits
```

| Boundary | Default | Python override | TypeScript override |
| --- | ---: | --- | --- |
| Tool iterations per turn | 5 | `AgentStrategy(max_iterations=...)` | `.strategy({ maxToolIterations: ... })` |
| Complete context turns | 32 | `.context_window(ContextWindow(max_turns=...))` | `.contextWindow({ maxTurns: ..., maxCharacters: ... })` |
| Context characters | 100,000 | `ContextWindow(max_characters=...)` | `contextWindow.maxCharacters` |
| Turn work timeout | 120 seconds | `.turn_execution_limits(TurnExecutionLimits(timeout_seconds=...))` | `.turnExecutionLimits({ turnTimeoutMs: ... })` |
| Provider cancellation grace | 5 seconds | `TurnExecutionLimits(provider_cancellation_grace_seconds=...)` | `.turnExecutionLimits({ providerCancellationGraceMs: ... })` |
| Provider text | 262,144 UTF-8 bytes | Runtime provider limits | Runtime provider limits |
| Provider tool arguments | 65,536 UTF-8 bytes | Runtime provider limits | Runtime provider limits |
| Provider response | 524,288 UTF-8 bytes | Runtime provider limits | Runtime provider limits |
| Provider tool calls | 64 | Runtime provider limits | Runtime provider limits |
| Parallel tool handlers | 4 | `ToolExecutionLimits(max_parallel=...)` | `.toolExecutionLimits({ maxParallel: ... })` |
| Tool queue-to-completion timeout | 30 seconds | `ToolExecutionLimits(timeout_seconds=...)` | `.toolExecutionLimits({ timeoutMs: ... })` |
| Approval timeout | 300 seconds | `ToolExecutionLimits(approval_timeout_seconds=...)` | `.toolExecutionLimits({ approvalTimeoutMs: ... })` |
| Subscriber queue | 1,024 events | `InMemoryEventJournal(subscriber_queue_capacity=...)` | `new InMemoryEventCommitter(store, { subscriberCapacity: ... })` |
| Durable tool arguments | 65,536 UTF-8 bytes | Not overridable in beta | Not overridable in beta |
| Durable tool results | 65,536 UTF-8 bytes | Not overridable in beta | Not overridable in beta |
| Durable event | 1,048,576 UTF-8 bytes | Not overridable in beta | Not overridable in beta |
| In-memory sessions | 1,000 | `InMemoryEventStore(max_sessions=...)` | `new InMemoryEventStore({ maxSessions: ... })` |
| Events per in-memory session | 10,000 | `InMemoryEventStore(max_events_per_session=...)` | `new InMemoryEventStore({ maxEventsPerSession: ... })` |
| History page | 1,024 events | `history(..., limit=...)` | `history(..., { limit: ... })` |
| Idempotency entries | 10,000 | `InMemoryToolIdempotencyLedger(max_entries=...)` | `new InMemoryToolIdempotencyLedger({ capacity: ... })` |
| Completed idempotency TTL | 86,400 seconds | `completed_ttl_seconds=...` | `completedTtlMs: ...` |

Whole-turn expiry raises `TurnTimeoutError`, whose phase, outcome, and
retryability distinguish queue, provider, approval, and tool work. A provider
that does not settle within cancellation grace raises
`ProviderCancellationContractViolation`; the session remains quarantined until
`drain_providers()` / `drainProviders()` succeeds.

Standalone/custom TypeScript `ToolPlanner` emitters receive the controller's
linked `AbortSignal` for start events and must settle when it aborts. The stable
`AgentRuntime` path uses the runtime-owned bounded in-memory committer; a custom
`EventCommitter.commit()` has no signal-capable ABI and must be independently
bounded. Kaji keeps the tool claim and permit owned until the append physically
settles, preventing a late Started event from overtaking Failed. A boundary that
never settles remains visible through `drainTools()` and requires process
restart.

The in-memory coordinator, event store, journal, and idempotency ledger are
process-local. Kaji ships and release-certifies no durable/distributed
replacement in the embedded beta. Hosts may inject their own implementations,
but their durability, deletion, and cross-process correctness remain host
responsibilities.

`Clock`, `IdFactory`, `SystemClock`, and `SystemIdFactory` are public Python
determinism seams. Applications normally keep the system defaults; tests may
inject scoped implementations through `AgentBuilder.clock()` and
`AgentBuilder.id_factory()`.

## Promotion evidence

The local release rehearsal is necessary but not sufficient:

```bash
uv run --project kaji/packages/py python kaji/scripts/beta_release_check.py --release
```

Promotion additionally requires evidence from the exact release commit for:

- Python 3.11 and the latest supported Python;
- exact-current-run TypeScript npm and Bun install, scaffold, no-key, Echo
  lifecycle, cold, and warm receipts aggregated under
  `kaji-onboarding` on GitHub-hosted Linux/x64: Node 22 on
  `ubuntu-22.04` and Node 24 on `ubuntu-24.04`; this is not evidence for other
  runtimes or platforms;
- required keyed OpenAI tool loops in Python under the
  separate `kaji-release` review boundary; a missing `OPENAI_API_KEY` blocks
  release rather than producing a readiness skip;
- the immutable-reference paired A/B benchmark on three numbered same-attempt
  `macos-15` matrix replicas, including retained raw runner/image receipts;
- the separate protected 30-minute soak of the exact candidate;
- an immutable signed tag with the configured signer identity;
- exact-artifact SBOM/provenance and registry publication verification;
- a closed publisher-identity receipt and the sole npm write under the
  independent `kaji-publish` review boundary. PyPI remains deferred.

The protected rehearsal and publish workflows are authoritative; the three
environment names above are distinct approval scopes, not workflow names. See
[releasing.md](releasing.md) for the signed release and rollback runbook.
