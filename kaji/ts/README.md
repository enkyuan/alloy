# Kaji (TypeScript)

`@kaji/sdk` is an embeddable SDK for building agents in TypeScript: import
the pieces you need and compose them. The core is infra-free (no database,
server, or environment configured). It mirrors the runtime core of the Python
`kaji` SDK.

<!-- canonical-status-links:start -->
> Canonical documentation: https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md
> Release status and evidence: https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md
<!-- canonical-status-links:end -->

See [**Kaji MVP**](https://github.com/enkyuan/alloy/blob/main/docs/MVP.md) for
the full five-step developer path and scope definition.

## Install

```bash
npm install @kaji/sdk@0.2.0-beta.2 zod openai        # OpenAI
# or
npm install @kaji/sdk@0.2.0-beta.2 zod @anthropic-ai/sdk  # Anthropic
# or: bun add @kaji/sdk@0.2.0-beta.2 zod openai
```

`zod` is a required peer dependency (Zod 4). `openai` and `@anthropic-ai/sdk`
are optional peers -- install only the one you use. Supported runtimes are
Node 22 or 24 with npm or Bun. Supported compilers are TypeScript 5.7 and the
current TypeScript 6 release.

## Quick start

First prove a text-only turn without credentials. No principal is required
because this runtime has no enabled tools:

```ts
import { AgentBuilder } from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";

const runtime = new AgentBuilder()
  .provider(new MockProvider({ reply: "hello" }))
  .build();
const result = await runtime.turn("Say hello.");
console.log(result.text, result.accounting);
```

## Privileged event journal and disposal

> **Security boundary:** `TurnResult.events` and `AgentRuntime.history()` are a
> privileged full-fidelity journal. They can contain user prompts,
> provider-derived text and deltas, tool arguments, tool results, and arbitrary
> metadata. They are not redaction-safe; never log, attach, or export them
> wholesale.

`MetricsSink` and `TraceSink` are best-effort timing and correlation surfaces,
not complete business or audit records. Sink failures are swallowed so
observability cannot change turn behavior. Traces still contain access-controlled
correlation identifiers even though they omit full event payloads.

Failed turns throw: failed turns have no `TurnResult` and therefore no
`TurnResult.events` or successful-turn `TurnAccounting` aggregate. Applications
that need failure evidence must choose a preselected session ID, retain the
caught error separately for live control flow, page history with an
exclusive `afterSequence` cursor until an empty page, and reduce to an allowlist
before export; generic provider failures have no durable recovery code today. Use the
caught typed provider error and `normalizeProviderError()` where applicable.
Always page until an empty page; a short page is not proof of exhaustion.

```ts
import type { AgentRuntime, StoredKajiEvent } from "@kaji/sdk";

async function pageHistory(runtime: AgentRuntime, sessionId: string, limit = 128) {
  const events: StoredKajiEvent[] = [];
  let afterSequence = 0;
  for (;;) {
    const page = await runtime.history(sessionId, { afterSequence, limit });
    if (page.length === 0) return events;
    const nextSequence = page.at(-1)!.sequence;
    if (nextSequence <= afterSequence) throw new Error("history cursor did not advance");
    events.push(...page);
    afterSequence = nextSequence;
  }
}

const SAFE_FIELDS = [
  "tool_name",
  "tool_call_id",
  "error_code",
  "phase",
  "retryable",
  "outcome",
  "reason_code",
  "recovery_code",
  "doc_url",
] as const;

function safeJournalEvidence(event: StoredKajiEvent): Record<string, unknown> {
  const safe: Record<string, unknown> = { sequence: event.sequence, type: event.type };
  if (event.turn_id !== undefined) safe.turn_id = event.turn_id;
  for (const field of SAFE_FIELDS) {
    const value = Reflect.get(event, field);
    if (value !== undefined) safe[field] = value;
  }
  return safe; // never content, delta, tool_args, result, metadata, or raw session_id
}

const sessionId = crypto.randomUUID();
let failure: { error: unknown } | undefined;
try {
  await runtime.turn("Investigate the failure.", { sessionId });
} catch (error) {
  failure = { error }; // retain separately; never add this value to safe evidence
}

if (failure !== undefined) {
  stopIngress(sessionId);
  await runtime.drainTools(10_000);
  await runtime.drainProviders(10_000);
  try {
    const privilegedHistory = await pageHistory(runtime, sessionId);
    const exportableEvidence = privilegedHistory.map(safeJournalEvidence);
    sendToYourIncidentStore(exportableEvidence);
  } catch (evidenceError) {
    handleEvidenceExportError(evidenceError); // report separately; original failure stays authoritative
  } finally {
    await runtime.purgeSession(sessionId);
  }
  handleOriginalError(failure.error); // cleanup finished; preserve original control flow
}
```

Before disposal, stop ingress for the named session so another caller cannot
race the drain-to-purge interval. On a live runtime, drain tools and providers,
page and reduce any required evidence, then call `purgeSession(sessionId)` while
leaving other sessions running. For whole-runtime shutdown, `close()` may run
first to reject future turn APIs; history and purge remain callable afterward.
`close()` does not delete retained history and does not cancel already-active
work.

This lifecycle is identical to Python's supported in-memory path. The bounded
store never evicts a retained session implicitly: a full store raises
`EventStoreCapacityError` until the host explicitly purges one. Runtime purge
closes its old subscribers, removes the event and ID indexes, and clears every
runtime owner sharing the store; a standalone raw listener must be closed by
its caller. Reset cursors to `0` before reuse; the next generation begins at
sequence `1`.

`PurgeableEventStore.purgeSession(sessionId)` is the public one-argument
store-only capability, detected by `supportsSessionPurge()`. Runtime purge also
requires Kaji's internal opaque coordinated capability, so a custom store that
implements only the public method fails closed at the runtime boundary. Direct
store operations and new owners remain fenced throughout purge. Split delivery
is unsupported because its outbox cannot cross a reused generation.

TypeScript's embedded defaults are bounded, in-memory, and process-local. This
beta ships no persistent event store or distributed coordinator and does not
release-certify host implementations; durability, deletion, and cross-process
correctness are host responsibilities. `purgeSession()` removes SDK-owned
retained indexes and caches but cannot promise VM string zeroization or erase
copies already sent to logs, sinks, providers, custom stores, crash dumps, or
caller-owned objects.

A custom `ToolIdempotencyLedger` must implement optional `releaseSettled()` to
participate in purge. The event store and SDK caches are already cleared before
host ledger cleanup is awaited. If that cleanup rejects, deletion cannot be
rolled back; repair the host ledger and retry the named purge. If it never
settles, the strong `cleanup_pending` tombstone keeps turns, direct store
operations, subscriptions, and new owners fenced. A later runtime purge retries
cleanup without repeating physical deletion. Kaji cannot force hostile
in-process host code to settle. `TurnAccounting` remains TypeScript-only and is
separate from the cross-SDK purge contract.

Then set an API key and add a risk-classified tool with explicit caller
identity, deadline, and cancellation:

```bash
export OPENAI_API_KEY=sk-...
# or: export ANTHROPIC_API_KEY=sk-ant-...
```

```ts
import {
  AgentBuilder,
  OpenAIProvider,
  Integration,
  deadlineAfter,
  tool,
} from "@kaji/sdk";
import { z } from "zod";

class WeatherIntegration extends Integration {
  readonly namespace = "weather";

  readonly getWeather = tool(
    {
      description: "Return weather for a city.",
      parameters: z.object({ city: z.string() }),
      risk: "read",
    },
    async (args, _context) => ({ city: args.city, tempF: 68 }),
  );
}

const runtime = new AgentBuilder()
  .provider(new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! }))
  .integration(new WeatherIntegration())
  .systemPrompt("You are a weather assistant.")
  .build();

const result = await runtime.turn("Weather in Seattle?", {
  context: {
    principalId: "weather-app",
    deadlineAtMs: deadlineAfter(30_000),
  },
});
console.log(result.text, result.accounting);
```

Swap `OpenAIProvider` for `AnthropicProvider` (and `OPENAI_API_KEY` for
`ANTHROPIC_API_KEY`) to use Anthropic.

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable.

### GitHub integration

The experimental TypeScript package subpath exposes a fixed-origin GitHub
integration without copying its source into your application. For an
investigation agent, opt into read-only exposure so the two mutation tools are
not registered or sent to the model.

<!-- docs-test:github-read-only:start -->
```ts
import { AgentBuilder, OpenAIProvider, deadlineAfter } from "@kaji/sdk";
import { createGithubIntegration } from "@kaji/sdk/integrations/github";

const principalId = "github-investigator";
const github = createGithubIntegration({
  repositories: ["owner/repo"],
  toolExposure: "read-only",
  tokenFor: async (context) => {
    if (context.signal.aborted) throw context.signal.reason;
    if (context.principalId !== principalId) throw new Error("GitHub credential unavailable");
    const token = process.env.GITHUB_TOKEN;
    if (!token) throw new Error("GITHUB_TOKEN is required");
    return token;
  },
});

try {
  const runtime = new AgentBuilder()
    .provider(new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! }))
    .integration(github)
    .defaultContext({ principalId })
    .systemPrompt("Use GitHub evidence from owner/repo and cite immutable refs.")
    .build();

  try {
    const result = await runtime.turn("Inspect the latest failed checks.", {
      context: { deadlineAtMs: deadlineAfter(30_000) },
    });
    console.log(result.text);
  } finally {
    try {
      const unsettledTools = await runtime.drainTools(10_000);
      const unsettledProviders = await runtime.drainProviders(10_000);
      if (unsettledTools.length > 0 || unsettledProviders.length > 0) {
        throw new Error("Kaji shutdown did not settle");
      }
    } finally {
      runtime.close();
    }
  }
} finally {
  github.close();
}
```
<!-- docs-test:github-read-only:end -->

`toolExposure` controls which tools reach the model; it does not reduce token
permissions. Keep the repository allowlist narrow and use a fine-grained token
with only the read permissions needed by the selected tools. The callback is
lazy, receives the tool execution context, and returns the raw token; Kaji
validates it and adds the `Bearer` header. `AgentBuilder` does not own the
integration, so close it only after active tool work has settled. See the
[GitHub integration guide](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/integrations/github.mdx)
for the 15-tool catalog, mutation policy, limits, and unsupported surfaces.

`deadlineAtMs` is an absolute Unix epoch value; use `deadlineAfter()` when the
caller has a duration. An earlier caller deadline can tighten, but never extend,
the configured 120-second whole-turn default covering queue wait, provider open
and streaming, approval, and tool work. Cooperative provider shutdown may use
the additional configured cancellation grace.

Catch a Kaji `ProviderError`, then call `normalizeProviderError(error)` for the
redaction-safe `type`, `code`, `service`, `action`, `status`, and `retryable`
fields. The normalizer accepts Kaji provider errors, not arbitrary vendor
exceptions.

See [`docs/kaji/production-beta.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/production-beta.md) for
the installed-package version of both first-success examples and exact default
limits. Operating details are in
[`concurrency-and-ordering.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/concurrency-and-ordering.md),
[`tool-contracts.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/tool-contracts.md), and
[`troubleshooting.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/troubleshooting.md).
Call `runtime.effectiveLimits()` to inspect the immutable
`EffectiveRuntimeLimits` resolved for one runtime.

Runtimes that share the same `EventStore` also share a default per-store turn
coordinator within the current process, so same-session turns serialize even
when separate builders create the runtimes. Different stores do not block one
another. This is not a distributed lock: multi-process deployments must inject
a `SessionTurnCoordinator` backed by shared infrastructure.

## Prove it with a model

OpenAI with `gpt-5.4-mini` is the recommended first live check because it is
cost-effective and exercises the SDK's Chat Completions tool path.

```bash
cd kaji/ts
bun run test:quickstart
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  bun run test:integration tests/integration/openai-tools.test.ts
```

The live test registers a read-only probe tool, verifies the model calls it,
and verifies the runtime emits final assistant text using the tool result.
Release evidence requires protected OpenAI and Anthropic tool loops in both
SDKs on one exact commit. A missing credential blocks that release evidence.
The TS Kimi and Gemini paths are experimental OpenAI-compatible factories, not
native provider implementations.

For the cross-SDK release gate, run from the repository root:

```bash
uv run --project kaji python kaji/scripts/beta_release_check.py
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, mandatory pinned ast-grep boundary checks, and no-key
live-gate hygiene. The ast-grep step guards the Python SDK/service boundary, core package dependency direction, removed tool-model imports, TypeScript optional provider imports, and cancellation error shape.

For the live-gate credential modes specifically:

```bash
uv run --project kaji python kaji/scripts/verify_openai_loop.py
KAJI_REQUIRE_LIVE_KEYS=1 uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

Without `OPENAI_API_KEY`, the first command proves missing-key hygiene only.
It is not provider evidence. The protected release mode requires both
`OPENAI_API_KEY` and `ANTHROPIC_API_KEY` and fails when either is absent.

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

`KAJI_RUN_KEYED_LIVE=1` is not a one-key shortcut. It is the fail-closed
four-cell proof and requires both provider keys, the frozen artifact set, and
the exact 40-character release commit:

```bash
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... \
KAJI_RELEASE_ARTIFACTS_DIR="$PWD/.artifacts/kaji-release" \
KAJI_RELEASE_COMMIT=<40-character-commit> KAJI_RUN_KEYED_LIVE=1 \
uv run --project kaji python kaji/scripts/beta_release_check.py
```

The protected `kaji-beta` workflow is authoritative release evidence; the
single-provider command above is only a local paid smoke test.

## Stability tiers

- **Stable core:** `AgentBuilder`, `AgentRuntime`, `ToolRegistry`,
  `ToolPlanner`, session replay, OpenAI/Anthropic providers, and the in-memory
  event store/committer form the supported embedded-agent surface.
- **Experimental Python-only:** Redis realtime/history, voice/TTS,
  `DocumentRAG`, native Gemini/Kimi providers, tool retrieval, and text/voice
  modalities exist in Python but are not production-hardened.
- **TS not ported:** Redis realtime, voice/TTS, and RAG are not implemented in
  TypeScript. TS Gemini/Kimi remain OpenAI-compatible factories rather than
  native provider implementations.

See https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md for the
cross-SDK release matrix and the exact distinction between stable core,
experimental Python-only surfaces, and TypeScript surfaces that are not ported.

The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
`DocumentRAG`, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.
Gemini and Kimi are OpenAI-compatible factories in TypeScript, not native
provider implementations.

## Approval handler

Tools whose risk exceeds your policy threshold pause for approval before the
runtime executes them. All hosts use `TypedApprovalHandler` and return an
`ApprovalDecision`. `cliApprovalHandler` is a typed dev/REPL implementation
that prints the tool name, risk, and arguments, then reads `y` / `N` on stdin:

```ts
import {
  AgentBuilder,
  cliApprovalHandler,
  openai,
} from "@kaji/sdk";

const agent = new AgentBuilder()
  .provider(openai())
  .approvalHandler(cliApprovalHandler({ label: "agent-a" }))
  .build();
```

Custom hosts implement `TypedApprovalHandler.request(call, context)` and return
an `ApprovalDecision`, for example
`{ granted: true, code: "approved" }` or a rejected decision with an explicit
code and safe reason. See
[`tool-contracts.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/tool-contracts.md) for the lifecycle.

`EventApprovalHandler` requires a non-empty turn ID and accepts a decision only
when `turn_id`, `tool_call_id`, and `tool_name` all match the pending request.
Unscoped or stale backlog decisions are ignored.

## CLI

```
kaji --help                            # list subcommands
kaji add <integration>                 # copy an integration into your project
kaji add <integration> --allow-experimental  # explicitly copy a non-beta template
kaji init [path] --provider mock --yes # no-key TypeScript scaffold
kaji list-integrations                 # enumerate the registry catalog
kaji replay <session.jsonl>            # render a stored JSONL session log
```

This is the embedded `@kaji/sdk` CLI. The standalone cross-language
`@kaji/cli` scaffold has its own `--lang`/`--provider` options; Python's `kaji`
package also exposes additional Python-only maintenance commands.
Generated projects pin dotenvx and load `.env` from their `start` script after
you copy `.env.example` to `.env`.

`echo` is the only beta catalog entry. `github` is the only experimental
catalog entry and requires `--allow-experimental` when copied.

## Global tool registry (advanced)

For simple setups you can use the process-level registry:

```ts
import { executeTool, registerTool, toolSpecFromSchema } from "@kaji/sdk";
import { z } from "zod";

registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() }), "read"),
  async (args, context) => ({
    principalId: context.principalId,
    city: args.city,
    tempF: 68,
  }),
);

const result = await executeTool(
  "get_weather",
  { city: "Seattle" },
  {
    principalId: "user-1",
    sessionId: "session-1",
    turnId: "turn-1",
    requestId: "request-1",
    traceId: "trace-1",
    toolCallId: "call-1",
    idempotencyKey: "session-1:call-1",
    signal: new AbortController().signal,
    metadata: {},
  },
);
```

## What's exported

| Export | What it is |
| --- | --- |
| `EventType`, `KajiEvent` | Event discriminants and Zod-validated event union |
| `EventStore`, `InMemoryEventStore` | Event log that is append-only while retained; explicit session purge is an optional lifecycle capability |
| `EventBus` | In-memory pub/sub per session |
| `replaySession`, `SessionManager`, session store types | Session projection and management |
| `registerTool`, `ToolRegistry`, `toolSpecFromSchema`, `executeTool`, `listToolSpecs` | Tool registry (global + scoped) |
| `ToolPolicy`, `ToolPlanner` | Allow/deny and approval-gated execution |
| `TypedApprovalHandler`, `cliApprovalHandler`, `EventApprovalHandler`, `AutoApprovalHandler` | Structured approval handlers: stdin, event-driven (publishes `TOOL_APPROVAL_REQUESTED` for a host UI to answer), and auto-decide by policy |
| `OpenAIProvider`, `AnthropicProvider` | LLM providers |
| `normalizeProviderError`, `NormalizedProviderError` | Redaction-safe semantic classification for Kaji provider errors |
| `openai`, `anthropic`, `kimi`, `gemini`, `openrouter` | One-line provider factories; Kimi, Gemini, and OpenRouter presets are experimental |
| `getProvider`, `registerProvider` | Name-keyed provider registry, for host code that resolves a provider by config string |
| `generateText`, `streamText` | One-shot provider calls without a full `AgentRuntime`: a single request/response or stream, no event log |
| `AgentRuntime`, `AgentBuilder`, `CancellationToken` | ReAct loop and fluent builder |
| `EffectiveRuntimeLimits` | Immutable values returned by `AgentRuntime.effectiveLimits()` after overrides |
| `Integration`, `tool` | Integration helper for scoped tools |
| `EnvSecretSource` | Reads a named secret from `process.env`; the default `SecretSource` implementation |

Events use snake_case field names (`session_id`, `tool_name`) as the wire format
shared with the Python SDK.

## Python vs TypeScript parity

| Feature | Python SDK | TS SDK |
| --- | --- | --- |
| Event-sourced runtime | Yes | Yes |
| Tool registry + planner + policy | Yes | Yes |
| `AgentBuilder` + integrations | Yes | Yes |
| OpenAI / Anthropic providers | Yes | Yes |
| Kimi / Gemini providers | Yes | Yes (OpenAI-compatible factories) |
| Document RAG / vector store | Yes (non-MVP) | No |
| Tool retriever | Yes (non-MVP) | No |
| Text modality adapter | Yes (non-MVP) | No |
| Voice / TTS | Yes (non-MVP) | No |
| Redis realtime bus | Yes (non-MVP) | No (in-memory only) |
| CLI scaffold | Yes | Yes |

## Testing without API keys

Unit and integration tests mock the provider HTTP client -- no keys needed for
the default test suite:

```bash
bun run test
```

Live provider tests are opt-in and skip automatically when keys are absent:

```bash
OPENAI_API_KEY=... bun run test:integration
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  bun run test:integration tests/integration/openai-tools.test.ts
ANTHROPIC_API_KEY=... bun run test:integration
```

`MockProvider` is a deterministic stub that exercises the full tool loop. It is
available from `@kaji/sdk/testing` for unit tests, not from the main package
entrypoint used to build real agents.

```ts
import { MockProvider } from "@kaji/sdk/testing";
```

## Development

```bash
cd kaji/ts
bun install
bun run typecheck
bun run format:check
bun run test
bun run build
```

## Relation to the Python SDK

This package ports the **runtime core** of the Python `kaji` SDK: events,
sessions, tools, providers, and the ReAct loop. Python's Redis realtime bus,
RAG, and text/voice modalities are not yet ported. The Python bus can be
Redis-backed for multi-process deployments; the TS `EventBus` is in-memory only.
