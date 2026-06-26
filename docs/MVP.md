# Kaji MVP

This document defines the MVP scope for the Kaji SDKs. It is focused on the
Python (`kaji`) and TypeScript (`@kaji/sdk`) packages; `kaji-serve`
is treated as out of scope for the SDK production-readiness path.

Both SDKs target the same five-step developer path:

**install → configure provider → register tools → run agent → inspect events**

---

## Prerequisites

Before you write any code:

1. **Install the package** (`pip install kaji` or `npm install @kaji/sdk zod`)
2. **Install your provider SDK** (OpenAI or Anthropic; see below)
3. **Set an API key** (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`)

The SDK core has no required LLM dependency. The provider package is opt-in so
your image size reflects only what you use.

---

## MVP scope

| Feature | Python | TypeScript |
|---------|--------|------------|
| `AgentBuilder` + integrations | Yes | Yes |
| `AgentRuntime` ReAct loop | Yes | Yes |
| Tool registry + `ToolPlanner` + `ToolPolicy` | Yes | Yes |
| OpenAI provider | Yes | Yes |
| Anthropic provider | Yes | Yes |
| Event store + bus (in-memory) | Yes | Yes |
| Session replay (`replaySession`) | Yes | Yes |
| `kaji init` CLI scaffold | Yes | Not planned |
| `CancellationToken` | Yes | Yes |

---

## Current readiness snapshot

The core runtime exists in both packages, but "production-ready for developers"
also requires a stable first-run path, clear provider failures, and a real
integration catalog contract.

| Area | Python SDK | TypeScript SDK | MVP status |
|------|------------|----------------|------------|
| Embedded ReAct runtime | `AgentBuilder` builds a scoped `ToolRegistry`, `ToolPlanner`, and `AgentRuntime`. | Same shape as Python. | Implemented. |
| Custom tools | Works through `ToolRegistry`; `Integration` + `Tool` are exported from top-level `kaji`. | Works through `ToolRegistry`; `Integration` + `tool` accept Zod or JSON Schema parameters. | Implemented. |
| Provider setup | OpenAI/Anthropic raise `ProviderConfigError` and `ProviderAPIError`. | OpenAI/Anthropic raise `ProviderConfigError`, `ProviderAPIError`, and `ProviderConnectionError`. | Implemented. |
| Provider-safe tool names | `ToolSpec.name` is provider-safe (e.g. `weather_get_weather`); dotted identity preserved in `catalog_name`. | Same; preserved as `catalogName`. | Implemented. |
| First-party integration catalog | `kaji add` vendors GitHub/Gmail/GCal source into the user's tree. | No catalog yet. | Python partial; TS gap. |
| Event inspection | Store-backed event log is the source of truth. | Store-backed event log is the source of truth. | Implemented. |
| Quickstart protection | `tests/test_quickstart.py` + `tests/test_public_api.py`. | `bun run test:quickstart` plus Vitest discovery of `examples/**/*.test.ts`. | Implemented. |
| Public surface | Top-level `kaji` advertises only the MVP runtime; non-MVP features (RAG, text/voice modalities) live under submodules. | Top-level entry is MVP-only; `MockProvider` moved to `@kaji/sdk/testing`. | Implemented. |

The practical readiness judgement:

- Both SDKs satisfy the five-step embedded-agent path with OpenAI/Anthropic
  and developer-authored tools.
- Provider error contracts, tool-name safety, and the public surface are
  aligned across Python and TypeScript.
- The remaining gap is the first-party integration catalog contract: Python
  ships three CLI-vendored integrations but no shared manifest/auth/credential
  shape, and TypeScript has no catalog at all. See Plan 3 below.

---

## Out of MVP scope

These features exist in the Python SDK (and some in TS) but are **not required**
to build a working embedded agent and are not part of the getting-started path:

| Feature | Status |
|---------|--------|
| Kimi / Gemini providers | Python only |
| Document RAG / vector store | Python only |
| Tool retriever | Python only |
| Text modality adapter | Python only |
| Voice / TTS adapters | Python only (not hardened) |
| Redis realtime bus | Python only (not hardened) |
| `kaji-serve` (FastAPI + workers) | Python only (not hardened) |
| Durable event/session stores | Neither; bring your own |
| Observability / token metrics | Post-MVP |

"Not hardened" means the code is present but multi-process deployments need
additional load and durability testing before production use. See the Python
README for details.

---

## The five steps

### Step 1 - Install

**Python**

```bash
pip install 'kaji[openai]'     # OpenAI
# or
pip install 'kaji[anthropic]'  # Anthropic
```

**TypeScript**

```bash
npm install @kaji/sdk zod openai        # OpenAI
# or
npm install @kaji/sdk zod @anthropic-ai/sdk  # Anthropic
```

### Step 2 - Configure provider

**Python**

```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
import kaji
provider = kaji.get_provider("openai")   # reads OPENAI_API_KEY
# or
provider = kaji.get_provider("anthropic")
```

**TypeScript**

```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

```ts
import { OpenAIProvider } from "@kaji/sdk";
const provider = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! });
// or
import { AnthropicProvider } from "@kaji/sdk";
const provider = new AnthropicProvider({ apiKey: process.env.ANTHROPIC_API_KEY! });
```

### Step 3 - Register tools

**Python**

```python
from kaji import Integration, Tool, ToolContext

class WeatherIntegration(Integration):
    namespace = "weather"

    @Tool(
        description="Return weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        risk="read",
    )
    async def get_weather(self, ctx: ToolContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}
```

**TypeScript**

```ts
import { Integration, tool } from "@kaji/sdk";
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
```

### Step 4 - Run agent

**Python**

```python
import asyncio
from kaji import AgentBuilder, InMemoryEventBus, InMemoryEventStore, UserMessage

async def main():
    bus = InMemoryEventBus()
    store = InMemoryEventStore()

    runtime = (
        AgentBuilder()
        .provider(provider)             # from step 2
        .integration(WeatherIntegration())  # from step 3
        .system_prompt("You are a weather assistant.")
        .build(bus=bus, store=store)
    )

    await store.append(UserMessage(session_id="s1", content="Weather in Seattle?"))
    await runtime.run_turn("s1")

asyncio.run(main())
```

**TypeScript**

```ts
import {
  AgentBuilder,
  InMemoryEventStore,
  EventBus,
  KajiEvent,
  EventType,
} from "@kaji/sdk";

const store = new InMemoryEventStore();
const bus = new EventBus();

const runtime = new AgentBuilder()
  .provider(provider)                   // from step 2
  .integration(new WeatherIntegration())  // from step 3
  .systemPrompt("You are a weather assistant.")
  .build({ bus, store });

await store.append(
  KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }),
);
await runtime.send("s1", "Weather in Seattle?");
```

### Step 5 - Inspect events

**Python**

```python
events = await store.get_events("s1")
for e in events:
    print(e.type, getattr(e, "content", getattr(e, "delta", "")))
```

**TypeScript**

```ts
const events = await store.getEvents("s1");
for (const e of events) {
  console.log(e.type, "content" in e ? e.content : "delta" in e ? e.delta : "");
}
```

Events are written in chronological order. Key types to look for:

| Event type | Meaning |
|------------|---------|
| `user.message` | The message you sent |
| `agent.message.delta` | Streaming text chunk from the model |
| `agent.message.completed` | Full model response text |
| `tool.call.requested` | Model requested a tool |
| `tool.call.started` | Execution began |
| `tool.call.completed` | Tool returned a result |
| `tool.call.failed` | Tool raised an error |

---

## Adding persistence

The in-memory stores lose state on process restart. To persist:

- Drop in your own `EventStore` implementation (any async append + getEvents backend works)
- For a full platform with Postgres, Redis, and workers, see `kaji-serve`

---

## Testing without API keys

In unit tests, use mocked provider HTTP clients instead of real network calls.
Both SDKs have examples in their `tests/` directories. `MockProvider` (Python
and TS) is a deterministic stub that exercises the full tool loop; it is
**intentionally not** part of the production developer path; its behavior is
fixed and does not reflect real LLM outputs.

---

## CI checks by package

| Package | Checks |
|---------|--------|
| `kaji/sdk` | ty (type check), ruff (lint), pytest (unit + quickstart) |
| `kaji/ts` | tsc (type check), oxfmt (format), vitest (unit + quickstart) |
| `kaji/serve` | ruff (lint), pytest (unit); no ty until typing debt is addressed |

Install smoke jobs for both SDK packages validate that the published wheel /
tarball exports resolve correctly and provider errors are clear.

---

## When to use Redis vs kaji-serve

- **Single-process app, only one agent runtime:** in-memory bus and store. No Redis needed.
- **Multiple processes that need to share events:** add `pip install 'kaji[realtime]'` and swap `InMemoryEventBus` for `EventBus` (Redis-backed). Still no `kaji-serve` required.
- **Full hosted platform (REST API, voice WebSocket, async tool workers):** install `kaji-serve`. It wires the SDK + Redis + Postgres + TaskIQ into a deployable reference service.

---

## Runtime shape audit

The runtime should stay centered on this pipeline:

```text
AgentBuilder
  -> scoped ToolRegistry
  -> ToolPlanner
  -> AgentRuntime
  -> EventStore + EventBus
  -> ModelProvider
```

Current code paths:

- Python: `kaji/sdk/kaji/runtime/agents/builder.py` creates a scoped
  registry, registers each integration, builds a planner, and passes
  `registry.list_specs()` into `AgentRuntime`.
- Python: `kaji/sdk/kaji/runtime/agents/runtime.py` emits user,
  reasoning, message, cancellation, and tool events through `_emit()`, which
  appends to the store and publishes on the bus.
- TypeScript: `kaji/ts/src/runtime/builder.ts` mirrors the Python builder
  by creating a scoped `ToolRegistry`, `ToolPlanner`, and runtime.
- TypeScript: `kaji/ts/src/runtime/runtime.ts` appends `USER_MESSAGE` in
  `send()`, replays state in `runTurn()`, streams the provider, emits message
  events, and executes tool calls through `ToolPlanner`.

This shape is good for an SDK MVP. The main issue is not the ReAct loop; it is
the public contract around tool schemas, integration names, provider errors, and
catalog packaging.

---

## Hardening plans

Status summary: Plans 1, 2, 4, 5, 6 are implemented and are kept here as a
record of the contract each one fixes. Plan 3 (first-party integration
catalog) is the only outstanding item.

### Plan 1 - Make integration authoring one obvious path (implemented)

Today there are two styles:

- Plain objects with `register(registry)`.
- `Integration` subclasses with `namespace` and `Tool(...)` discovery.

Keep both internally if useful, but document and protect one beginner path in
both SDKs. The recommended external API should be the class-based integration
path, because it is the natural foundation for Gmail, Spotify, calendar, and
scraper-backed integrations.

Target Python shape:

```python
from kaji import Integration, Tool, ToolContext

class WeatherIntegration(Integration):
    @property
    def namespace(self) -> str:
        return "weather"

    @Tool(
        description="Return weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        risk="read",
    )
    async def get_weather(self, ctx: ToolContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}
```

Implemented Python changes:

- Export `Tool` from `kaji/__init__.py` next to `Integration`.
- Add a quickstart test that imports only from `kaji` and uses the snippet
  above.
- Keep `ToolRegistry` as the runtime primitive; do not move tool execution into
  service-style modules.

Target TypeScript shape:

```ts
import { Integration, tool } from "@kaji/sdk";
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
```

Implemented TypeScript changes:

- Change `ToolMeta.parameters` to accept `JSONSchema | z.ZodType`, then convert
  Zod schemas in `Integration.tools()` and `specFromTagged()`.
- Add `examples/**/*.test.ts` to `vitest.config.ts`.
- Ensure the example typechecks under the package `tsconfig`.

### Plan 2 - Separate catalog namespace from provider tool name (implemented)

The integration base currently prefixes names as `{namespace}.{tool_name}`.
That is useful for humans, policy, and catalog discovery, but provider tool-name
rules are stricter and commonly reject dots. The runtime should preserve a
catalog identity while exposing provider-safe tool names.

Target shape:

```ts
interface ToolSpec {
  name: string;          // provider-safe, e.g. "weather_get_weather"
  catalogName?: string;  // human/catalog identity, e.g. "weather.get_weather"
  description: string;
  parameters: Record<string, unknown>;
  risk?: ToolRisk;
}
```

Python should mirror the same idea on `ToolSpec`.

Implemented changes:

- Update integration registration to create provider-safe names consistently.
- Keep policy checks and event logs able to show the catalog identity.
- Add OpenAI and Anthropic provider tests that use an integration tool and assert
  the outbound tool names are provider-safe.

Current behavior:

- `Integration.register(...)` stores a provider-safe `ToolSpec.name` such as
  `weather_get_weather` or `weather_getWeather`.
- The original dotted catalog identity is retained as `ToolSpec.catalog_name`
  in Python and `ToolSpec.catalogName` in TypeScript.
- Tool lifecycle events keep the catalog identity in
  `metadata.catalog_name`.
- Tool policies accept either the safe provider name or the catalog name, with
  deny rules taking precedence.

### Plan 3 - Define the first-party integration catalog contract (open)

The production developer goal includes integrations such as Gmail and Spotify.
The current SDKs only provide a registry abstraction; they do not provide a
catalog, auth model, manifest, credential shape, or scraper fallback contract.

Add a small manifest contract before adding many integrations:

```ts
interface IntegrationManifest {
  id: string;
  displayName: string;
  auth: "api_key" | "oauth" | "none";
  scopes?: string[];
  tools: Array<{
    name: string;
    description: string;
    risk: ToolRisk;
  }>;
}
```

Python should expose the same fields as a dataclass or Pydantic model.

Implementation order:

1. Add shared manifest concepts in each SDK's integration package.
2. Build one low-risk integration end to end in both SDKs, such as a read-only
   web/search or mock calendar integration.
3. Add one authenticated integration after credential injection is explicit.
4. Only then add scraper-backed fallbacks, with clear risk and rate-limit
   behavior.

### Plan 4 - Normalize provider errors across SDKs (implemented)

Python already has provider-specific error classes in
`kaji.runtime.providers.errors`. TypeScript should get the same public
contract so missing packages, missing keys, provider API failures, and
cancellation are distinguishable.

Status: implemented for TypeScript provider configuration and provider API
failures. Cancellation remains on the existing runtime cancellation path and is
not wrapped as a provider error.

Implemented TypeScript shape:

```ts
export class ProviderError extends Error {}
export class ProviderConfigError extends ProviderError {}
export class ProviderAPIError extends ProviderError {}
export class ProviderConnectionError extends ProviderError {}
```

Required TypeScript changes:

- Wrap lazy import failures with `ProviderConfigError`.
- Validate empty API keys in provider constructors.
- Wrap OpenAI/Anthropic API failures with `ProviderAPIError`.
- Keep cancellation as a runtime cancellation error, not a provider config or
  provider API error.

### Plan 5 - Tighten the public MVP surface (implemented)

Python exports several non-MVP features from the top-level package: text
modality, TTS, tool retrieval, and document RAG. These can remain implemented,
but the public getting-started surface should make the MVP path obvious.

Status: implemented for the package entrypoints. The Python top-level
`kaji` namespace now advertises the MVP runtime, providers, events,
sessions, tools, and integration helpers. Non-MVP extensions remain importable
from their owning submodules, such as `kaji.knowledge` and
`kaji.modalities.text`. The TypeScript main entrypoint no longer exports
the deterministic test provider; tests import it from `@kaji/sdk/testing`.

Required changes:

- Keep top-level exports for stable MVP names: events, builder/runtime,
  providers, integrations, tools, sessions, policies, and cancellation.
- Move non-MVP features in docs to explicit subpackage imports.
- Use `@kaji/sdk/testing` for TypeScript test-only helpers such as
  `MockProvider`.
- Add `test_public_api.py` assertions for the names that must stay available in
  the five-step path.

### Plan 6 - Make CI prove the first-run experience (implemented)

The SDKs should not be considered MVP-ready unless CI runs the exact first-run
path without API keys.

Required checks:

```bash
# Python SDK
uv run ty check
uv run ruff check src tests
uv run pytest tests/test_quickstart.py tests/test_public_api.py -q

# TypeScript SDK
bun run typecheck
bun run format:check
bun run test
bun run test:quickstart
```

The TypeScript quickstart check must actually discover the quickstart test. The
package now includes `examples/**/*.test.ts` in Vitest and includes `examples`
in the local TypeScript project so the source quickstart typechecks.

---

## Production MVP exit criteria

Both SDKs are ready for a developer MVP when all of these are true:

- A new developer can install the package and one provider dependency, paste the
  five-step snippet, and run an agent without reading internal module docs.
- The same integration authoring pattern works in Python and TypeScript.
- Tool schema input is ergonomic in each language: Pydantic or JSON Schema in
  Python, Zod or JSON Schema in TypeScript.
- Provider errors explain the missing package, missing key, API failure, or
  cancellation clearly.
- At least one first-party integration proves the catalog contract end to end.
- Event stores remain pluggable, and in-memory store/bus behavior is documented
  as single-process only.
- CI protects typecheck, lint/format, unit tests, package install smoke, and the
  quickstart path for both SDKs.
