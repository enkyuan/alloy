# Troubleshooting

## `INVALID_TOOL_RESULT`

The handler returned a value that cannot cross the durable JSON boundary or
exceeds 64 KiB. Inspect the safe subject/JSON Pointer and tool name, then return
finite JSON within the I-JSON integer range. The outcome is `unknown`; do not
automatically retry a tool that may have produced an external effect.

## `TURN_TIMEOUT`

Inspect `phase`, configured/effective limit, `retryable`, and `outcome`.
Queue and pre-execution approval timeouts are `not_started` and may be retried
under application policy. Active tool and provider-stream timeouts require
manual outcome review. The default work limit is 120 seconds plus at most a
5-second provider cancellation grace.

## `PROVIDER_CANCELLATION_CONTRACT_VIOLATION`

The provider ignored cancellation beyond the grace period and the session is
quarantined. Drain and replace the provider, then close the runtime. If the
operation never settles, restart the process; do not start another turn for
that session.

## `PROVIDER_OUTPUT_LIMIT`

The diagnostic names only the closed text, tool-argument, total-response, or
tool-count dimension and its configured limit. Reduce model output or the tool
schema. Do not log the rejected provider body.

## `INTEGRATION_ABI_MISMATCH`

Use the redacted JSON Pointer, expected/actual field, and remediation command.
Update the canonical manifest or executable runtime metadata, then run
`kaji/scripts/check_integration_abi.py --explain`. Do not bypass the Echo
stable-ABI check.

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

Stable replay requires one session and contiguous unique sequences. Migrate
unsequenced historical rows offline before loading them; timestamp sorting is
not a runtime replay contract.

The TypeScript CLI also fails closed on any corrupt JSONL line. Its human and
JSON output are safe projections and never include prompts, assistant text,
tool arguments/results, arbitrary metadata, keys, or raw cause strings.

## Integration is experimental

Echo is the only beta catalog entry. The CLI requires
`--allow-experimental` for GitHub. This flag opts into an unsupported surface;
it does not promote the integration.

## Normalized provider errors

Catch the package-root `ProviderError` (`from kaji import ProviderError` or
`import { ProviderError } from "kaji"`) and pass it to
`normalize_provider_error()` or `normalizeProviderError()`. All Kaji provider
auth, rate-limit, network, configuration, and API failures cross that boundary.
Do not pass arbitrary vendor exceptions or log raw provider responses, causes,
prompts, tool arguments, credentials, or headers. The normalized shape is safe
for routing and retry policy, not a full diagnostic payload.

## A local release check passed, but release is still blocked

`beta_release_check.py --release` is an offline rehearsal. It does not prove
the exact-current-run TypeScript onboarding aggregate reviewed in
`kaji-onboarding`, the keyed-provider run reviewed separately in
`kaji-release`, the floor/latest runtime matrix, three-replica paired A/B
benchmark, separate 30-minute soak, real signed tag, SBOM/provenance, closed
publisher identity, or the sole npm write reviewed in `kaji-publish`.
The protected rehearsal and publish workflows are authoritative. The
benchmark must use the checked-in immutable reference, measure five adjacent
pairs after two warmups on each of three numbered same-attempt `macos-15`
matrix replicas, and retain raw runner/image receipts. Diagnostic runner names
may repeat. Evidence must come from the exact release commit. See
[production-beta.md](production-beta.md) and [releasing.md](releasing.md).
