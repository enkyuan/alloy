# Troubleshooting

The failures you're most likely to hit when embedding `agentkit`, with the
shortest path to a fix.

## "OpenAI API key is not configured"

```
ProviderConfigError: OpenAI API key is not configured. Set OPENAI_API_KEY.
```

Set `OPENAI_API_KEY` in the environment, or pass the key inline:
`agentkit.get_provider("openai", api_key="sk-...")`. The other providers
have parallel checks:

- `anthropic` -> `ANTHROPIC_API_KEY` (raises `ProviderConfigError`)
- `kimi` -> reads `OPENROUTER_API_KEY` first, then falls back to
  `KIMI_API_KEY`; the error message asks for `OPENROUTER_API_KEY`
- `gemini` -> `GEMINI_API_KEY` (raises plain `ValueError`, not
  `ProviderConfigError`)

Run `agentkit info` to see what's currently set.

## "OpenAI provider requires the openai package"

```
ProviderConfigError: OpenAI provider requires openai. Install agentkit[openai].
```

Provider SDKs are optional peer dependencies. Install the extra:

```bash
pip install 'agentkit[openai]'        # OpenAI
pip install 'agentkit[anthropic]'     # Anthropic
pip install 'agentkit[gemini]'        # Gemini
pip install 'agentkit[providers]'     # all of the above
```

For the TS SDK, install the matching peer (`openai`, `@anthropic-ai/sdk`)
with `bun add`.

## "Unknown tool: <name>"

```
UnknownToolError: Unknown tool: get_weather
```

The model called a tool name the registry doesn't know. Usually one of:

- The tool was registered on a scoped `ToolRegistry` but the runtime is
  hitting the process-default registry. Pass the scoped registry's
  `list_specs()` and `execute` into `AgentRuntime`/`AgentBuilder`.
- The tool name in the spec doesn't match the handler's
  attribute name on the `Integration`. The default `Integration.tools()`
  scan uses the attribute name; if you've manually overridden `tools()`,
  the `ToolSpec.name` you return is canonical.
- Provider-safe name mangling collapsed two different tools to the same
  name. Check `agentkit.runtime.tools.registry.provider_safe_tool_name`.

## "Invalid tool arguments"

The runtime emits a `tool.call.failed` event with an `error` field like:

```
Invalid tool arguments: missing required argument: 'city'
```

This is an event on the bus, not a raised exception. (Internally: event
class `ToolCallFailed`, enum `EventType.TOOL_CALL_FAILED`.) The model
produced args that fail the JSON Schema gate in `ToolPlanner`. Either:

- The schema is wrong (missing a property in `parameters.properties` or
  too aggressive a `required` list). Pydantic models tend to get this
  right; hand-rolled JSON Schemas drift.
- The model is genuinely bad at this tool's schema. Tighten the
  description, drop optional fields, or pre-fill defaults in the handler.

The model sees the `tool.call.failed` event in the next turn and usually
self-corrects. If you'd rather fail loudly, subscribe to the bus and
abort on the first failure.

## "ProviderAPIError: <upstream>"

```
ProviderAPIError: OpenAI request failed: rate_limit_exceeded
```

The upstream API rejected the request. The error carries
`statusCode` and `responseText` when available. The runtime does not
retry; wrap your `runtime.send` call if you want backoff. The same
class is raised by every provider so you can catch it generically.

## `import agentkit` is slow / requires env

It shouldn't. `agentkit` resolves top-level names lazily and reads no
environment at import. If you're seeing import-time failures or
slowness, you've likely imported a non-MVP subpackage directly
(`agentkit.knowledge`, `agentkit.modalities.voice`). Those have heavier
deps and may read settings.

## Test runs fail with `ValueError: Tool already registered`

```
ValueError: Tool already registered: get_weather
```

The process-default `ToolRegistry` is module-global and persists across
tests in the same interpreter. Call `agentkit.runtime.tools.registry.clear_tools()`
in a fixture, or build a fresh scoped `ToolRegistry` per test instead of
using the global decorator path.

## TS streamText() hangs

The `text` and `toolCalls` promises only resolve after `textStream` has
been iterated to completion. Awaiting `text` without ever consuming
`textStream` deadlocks. Either iterate the stream first, or use
`generateText` if you don't need the deltas.

## See also

- [CLI.md](CLI.md) for `agentkit doctor` and `agentkit info`.
- [RUNTIME_API.md](RUNTIME_API.md) for the headline API surface.
- [AGENTKIT.md](AGENTKIT.md) for the shared concepts overview.
