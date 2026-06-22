# agentkit

agentkit is an embeddable SDK for building agents: an event-sourced runtime,
tool registry, and pluggable LLM/TTS providers. the core is infra-free -- no
database or server required to import and use it. deploy it yourself or run the
reference service (`agentkit-serve`) when you need FastAPI, Redis/Postgres
persistence, workers, or STT voice input.

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

the reasoning loop is modality-agnostic. `agentkit-serve` adds STT at the input
edge and TTS at the output edge; text skips both.

```
   voice:   audio → STT → [runtime loop] → TTS → audio
   text:    text  →       [runtime loop] →       text
```

## core concepts

### events

all session state is derived from an append-only event log. events are
discriminated by `type`. the string values below are the wire format and are
identical across both SDKs.

| group | type string | meaning |
| --- | --- | --- |
| session | `session.created` | a new session opened |
| session | `session.closed` | session terminated |
| user input | `user.message` | text turn from the user |
| user input | `user.audio.chunk` | audio frame, voice modality only |
| transcript | `transcript.partial` | interim STT result |
| transcript | `transcript.final` | finalized user transcript, becomes a user message in replay |
| memory | `memory.retrieval.started` | RAG lookup kicked off |
| memory | `memory.retrieval.completed` | RAG returned chunks |
| agent | `agent.reasoning.started` | runtime entered a turn |
| agent | `agent.message.delta` | streaming token from the model |
| agent | `agent.message.completed` | model finalized its text for the turn |
| tool call | `tool.call.requested` | model asked for a tool call |
| tool call | `tool.call.started` | runtime began executing |
| tool call | `tool.call.completed` | tool returned a result |
| tool call | `tool.call.failed` | tool raised, was denied, or had invalid args |
| tool approval | `tool.approval.requested` | policy gate paused before execution |
| tool approval | `tool.approval.approved` | approval handler said yes |
| tool approval | `tool.approval.rejected` | approval handler said no |
| workflow | `workflow.started` | long-running tool workflow began |
| workflow | `workflow.completed` | workflow finished |
| workflow | `workflow.failed` | workflow raised |
| cancellation | `cancellation.requested` | caller asked the runtime to stop |
| cancellation | `cancellation.completed` | runtime acknowledged and stopped |

the canonical sources are
[`agentkit/sdk/agentkit/infra/events/types.py`](../agentkit/sdk/agentkit/infra/events/types.py)
and [`agentkit/ts/src/events/types.ts`](../agentkit/ts/src/events/types.ts);
the table above must match them byte-for-byte.

### session state

`replaySession` (python: `replay_session`) takes the event log for a session and
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
(OpenRouter/Kimi, the default), `gemini`, `openai`, `anthropic`, and `mock`
(for tests). selected via `AGENTKIT_MODEL_PROVIDER`. provider SDKs are optional
extras (`agentkit[openai]`, `agentkit[anthropic]`, `agentkit[gemini]`, or
`agentkit[providers]`). adding a new provider means implementing the
`ModelProvider` protocol and registering it.

TTS providers (`gemini`, `openai`, `none`) follow the same pattern via the
`TTSProvider` protocol. STT/Soniox lives in `agentkit-serve`, not the embeddable
SDK.

## the reference service (agentkit-serve)

`agentkit-serve` (`agentkit/serve`) wraps the SDK as three processes over Redis
so heavy tool execution never stalls a real-time exchange:

| process | role |
| ------------ | ------------------------------------------------------- |
| `api` | FastAPI app: REST routes and STT WebSocket |
| `bus-worker` | service runtime: LLM calls, event bus, tool dispatch |
| `worker` | async tool execution (TaskIQ), results back to bus-worker |

Redis Streams provide durable at-least-once hand-off between processes.
Redis Pub/Sub fans out agent responses to the connected client in real time.

use `agentkit-serve` when you need multi-process durability and real-time voice.
embed `agentkit` directly when you want infra-free usage inside your own app.

## typescript SDK

`@agentkit/sdk` (`agentkit/ts`) is a TypeScript port of the python core. it
mirrors the public surface (event types, store, bus, replay, tool registry,
agent runtime, and provider interfaces) and uses Zod 4 for validation. wire
format (event type strings, field names) is identical to the python SDK so
events can round-trip across both.

voice modalities (STT, TTS) are not yet ported to TypeScript.

## further reading

- individual package READMEs: `agentkit/sdk/agentkit/README.md`,
  `agentkit/serve/README.md`, `agentkit/ts/README.md`
- agentpay (the product built on agentkit): [`docs/AGENTPAY.md`](AGENTPAY.md)
