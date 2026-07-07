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
| `kaji init` CLI scaffold | Yes | Yes |
| `CancellationToken` | Yes | Yes |

---

## Current readiness snapshot

The core runtime exists in both packages, but "production-ready for developers"
also requires a stable first-run path, clear provider failures, and a real
integration catalog contract.

| Area | Python SDK | TypeScript SDK | MVP status |
|------|------------|----------------|------------|
| Embedded ReAct runtime | `AgentBuilder` builds a scoped `ToolRegistry`, `ToolPlanner`, and `AgentRuntime`. | Same shape as Python. | Implemented. |
| Custom tools | Works through `ToolRegistry`; `Integration` + `tool` are exported from top-level `kaji`. | Works through `ToolRegistry`; `Integration` + `tool` accept Zod or JSON Schema parameters. | Implemented. |
| Provider setup | OpenAI/Anthropic raise `ProviderConfigError` and `ProviderAPIError`. | OpenAI/Anthropic raise `ProviderConfigError`, `ProviderAPIError`, and `ProviderConnectionError`. | Implemented. |
| Provider-safe tool names | `ToolSpec.name` is provider-safe (e.g. `weather_get_weather`); dotted identity preserved in `catalog_name`. | Same; preserved as `catalogName`. | Implemented. |
| First-party integration catalog | Python ships the `echo` proof integration and validates manifests against the shared schema. | TypeScript ships local/dev examples and validates manifests against the same schema. | Catalog contract implemented; production third-party integrations remain out of MVP. |
| Event inspection | Store-backed event log is the source of truth. | Store-backed event log is the source of truth. | Implemented. |
| Quickstart protection | `tests/test_quickstart.py` + `tests/test_public_api.py`. | `bun run test:quickstart` plus Vitest discovery of `examples/**/*.test.ts`. | Implemented. |
| Public surface | Top-level `kaji` includes the core runtime plus documented Python extensions. | Top-level entry is MVP-focused; `MockProvider` moved to `@kaji/sdk/testing`. | Implemented; keep docs honest. |

The practical readiness judgement:

- Both SDKs satisfy the five-step embedded-agent path with OpenAI/Anthropic
  and developer-authored tools.
- Provider error contracts, tool-name safety, and the public surface are
  aligned across Python and TypeScript.
- Catalog contract implemented: both SDKs validate the same v0 manifest shape,
  including `extras`, `peerDeps`, and non-empty `tools`. The remaining
  integration work is production expansion: auth flows, credential storage,
  third-party catalogs, and scraper fallback policy.

---

## Out of MVP scope

These features exist in the Python SDK (and some in TS) but are **not required**
to build a working embedded agent and are not part of the getting-started path:

| Feature | Status |
|---------|--------|
| Kimi / Gemini providers | Python native; TS OpenAI-compatible factories |
| Document RAG / vector store | Python only |
| Tool retriever | Python only |
| Text modality adapter | Python only |
| Voice / TTS adapters | Python only (not hardened) |
| Redis realtime bus | Python only (not hardened) |
| `kaji-serve` (FastAPI + workers) | Python only (not hardened) |
| Durable event/session stores | Neither; bring your own |
| Observability / token metrics | Core event schema and streamed usage/cost metadata only |

"Not hardened" means the code is present but multi-process deployments need
additional load and durability testing before production use. See the Python
README for details.

## Stability tiers

- **Stable core:** `AgentBuilder`, `AgentRuntime`, `ToolRegistry`,
  `ToolPlanner`, session replay, OpenAI/Anthropic providers, and the in-memory
  event bus/store are the embedded-agent contract both SDKs must keep green.
- **Experimental Python-only:** Redis realtime/history, voice/TTS,
  `DocumentRAG`, native Gemini/Kimi providers, tool retrieval, and text/voice
  modalities are available in Python but are not production-hardened.
- **TS not ported:** Redis realtime, voice/TTS, and RAG are not implemented in
  TypeScript. TS Gemini/Kimi remain OpenAI-compatible factories rather than
  native provider implementations.

See [`kaji/RELEASE_MATRIX.md`](../kaji/RELEASE_MATRIX.md) for the cross-SDK
release matrix and the exact distinction between stable core, experimental
Python-only surfaces, and TypeScript surfaces that are not ported.

The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
`DocumentRAG`, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.

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

### Step 2.5 - Prove one real agent

Use OpenAI `gpt-5.4-mini` as the first live SDK proof. It is the lowest-friction
path that exercises a real model, a real tool call, SDK tool execution, and
final assistant text.

**Python**

```bash
cd kaji/sdk
uv run pytest tests/test_quickstart.py -q
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  uv run pytest -m integration tests/integration/test_openai_tools.py -q
```

**TypeScript**

```bash
cd kaji/ts
bun run test:quickstart
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  bun run test:integration tests/integration/openai-tools.test.ts
```

Live tests are optional and skip without keys. After OpenAI passes, test
Anthropic, Python Gemini native, TS Gemini via the OpenAI-compatible factory,
then Kimi/OpenRouter. TS Kimi and Gemini are OpenAI-compatible factories, not
native provider implementations.

For release readiness, run the cross-SDK gate from the repository root:

```bash
bash kaji/scripts/beta-release-check.sh
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, ast-grep when available, and no-key live-gate hygiene.

For the live-gate credential modes specifically:

```bash
bash kaji/scripts/live-openai-tool-loop.sh
KAJI_REQUIRE_LIVE_KEYS=1 bash kaji/scripts/live-openai-tool-loop.sh
```

Without `OPENAI_API_KEY`, the first command proves import and skip hygiene only.
It is not a provider-readiness signal. With `KAJI_REQUIRE_LIVE_KEYS=1`, the
same no-key state fails loudly. A release cannot be called live-ready until this
command exits with `PASS: OpenAI live tool-loop readiness verified` while
`OPENAI_API_KEY` is set:

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```

The same keyed proof can be included in the wrapper with
`OPENAI_API_KEY=... KAJI_RUN_KEYED_LIVE=1 bash kaji/scripts/beta-release-check.sh`.

### Step 2.6 - Scaffold the first run

The cross-language `@kaji/cli` scaffold should lead to the same public SDK API
as the hand-written quickstarts:

```bash
kaji init --cwd ./my-agent --lang ts --provider openai --yes
cd ./my-agent
bun install
export OPENAI_API_KEY=sk-...
bun start
```

```bash
kaji init --cwd ./my-agent --lang python --provider openai --yes
cd ./my-agent
python -m pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python agent.py
```

Generated agents call `turn("Say hello.")`. MCP server setup is not part of
the MVP scaffold path until a real server command exists.

### Step 3 - Register tools

**Python**

```python
from kaji import Integration, ToolContext, tool

class WeatherIntegration(Integration):
    namespace = "weather"

    @tool(
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
from kaji import AgentBuilder

async def main():
    runtime = (
        AgentBuilder()
        .provider(provider)             # from step 2
        .integration(WeatherIntegration())  # from step 3
        .system_prompt("You are a weather assistant.")
        .build()
    )

    result = await runtime.turn("Weather in Seattle?")
    print(result.text)

asyncio.run(main())
```

**TypeScript**

```ts
import { AgentBuilder } from "@kaji/sdk";

const runtime = new AgentBuilder()
  .provider(provider)                   // from step 2
  .integration(new WeatherIntegration())  // from step 3
  .systemPrompt("You are a weather assistant.")
  .build();

const result = await runtime.turn("Weather in Seattle?");
console.log(result.text);
```

### Step 5 - Inspect events

**Python**

```python
for e in result.events:
    print(e.type, getattr(e, "content", getattr(e, "delta", "")))
```

**TypeScript**

```ts
for (const e of result.events) {
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
| `kaji/sdk` | `scripts/typecheck_ty.py` (ty with the src remap), ruff (lint), pytest (unit + quickstart) |
| `kaji/ts` | tsc (type check), oxfmt (format), vitest (unit + quickstart) |
| `kaji/serve` | ruff (lint), pytest (unit); no ty until typing debt is addressed |

Install smoke jobs for both SDK packages validate that the published wheel /
tarball exports resolve correctly and provider errors are clear.

Python release packaging must also run:

```bash
cd kaji/sdk
bash scripts/clean_generated.sh
bash scripts/release_smoke.sh
```

`scripts/release_smoke.sh` builds the wheel, verifies wheel contents, installs
the wheel into a temporary virtualenv, and runs `scripts/smoke_install.py`.

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
- `Integration` subclasses with `namespace` and `tool(...)` discovery.

Keep both internally if useful, but document and protect one beginner path in
both SDKs. The recommended external API should be the class-based integration
path, because it is the natural foundation for Gmail, Spotify, calendar, and
scraper-backed integrations.

Target Python shape:

```python
from kaji import Integration, ToolContext, tool

class WeatherIntegration(Integration):
    @property
    def namespace(self) -> str:
        return "weather"

    @tool(
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

- Export `tool` from `kaji/__init__.py` next to `Integration`.
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

### Plan 3 - Define the first-party integration catalog contract (implemented)

The production developer goal includes integrations such as Gmail and Spotify.
The current SDKs now share a v0 manifest contract for registry entries, but
production auth, credential storage, third-party catalogs, and scraper fallback
policy remain future integration-expansion work.

Current manifest contract:

```ts
interface IntegrationManifest {
  name: string;
  version: string;
  namespace: string;
  description: string;
  auth: { kind: "none" | "api_key" | "oauth" };
  files: string[];
  extras?: string[];
  peerDeps?: Record<string, string>;
  tools: Array<{
    name: string;
    description: string;
  }>;
}
```

Python and TypeScript validate this contract against normalized equivalent
`schema.json` files. This is enough for the pre-beta SDK catalog proof.

Future production integration expansion order:

1. Build one low-risk integration end to end in both SDKs, such as a read-only
   web/search or mock calendar integration.
2. Add one authenticated integration after credential injection is explicit.
3. Only then add scraper-backed fallbacks, with clear risk and rate-limit
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
uv run python scripts/typecheck_ty.py
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
