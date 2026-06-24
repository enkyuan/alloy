# kaji

`kaji` is an embeddable SDK for building agents into your own platform:
import the pieces you need and compose them. The core is dependency-injected and
infra-free (no database, Supabase, FastAPI, or web server required).

> **Status:** pre-beta, MVP-ready for embedded agents. The core SDK (runtime,
> toolgen, OpenAI/Anthropic providers, and session replay) is suitable for
> internal embedded agents. Multi-process platform features (Redis event
> backbone, durable sessions, voice workers) are present but not
> production-hardened -- do not deploy the realtime/voice stack without
> additional load and durability testing.

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
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()

    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("openai"))  # reads OPENAI_API_KEY
        .integration(WeatherIntegration())
        .system_prompt("You are a weather assistant.")
        .build(bus=bus, store=store)
    )

    await store.append(kaji.UserMessage(session_id="s1", content="Weather in Seattle?"))
    await runtime.run_turn("s1")

    events = await store.get_events("s1")
    for e in events:
        print(e.type, getattr(e, "content", getattr(e, "delta", "")))


asyncio.run(main())
```

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable. Swap `.provider(kaji.get_provider("anthropic"))` to use Anthropic.

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
| Document RAG / vector store | Yes (non-MVP) | No |
| Tool retriever | Yes (non-MVP) | No |
| Text modality adapter | Yes (non-MVP) | No |
| Voice / TTS | Yes (non-MVP) | No |
| Redis realtime bus | Yes (non-MVP) | No |
| CLI scaffold | Yes | No |

## Development

**Prerequisites:** Python 3.11+, [Poetry](https://python-poetry.org/).

```bash
cd kaji/sdk
poetry install
poetry run pytest tests/          # no API keys required
poetry run pyrefly check          # static type check
poetry run ruff check kaji        # lint
```

Live provider tests are opt-in:

```bash
OPENAI_API_KEY=... poetry run pytest -m integration tests/integration/test_openai_provider.py
ANTHROPIC_API_KEY=... poetry run pytest -m integration tests/integration/test_anthropic_provider.py
```

The SDK test suite needs no environment. The service tests under
`kaji/serve/tests/` cover the FastAPI app and workers; those need Postgres
(see [`kaji/serve/README.md`](../serve/README.md)).

## Testing without API keys

The default test path mocks provider HTTP clients and requires no keys:

```bash
poetry run pytest -m "not integration"
```

`MockProvider` is a deterministic stub used in unit tests to exercise the full
tool loop without network calls. It is not the recommended provider for building
real agents -- it produces fixed, non-intelligent responses.

---

## Extensions (non-MVP)

The following features are available in the Python SDK but are outside the
five-step MVP path. They require additional configuration, infra, or hardening
before production use.

### Document RAG

Ingest documents and retrieve relevant chunks. Both the embedder and the vector
store are pluggable; the example injects a tiny stub embedder so it runs with no
API key (swap in a keyed embedder for production).

```python
import asyncio
from kaji.knowledge import Document, DocumentRAG

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
`kaji-serve`).

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
| `OPENAI_MODEL` | no | OpenAI model (default `gpt-4o`) |
| `REDIS_URL` | for realtime extra | Defaults to `redis://redis:6379/0` |
| `GEMINI_API_KEY` | for gemini provider | Gemini LLM + TTS |
| `TTS_PROVIDER` | no | `none` (default), `gemini`, or `openai` |
| `DATABASE_URL` | kaji-serve only | Postgres connection |
| `SUPABASE_ANON_KEY` | kaji-serve only | Supabase auth |

See [`.env.example`](.env.example) for the full list.

## Project layout notes

The repo ships **two distributions**: `kaji` (this SDK) and
[`kaji-serve`](../serve/README.md) (the reference FastAPI + workers
service). The SDK has no dependency on the service -- the boundary mirrors
langchain / langserve.
