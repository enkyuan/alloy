# Runtime API reference

The headline API surface for embedding `kaji` in your own app. For the
shared concepts and architecture, see [KAJI.md](KAJI.md).

This page focuses on the Python SDK. The TypeScript SDK
(`@kaji/sdk`) ships an equivalent surface with the same wire format;
its differences are noted inline.

## Building an agent

`AgentBuilder` is the fluent entry point. It composes a provider, any
integrations, an optional policy, and a system prompt into an
`AgentRuntime`.

```python
import kaji

runtime = (
    kaji.AgentBuilder()
    .provider(kaji.get_provider("openai"))
    .system_prompt("You are a helpful assistant.")
    .build(
        bus=kaji.InMemoryEventBus(),
        store=kaji.InMemoryEventStore(),
    )
)
```

| method | purpose |
| --- | --- |
| `.provider(provider)` | required; a `ModelProvider` instance |
| `.integration(integration)` | adds a namespaced `Integration` bundle (chainable) |
| `.tool(t)` | adds a single `@function_tool`-decorated tool (chainable) |
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

Two decorator paths. Use `@function_tool` for a single function,
`@tool` for namespaced bundles of related methods.

### Single function: `@function_tool`

```python
import kaji

provider = kaji.get_provider("openai")

@kaji.function_tool(description="Look up weather for a city.", risk="read")
async def get_weather(city: str) -> dict:
    return {"city": city, "tempF": 68}

runtime = kaji.AgentBuilder().provider(provider).tool(get_weather).build(
    bus=kaji.InMemoryEventBus(), store=kaji.InMemoryEventStore(),
)
```

Note: `register_tool` writes to a process-global `ToolRegistry`;
`AgentBuilder` builds a private one. The two don't share state.

### Namespaced bundle: `Integration` + `@tool`

```python
import kaji
from pydantic import BaseModel

class GetWeather(BaseModel):
    city: str

class WeatherIntegration(kaji.Integration):
    @property
    def namespace(self) -> str:
        return "weather"

    @kaji.tool(description="Look up weather.", parameters=GetWeather, risk="read")
    async def get_weather(self, ctx: kaji.ToolContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}

runtime = (
    kaji.AgentBuilder()
    .provider(kaji.get_provider("openai"))
    .integration(WeatherIntegration())
    .build(bus=kaji.InMemoryEventBus(), store=kaji.InMemoryEventStore())
)
```

| call | shape |
| --- | --- |
| `kaji.function_tool(fn)` or `kaji.function_tool(*, description, parameters=None, risk=None, ...)` | wrap a single async function; schema derived from type hints when `parameters` is omitted |
| `kaji.tool(*, description, parameters, risk=None, tags=(), enabled=True)` | decorate a method on an `Integration` subclass |
| `kaji.register_tool(spec)(handler)` | register against the process-default `ToolRegistry` |
| `kaji.list_tool_specs(tags=None, enabled_only=True)` | enumerate registered specs |

`parameters` accepts either a JSON Schema dict or a Pydantic `BaseModel`
subclass; the model is converted to JSON Schema at registration time.

Built-in integrations:

- `from kaji.integrations.registry.github.github import GitHub`
- `from kaji.integrations.registry.gmail.gmail import Gmail`
- `from kaji.integrations.registry.gcal.gcal import GoogleCalendar`

## Providers

```python
provider = kaji.get_provider("openai")    # reads OPENAI_API_KEY
provider = kaji.get_provider("anthropic") # reads ANTHROPIC_API_KEY
provider = kaji.get_provider("kimi")      # reads OPENROUTER_API_KEY
provider = kaji.get_provider("gemini")    # reads GEMINI_API_KEY
provider = kaji.get_provider("mock")      # deterministic, no key
```

Register a custom provider:

```python
kaji.register_provider("my-provider", MyProvider)
```

A provider implements the `kaji.ModelProvider` Protocol with two
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
state = kaji.replay_session(events)
state.is_active     # bool
state.messages      # [{"role": "user" | "assistant" | "tool", "content": ...}, ...]
```

`SessionManager` is the higher-level wrapper if you want session
metadata (titles, user_id, list_active) on top of the raw event store.

For the wire format and the full discriminator list, see the events
table in [KAJI.md](KAJI.md#events).

## Subscribing to events

The `EventBus` fans out events to subscribers per session. Useful for
streaming a UI:

```python
bus = kaji.InMemoryEventBus()
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
