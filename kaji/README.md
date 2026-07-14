# kaji

kaji is an embeddable SDK for building agents: an event-sourced runtime,
tool registry, and pluggable LLM/TTS providers. the core is infra-free -- no
database or server required to import and use it. `kaji-serve` is a separate,
experimental reference service for evaluating FastAPI, Redis/Postgres, and STT
voice integration; it is not part of the 0.2 SDK beta promise.

it is used by ryo as the agent runtime layer. it can also be used
standalone in any python or typescript project.

## packages

three packages live under `kaji/`:

| package      | path         | what it is                                       |
| ------------ | ------------ | ------------------------------------------------ |
| `kaji-sdk`   | `kaji/sdk`   | python SDK: the core runtime, imported as `kaji` |
| `kaji-serve` | `kaji/serve` | python: experimental FastAPI + voice service     |
| `@kaji/sdk`  | `kaji/ts`    | TypeScript SDK for the shared embedded core      |

individual package setup lives in each package's own README. this doc covers
the shared concepts across all three.

## architecture

```
   ┌────────────────────────────────────────────────────┐
   │  your app  (or ryo/api)                            │
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
   │  3. execute tools sequentially by default         │
   │  4. loop until model response is final            │
   └────────┬────────────────────────────┬─────────────┘
            │ events                     │ tool calls
            ▼                            ▼
   ┌──────────────────┐        ┌──────────────────────┐
   │  event store     │        │  tool handlers       │
   │  (in-memory or   │        │  (bounded; explicit  │
   │   persistent)    │        │   parallel opt-in)   │
   └──────────────────┘        └──────────────────────┘
```

the reasoning loop is modality-agnostic. `kaji-serve` adds STT at the input
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

| group         | type string                  | meaning                                                                  |
| ------------- | ---------------------------- | ------------------------------------------------------------------------ |
| session       | `session.created`            | a new session opened                                                     |
| session       | `session.closed`             | session terminated                                                       |
| user input    | `user.message`               | text turn from the user                                                  |
| user input    | `user.audio.chunk`           | audio frame, voice modality only                                         |
| transcript    | `transcript.partial`         | interim STT result                                                       |
| transcript    | `transcript.final`           | finalized user transcript, becomes a user message in replay              |
| memory        | `memory.retrieval.started`   | RAG lookup kicked off                                                    |
| memory        | `memory.retrieval.completed` | RAG returned chunks                                                      |
| agent         | `agent.reasoning.started`    | runtime entered a turn                                                   |
| agent         | `agent.message.delta`        | streaming token from the model                                           |
| agent         | `agent.message.completed`    | model finalized its text for the turn                                    |
| agent         | `agent.turn.exhausted`       | runtime hit the configured tool-iteration limit without a final response |
| tool call     | `tool.call.requested`        | model asked for a tool call                                              |
| tool call     | `tool.call.started`          | runtime began executing                                                  |
| tool call     | `tool.call.completed`        | tool returned a result                                                   |
| tool call     | `tool.call.failed`           | tool raised, was denied, or had invalid args                             |
| tool approval | `tool.approval.requested`    | policy gate paused before execution                                      |
| tool approval | `tool.approval.approved`     | approval handler said yes                                                |
| tool approval | `tool.approval.rejected`     | approval handler said no                                                 |
| workflow      | `workflow.started`           | long-running tool workflow began                                         |
| workflow      | `workflow.completed`         | workflow finished                                                        |
| workflow      | `workflow.failed`            | workflow raised                                                          |
| cancellation  | `cancellation.requested`     | caller asked the runtime to stop                                         |
| cancellation  | `cancellation.completed`     | runtime acknowledged and stopped                                         |

the canonical sources are
[`kaji/sdk/src/infra/events/types.py`](sdk/src/infra/events/types.py)
and [`kaji/ts/src/events/types.ts`](ts/src/events/types.ts);
the table above must match them byte-for-byte.

### session state

`replaySession` (python: `replay_session`) takes the event log for a session and
projects it into a `SessionState`: `isActive`, and `messages` (the conversation
history in `{role, content}` form that gets passed to the LLM).

### tool registry

tools are registered with a spec (name, description, JSON Schema parameters,
and risk) plus a handler. the runtime validates each requested call before
approval or execution. tools execute sequentially unless an effect-independent
spec explicitly sets `parallel_safe`; even then, the default limit is four
active handlers.

```python
# python
import asyncio
import kaji

@kaji.function_tool(description="Look up weather.", risk="read")
async def get_weather(
    context: kaji.ToolExecutionContext,
    city: str,
) -> dict:
    return {
        "city": city,
        "tempF": 68,
        "principal": context.principal_id,
    }

runtime = (
    kaji.AgentBuilder()
    .provider(kaji.get_provider("openai"))
    .tool(get_weather)
    .build()
)

async def main() -> None:
    result = await runtime.turn(
        "Weather in Seattle?",
        context=kaji.TurnContext(principal_id="weather-app"),
    )
    print(result.text)


asyncio.run(main())
```

See [the canonical tool contract](../docs/kaji/tool-contracts.md) for richer
schemas, `Integration` bundles, deadlines, cancellation, and idempotency.

```ts
// typescript
import { AgentBuilder, functionTool, OpenAIProvider } from "@kaji/sdk";
import { z } from "zod";

const getWeather = functionTool(
  {
    name: "get_weather",
    description: "Look up weather.",
    parameters: z.object({ city: z.string() }),
    risk: "read",
  },
  async (args, context) => ({
    city: args.city,
    tempF: 68,
    principal: context.principalId,
  }),
);

const runtime = new AgentBuilder()
  .provider(new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! }))
  .tool(getWeather)
  .build();

const result = await runtime.turn("Weather in Seattle?", {
  context: { principalId: "weather-app" },
});
```

Python integration handlers use `(context, args)`; TypeScript function and
integration handlers use `(args, context)`. every tool-capable turn needs an
explicit principal, either per turn as above or as a deliberately configured
single-tenant builder default. handlers receive an immutable
`ToolExecutionContext` snapshot with principal, session, turn, request, trace,
tool-call, idempotency, deadline, cancellation, metadata, and optional `db`
values.

### event bus

the event journal/committer atomically persists and fans out events per session.
both embedded SDKs default to bounded in-memory implementations. persisted
sequence, not timestamp, defines ordering; history is read through bounded,
exclusive cursors. python also has experimental Redis/split adapters for
service hand-off. TypeScript remains in-memory only.

### providers

LLM providers implement a common interface. the python SDK ships `kimi`
(OpenRouter/Kimi), `gemini`, `openai`, `anthropic`, and `mock` (the default).
selected via `KAJI_MODEL_PROVIDER`. provider SDKs are optional
extras (`kaji-sdk[openai]`, `kaji-sdk[anthropic]`, `kaji-sdk[gemini]`, or
`kaji-sdk[providers]`). the distribution installs the import package and CLI
as `kaji`. adding a new provider means implementing the
`ModelProvider` protocol and registering it.

TTS providers (`gemini`, `openai`, `none`) follow the same pattern via the
`TTSProvider` protocol. STT/Soniox lives in `kaji-serve`, not the embeddable
SDK.

## the reference service (kaji-serve)

`kaji-serve` (`kaji/serve`) is an experimental service shell around the SDK.
Its current voice path uses Redis plus the pre-beta service worker runtime:

| process      | role                                                    |
| ------------ | ------------------------------------------------------- |
| `api`        | FastAPI app: REST routes and STT WebSocket              |
| `bus-worker` | legacy runtime: LLM calls and in-process tool execution |
| `worker`     | TaskIQ surface, not used by the normal reasoning path   |

Redis Pub/Sub fans out agent responses to the connected client in real time.
The service is excluded from the 0.2 SDK beta because it does not yet use the
canonical `AgentRuntime`, acknowledge input only after a completed turn, or
provide persistent event replay and distributed coordination.

Use `kaji-serve` only for reference-service evaluation and voice experiments.
Embed `kaji` directly for the supported SDK beta surface.

## typescript SDK

`@kaji/sdk` (`kaji/ts`) implements the shared embedded beta core: events,
bounded store/committer, replay, tool registry and planner, agent runtime, and
OpenAI/Anthropic providers. it requires Zod `>=4.3 <5` as a peer dependency.
the stable event wire format (type strings and field names) is shared with the
python SDK so validated stored events can round-trip across both.

voice modalities (STT, TTS) are not yet ported to TypeScript.

## further reading

- [docs/CLI.md](docs/CLI.md) -- `kaji` CLI subcommand reference.
- [docs/RUNTIME_API.md](docs/RUNTIME_API.md) -- headline API surface for embedding.
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) -- common errors and fixes.
- individual package READMEs: [sdk/README.md](sdk/README.md),
  [serve/README.md](serve/README.md), [ts/README.md](ts/README.md).
- ryo (the product built on kaji): [`ryo/README.md`](../ryo/README.md).
