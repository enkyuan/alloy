# Kaji (TypeScript)

`@kaji/sdk` is an embeddable SDK for building agents in TypeScript: import
the pieces you need and compose them. The core is infra-free (no database,
server, or environment configured). It mirrors the runtime core of the Python
`kaji` SDK.

> **Status:** beta candidate for the core embedded loop. Event-sourced building
> blocks, tool registry, `ToolPlanner` / `ToolPolicy`, `AgentBuilder`, OpenAI
> and Anthropic providers, and the agent runtime are implemented and CI-tested.
> RAG, voice, Redis realtime, and CLI are not yet ported from Python.

See [**Kaji MVP**](../MVP.md) for the full five-step developer path and scope
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
  EventBus,
  InMemoryEventStore,
  OpenAIProvider,
  Integration,
  tool,
  KajiEvent,
  EventType,
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
    async (_ctx, args) => ({ city: args.city, tempF: 68 }),
  );
}

const store = new InMemoryEventStore();
const bus = new EventBus();
const runtime = new AgentBuilder()
  .provider(new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! }))
  .integration(new WeatherIntegration())
  .systemPrompt("You are a weather assistant.")
  .build({ bus, store });

await store.append(
  KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }),
);
await runtime.send("s1", "Weather in Seattle?");

const events = await store.getEvents("s1");
for (const e of events) {
  console.log(e.type, "content" in e ? e.content : "delta" in e ? e.delta : "");
}
```

Swap `OpenAIProvider` for `AnthropicProvider` (and `OPENAI_API_KEY` for
`ANTHROPIC_API_KEY`) to use Anthropic.

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable.

## Global tool registry (advanced)

For simple setups you can use the process-level registry:

```ts
import { executeTool, registerTool, toolSpecFromSchema } from "@kaji/sdk";
import { z } from "zod";

registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ city: args.city, tempF: 68 }),
);

const result = await executeTool("user-1", "get_weather", { city: "Seattle" });
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
| Kimi / Gemini providers | Yes | No |
| Document RAG / vector store | Yes (non-MVP) | No |
| Tool retriever | Yes (non-MVP) | No |
| Text modality adapter | Yes (non-MVP) | No |
| Voice / TTS | Yes (non-MVP) | No |
| Redis realtime bus | Yes (non-MVP) | No (in-memory only) |
| CLI scaffold | Yes | No |

## Testing without API keys

Unit and integration tests mock the provider HTTP client -- no keys needed for
the default test suite:

```bash
bun run test
```

Live provider tests are opt-in and skip automatically when keys are absent:

```bash
OPENAI_API_KEY=... bun run test:integration
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
RAG, text/voice modalities, and CLI are not yet ported. The Python bus can be
Redis-backed for multi-process deployments; the TS `EventBus` is in-memory only.
