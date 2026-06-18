# AgentKit (TypeScript)

`@agentkit/sdk` is an embeddable SDK for building agents in TypeScript: import
the pieces you need and compose them. The core is infra-free (no database,
server, or environment configured). It mirrors the runtime core of the Python
`agentkit` SDK.

> **Status:** beta candidate. Event-sourced building blocks, tool registry,
> `ToolPlanner` / `ToolPolicy`, `AgentBuilder`, OpenAI and Anthropic providers,
> and the agent runtime are implemented and CI-tested. RAG, voice, Redis
> realtime, and CLI are not yet ported from Python.

## Install

```bash
npm install @agentkit/sdk zod
# or: bun add @agentkit/sdk zod
```

`zod` is a peer dependency (Zod 4). Node 22+.

## Quick start (AgentBuilder)

The recommended path registers tools in a scoped registry via integrations:

```ts
import {
  AgentBuilder,
  EventBus,
  InMemoryEventStore,
  MockProvider,
  Integration,
  tool,
  AgentKitEvent,
  EventType,
} from "@agentkit/sdk";
import { z } from "zod";

class PingIntegration extends Integration {
  register(registry) {
    registry.register(
      "ping",
      tool(
        {
          description: "Respond with pong",
          parameters: { type: "object", properties: {} },
        },
        async () => ({ pong: true }),
      ),
    );
  }
}

const store = new InMemoryEventStore();
const bus = new EventBus();
const runtime = new AgentBuilder()
  .provider(new MockProvider())
  .integration(new PingIntegration())
  .build({ bus, store });

await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }));
await runtime.send("s1", "ping");
```

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable.

## Global tool registry (advanced)

For simple setups you can use the process-level registry:

```ts
import { registerTool, toolSpecFromSchema, executeTool } from "@agentkit/sdk";
import { z } from "zod";

registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ city: args.city, tempF: 68 }),
);

const result = await executeTool("user-1", "get_weather", { city: "Seattle" });
```

## Run an agent

`AgentRuntime` is the provider-agnostic ReAct loop: replay session state, call a
`ModelProvider`, execute tool calls via `ToolPlanner`, loop until done.

```ts
import { AgentRuntime, EventBus, InMemoryEventStore, MockProvider } from "@agentkit/sdk";

const store = new InMemoryEventStore();
const bus = new EventBus();
const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });

await runtime.send("s1", "hi");
```

## What's exported

| Export | What it is |
| --- | --- |
| `EventType`, `AgentKitEvent` | Event discriminants and Zod-validated event union |
| `EventStore`, `InMemoryEventStore` | Append-only event log |
| `EventBus` | In-memory pub/sub per session |
| `replaySession`, `SessionManager`, session store types | Session projection and management |
| `registerTool`, `ToolRegistry`, `toolSpecFromSchema`, `executeTool` | Tool registry (global + scoped) |
| `ToolPolicy`, `ToolPlanner` | Allow/deny and approval-gated execution |
| `MockProvider`, `OpenAIProvider`, `AnthropicProvider` | LLM providers |
| `AgentRuntime`, `AgentBuilder`, `CancellationToken` | ReAct loop and fluent builder |
| `Integration`, `tool` | Integration helper for scoped tools |

Events use snake_case field names (`session_id`, `tool_name`) as the wire format
shared with the Python SDK.

## Python vs TypeScript parity

| Feature | Python SDK | TS SDK |
| --- | --- | --- |
| Event-sourced runtime | Yes | Yes |
| Tool registry + planner + policy | Yes | Yes |
| AgentBuilder + integrations | Yes | Yes |
| OpenAI / Anthropic providers | Yes | Yes |
| Mock provider | Yes | Yes |
| Kimi / Gemini providers | Yes | No |
| Document RAG / vector store | Yes | No |
| Tool retriever | Yes | No |
| Text modality adapter | Yes | No |
| Voice / TTS | Yes | No |
| Redis realtime bus | Yes | No (in-memory only) |
| CLI | Yes | No |

## Development

```bash
cd agentkit/ts
npm install
npm run typecheck
npm run test
npm run build
```

Optional live provider tests (require API keys):

```bash
npm run test:integration
```

## Relation to the Python SDK

This package ports the **runtime core** of the Python `agentkit` SDK. The Python
bus can be Redis-backed for multi-process deployments; the TS `EventBus` is
in-memory until a server runtime exists.
