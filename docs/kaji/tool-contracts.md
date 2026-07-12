# Tool Contracts

## Schema validation

Tool parameters are JSON Schema Draft 2020-12. Both SDKs validate complete
nested constraints and formats before approval or handler execution. Invalid
schemas fail registration; invalid arguments fail with a normalized code and
JSON Pointer. TypeScript uses Zod 4 only as a declaration/validation input and
discards defaults, coercions, and transforms so handlers receive a detached
copy equivalent to the provider arguments.

Tool arguments persisted in durable events must be finite JSON and no larger
than 65,536 UTF-8 bytes in canonical form. The limit is not configurable in
the beta contract.

Tool and workflow results cross the same durable boundary before idempotency
bookkeeping or success-event construction. Values are detached canonical JSON:
cycles, class instances, functions, non-finite numbers, lone surrogates, and
integers outside the I-JSON safe range fail. A tool result is limited to 64 KiB
and the whole stored event to 1 MiB. `INVALID_TOOL_RESULT` reports the tool,
closed durable-value subject/pointer, `outcome=unknown`, and the limit without
including the rejected value.

## Identity and risk

Every enabled tool requires one explicit risk:

`read`, `write`, `external_effect`, `destructive`, or `admin`.

Money-moving operations are `destructive`. Unknown or omitted risk fails
closed.

A text-only turn may omit principal context. A turn that can execute a tool
must supply `TurnContext.principal_id` or `TurnContext.principalId`, either per
turn or as an explicitly configured single-tenant builder default. Before a
side effect, the handler receives the principal, session, turn, request, trace,
tool-call, idempotency, cancellation, deadline, and metadata values in an
immutable execution context.

## Execution bounds

Tools execute sequentially unless explicitly marked parallel-safe. The runtime
allows at most four parallel handlers and applies a 30-second queue-to-
completion deadline by default. A tool-specific timeout may only tighten that
deadline. Approval defaults to 300 seconds.

Cancellation or timeout before the handler starts has `outcome=not_started`.
After the handler starts, a non-cooperative external side effect may have an
unknown outcome. Kaji records `outcome=unknown`, retains the idempotency
tombstone, and does not auto-retry. Reconcile the external system using the
provided key:

```text
<session_id>:<tool_call_id>
```

External systems must honor that key for retry-safe effects. The default
in-memory ledger holds 10,000 entries and completed results for 86,400 seconds;
unknown-outcome entries are not silently evicted. Durable side-effect tools
should inject a restart-safe ledger.

## Executor and handler shapes

Python executors accept one `ToolInvocation` containing name, arguments, and
`ToolExecutionContext`. TypeScript executors accept `(name, args, context)`.
Integration handlers in both SDKs receive arguments plus the resolved context;
Python's `ToolContext` remains a compatibility alias for
`ToolExecutionContext`.

## Approval decisions

Approval handlers return typed decisions. Approval, rejection, timeout,
cancellation, and unavailable-handler outcomes persist an explicit lifecycle
and leave no pending approval after replay.

```python
return kaji.ApprovalDecision(granted=True, code="approved")
```

```ts
return { granted: true, code: "approved" };
```

Boolean approval callbacks remain a deprecated compatibility path. Production
hosts should use a typed handler and the canonical runtime journal. External
decision bridges match turn ID, tool-call ID, and tool name.
