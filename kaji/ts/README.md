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
npm install @kaji/sdk@0.2.0-beta.1 zod openai        # OpenAI
# or
npm install @kaji/sdk@0.2.0-beta.1 zod @anthropic-ai/sdk  # Anthropic
# or: bun add @kaji/sdk@0.2.0-beta.1 zod openai
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
console.log(result.text, result.sessionId, result.turnId);
console.log(result.events.map((event) => [event.sequence, event.turn_id, event.type]));
```

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
console.log(result.text, result.sessionId, result.turnId);

for (const e of result.events) {
  console.log(e.id, e.sequence, e.turn_id, e.type);
}
```

Swap `OpenAIProvider` for `AnthropicProvider` (and `OPENAI_API_KEY` for
`ANTHROPIC_API_KEY`) to use Anthropic.

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable.

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
| `EventStore`, `InMemoryEventStore` | Append-only event log |
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
