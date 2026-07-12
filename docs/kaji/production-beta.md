# Kaji Production Beta Operating Contract

Kaji is in pre-beta release implementation. The stable core described here is
implemented and covered by local deterministic gates, but promotion is blocked
until the same release commit passes required keyed OpenAI and Anthropic tool
loops in both SDKs, floor/latest runtime, full benchmark, 30-minute soak,
signed-tag, provenance, and publication checks. Do not describe either package
as production beta-ready before those artifacts are attached to the release.

The shared machine contract is
[`kaji/contracts/beta-core-v1.json`](../../kaji/contracts/beta-core-v1.json).
The feature promise is generated and checked through
[`kaji/RELEASE_MATRIX.md`](../../kaji/RELEASE_MATRIX.md).

## First success

These examples use the deterministic mock provider so they run from the exact
installed wheel and npm tarball without credentials. Replace it with OpenAI or
Anthropic only after this local path works. Both examples demonstrate the same
four boundaries:

1. A text-only turn needs no principal because it cannot execute a tool.
2. A tool-enabled turn supplies an explicit principal and every tool declares risk.
3. A whole-turn deadline pairs the tool deadline with cooperative cancellation.
4. Results expose turn, event, and sequence IDs; Kaji provider errors normalize
   to a redaction-safe shape.

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
    print(text.session_id, text.turn_id, [event.sequence for event in text.events])

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
import {
  AgentBuilder,
  Integration,
  ProviderConfigError,
  deadlineAfter,
  normalizeProviderError,
  tool,
} from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";
import { z } from "zod";

class EchoIntegration extends Integration {
  namespace = "docs";

  ping = tool(
    {
      description: "Return a deterministic acknowledgement.",
      parameters: z.object({}),
      risk: "read",
    },
    async (_args, context) => ({ ok: true, principal: context.principalId }),
  );
}

const textRuntime = new AgentBuilder()
  .provider(new MockProvider({ reply: "hello" }))
  .build();
const text = await textRuntime.turn("Say hello.");
if (text.text !== "hello") throw new Error("unexpected text result");
if (!text.events.every((event) => event.turn_id === text.turnId)) {
  throw new Error("turn IDs did not propagate");
}
console.log(text.sessionId, text.turnId, text.events.map((event) => event.sequence));

const toolRuntime = new AgentBuilder()
  .provider(new MockProvider())
  .integration(new EchoIntegration())
  .build();
const toolResult = await toolRuntime.turn("Call ping.", {
  context: {
    principalId: "docs-user",
    deadlineAtMs: deadlineAfter(30_000),
  },
});
if (toolResult.toolCallEvents.length === 0) throw new Error("tool was not called");

const normalized = normalizeProviderError(
  new ProviderConfigError("safe public message", { service: "example" }),
);
console.log(normalized.code, normalized.retryable);
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

## Stable core

The beta promise is the cross-SDK embedded loop: agent builder and runtime,
same-session coordination, cancellation, sequenced in-memory event history and
replay, tool schema/policy/execution, OpenAI and Anthropic adapters, and the echo
catalog integration. RAG/retrieval may be implemented in Python but remains
experimental and outside this promise.

Echo is the only beta catalog entry. TypeScript HTTP, Web, filesystem, and
SQLite integrations are experimental and require explicit opt-in. Python-only
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
process-local. Inject durable/distributed implementations when work spans
processes or must survive restart.

`Clock`, `IdFactory`, `SystemClock`, and `SystemIdFactory` are public Python
determinism seams. Applications normally keep the system defaults; tests may
inject scoped implementations through `AgentBuilder.clock()` and
`AgentBuilder.id_factory()`.

## Promotion evidence

The local release rehearsal is necessary but not sufficient:

```bash
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py --release
```

Promotion additionally requires evidence from the exact release commit for:

- Python 3.11 and the latest supported Python;
- Node 22 and 24;
- required keyed OpenAI and Anthropic tool loops in both Python and TypeScript;
  a missing credential blocks release rather than producing a readiness skip;
- dedicated-runner full benchmarks and the 30-minute soak;
- an immutable signed tag with the configured signer identity;
- exact-artifact SBOM/provenance and registry publication verification.

See [releasing.md](releasing.md) for the signed release and rollback runbook.
