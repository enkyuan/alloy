# AgentKit (TypeScript)

`@agentkit/sdk` is an embeddable SDK for building agents in TypeScript: import
the pieces you need and compose them. The core is infra-free (no database,
server, or environment configured). It mirrors the public surface of the Python
`agentkit` SDK.

> **Status:** pre-release. This is the runtime core: event-sourced building
> blocks (events, bus, store, replay) and a tool registry. The reasoning loop,
> providers, and voice modalities are not yet ported.

## Install

```bash
bun add @agentkit/sdk zod
```

`zod` is a peer dependency (Zod 4).

## Quick start

Nothing here requires infra. Compose the building blocks yourself:

```ts
import {
  InMemoryEventStore,
  EventBus,
  AgentKitEvent,
  EventType,
  replaySession,
  registerTool,
  toolSpecFromSchema,
  executeTool,
} from "@agentkit/sdk";
import { z } from "zod";

// Event-sourced building blocks, all in-memory:
const store = new InMemoryEventStore();
const bus = new EventBus();

// Events are validated and carry defaults (id, version, timestamp, metadata):
const event = AgentKitEvent.parse({
  type: EventType.USER_MESSAGE,
  session_id: "s1",
  content: "hello",
});
await store.append(event);

// Project the event log into session state:
const state = replaySession(await store.getEvents("s1"));

// Tools: register your own. Schemas come from Zod models.
registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ city: args.city, tempF: 68 }),
);

// Tools run without a database by default; ctx.db is undefined unless injected.
const result = await executeTool("user-1", "get_weather", { city: "Seattle" });
```

## What's here

| Export | What it is |
| ------------------------------------------- | ---------------------------------------------------- |
| `EventType`, `AgentKitEvent` | Event discriminants and the Zod-validated event union |
| `EventStore`, `InMemoryEventStore` | Append-only event log interface and in-memory backend |
| `EventBus` | In-memory pub/sub, fan-out per session via async iterators |
| `replaySession`, `SessionState` | Projection of the event log into current session state |
| `registerTool`, `listToolSpecs`, `executeTool`, `toolSpecFromSchema`, `ToolSpec`, `ToolContext` | Tool registry |

Events use snake_case field names (`session_id`, `tool_name`) because they are
the wire format shared with the Python SDK.

## Development

**Prerequisites:** [Bun](https://bun.sh) and Node 22+.

```bash
bun install
bun run typecheck   # tsc --noEmit
bun run test        # vitest
bun run build       # tsup -> dist/ (ESM + CJS + types)
```

## Relation to the Python SDK

This package ports the runtime core of the Python `agentkit` SDK (which lives at
the repo root). The `EventBus` here is in-memory; the Python bus is Redis Stream
backed. A Redis backend is deferred until there is a TS server runtime, since an
embedded SDK does not need cross-process durability.
