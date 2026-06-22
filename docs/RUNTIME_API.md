# Runtime API reference

The headline API surface for embedding `agentkit` in your own app. For the
shared concepts and architecture, see [AGENTKIT.md](AGENTKIT.md).

This page focuses on the Python SDK. The TypeScript SDK
(`@agentkit/sdk`) ships an equivalent surface with the same wire format;
its differences are noted inline.

## Building an agent

`AgentBuilder` is the fluent entry point. It composes a provider, any
integrations, an optional policy, and a system prompt into an
`AgentRuntime`.

```python
import agentkit

runtime = (
    agentkit.AgentBuilder()
    .provider(agentkit.get_provider("openai"))
    .system_prompt("You are a helpful assistant.")
    .build(
        bus=agentkit.InMemoryEventBus(),
        store=agentkit.InMemoryEventStore(),
    )
)
```

| method | purpose |
| --- | --- |
| `.provider(provider)` | required; a `ModelProvider` instance |
| `.integration(integration)` | adds a namespaced `Integration` bundle (chainable) |
| `.tool(bound_tool)` | adds a single `BoundTool` from `@function_tool` (chainable) |
| `.policy(policy)` | attaches a `ToolPolicy` for allow/deny + approval gating |
| `.approval_handler(handler)` | wires the policy's approval callback |
| `.system_prompt(text)` | overrides the default system prompt |
| `.strategy(strategy)` | tunes max tool iterations etc. |
| `.build(*, bus, store)` | returns an `AgentRuntime` |

`AgentRuntime` can also be constructed directly when you already have a
`ToolPlanner` and tool list -- see the source for the full constructor.

## Driving a turn

```python
session_id = "s1"
await runtime.send(session_id, "What's the weather in Seattle?")

for event in await runtime.history(session_id):
    print(event.type, getattr(event, "content", getattr(event, "delta", "")))
```

| method | purpose |
| --- | --- |
| `await runtime.send(session_id, content)` | append a user message + run one turn |
| `await runtime.run_turn(session_id)` | run a turn against an existing log |
| `await runtime.history(session_id)` | shortcut for `runtime.store.get_events(...)` |

Both `send` and `run_turn` accept an optional `CancellationToken` to stop
mid-turn.

## Tools

The PEP 8 decorator surface, shortest path:

```python
import agentkit
from pydantic import BaseModel

class GetWeather(BaseModel):
    city: str

@agentkit.tool(
    description="Look up weather for a city.",
    parameters=GetWeather,
    risk="read",
)
async def get_weather(self, ctx: agentkit.ToolContext, args: dict) -> dict:
    return {"city": args["city"], "tempF": 68}
```

`@agentkit.tool` decorates methods on an `Integration` subclass.
`@agentkit.function_tool` wraps a bare async function as a registrable
`BoundTool` you pass to `AgentBuilder().tool(...)`.

| call | shape |
| --- | --- |
| `agentkit.tool(*, description, parameters, risk=None, tags=(), enabled=True)` | decorator for Integration methods |
| `agentkit.function_tool(fn)` or `agentkit.function_tool(...)` | wrap a single async function |
| `agentkit.register_tool(spec)(handler)` | register against the process-default `ToolRegistry` |
| `agentkit.list_tool_specs(tags=None, enabled_only=True)` | enumerate registered specs |

`parameters` accepts either a JSON Schema dict or a Pydantic `BaseModel`
subclass; the model is converted to JSON Schema at registration time.

## Providers

```python
provider = agentkit.get_provider("openai")    # reads OPENAI_API_KEY
provider = agentkit.get_provider("anthropic") # reads ANTHROPIC_API_KEY
provider = agentkit.get_provider("kimi")      # reads OPENROUTER_API_KEY
provider = agentkit.get_provider("gemini")    # reads GEMINI_API_KEY
provider = agentkit.get_provider("mock")      # deterministic, no key
```

Register a custom provider:

```python
agentkit.register_provider("my-provider", MyProvider)
```

A provider implements the `agentkit.ModelProvider` Protocol with two
async methods (`generate`, `generate_stream`) and yields
`ModelResponseChunk` from the stream. Errors raise
`ProviderError` / `ProviderConfigError` / `ProviderAPIError` so callers
can distinguish setup mistakes from upstream failures.

The TypeScript SDK ships function-style factories
(`openai("gpt-4o")`, `anthropic(...)`, `openrouter(...)`, `kimi(...)`,
`gemini(...)`) plus a `generateText` / `streamText` one-shot pair for
callers who don't need the full event-sourced runtime.

## Events and replay

`AgentRuntime` is event-sourced. Every state change is an append to the
`EventStore`. To project current state from a log:

```python
state = agentkit.replay_session(events)
state.is_active     # bool
state.messages      # [{"role": "user" | "assistant" | "tool", "content": ...}, ...]
```

`SessionManager` is the higher-level wrapper if you want session
metadata (titles, user_id, list_active) on top of the raw event store.

For the wire format and the full discriminator list, see the events
table in [AGENTKIT.md](AGENTKIT.md#events).

## Subscribing to events

The `EventBus` fans out events to subscribers per session. Useful for
streaming a UI:

```python
bus = agentkit.InMemoryEventBus()
async for event in bus.subscribe("s1"):
    if event.type == "agent.message.delta":
        ui.append(event.delta)
    elif event.type == "agent.message.completed":
        break
```

The TypeScript SDK's `EventBus.subscribe(sessionId)` returns the same
async-iterable shape.

## Errors

| class | raised when |
| --- | --- |
| `ProviderConfigError` | missing API key, missing peer dep |
| `ProviderAPIError` | upstream API rejected the request |
| `ProviderError` | base class for both |
| `UnknownToolError` | model called a tool name not in the registry |

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for what to do about each.
