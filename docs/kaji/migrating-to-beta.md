# Migrating to the Beta Contract

The beta wire contract is version `1.0.0`. Apply these changes before enabling
side-effect tools.

## Executor signature

Before, executors commonly accepted only a tool name and arguments, handlers
had no caller identity, and omitted risk could behave like a read. After,
Python receives `ToolInvocation`; TypeScript receives `(name, args, context)`;
and every enabled tool declares risk.

Pre-beta executor overloads were removed rather than carried into the beta
contract. Update the call boundary before installing the beta artifact:

<!-- docs-test:python-migration-after:start -->
```python
import kaji


async def execute(invocation: kaji.ToolInvocation) -> dict:
    invocation.context.cancellation_token.raise_if_cancelled()
    return {
        "tool": invocation.name,
        "principal": invocation.context.principal_id,
        "idempotency_key": invocation.context.idempotency_key,
    }


@kaji.function_tool(risk="read")
async def inspect(context: kaji.ToolExecutionContext, value: str) -> dict:
    return {"value": value, "turn_id": context.turn_id}
```
<!-- docs-test:python-migration-after:end -->

<!-- docs-test:typescript-migration-after:start -->
```ts
import type { ToolExecutionContext, ToolExecutor } from "@kaji/sdk";

const execute: ToolExecutor = async (
  name: string,
  _args: Readonly<Record<string, unknown>>,
  context: ToolExecutionContext,
) => ({
  tool: name,
  principal: context.principalId,
  idempotencyKey: context.idempotencyKey,
});

void execute;
```
<!-- docs-test:typescript-migration-after:end -->

Supply `TurnContext` per turn for multi-tenant hosts. A builder default is only
for an explicitly single-tenant application. Python deadlines are absolute
monotonic seconds; TypeScript deadlines are absolute epoch milliseconds. Pair
either with `CancellationToken` to request cooperative cancellation. Providers
observe cancellation at supported checkpoints or stream yields; it is not a
hard interrupt for every in-flight request.

## Required risk and caller identity

Old declarations without risk and tool-capable turns without a principal now
fail before approval, provider-directed execution, or side effects. These
"before" examples execute the failure modes intentionally.

<!-- docs-test:python-risk-context-before:start -->
```python
import asyncio

import kaji


class MissingRisk(kaji.Integration):
    namespace = "migration"

    @kaji.tool(description="Unclassified tool.", parameters={"type": "object"})
    async def unsafe(self, context: kaji.ToolExecutionContext, args: dict) -> dict:
        return {"ok": True}


try:
    (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock"))
        .integration(MissingRisk())
        .build()
    )
except kaji.UnclassifiedToolRiskError:
    pass
else:
    raise AssertionError("missing tool risk must fail")


class Classified(kaji.Integration):
    namespace = "migration"

    @kaji.tool(
        description="Classified tool.",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )
    async def inspect(self, context: kaji.ToolExecutionContext, args: dict) -> dict:
        return {"principal": context.principal_id}


async def verify_missing_identity() -> None:
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock"))
        .integration(Classified())
        .build()
    )
    try:
        await runtime.turn("Call inspect.")
    except kaji.MissingToolIdentityError:
        return
    raise AssertionError("tool-capable turn without principal must fail")


asyncio.run(verify_missing_identity())
```
<!-- docs-test:python-risk-context-before:end -->

<!-- docs-test:python-risk-context-after:start -->
```python
import asyncio

import kaji


class Classified(kaji.Integration):
    namespace = "migration"

    @kaji.tool(
        description="Classified tool.",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )
    async def inspect(self, context: kaji.ToolExecutionContext, args: dict) -> dict:
        return {"principal": context.principal_id}


async def verify_identity() -> None:
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock"))
        .integration(Classified())
        .build()
    )
    result = await runtime.turn(
        "Call inspect.",
        context=kaji.TurnContext(principal_id="user-42"),
    )
    assert result.tool_call_events


asyncio.run(verify_identity())
```
<!-- docs-test:python-risk-context-after:end -->

<!-- docs-test:typescript-risk-context-before:start -->
```ts
import {
  AgentBuilder,
  MissingToolIdentityError,
  ToolRegistry,
  UnclassifiedToolRiskError,
  functionTool,
  type ToolSpec,
} from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";
import { z } from "zod";

const unsafe = {
  name: "unsafe",
  description: "Unclassified tool.",
  parameters: { type: "object" },
} as unknown as ToolSpec;
try {
  new ToolRegistry().register(unsafe, async () => ({ ok: true }));
  throw new Error("missing tool risk must fail");
} catch (error) {
  if (!(error instanceof UnclassifiedToolRiskError)) throw error;
}

const classified = functionTool(
  {
    name: "inspect",
    description: "Classified tool.",
    parameters: z.object({}),
    risk: "read",
  },
  async (_args, context) => ({ principal: context.principalId }),
);
const runtime = new AgentBuilder()
  .provider(new MockProvider())
  .tool(classified)
  .build();
try {
  await runtime.turn("Call inspect.");
  throw new Error("tool-capable turn without principal must fail");
} catch (error) {
  if (!(error instanceof MissingToolIdentityError)) throw error;
}
```
<!-- docs-test:typescript-risk-context-before:end -->

<!-- docs-test:typescript-risk-context-after:start -->
```ts
import { AgentBuilder, functionTool } from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";
import { z } from "zod";

const inspect = functionTool(
  {
    name: "inspect",
    description: "Classified tool.",
    parameters: z.object({}),
    risk: "read",
  },
  async (_args, context) => ({ principal: context.principalId }),
);
const runtime = new AgentBuilder()
  .provider(new MockProvider())
  .tool(inspect)
  .build();
const result = await runtime.turn("Call inspect.", {
  context: { principalId: "user-42" },
});
if (result.toolCallEvents.length === 0) throw new Error("tool was not called");
```
<!-- docs-test:typescript-risk-context-after:end -->

## Stored events and cursors

Before, callers could sort unsequenced events by timestamp and read an entire
session. After, new events are drafts until committed; stored events have a
contiguous sequence and turn events share one turn ID.

The frozen `1.0` wire definition requires serialized rows to carry `id`,
`type`, `version`, `timestamp`, and `session_id`; stored rows also require a
positive `sequence`. IDs are opaque non-empty strings, not UUID-only. Unknown
fields and fields belonging to a different event variant are rejected instead
of being ignored or coerced.

Durable integral numbers, including integral floating-point values, must stay
within the I-JSON range `-9,007,199,254,740,991` through
`9,007,199,254,740,991`. The former pre-beta acceptance of `2**53` is removed;
finite non-integral values remain valid. Check an existing stored-event log
without modifying it before promotion:

```console
uv run --project kaji python kaji/scripts/check_event_migration.py path/to/events.jsonl
```

The preflight reports every incompatible line with
`EVENT_SCHEMA_INCOMPATIBLE` and a normalized JSON Pointer, then exits non-zero.

<!-- docs-test:python-cursor-before:start -->
```python
import asyncio

import kaji


async def full_read() -> None:
    store = kaji.InMemoryEventStore()
    await store.append(kaji.UserMessage(session_id="cursor", content="one"))
    await store.append(kaji.UserMessage(session_id="cursor", content="two"))
    events = await store.get_events("cursor")
    assert len(events) == 2


asyncio.run(full_read())
```
<!-- docs-test:python-cursor-before:end -->

<!-- docs-test:python-cursor-after:start -->
```python
import asyncio

import kaji


async def cursor_read() -> None:
    store = kaji.InMemoryEventStore()
    first = await store.append(
        kaji.UserMessage(session_id="cursor", turn_id="turn-1", content="one")
    )
    second = await store.append(
        kaji.UserMessage(session_id="cursor", turn_id="turn-2", content="two")
    )
    assert (first.event.sequence, second.event.sequence) == (1, 2)
    page = await store.get_events("cursor", after_sequence=1, limit=1)
    assert [(event.sequence, event.turn_id) for event in page] == [(2, "turn-2")]
    assert await store.last_sequence("cursor") == 2


asyncio.run(cursor_read())
```
<!-- docs-test:python-cursor-after:end -->

<!-- docs-test:typescript-cursor-before:start -->
```ts
import { EventType, InMemoryEventStore, KajiEvent } from "@kaji/sdk";

const store = new InMemoryEventStore();
await store.append(
  KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "cursor", content: "one" }),
);
await store.append(
  KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "cursor", content: "two" }),
);
const events = await store.getEvents("cursor");
if (events.length !== 2) throw new Error("full read failed");
```
<!-- docs-test:typescript-cursor-before:end -->

<!-- docs-test:typescript-cursor-after:start -->
```ts
import { EventType, InMemoryEventStore, KajiEvent } from "@kaji/sdk";

const store = new InMemoryEventStore();
const first = await store.append(
  KajiEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: "cursor",
    turn_id: "turn-1",
    content: "one",
  }),
);
const second = await store.append(
  KajiEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: "cursor",
    turn_id: "turn-2",
    content: "two",
  }),
);
if (first.event.sequence !== 1 || second.event.sequence !== 2) {
  throw new Error("sequence assignment failed");
}
const page = await store.getEvents("cursor", { afterSequence: 1, limit: 1 });
if (page[0]?.sequence !== 2 || page[0]?.turn_id !== "turn-2") {
  throw new Error("cursor or turn ID failed");
}
if ((await store.lastSequence("cursor")) !== 2) throw new Error("last sequence failed");
```
<!-- docs-test:typescript-cursor-after:end -->

Unsequenced historical logs are not accepted by the beta runtime. Migrate them
offline by choosing and documenting one source order, assigning contiguous
sequence values, validating every stored event, and preserving original
timestamps only as audit metadata. Mixed logs are rejected.

## Typed approvals

Replace Boolean approval results with explicit decisions:

<!-- docs-test:python-approval-after:start -->
```python
import kaji


class ApprovalHandler:
    async def request(self, call, context) -> kaji.ApprovalDecision:
        return kaji.ApprovalDecision(granted=True, code="approved")
```
<!-- docs-test:python-approval-after:end -->

<!-- docs-test:typescript-approval-after:start -->
```ts
import type { TypedApprovalHandler } from "@kaji/sdk";

const approvalHandler: TypedApprovalHandler = {
  async request() {
    return { granted: true, code: "approved" };
  },
};
void approvalHandler;
```
<!-- docs-test:typescript-approval-after:end -->

Rejections must include one of `rejected`, `timeout`, `cancelled`, or
`unavailable` and a safe public reason. `recorded=true` is reserved for a
bridge that already persisted the exact decision through the canonical journal.

## Zod 4

`@kaji/sdk` supports Zod `>=4.3 <5` as a peer dependency. Upgrade Zod before the
SDK and remove any Zod 3 lock entry. Kaji uses Zod for schema/refinement
validation but passes the original detached provider arguments to the handler;
defaults, coercions, and transforms do not rewrite tool input.

The before block models a lockfile still pinned to Zod 3 and proves the
compatibility guard rejects it. The after block executes the Zod 4-only schema
export API used by Kaji.

<!-- docs-test:typescript-zod-before:start -->
```ts
function requireZod4(version: string): void {
  const major = Number(version.split(".")[0]);
  if (major !== 4) throw new Error("@kaji/sdk requires Zod 4");
}

try {
  requireZod4("3.25.0");
  throw new Error("Zod 3 must be rejected");
} catch (error) {
  if (!(error instanceof Error) || !error.message.includes("requires Zod 4")) throw error;
}
```
<!-- docs-test:typescript-zod-before:end -->

<!-- docs-test:typescript-zod-after:start -->
```ts
import { z } from "zod";

const parameters = z.object({ id: z.string() });
const jsonSchema = z.toJSONSchema(parameters);
if (jsonSchema.type !== "object") throw new Error("Zod 4 schema export failed");
```
<!-- docs-test:typescript-zod-after:end -->

```bash
npm install @kaji/sdk@0.2.0-beta.1 'zod@>=4.3 <5'
```

## Manifest and index schema

Pre-beta API-key auth and tools without risk are rejected:

<!-- docs-test:manifest-before:start -->
```json
{
  "name": "echo",
  "version": "0.1.0",
  "namespace": "echo",
  "description": "Pre-beta manifest.",
  "auth": { "kind": "api_key", "env": "ECHO_API_KEY" },
  "files": ["index.ts"],
  "tools": [{ "name": "say", "description": "Echo input." }]
}
```
<!-- docs-test:manifest-before:end -->

The beta manifest uses a closed auth variant, executable tool metadata, and
validated installation metadata:

<!-- docs-test:manifest-after:start -->
```json
{
  "name": "echo",
  "version": "0.1.0",
  "namespace": "echo",
  "description": "Validated manifest.",
  "auth": {
    "kind": "env",
    "env": "ECHO_API_KEY",
    "optional": true,
    "docs": "https://example.com/auth"
  },
  "files": ["index.ts"],
  "tools": [
    {
      "name": "say",
      "description": "Echo input.",
      "parameters": {
        "type": "object",
        "properties": { "message": { "type": "string" } },
        "required": ["message"],
        "additionalProperties": false
      },
      "risk": "read",
      "parallel_safe": false
    }
  ],
  "extras": ["echo"],
  "peerDeps": { "zod": ">=4.3 <5" }
}
```
<!-- docs-test:manifest-after:end -->

Before, an index entry could be a path string:

<!-- docs-test:index-before:start -->
```json
{"integrations":{"echo":"echo/manifest.json"}}
```
<!-- docs-test:index-before:end -->

After, the index points to its own schema and makes stability/runtime ownership
explicit:

<!-- docs-test:index-after:start -->
```json
{
  "$schema": "./index.schema.json",
  "version": "0.1.0",
  "integrations": {
    "echo": {
      "manifest": "echo/manifest.json",
      "stability": "beta",
      "runtimes": ["python", "typescript"]
    }
  }
}
```
<!-- docs-test:index-after:end -->

Migrate manifest auth to the closed `none`, `env`, or `oauth` union; add risk
to every tool; remove unknown fields; and use safe contained relative paths.
Replace checks for `INVALID_INTEGRATION_MANIFEST` or
`INVALID_INTEGRATION_INDEX` with `INTEGRATION_SCHEMA_INVALID`; use the
exception class and JSON Pointer to distinguish the document. Experimental
CLI opt-in denial now uses `INTEGRATION_EXPERIMENTAL`.

Each manifest tool now carries executable `parameters`, `parallel_safe`, and
optional `timeout_ms` metadata. Stable Echo metadata must exactly match the
registered `ToolSpec`; run `kaji/scripts/check_integration_abi.py --explain`
and resolve every `INTEGRATION_ABI_MISMATCH` before release.

## Whole-turn deadline and provider quarantine

The runtime now applies one effective deadline to queue wait, provider open and
streaming, approval, and tool work. Python caller deadlines use absolute
monotonic seconds in `deadline_monotonic`. TypeScript's removed absolute
`deadlineMs` field is now `deadlineAtMs`; use `deadlineAfter(timeoutMs)` when
starting from a duration. Delete application-owned cancellation timers that
attempt to duplicate the runtime's 120-second work limit.

`TURN_TIMEOUT` now carries phase, retryability, and `not_started`, `failed`, or
`unknown` outcome. A provider that ignores the 5-second cancellation grace
raises `PROVIDER_CANCELLATION_CONTRACT_VIOLATION` and quarantines the session.
Drain and replace it before another turn, or restart if it never settles.

## Durable results and coalesced deltas

Tool and workflow success results are validated as detached canonical JSON
before idempotency completion and persistence. They must use finite values,
I-JSON-safe integers, and fit the 64 KiB result limit; the complete stored
event must fit 1 MiB. Invalid values now fail with `INVALID_TOOL_RESULT`
instead of poisoning later replay.

Provider text, tool arguments, total response bytes, and tool-call count are
bounded. Durable deltas may be coalesced into chunks of at most 4 KiB. Only the
ordered concatenated text is stable; do not rely on vendor chunk boundaries or
one durable delta per provider chunk.

## Removed pre-beta compatibility

Two-argument Python executors, user-ID registry overloads, Boolean approval
callbacks, inferred context aliases, and unsequenced replay are not part of the
beta artifacts. Migrate those boundaries before upgrading.
