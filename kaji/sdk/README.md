# kaji

`kaji` is an embeddable SDK for building agents into your own platform:
import the pieces you need and compose them. The core is dependency-injected and
infra-free (no database, Supabase, FastAPI, or web server required).

> **Status:** pre-beta, MVP-ready for embedded agents. The core SDK (runtime,
> toolgen, OpenAI/Anthropic providers, and session replay) is suitable for
> internal embedded agents. Multi-process platform features (Redis event
> backbone, Postgres session index, voice workers) are present but not
> production-hardened. Durable event replay is not wired by default; do not
> deploy the realtime/voice stack without additional load and durability
> testing.

See [**Kaji MVP**](../../docs/MVP.md) for the full five-step developer path and scope
definition.

## Install

```bash
pip install 'kaji[openai]'     # OpenAI (recommended)
# or
pip install 'kaji[anthropic]'  # Anthropic
# or
pip install kaji               # core only, bring your own provider
```

Other optional extras:

```bash
pip install 'kaji[gemini]'      # Gemini provider
pip install 'kaji[realtime]'    # Redis event bus (multi-process)
pip install 'kaji[providers]'   # all provider SDKs
```

## Quick start

Set an API key, then build an agent with `AgentBuilder`:

```bash
export OPENAI_API_KEY=sk-...
# or: export ANTHROPIC_API_KEY=sk-ant-...
```

```python
import asyncio
import kaji


class WeatherIntegration(kaji.Integration):
    namespace = "weather"

    @kaji.tool(
        description="Return weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        risk="read",
    )
    async def get_weather(self, ctx: kaji.ToolContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}


async def main():
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("openai"))  # reads OPENAI_API_KEY
        .integration(WeatherIntegration())
        .system_prompt("You are a weather assistant.")
        .build()
    )

    result = await runtime.turn("Weather in Seattle?")
    print(result.text)


asyncio.run(main())
```

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable. Swap `.provider(kaji.get_provider("anthropic"))` to use Anthropic.

Tool schemas use Draft 2020-12 JSON Schema with format checking. Both
`ToolPlanner` and direct `ToolRegistry.execute()` calls validate before a
handler can start. `ToolSchemaValidator` is available for hosts that need the
same validation boundary outside the runtime; invalid definitions raise
`ToolSchemaValidationError`, and invalid arguments raise
`ToolArgumentValidationError` with a safe error code, JSON Pointer, and
message.

## Event journal contract

`EventJournal` is the stable persistence boundary for runtime events. New
events enter as `NewKajiEvent` values without a sequence; a successful commit
returns a sequenced `StoredKajiEvent` directly. The lower-level
`EventStore.append()` compatibility path returns `AppendResult(event, inserted)`
so journals can suppress duplicate fanout. `AgentBuilder` uses
`InMemoryEventJournal` by default so persistence and live delivery share one
atomic, process-local path.

`AgentRuntime.history()` and `TextSession.events()` return at most 1,024 stored
events by default. Pass `after_sequence` and `limit` to page explicitly.

`replay_session()` accepts stored, sequenced events only. Applications importing
old unsequenced logs must opt into `replay_legacy_session()`, which emits
`LegacyEventOrderingWarning` and uses stable timestamp/input order.

`SplitEventJournal` is the experimental adapter for deployments with separate
`EventStore` and `EventBus` implementations. Callers can distinguish
`EventIdConflictError`, `EventStoreCapacityError`,
`EventBufferOverflowError`, and `EventDeliveryError` when applying retry,
resume, or backpressure policy.

## Prove it with a model

OpenAI with `gpt-5.4-mini` is the recommended first live check because it is
cost-effective and exercises the SDK's Chat Completions tool path.

```bash
cd kaji/sdk
uv sync --extra openai
uv run pytest tests/test_quickstart.py -q
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  uv run pytest -m integration tests/integration/test_openai_tools.py -q
```

The live test registers a read-only probe tool, verifies the model calls it,
and verifies the runtime emits final assistant text using the tool result. It
skips automatically when `OPENAI_API_KEY` is absent. After OpenAI passes, test
providers in this order: Anthropic, Python Gemini native, then Kimi/OpenRouter.

For the cross-SDK release gate, run from the repository root:

```bash
bash kaji/scripts/beta-release-check.sh
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, ast-grep boundary checks when available, and no-key
live-gate hygiene. The ast-grep step guards the Python SDK/service boundary, core package dependency direction, legacy tool-model imports, TypeScript optional provider imports, and cancellation error shape.

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

## Stability tiers

- **Stable core:** `AgentBuilder`, `AgentRuntime`, `ToolRegistry`,
  `ToolPlanner`, session replay, OpenAI/Anthropic providers, and the in-memory
  event bus/store are the pre-beta embedded-agent surface.
- **Experimental Python-only:** Redis realtime/history, voice/TTS,
  `DocumentRAG`, native Gemini/Kimi providers, tool retrieval, and text/voice
  modalities exist for early adopters but are not production-hardened.
- **TS not ported:** Redis realtime, voice/TTS, and RAG are not implemented in
  TypeScript. TS Gemini/Kimi remain OpenAI-compatible factories rather than
  native provider implementations.

See [`kaji/RELEASE_MATRIX.md`](../RELEASE_MATRIX.md) for the cross-SDK release
matrix and the exact distinction between stable core, experimental Python-only
surfaces, and TypeScript surfaces that are not ported.

The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
`DocumentRAG`, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.

## CLI scaffold

```bash
kaji init ./my-agent
```

Creates `agent.py` and `.env.example` in `./my-agent` wired to `AgentBuilder`
with an env-driven provider (set `KAJI_MODEL_PROVIDER` to `openai` or
`anthropic`, plus the matching API key).

## What's exported

| Name | What it is |
| --- | --- |
| `AgentBuilder` | Fluent builder wiring provider + integrations + policy into `AgentRuntime` |
| `AgentRuntime` | Provider-agnostic ReAct loop |
| `ToolSpec`, `ToolRegistry`, `ToolContext` | Tool definition, scoped registry, and execution context |
| `tool`, `function_tool`, `register_tool`, `list_tool_specs` | PEP 8 decorators and registry helpers for declaring and listing tools |
| `Integration` | Namespace-scoped tool bundle base class |
| `EventStore`, `InMemoryEventStore`, `EventBus`, `InMemoryEventBus` | Append-only event log and per-session pub/sub (abstract + in-memory) |
| `UserMessage` | Convenience constructor for the initial `user.message` event |
| `replay_session`, `SessionManager`, `SessionState` | Session state projection and management |
| `SessionStore`, `InMemorySessionStore`, `SessionRecord` | Cross-session index keyed by user (process-local default; postgres opt-in) |
| `HistoryStore`, `InMemoryHistoryStore` | Conversation history backend for reasoning nodes (in-memory default; Redis opt-in) |
| `Chunk`, `Document`, `DocumentRAG`, `VectorStore`, `InMemoryVectorStore` | Document RAG primitives: chunking, ingest, retrieval |
| `ToolRetriever`, `Embedder`, `EmbeddingCache` | Semantic tool retrieval with a pluggable embedder and cache |
| `build_tools_payload`, `spec_to_neutral` | Build the neutral tool payload from the registry |
| `to_openai`, `to_anthropic`, `to_gemini` | Per-provider translators applied at the provider boundary |
| `ModelProvider`, `get_provider`, `register_provider` | Provider protocol + registry |
| `ProviderMessage`, `ProviderToolSpec` | TypedDicts documenting the neutral message + tool payload the runtime sends to providers (importable from `kaji.runtime.providers.types`) |
| `ProviderError`, `ProviderConfigError`, `ProviderAPIError` | Provider error class hierarchy (subclasses of `ProviderError`) |
| `UnknownToolError` | Raised when the model calls a tool name not in the registry |
| `CancellationToken` | Cooperative cancellation across async boundaries |

Events use snake_case field names (`session_id`, `tool_name`) as the wire format
shared with the TypeScript SDK.

## Python vs TypeScript parity

| Feature | Python SDK | TS SDK |
| --- | --- | --- |
| Event-sourced runtime | Yes | Yes |
| Tool registry + planner + policy | Yes | Yes |
| `AgentBuilder` + integrations | Yes | Yes |
| OpenAI / Anthropic providers | Yes | Yes |
| OpenRouter / Kimi / Gemini providers | Yes (native) | Yes (via OpenAI-compatible factory) |
| Document RAG / vector store | Yes | No |
| Tool retriever | Yes | No |
| Text modality adapter | Yes (non-MVP) | No |
| Voice / TTS | Yes (non-MVP) | No |
| Redis realtime bus | Yes (non-MVP) | No |
| CLI scaffold | Yes | Yes |

## Development

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
cd kaji/sdk
uv sync                           # creates .venv, installs deps + dev group
uv run pytest tests/              # no API keys required
uv run python scripts/typecheck_ty.py  # static type check for the src/ remap
uv run ruff check src             # lint
```

Release smoke checks the current `src/` package remap in an installed wheel:

```bash
bash scripts/clean_generated.sh
bash scripts/release_smoke.sh
```

Live provider tests are opt-in (extras pull in the provider SDK):

```bash
uv sync --extra openai
OPENAI_API_KEY=... uv run pytest -m integration tests/integration/test_openai_provider.py
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  uv run pytest -m integration tests/integration/test_openai_tools.py

uv sync --extra anthropic
ANTHROPIC_API_KEY=... uv run pytest -m integration tests/integration/test_anthropic_provider.py
```

The SDK test suite needs no environment. The service tests under
`kaji/serve/tests/` cover the FastAPI app and workers; those need Postgres
(see [`kaji/serve/README.md`](../serve/README.md)).

## Testing without API keys

The default test path mocks provider HTTP clients and requires no keys:

```bash
uv run pytest -m "not integration"
```

`MockProvider` is a deterministic stub used in unit tests to exercise the full
tool loop without network calls. It is not the recommended provider for building
real agents -- it produces fixed, non-intelligent responses.

---

## Document RAG

Ingest documents and retrieve relevant chunks. Both the embedder and the vector
store are pluggable; the example injects a tiny stub embedder so it runs with no
API key (swap in a keyed embedder for production).

```python
import asyncio
from kaji import Document, DocumentRAG

class StubEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "cat" in text.lower() else [0.0, 1.0]

async def main():
    rag = DocumentRAG(embedder=StubEmbedder())
    await rag.add_document(Document(id="d1", text="cats purr; dogs bark"))
    chunks = await rag.retrieve("tell me about cats", top_k=1)
    print(chunks[0].text)  # "cats purr; dogs bark"

asyncio.run(main())
```

---

## Extensions (non-MVP)

The following features are available in the Python SDK but are outside the
five-step MVP path. They require additional configuration, infra, or hardening
before production use.

Pass a `DocumentRAG` instance to `AgentRuntime(rag=rag)` to automatically inject
retrieved chunks into the system prompt on each turn.

### Text sessions

For a small text-chat facade, use `TextModalityAdapter`. `open_session()` binds
a session to an `AgentRuntime` and can send messages directly.

```python
from kaji.modalities.text import TextModalityAdapter

session = TextModalityAdapter().open_session("s1", "u1")
events = await session.send("hello")
```

### Session management

`SessionManager.list_active` returns a user's sessions when a `SessionStore` is
configured (the SDK ships an in-memory one; a durable backend lives in
`kaji-serve` for session-list metadata).

```python
import asyncio
import kaji

async def main():
    store = kaji.InMemoryEventStore()
    sessions = kaji.InMemorySessionStore()
    mgr = kaji.SessionManager(store, session_store=sessions)

    await mgr.record_session("s1", user_id="u1", title="First chat")
    active = await mgr.list_active("u1")
    print(active)

asyncio.run(main())
```

### Redis realtime bus

For multi-process deployments where multiple workers share events, replace the
in-memory bus with the Redis-backed `EventBus`:

```bash
pip install 'kaji[realtime]'
export REDIS_URL=redis://localhost:6379/0
```

```python
from kaji.infra.events.bus import EventBus
bus = EventBus()  # Redis-backed; same interface as InMemoryEventBus
```

This is the SDK-level building block. The full hosted platform (FastAPI, async
tool workers, Postgres) is in `kaji-serve`.

### When to use Redis vs kaji-serve

| Need | Use |
|------|-----|
| Single process, one agent | `InMemoryEventBus` -- no Redis |
| Multiple processes sharing events | `kaji[realtime]` + `EventBus` |
| Full hosted platform (REST, voice, workers) | `kaji-serve` |

---

## Reference service architecture

`kaji-serve` is a deployable reference service -- one way to run the SDK in
production, not a requirement for using it. It runs as three processes over Redis:

| Process | Responsibility |
| --- | --- |
| `api` | FastAPI app: REST routes and the (voice) STT WebSocket endpoint |
| `bus-worker` | The reasoning loop: consumes input, calls the LLM, runs the event bus |
| `worker` | TaskIQ workers that execute tool calls asynchronously |

```
   ┌────────────────────────────────┐
   │             client             │
   └────────┬──────────────┴────────┘
            ▼              │
   ┌────────────────────────────────┐
   │         api (FastAPI)          │
   └────────┬──────────────┴────────┘
            ▼              │            Redis streams / pub-sub
   ┌────────────────────────────────┐
   │     bus-worker (reasoning)     │
   └────────┬──────────────┴────────┘
            ▼              │            TaskIQ / Redis streams
   ┌────────────────────────────────┐
   │       worker (tool exec)       │
   └────────────────────────────────┘
```

FastAPI, Supabase auth, SQLAlchemy/Postgres models, STT/Soniox, service runtime
nodes, and TaskIQ workers are **not** in the SDK -- they live in the separate
[`kaji-serve`](../serve/README.md) distribution.

## Module layout

```
kaji/
├── core/             # foundation: config, logging, errors
├── types/            # shared type definitions
├── infra/            # backbone above core
│   ├── events/       #   event envelopes, store, replay
│   ├── realtime/     #   redis stream/pub-sub helpers (opt-in, [realtime] extra)
│   └── observability/#   tracing, metrics, timeline
├── modalities/       # input/output channels that plug into the runtime
│   ├── voice/        #   TTS adapters (not hardened)
│   └── text/         #   text modality adapter
└── runtime/          # the agent reasoning/orchestration engine
    ├── agents/       #   AgentRuntime, AgentBuilder, ToolPlanner
    ├── providers/    #   OpenAI, Anthropic, Kimi, Gemini, mock
    ├── tools/        #   tool registry, execution, policies
    ├── sessions/     #   session state, replay
    └── workflows/    #   idempotency helpers
```

## Configuration

Settings load lazily from environment variables (or a `.env` file). No
configuration is needed to `import kaji`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | for openai provider | OpenAI LLM |
| `ANTHROPIC_API_KEY` | for anthropic provider | Anthropic LLM |
| `KAJI_MODEL_PROVIDER` | no | Provider name: `openai`, `anthropic`, `kimi`, `gemini`, `mock` |
| `OPENAI_MODEL` | no | OpenAI model (default `gpt-5.4-mini`) |
| `REDIS_URL` | for realtime extra | Defaults to `redis://redis:6379/0` |
| `GEMINI_API_KEY` | for gemini provider | Gemini LLM + TTS |
| `TTS_PROVIDER` | no | `none` (default), `gemini`, or `openai` |
| `DATABASE_URL` | kaji-serve only | Postgres connection |
| `SUPABASE_ANON_KEY` | kaji-serve only | Supabase auth |

See [`.env.example`](../../.env.example) for the full list.

## Project layout notes

The repo ships **two distributions**: `kaji` (this SDK) and
[`kaji-serve`](../serve/README.md) (the reference FastAPI + workers
service). The SDK has no dependency on the service -- the boundary mirrors
langchain / langserve.
