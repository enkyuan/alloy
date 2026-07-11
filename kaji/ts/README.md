# Kaji (TypeScript)

`@kaji/sdk` is an embeddable SDK for building agents in TypeScript: import
the pieces you need and compose them. The core is infra-free (no database,
server, or environment configured). It mirrors the runtime core of the Python
`kaji` SDK.

> **Status:** beta candidate for the core embedded loop. Event-sourced building
> blocks, tool registry, `ToolPlanner` / `ToolPolicy`, `AgentBuilder`, OpenAI
> and Anthropic providers, and the agent runtime are implemented and CI-tested.
> RAG, voice, and Redis realtime are not yet ported from Python. CLI scaffold
> and integration-registry commands are present.

See [**Kaji MVP**](../../docs/MVP.md) for the full five-step developer path and scope
definition.

## Install

```bash
npm install @kaji/sdk zod openai        # OpenAI
# or
npm install @kaji/sdk zod @anthropic-ai/sdk  # Anthropic
# or: bun add @kaji/sdk zod openai
```

`zod` is a required peer dependency (Zod 4). `openai` and `@anthropic-ai/sdk`
are optional peers -- install only the one you use. Node 22+.

## Quick start

Set an API key, then build an agent with `AgentBuilder`:

```bash
export OPENAI_API_KEY=sk-...
# or: export ANTHROPIC_API_KEY=sk-ant-...
```

```ts
import {
  AgentBuilder,
  OpenAIProvider,
  Integration,
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
  .defaultContext({ principalId: "weather-app" })
  .build();

const result = await runtime.turn("Weather in Seattle?");
console.log(result.text);

for (const e of result.events) {
  console.log(e.type, "content" in e ? e.content : "delta" in e ? e.delta : "");
}
```

Swap `OpenAIProvider` for `AnthropicProvider` (and `OPENAI_API_KEY` for
`ANTHROPIC_API_KEY`) to use Anthropic.

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable.

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
and verifies the runtime emits final assistant text using the tool result. It
skips automatically when `OPENAI_API_KEY` is absent. After OpenAI passes, test
providers in this order: Anthropic, the Gemini OpenAI-compatible factory, then
Kimi/OpenRouter. The TS Kimi and Gemini paths are OpenAI-compatible factories,
not native provider implementations.

For the cross-SDK release gate, run from the repository root:

```bash
bash kaji/scripts/beta-release-check.sh
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, ast-grep boundary checks when available, and no-key
live-gate hygiene. The ast-grep step guards the Python SDK/service boundary, core package dependency direction, legacy tool-model imports, TypeScript optional provider imports, and cancellation error shape.

For the live-gate credential modes specifically:

```bash
bash kaji/scripts/live-openai-tool-loop.sh
KAJI_REQUIRE_LIVE_KEYS=1 bash kaji/scripts/live-openai-tool-loop.sh
```

Without `OPENAI_API_KEY`, the first command proves import and skip hygiene only.
It is not a provider-readiness signal. With `KAJI_REQUIRE_LIVE_KEYS=1`, the
same no-key state fails loudly. A release cannot be called live-ready until this
command exits with `PASS: OpenAI live tool-loop readiness verified` while
`OPENAI_API_KEY` is set:

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```

The same keyed proof can be included in the wrapper with
`OPENAI_API_KEY=... KAJI_RUN_KEYED_LIVE=1 bash kaji/scripts/beta-release-check.sh`.

## Stability tiers

- **Stable core:** `AgentBuilder`, `AgentRuntime`, `ToolRegistry`,
  `ToolPlanner`, session replay, OpenAI/Anthropic providers, and the in-memory
  event bus/store are the beta-candidate embedded-agent surface.
- **Experimental Python-only:** Redis realtime/history, voice/TTS,
  `DocumentRAG`, native Gemini/Kimi providers, tool retrieval, and text/voice
  modalities exist in Python but are not production-hardened.
- **TS not ported:** Redis realtime, voice/TTS, and RAG are not implemented in
  TypeScript. TS Gemini/Kimi remain OpenAI-compatible factories rather than
  native provider implementations.

See [`kaji/RELEASE_MATRIX.md`](../RELEASE_MATRIX.md) for the cross-SDK release
matrix and the exact distinction between stable core, experimental Python-only
surfaces, and TypeScript surfaces that are not ported.

The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
`DocumentRAG`, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.
Gemini and Kimi are OpenAI-compatible factories in TypeScript, not native
provider implementations.

## Approval handler

Tools whose risk exceeds your policy threshold pause for approval before the
runtime executes them. `cliApprovalHandler` is a built-in handler for
dev / REPL use that prints the tool name, risk, and arguments, then reads
`y` / `N` on stdin:

```ts
import { AgentBuilder, cliApprovalHandler, openai } from "@kaji/sdk";

const agent = new AgentBuilder()
  .provider(openai())
  .approvalHandler(cliApprovalHandler({ label: "agent-a" }))
  .build();
```

`ApprovalHandler` is `(name, args, risk) => Promise<boolean>`. For production
hosts, implement your own handler that talks to a web modal, Slack, or
whatever your operator workflow needs.

`EventApprovalHandler` requires a non-empty turn ID and accepts a decision only
when `turn_id`, `tool_call_id`, and `tool_name` all match the pending request.
Unscoped or stale backlog decisions are ignored.

## CLI

```
kaji --help                            # list subcommands
kaji add <integration>                 # copy an integration into your project
kaji init [--out <dir>] [--force]      # scaffold a TypeScript Kaji project
kaji list-integrations                 # enumerate the registry catalog
```

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
| `ApprovalHandler`, `cliApprovalHandler` | Approval callback type + default stdin handler for dev / REPL |
| `TypedApprovalHandler`, `EventApprovalHandler`, `AutoApprovalHandler` | Structured approval handlers: event-driven (publishes `TOOL_APPROVAL_REQUESTED` for a host UI to answer) and auto-decide by policy, as alternatives to `cliApprovalHandler` |
| `OpenAIProvider`, `AnthropicProvider` | LLM providers |
| `AgentRuntime`, `AgentBuilder`, `CancellationToken` | ReAct loop and fluent builder |
| `Integration`, `tool` | Integration helper for scoped tools |

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
