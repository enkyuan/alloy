# Troubleshooting

## `MISSING_TOOL_IDENTITY`

The runtime offered at least one tool but the turn had no principal. Pass a
per-turn `TurnContext`, or configure an explicit single-tenant builder default.
Do not invent a shared literal identity inside an executor. Text-only agents
need no principal.

## `INVALID_TOOL_SCHEMA` or `INVALID_TOOL_ARGUMENTS`

Tool schemas use Draft 2020-12 with format checking. Inspect the normalized
JSON Pointer and fix the schema or model-produced arguments. Validation happens
before approval and side effects. In TypeScript, use Zod 4; Zod 3 is outside
the supported peer range.

## `TOOL_TIMEOUT` or `TOOL_CANCELLED` with `outcome=unknown`

The handler had already started, so an external side effect may have happened.
Do not retry automatically. Reconcile the external system with
`<session_id>:<tool_call_id>`, then decide whether a manual retry is safe.

## `drainTools()` keeps reporting a tool whose handler never started

The TypeScript runtime waits for the `tool.call.started` append to physically
settle before it records a timeout failure, so a late Started event cannot
overtake Failed. A standalone/custom `ToolPlanner` emitter receives the start
callback's optional `AbortSignal` and must settle when it aborts. The
`AgentRuntime` custom `EventCommitter.commit()` ABI does not receive that
signal, so custom committers there must be independently bounded. If either
boundary never settles, the claim and permit remain owned, retries stay
blocked, and `drainTools()` continues to report the call. Restart the process;
do not fabricate a terminal event or retry the call.

## Subscriber overflow

Catch `EventBufferOverflowError`, record `last_sequence`/`lastSequence`, and
open a new journal subscription after that cursor. Do not restart the agent
turn; persisted history remains authoritative.

## Replay rejects a log

Stable replay requires one session, contiguous unique sequences, and no mixed
legacy rows. Fully unsequenced historical logs must use the named legacy replay
function, then be migrated offline. Timestamp sorting is not a stable replay
contract.

## Integration is experimental

Echo is the only beta catalog entry. The CLI requires
`--allow-experimental` for HTTP, Web, filesystem, and SQLite. This flag opts
into an unsupported surface; it does not promote the integration. HTTP/Web
also require an application-owned bound transport or egress proxy.

## Normalized provider errors

Catch the package-root `ProviderError` (`from kaji import ProviderError` or
`import { ProviderError } from "@kaji/sdk"`) and pass it to
`normalize_provider_error()` or `normalizeProviderError()`. All Kaji provider
auth, rate-limit, network, configuration, and API failures cross that boundary.
Do not pass arbitrary vendor exceptions or log raw provider responses, causes,
prompts, tool arguments, credentials, or headers. The normalized shape is safe
for routing and retry policy, not a full diagnostic payload.

## A local release check passed, but release is still blocked

`beta_release_check.py --release` is an offline rehearsal. It does not prove
the protected keyed-provider run, floor/latest runtime matrix, full benchmark,
30-minute soak, real signed tag, provenance, or publication. Evidence must
come from the exact release commit. See [production-beta.md](production-beta.md)
and [releasing.md](releasing.md).
