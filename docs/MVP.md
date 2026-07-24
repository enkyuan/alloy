# Kaji MVP

This document defines the MVP scope for the Kaji SDKs. It is focused on the
Python (`kaji`) and TypeScript (`kaji-sdk`) packages; `kaji-serve`
is treated as out of scope for the SDK production-readiness path.

Both SDKs target the same five-step developer path:

**install → configure provider → register tools → run agent → inspect events**

---

## Prerequisites

Before you write any code:

1. **Install the package** (`pip install 'kaji-sdk==0.2.0b1'` or `npm install kaji-sdk@0.2.0-beta.2 zod`)
2. **Install your provider SDK** (OpenAI or Anthropic; see below)
3. **Set an API key for live providers** (`OPENAI_API_KEY` or
   `ANTHROPIC_API_KEY`). The installed-package mock quickstart needs no key.

The SDK core has no required LLM dependency. The provider package is opt-in so
your image size reflects only what you use.

---

## MVP scope

| Feature                                      | Python | TypeScript |
| -------------------------------------------- | ------ | ---------- |
| `AgentBuilder` + integrations                | Yes    | Yes        |
| `AgentRuntime` ReAct loop                    | Yes    | Yes        |
| Tool registry + `ToolPlanner` + `ToolPolicy` | Yes    | Yes        |
| OpenAI provider                              | Yes    | Yes        |
| Anthropic provider                           | Yes    | Yes        |
| Event store + bus (in-memory)                | Yes    | Yes        |
| Session replay (`replaySession`)             | Yes    | Yes        |
| `kaji init` CLI scaffold                     | Yes    | Yes        |
| `CancellationToken`                          | Yes    | Yes        |

---

## Current readiness snapshot

The core runtime exists in both packages. This is a pre-beta release
implementation, not a production-beta claim. Promotion remains blocked until
the same release commit supplies the protected floor/latest runtime, required
keyed OpenAI and Anthropic proofs, three-replica paired A/B benchmark, separate
30-minute soak, signed-tag, provenance, and publication evidence.

The operating contract and exact defaults are in
[`docs/kaji/production-beta.md`](kaji/production-beta.md). Concurrency,
tool-safety, integration-schema, migration, and failure guidance live beside
it in [`docs/kaji/`](kaji/).

| Area                            | Python SDK                                                                                                  | TypeScript SDK                                                                                   | MVP status                                                                           |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Embedded ReAct runtime          | `AgentBuilder` builds a scoped `ToolRegistry`, `ToolPlanner`, and `AgentRuntime`.                           | Same shape as Python.                                                                            | Implemented.                                                                         |
| Custom tools                    | Works through `ToolRegistry`; `Integration` + `tool` are exported from top-level `kaji`.                    | Works through `ToolRegistry`; `Integration` + `tool` accept Zod or JSON Schema parameters.       | Implemented.                                                                         |
| Provider setup                  | OpenAI/Anthropic raise `ProviderConfigError` and `ProviderAPIError`.                                        | OpenAI/Anthropic raise `ProviderConfigError`, `ProviderAPIError`, and `ProviderConnectionError`. | Implemented.                                                                         |
| Provider-safe tool names        | `ToolSpec.name` is provider-safe (e.g. `weather_get_weather`); dotted identity preserved in `catalog_name`. | Same; preserved as `catalogName`.                                                                | Implemented.                                                                         |
| First-party integration catalog | Python ships the `echo` proof integration and validates manifests against the shared schema.                | TypeScript ships local/dev examples and validates manifests against the same schema.             | Catalog contract implemented; production third-party integrations remain out of MVP. |
| Event inspection                | Store-backed event log is the source of truth.                                                              | Store-backed event log is the source of truth.                                                   | Implemented.                                                                         |
| Quickstart protection           | `tests/test_quickstart.py` + `tests/test_public_api.py`.                                                    | `bun run test:quickstart` plus Vitest discovery of `examples/**/*.test.ts`.                      | Implemented.                                                                         |
| Public surface                  | Top-level `kaji` includes the core runtime plus documented Python extensions.                               | Top-level entry is MVP-focused; `MockProvider` moved to `kaji-sdk/testing`.                     | Implemented; keep docs honest.                                                       |

The practical readiness judgement:

- Both SDKs satisfy the five-step embedded-agent path with OpenAI/Anthropic
  and developer-authored tools.
- Provider error contracts, tool-name safety, and the public surface are
  aligned across Python and TypeScript.
- Catalog contract implemented: both SDKs validate the same closed manifest
  and registry-index schemas,
  including `extras`, `peerDeps`, and non-empty `tools`. The remaining
  integration work is production expansion: auth flows, credential storage,
  third-party catalogs, and scraper fallback policy.
- RAG/retrieval remains experimental even where implemented; it is not part of
  the beta support promise.

---

## Out of MVP scope

These features exist in the Python SDK (and some in TS) but are **not required**
to build a working embedded agent and are not part of the getting-started path:

| Feature                          | Status                                                  |
| -------------------------------- | ------------------------------------------------------- |
| Kimi / Gemini providers          | Python native; TS OpenAI-compatible factories           |
| Document RAG / vector store      | Python only                                             |
| Tool retriever                   | Python only                                             |
| Text modality adapter            | Python only                                             |
| Voice / TTS adapters             | Python only (not hardened)                              |
| Redis realtime bus               | Python only (not hardened)                              |
| `kaji-serve` (REST + Soniox STT) | Python only; excluded from the 0.2 SDK beta             |
| Durable event/session stores     | Neither; bring your own                                 |
| Observability / token metrics    | Core event schema and streamed usage/cost metadata only |

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
pip install 'kaji-sdk[openai]==0.2.0b1'     # OpenAI
# or
pip install 'kaji-sdk[anthropic]==0.2.0b1'  # Anthropic
```

**TypeScript**

```bash
npm install kaji-sdk@0.2.0-beta.2 zod openai        # OpenAI
# or
npm install kaji-sdk@0.2.0-beta.2 zod @anthropic-ai/sdk  # Anthropic
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
import { OpenAIProvider } from "kaji-sdk";
const provider = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! });
// or
import { AnthropicProvider } from "kaji-sdk";
const provider = new AnthropicProvider({ apiKey: process.env.ANTHROPIC_API_KEY! });
```

### Step 2.5 - Prove one real agent

Use OpenAI `gpt-5.4-mini` as the first live SDK proof. It is the lowest-friction
path that exercises a real model, a real tool call, SDK tool execution, and
final assistant text.

**Python**

```bash
cd kaji
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

These developer tests may skip without keys, but a skip is not release
evidence. The protected release requires OpenAI and Anthropic normalized tool
loops in Python and TypeScript on one exact commit; either missing credential
blocks release. Native Gemini and Kimi remain experimental.

For release readiness, run the cross-SDK gate from the repository root:

```bash
uv run --project kaji python kaji/scripts/beta_release_check.py
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, mandatory pinned ast-grep boundary checks, and no-key
live-gate hygiene. The ast-grep step guards the Python SDK/service boundary, core package dependency direction, legacy tool-model imports, TypeScript optional provider imports, and cancellation error shape.

For the live-gate credential modes specifically:

```bash
uv run --project kaji python kaji/scripts/verify_openai_loop.py
KAJI_REQUIRE_LIVE_KEYS=1 uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

Without `OPENAI_API_KEY`, the first command proves missing-key hygiene only.
It is not provider evidence. The protected `live_provider_proof.py` gate
requires both OpenAI and Anthropic credentials and fails loudly if either is
absent.

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

The same keyed proof can be included in the wrapper with
`OPENAI_API_KEY=... KAJI_RUN_KEYED_LIVE=1 uv run --project kaji python kaji/scripts/beta_release_check.py`.

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
from kaji import Integration, ToolExecutionContext, tool

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
    async def get_weather(self, ctx: ToolExecutionContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}
```

**TypeScript**

```ts
import { Integration, tool } from "kaji-sdk";
import { z } from "zod";

class WeatherIntegration extends Integration {
  readonly namespace = "weather";

  readonly getWeather = tool(
    {
      description: "Return weather for a city.",
      parameters: z.object({ city: z.string() }),
      risk: "read",
    },
    async (args, _context) => ({ city: args.city, tempF: 68 }),
  );
}
```

### Step 4 - Run agent

**Python**

```python
import asyncio
from kaji import AgentBuilder, TurnContext

async def main():
    runtime = (
        AgentBuilder()
        .provider(provider)             # from step 2
        .integration(WeatherIntegration())  # from step 3
        .system_prompt("You are a weather assistant.")
        .build()
    )

    result = await runtime.turn(
        "Weather in Seattle?",
        context=TurnContext(principal_id="weather-app"),
    )
    print(result.text)

asyncio.run(main())
```

**TypeScript**

```ts
import { AgentBuilder } from "kaji-sdk";

const runtime = new AgentBuilder()
  .provider(provider) // from step 2
  .integration(new WeatherIntegration()) // from step 3
  .systemPrompt("You are a weather assistant.")
  .build();

const result = await runtime.turn("Weather in Seattle?", {
  context: { principalId: "weather-app" },
});
console.log(result.text);
```

### Step 5 - Inspect events

**Python**

```python
for e in result.events:
    print(e.id, e.sequence, e.turn_id, e.type)
```

**TypeScript**

```ts
for (const e of result.events) {
  console.log(e.id, e.sequence, e.turn_id, e.type);
}
```

Events are written in contiguous session-local sequence order. Timestamps are
observability data and do not determine replay order. Key types to look for:

| Event type                | Meaning                             |
| ------------------------- | ----------------------------------- |
| `user.message`            | The message you sent                |
| `agent.message.delta`     | Streaming text chunk from the model |
| `agent.message.completed` | Full model response text            |
| `tool.call.requested`     | Model requested a tool              |
| `tool.call.started`       | Execution began                     |
| `tool.call.completed`     | Tool returned a result              |
| `tool.call.failed`        | Tool raised an error                |

---

## Adding persistence

The in-memory stores lose state on process restart. To persist:

- Inject an `EventStore` with append, exclusive cursor reads, and
  `lastSequence`/`last_sequence`, plus the canonical journal/committer boundary.
- `kaji-serve` provides a Postgres-backed session index, not persistent runtime
  event replay; a host must supply that boundary explicitly.

---

## Testing without API keys

In unit tests, use mocked provider HTTP clients instead of real network calls.
Both SDKs have examples in their `tests/` directories. `MockProvider` (Python
and TS) is a deterministic stub that exercises the full tool loop; it is
**intentionally not** part of the production developer path; its behavior is
fixed and does not reflect real LLM outputs.

---

## CI checks by package

| Package      | Checks                                                                                    |
| ------------ | ----------------------------------------------------------------------------------------- |
| `kaji`   | `scripts/check_types.py` (ty with the src remap), ruff (lint), pytest (unit + quickstart) |
| `kaji/ts`    | tsc (type check), oxfmt (format), vitest (unit + quickstart)                              |
| `kaji/serve` | ruff (lint), pytest (unit); no ty until typing debt is addressed                          |

Install smoke jobs for both SDK packages validate that the published wheel /
tarball exports resolve correctly and provider errors are clear.

Python release packaging must also run:

```bash
cd kaji
uv run python scripts/clean_caches.py
uv run python scripts/release_smoke.py
```

`scripts/release_smoke.py` builds the wheel, verifies wheel contents, installs
the wheel into a temporary virtualenv, and runs `scripts/smoke_install.py`.

---

## Choosing an embedding or service boundary

- **Single-process app, only one agent runtime:** in-memory bus and store. No Redis needed.
- **Multiple processes that need to share events:** bring a durable event store
  and coordination layer. The Redis split adapter is experimental and is not a
  production durability claim.
- **REST and live transcription edge:** `kaji-serve` exposes reference REST
  routes and a Soniox STT WebSocket. The host application owns the hand-off of
  final transcripts to an embedded `AgentRuntime`; the service has no hosted
  agent loop or background tool worker.

---

## Runtime shape audit

The runtime should stay centered on this pipeline:

```text
AgentBuilder
  -> scoped ToolRegistry
  -> ToolPlanner
  -> AgentRuntime
  -> EventJournal / EventCommitter
  -> EventStore
  -> ModelProvider
```

Current code paths:

- Python: `kaji/src/kaji/runtime/agents/builder.py` creates a scoped
  registry, registers each integration, builds a planner, and passes
  `registry.list_specs()` into `AgentRuntime`.
- Python: `kaji/src/kaji/runtime/agents/runtime.py` commits runtime events through
  the journal and advances a cursor-based session projector.
- TypeScript: `kaji/ts/src/runtime/builder.ts` mirrors the Python builder
  by creating a scoped `ToolRegistry`, `ToolPlanner`, and runtime.
- TypeScript: `kaji/ts/src/runtime/runtime.ts` commits through `EventCommitter`,
  advances a cursor projector, streams the provider, and executes tool calls
  through `ToolPlanner`.

This shape is good for an SDK MVP. The main issue is not the ReAct loop; it is
the public contract around tool schemas, integration names, provider errors, and
catalog packaging.

---

## Hardening plans

Status summary: the plans below are a historical design record. Their current
contracts are implemented; the canonical status and supported surface now live
in `kaji/contracts`, `kaji/RELEASE_MATRIX.md`, and `docs/kaji/`.

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
from kaji import Integration, ToolExecutionContext, tool

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
    async def get_weather(self, ctx: ToolExecutionContext, args: dict) -> dict:
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
import { Integration, tool } from "kaji-sdk";
import { z } from "zod";

class WeatherIntegration extends Integration {
  readonly namespace = "weather";

  readonly getWeather = tool(
    {
      description: "Return weather for a city.",
      parameters: z.object({ city: z.string() }),
      risk: "read",
    },
    async (args, _context) => ({ city: args.city, tempF: 68 }),
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
  name: string; // provider-safe, e.g. "weather_get_weather"
  catalogName?: string; // human/catalog identity, e.g. "weather.get_weather"
  description: string;
  parameters: Record<string, unknown>;
  risk: ToolRisk;
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

The current SDKs share closed manifest and registry-index schemas. Echo is the
only beta catalog entry; GitHub is experimental. Production credential
storage, third-party catalogs, and scraper
fallback policy remain future integration-expansion work.

Current manifest contract:

```ts
interface IntegrationManifest {
  name: string;
  version: string;
  namespace: string;
  description: string;
  auth:
    | { kind: "none" }
    | { kind: "env"; env: string; optional?: boolean; docs?: string }
    | { kind: "oauth"; scopes: string[]; docs?: string };
  files: string[];
  extras?: string[];
  peerDeps?: Record<string, string>;
  tools: Array<{
    name: string;
    description: string;
    risk: "read" | "write" | "external_effect" | "destructive" | "admin";
  }>;
}
```

Python and TypeScript validate canonical byte-identical schema copies and the
index's explicit `manifest`, `stability`, and `runtimes` fields. See
`docs/kaji/integration-manifests.md` for the executable contract.

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

Status: implemented for the package entrypoints. The Python top-level `kaji`
namespace includes the stable runtime plus documented experimental extensions;
top-level importability does not promote RAG/retrieval into the beta promise.
The TypeScript main entrypoint does not export the deterministic test provider;
tests import it from `kaji-sdk/testing`.

Required changes:

- Keep top-level exports for stable MVP names: events, builder/runtime,
  providers, integrations, tools, sessions, policies, and cancellation.
- Move non-MVP features in docs to explicit subpackage imports.
- Use `kaji-sdk/testing` for TypeScript test-only helpers such as
  `MockProvider`.
- Add `test_public_api.py` assertions for the names that must stay available in
  the five-step path.

### Plan 6 - Make CI prove the first-run experience (implemented)

The SDKs should not be considered MVP-ready unless CI runs the exact first-run
path without API keys.

Required checks:

```bash
# Python SDK
uv run python scripts/check_types.py
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

## Historical MVP exit criteria

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
