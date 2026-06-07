# agentkit

agentkit is an embeddable SDK for building agents: an event-sourced runtime,
tool registry, pluggable LLM providers, and STT/TTS modalities. the core is
infra-free — no database or server required to import and use it. deploy it
yourself or run the reference service (`agentkit-serve`) when you need a
production-grade multi-process setup.

it is used by agentpay as the agent runtime layer. it can also be used
standalone in any python or typescript project.

## packages

three packages live under `agentkit/`:

| package | path | what it is |
| -------------------- | ---------------------- | ------------------------------------------------ |
| `agentkit` | `agentkit/sdk` | python SDK: the core runtime, embed anywhere |
| `agentkit-serve` | `agentkit/serve` | python: FastAPI + workers reference service |
| `@agentkit/sdk` | `agentkit/ts` | TypeScript port of the core runtime |

individual package setup lives in each package's own README. this doc covers
the shared concepts across all three.

## architecture

```
   ┌────────────────────────────────────────────────────┐
   │  your app  (or agentpay/api)                       │
   │                                                    │
   │  session manager   tool registry   model provider  │
   └────────────────────────┬───────────────────────────┘
                            │
                            ▼
   ┌───────────────────────────────────────────────────┐
   │  agent runtime  (ReAct loop)                      │
   │                                                   │
   │  1. project session state from event log          │
   │  2. call LLM provider with history + tool specs   │
   │  3. execute tool calls scatter-gather             │
   │  4. loop until model response is final            │
   └────────┬────────────────────────────┬─────────────┘
            │ events                     │ tool calls
            ▼                            ▼
   ┌──────────────────┐        ┌──────────────────────┐
   │  event store     │        │  tool handlers       │
   │  (in-memory or   │        │  (your functions,    │
   │   persistent)    │        │   run concurrently)  │
   └──────────────────┘        └──────────────────────┘
```

the reasoning loop is modality-agnostic. voice adds STT at the input edge and
TTS at the output edge; text skips both.

```
   voice:   audio → STT → [runtime loop] → TTS → audio
   text:    text  →       [runtime loop] →       text
```

## core concepts

### events

all session state is derived from an append-only event log. events are
discriminated by `type` (e.g. `user.message`, `tool.call.completed`,
`agent.message.completed`). the full list lives in the SDK source:

- `agentkit/sdk/agentkit/infra/events/schemas.py` (python)
- `agentkit/ts/src/events/schemas.ts` (typescript)

the event type string values are the wire format and are identical across both
SDKs.

### session state

`replaySession` (python: `ReplaySession`) takes the event log for a session and
projects it into a `SessionState`: `isActive`, and `messages` (the conversation
history in `{role, content}` form that gets passed to the LLM).

### tool registry

tools are registered with a spec (name, description, JSON schema parameters) and
a handler function. the runtime calls the LLM with the full tool spec list; when
the model requests a tool call, the registry dispatches it. multiple tool calls
from one LLM turn run concurrently (scatter-gather) and results are collected
before the next loop iteration.

```python
# python
@agentkit.register_tool(
    agentkit.tool_spec_from_model("get_weather", "Look up weather", GetWeather)
)
async def get_weather(ctx: agentkit.ToolContext, args: dict) -> dict:
    return {"tempF": 68}
```

```ts
// typescript
registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ tempF: 68 }),
);
```

`ToolContext` carries `userId` / `user_id` and an optional `db` handle (null by
default; inject one when the tool needs persistence).

### event bus

the event bus fans out events to subscribers per session. in the python SDK the
default implementation is in-memory (`InMemoryEventBus`); a Redis Stream-backed
bus is used in `agentkit-serve` for cross-process durability. the typescript SDK
ships an in-memory bus only (sufficient for an embedded SDK; Redis deferred until
there is a TS server runtime).

### providers

LLM providers implement a common interface. the python SDK ships `kimi`
(OpenRouter/Kimi, the default), `gemini`, `openai`, and `mock` (for tests). selected via
`AGENTKIT_MODEL_PROVIDER`. adding a new provider means implementing the
`ModelProvider` protocol and registering it.

TTS providers (`gemini`, `openai`, `none`) follow the same pattern via the
`TTSProvider` protocol. STT uses Soniox by default.

## the reference service (agentkit-serve)

`agentkit-serve` (`agentkit/serve`) wraps the SDK as three processes over Redis
so heavy tool execution never stalls a real-time exchange:

| process | role |
| ------------ | ------------------------------------------------------- |
| `api` | FastAPI app: REST routes and STT WebSocket |
| `bus-worker` | reasoning loop: LLM calls, event bus, tool dispatch |
| `worker` | async tool execution (TaskIQ), results back to bus-worker |

Redis Streams provide durable at-least-once hand-off between processes.
Redis Pub/Sub fans out agent responses to the connected client in real time.

use `agentkit-serve` when you need multi-process durability and real-time voice.
embed `agentkit` directly when you want infra-free usage inside your own app.

## typescript SDK

`@agentkit/sdk` (`agentkit/ts`) is a TypeScript port of the python core. it
mirrors the public surface (event types, store, bus, replay, tool registry) and
uses Zod 4 for validation. wire format (event type strings, field names) is
identical to the python SDK so events can round-trip across both.

the reasoning loop and LLM providers are being ported and are not yet part of
the exported public surface. voice modalities (STT, TTS) are not yet ported.

## further reading

- individual package READMEs: `agentkit/sdk/agentkit/README.md`,
  `agentkit/serve/README.md`, `agentkit/ts/README.md`
- agentpay (the product built on agentkit): [`docs/AGENTPAY.md`](AGENTPAY.md)
