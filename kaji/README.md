# kaji

`kaji` is an embeddable SDK for building agents into your own platform:
import the pieces you need and compose them. The core is dependency-injected and
infra-free (no database, Supabase, FastAPI, or web server required).

<!-- canonical-status-links:start -->
> Canonical documentation: https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md
> Release status and evidence: https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md
<!-- canonical-status-links:end -->

OpenAI is the sole beta-supported primary provider. Anthropic, Gemini, Kimi,
and OpenRouter are opt-in experimental/WIP adapters with no beta compatibility
or publication-proof commitment. Use the deterministic mock provider for local
and test flows.

See [**Kaji MVP**](https://github.com/enkyuan/alloy/blob/main/docs/MVP.md) for
the full five-step developer path and scope definition.

## Packages

The Python SDK project owns the `kaji/` root so its conventional source layout
is `kaji/src/kaji`. The service and TypeScript SDK remain independently
buildable subpackages.

| Package      | Project path | Source root                 | Purpose                                               |
| ------------ | ------------ | --------------------------- | ----------------------------------------------------- |
| `kaji-sdk`   | `kaji/`      | `kaji/src/kaji`             | Python embedded agent SDK, imported as `kaji`         |
| `kaji-serve` | `kaji/serve` | `kaji/serve/src/kaji_serve` | Experimental FastAPI and Soniox STT reference service |
| `kaji-sdk`   | `kaji/ts`    | `kaji/ts/src`               | TypeScript embedded agent SDK                         |

Canonical contracts, release scripts, benchmarks, and fixtures live once at
the Kaji root and are consumed by both SDKs. Package-specific source remains
under the owning distribution; `kaji-serve` depends on the root Python project,
while the Python SDK never imports service-only code.

## Install

The current beta publication target is npm only. The Python candidate is built,
installed, and tested from exact wheel/sdist artifacts during the protected
release, but `kaji-sdk==0.2.0b1` is not published to PyPI and must not be
presented as a registry install yet.

For Python SDK development from this repository:

```bash
uv sync --project kaji --extra openai
```

Optional source-checkout extras remain available for experimental development:

```bash
uv sync --project kaji --extra anthropic  # Anthropic (experimental/WIP)
uv sync --project kaji --extra gemini     # Gemini provider
uv sync --project kaji --extra realtime   # Redis event bus (multi-process)
uv sync --project kaji --extra providers  # all provider SDKs
```

The future PyPI distribution name is `kaji-sdk`; installed code is imported as
`kaji`, and the Python CLI command is `kaji`.

## Quick start

First prove a text-only turn without credentials. No principal is required
because this runtime has no enabled tools:

```python
import asyncio
import kaji


async def text_only() -> None:
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("mock", reply="hello"))
        .build()
    )
    result = await runtime.turn("Say hello.")
    print(result.text, result.session_id, result.turn_id)
    print([(event.sequence, event.turn_id, event.type) for event in result.events])


asyncio.run(text_only())
```

Then set an API key and add a risk-classified tool with explicit caller
identity, deadline, and cancellation:

```bash
export OPENAI_API_KEY=sk-...
# Experimental/WIP alternative: export ANTHROPIC_API_KEY=sk-ant-...
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
    async def get_weather(self, ctx: kaji.ToolExecutionContext, args: dict) -> dict:
        return {"city": args["city"], "tempF": 68}


async def main():
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider("openai"))  # reads OPENAI_API_KEY
        .integration(WeatherIntegration())
        .system_prompt("You are a weather assistant.")
        .build()
    )

    loop = asyncio.get_running_loop()
    result = await runtime.turn(
        "Weather in Seattle?",
        context=kaji.TurnContext(
            principal_id="quickstart",
            deadline_monotonic=loop.time() + 30,
        ),
    )
    print(result.text, result.session_id, result.turn_id)
    print([(event.id, event.sequence, event.turn_id) for event in result.events])


asyncio.run(main())
```

`AgentBuilder` wires a scoped `ToolRegistry` into `ToolPlanner` so integration
tools are both visible to the model and executable. For an opt-in
experimental/WIP path, swap `.provider(kaji.get_provider("anthropic"))` to use
Anthropic.

Catch a Kaji `ProviderError`, then call `normalize_provider_error(error)` for
the redaction-safe `type`, `code`, `service`, `action`, `status`, and
`retryable` fields. The normalizer accepts Kaji provider errors, not arbitrary
vendor exceptions.

See [`docs/kaji/production-beta.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/production-beta.md) for
the installed-package version of both first-success examples and exact default
limits. Operating details are in
[`concurrency-and-ordering.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/concurrency-and-ordering.md),
[`tool-contracts.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/tool-contracts.md), and
[`troubleshooting.md`](https://github.com/enkyuan/alloy/blob/main/docs/kaji/troubleshooting.md).
Call `runtime.effective_limits()` to inspect the immutable
`EffectiveRuntimeLimits` resolved for one runtime.

Tool-capable turns require a caller identity. Supply a `TurnContext` per turn,
or configure an explicit builder `default_context` for a deliberately
single-tenant host. Each handler
receives an immutable `ToolExecutionContext` through `ToolInvocation` (with
no inferred or shorthand context alias). Missing identity raises
`MissingToolIdentityError`; enabled tools without an explicit risk raise
`UnclassifiedToolRiskError` before registration or execution.

Tool schemas use Draft 2020-12 JSON Schema with format checking. Both
`ToolPlanner` and direct `ToolRegistry.execute()` calls validate before a
handler can start. `ToolSchemaValidator` is available for hosts that need the
same validation boundary outside the runtime; invalid definitions raise
`ToolSchemaValidationError`, and invalid arguments raise
`ToolArgumentValidationError` with a safe error code, JSON Pointer, and
message.

Tool execution is sequential by default. Mark only effect-independent tools
with `parallel_safe=True`; the shared `ToolExecutionController` then applies
the `ToolExecutionLimits` default of four active handlers and a 30-second
queue-to-completion deadline. A `ToolSpec.timeout_ms` can tighten that deadline,
and `AgentRuntime.drain_tools()` reports timed-out handlers that have not
actually settled, including durable setup operations still resolving after a
request deadline. A handler may raise `ToolExecutionError` only when it can
certify that it failed before producing a side effect; unexpected exceptions
are retained as unknown-outcome tombstones.

Exact `(session_id, tool_call_id)` replay is owned by the replaceable
`ToolIdempotencyLedger`; `InMemoryToolIdempotencyLedger` is the bounded default.
Applications can handle `IdempotencyCapacityExceeded` and
`IdempotencyConflictError` explicitly, while durable side-effect tools should
inject a restart-safe ledger. Durable ledgers must keep resolution waits
cancellation-cooperative and implement start-state reads as bounded operations.

Approval-gated tools use an `ApprovalHandler` that returns a validated
`ApprovalDecision`. Each request receives an `ApprovalRequestContext` carrying
the tool context, canonical event journal, a no-argument canonical request
operation, a stored-event observer, cancellation, and the effective deadline.
`EventApprovalHandler` implements the
`EventBackedApprovalHandler` contract for external decision bridges and matches
decisions by turn, call, and tool identity only after the exact stored request.
When a framework timeout or cancellation races an external bridge, Kaji appends
the framework rejection as a sequence fence and selects the first matching
decision after the request through that fence. Standalone `ToolPlanner` callers
must use `JournalEventEmitter` bound to the exact same journal object; bare
emitters and wrappers over another journal fail before lifecycle persistence.

Observability is optional and dependency-free. Inject a `MetricsSink` or
`TraceSink` through `AgentBuilder.metrics_sink()` and `.trace_sink()`;
measurements arrive as immutable `Measurement` values and traces return a
best-effort, idempotent `SpanHandle`. `NOOP_METRICS` and `NOOP_TRACE` are the
allocation-free defaults. Metric labels are closed and never include prompts,
tool arguments, or correlation IDs.

## Event journal contract

`EventJournal` is the stable persistence boundary for runtime events. New
events enter as `NewKajiEvent` values without a sequence; a successful commit
returns a sequenced `StoredKajiEvent` directly. The lower-level
`EventStore.append()` returns `AppendResult(event, inserted)`
so journals can suppress duplicate fanout. `AgentBuilder` uses
`InMemoryEventJournal` by default so persistence and live delivery share one
atomic, process-local path. A journal used by the tool runtime must acknowledge
`ToolCallStarted` appends atomically and cooperate with task cancellation; the
runtime cannot detach this append without allowing a late Started event to
overtake the terminal event.
Approval-capable journals also provide `open_subscription()`, which returns
only after backlog/live attachment and always yields an explicitly closable
subscription.

`AgentRuntime.history()` and `TextSession.events()` return at most 1,024 stored
events by default. Pass `after_sequence` and `limit` to page explicitly.

### Explicit session lifecycle

The Python and TypeScript SDKs share the same supported in-memory purge
lifecycle. The bounded store never evicts retained sessions implicitly: a full
store raises `EventStoreCapacityError` until the host explicitly purges one.
Stop ingress, drain tools and providers, export only reduced evidence, then run:

```python
await runtime.purge_session(session_id)
```

Purge rejects with `SessionPurgeBusyError` while owned work is active and with
`SessionPurgeUnsupportedError` when the store, delivery path, or idempotency
ledger cannot participate. Runtime purge closes its old subscribers, removes
the event and ID indexes, and clears all runtime owners sharing that store; a
standalone raw listener must be closed by its caller. Reset cursors to `0`
before reuse; the next generation begins at sequence `1`.

`PurgeableEventStore.purge_session(session_id)` is the public one-argument
store-only capability, detected by `supports_session_purge()`. Runtime purge
also requires Kaji's internal opaque coordinated capability, so a custom store
implementing only the public method fails closed at the runtime boundary.
Direct store operations and new owners remain fenced throughout purge. Split
delivery is unsupported. If post-delete cache or settled-ledger cleanup fails,
the strong `cleanup_pending` tombstone remains until a runtime purge retry
converges; physical deletion is not repeated.

`AgentRuntime.turn()` returns a `TurnResult` with a unique `turn_id`. The
default process-local `InMemoryTurnCoordinator` is shared by runtimes using the
same `EventStore` object, serializing same-session turns while allowing
different sessions and different stores to overlap. This is not a distributed
lock. Multi-process deployments must inject a shared `TurnCoordinator` with
`AgentBuilder.coordinator()`. Custom stores that cannot be weak-referenced must
also inject a coordinator explicitly.

`replay_session()` accepts stored, sequenced events only. Migrate historical
unsequenced logs offline by assigning contiguous sequence values before they
enter the runtime; the SDK does not guess an ordering at replay time.

`SplitEventJournal` is the experimental adapter for deployments with separate
`EventStore` and `EventBus` implementations. Callers can distinguish
`EventIdConflictError`, `EventStoreCapacityError`,
`EventBufferOverflowError`, and `EventDeliveryError` when applying retry,
resume, or backpressure policy.

## Prove it with a model

OpenAI with `gpt-5.4-mini` is the recommended first live check because it is
cost-effective and exercises the SDK's Chat Completions tool path.

```bash
cd kaji
uv sync --extra openai
uv run pytest tests/test_quickstart.py -q
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  uv run pytest -m integration tests/integration/test_openai_tools.py -q
```

The live test registers a read-only probe tool, verifies the model calls it,
and verifies the runtime emits final assistant text using the tool result.
Keyed OpenAI proof requires protected tool loops in both SDKs on one exact
commit. A missing `OPENAI_API_KEY` blocks that release evidence. Anthropic,
Gemini, Kimi, and OpenRouter are experimental/WIP and are not publication
proof.

For the cross-SDK release gate, run from the repository root:

```bash
uv run --project kaji python kaji/scripts/beta_release_check.py
```

This wraps Python unit/static checks, Python wheel smoke, TS unit/static/build
checks, TS package smoke, mandatory pinned ast-grep boundary checks, and no-key
live-gate hygiene. The ast-grep step guards the Python SDK/service boundary, core package dependency direction, removed tool-model imports, TypeScript optional provider imports, and cancellation error shape.

For the live-gate credential modes specifically:

```bash
uv run --project kaji python kaji/scripts/verify_openai_loop.py
KAJI_REQUIRE_LIVE_KEYS=1 uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

Without `OPENAI_API_KEY`, the first command proves missing-key hygiene only.
It is not provider evidence. The protected release mode requires
`OPENAI_API_KEY` and fails when it is absent.

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini uv run --project kaji python kaji/scripts/verify_openai_loop.py
```

`KAJI_RUN_KEYED_LIVE=1` is the fail-closed two-cell OpenAI proof (Python and
TypeScript). It requires the OpenAI key, frozen artifact set, and exact
40-character release commit:

```bash
OPENAI_API_KEY=... \
KAJI_RELEASE_ARTIFACTS_DIR="$PWD/.artifacts/kaji-release" \
KAJI_RELEASE_COMMIT=<40-character-commit> KAJI_RUN_KEYED_LIVE=1 \
uv run --project kaji python kaji/scripts/beta_release_check.py
```

The protected rehearsal and publish workflows are authoritative release
evidence. Their required-reviewer environments are purpose-specific:
`kaji-beta-onboarding` protects deterministic TypeScript onboarding,
`kaji-beta` protects keyed OpenAI proof, and `kaji-beta-publish` protects
publisher identity and the sole npm write. The single-provider command above
is only a local paid smoke test.

## Stability tiers

- **Stable core:** `AgentBuilder`, `AgentRuntime`, `ToolRegistry`,
  `ToolPlanner`, session replay, the OpenAI provider, and the in-memory
  event store/journal form the supported embedded-agent surface.
- **Experimental providers:** Anthropic, Gemini, Kimi, and OpenRouter remain
  opt-in WIP surfaces without a beta compatibility or publication-proof
  commitment.
- **Experimental Python-only:** Redis realtime/history, voice/TTS,
  `DocumentRAG`, native Gemini/Kimi providers, tool retrieval, and text/voice
  modalities exist for early adopters but are not production-hardened.
- **TS not ported:** Redis realtime, voice/TTS, and RAG are not implemented in
  TypeScript. TS Gemini/Kimi remain OpenAI-compatible factories rather than
  native provider implementations.

See https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md for the
cross-SDK release matrix and the exact distinction between stable core,
experimental Python-only surfaces, and TypeScript surfaces that are not ported.

The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
`DocumentRAG`, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.

## CLI scaffold

```bash
kaji init ./my-agent
```

Creates `agent.py` and `.env.example` in `./my-agent` wired to `AgentBuilder`
with an env-driven provider. Copy `.env.example` to `.env`, then use `openai`
with `OPENAI_API_KEY` for the beta-supported path. The `anthropic` scaffold
option remains available as experimental/WIP.

## What's exported

| Name                                                                                                                                         | What it is                                                                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `AgentBuilder`                                                                                                                               | Fluent builder wiring provider + integrations + policy into `AgentRuntime`                                                                |
| `AgentRuntime`                                                                                                                               | Provider-agnostic ReAct loop                                                                                                              |
| `EffectiveRuntimeLimits`                                                                                                                     | Immutable values returned by `AgentRuntime.effective_limits()` after overrides                                                            |
| `TurnResult`, `TurnCoordinator`, `InMemoryTurnCoordinator`                                                                                   | Turn-scoped result and injectable same-session FIFO coordination                                                                          |
| `ToolSpec`, `ToolRegistry`, `ToolExecutionContext`                                                                                           | Tool definition, scoped registry, and execution context                                                                                   |
| `ToolSchemaValidator`, `ToolSchemaValidationError`, `ToolArgumentValidationError`                                                            | Draft 2020-12 validation and normalized failures before tool side effects                                                                 |
| `ToolExecutionController`, `ToolExecutionLimits`, `ToolExecutionError`                                                                       | Bounded execution, deadlines, drain state, and certified retryable handler failures                                                       |
| `ToolIdempotencyLedger`, `InMemoryToolIdempotencyLedger`, `IdempotencyCapacityExceeded`, `IdempotencyConflictError`                          | Exact tool-call coalescing/replay and bounded-ledger failures                                                                             |
| `ApprovalDecision`, `ApprovalHandler`, `ApprovalRequestContext`, `EventApprovalHandler`, `EventBackedApprovalHandler`, `JournalEventEmitter` | Typed approval lifecycle and canonical event-backed bridge                                                                                |
| `Measurement`, `MetricsSink`, `TraceSink`, `SpanHandle`, `NOOP_METRICS`, `NOOP_TRACE`                                                        | Dependency-free, low-cardinality observability contracts and no-op defaults                                                               |
| `tool`, `function_tool`, `register_tool`, `list_tool_specs`                                                                                  | PEP 8 decorators and registry helpers for declaring and listing tools                                                                     |
| `Integration`                                                                                                                                | Namespace-scoped tool bundle base class                                                                                                   |
| `EventStore`, `InMemoryEventStore`, `EventBus`, `InMemoryEventBus`                                                                           | Append-only event log and per-session pub/sub (abstract + in-memory)                                                                      |
| `InvalidDurableValueError`, `DurableJsonLimitError`                                                                                          | Durable event boundary failures for non-JSON values and oversized UTF-8 payloads                                                          |
| `UserMessage`                                                                                                                                | Convenience constructor for the initial `user.message` event                                                                              |
| `replay_session`, `SessionManager`, `SessionState`                                                                                           | Session state projection and management                                                                                                   |
| `SessionStore`, `InMemorySessionStore`, `SessionRecord`                                                                                      | Cross-session index keyed by user (process-local default; postgres opt-in)                                                                |
| `HistoryStore`, `InMemoryHistoryStore`                                                                                                       | Host-facing bounded conversation history (in-memory default; Redis opt-in)                                                                |
| `Chunk`, `Document`, `DocumentRAG`, `VectorStore`, `InMemoryVectorStore`                                                                     | Document RAG primitives: chunking, ingest, retrieval                                                                                      |
| `ToolRetriever`, `Embedder`, `EmbeddingCache`                                                                                                | Semantic tool retrieval with a pluggable embedder and cache                                                                               |
| `build_tools_payload`, `spec_to_neutral`                                                                                                     | Build the neutral tool payload from the registry                                                                                          |
| `to_openai`, `to_anthropic`, `to_gemini`                                                                                                     | Per-provider translators applied at the provider boundary                                                                                 |
| `ModelProvider`, `get_provider`, `register_provider`                                                                                         | Provider protocol + registry                                                                                                              |
| `ProviderMessage`, `ProviderToolSpec`                                                                                                        | TypedDicts documenting the neutral message + tool payload the runtime sends to providers (importable from `kaji.runtime.providers.types`) |
| `ProviderError`, `ProviderConfigError`, `ProviderAPIError`, `ProviderConnectionError`, `ProviderRateLimitedError`                            | Provider error class hierarchy (subclasses of `ProviderError`)                                                                            |
| `NormalizedProviderError`, `normalize_provider_error`                                                                                        | Redaction-safe semantic classification for Kaji provider errors                                                                           |
| `Clock`, `IdFactory`, `SystemClock`, `SystemIdFactory`                                                                                       | Deterministic time/ID seams and their production defaults                                                                                 |
| `UnknownToolError`                                                                                                                           | Raised when the model calls a tool name not in the registry                                                                               |
| `CancellationToken`                                                                                                                          | Cooperative cancellation across async boundaries                                                                                          |

Events use snake_case field names (`session_id`, `tool_name`) as the wire format
shared with the TypeScript SDK.

## Python vs TypeScript parity

| Feature                               | Python SDK                     | TS SDK                                                |
| ------------------------------------- | ------------------------------ | ----------------------------------------------------- |
| Event-sourced runtime                 | Yes                            | Yes                                                   |
| Tool registry + planner + policy      | Yes                            | Yes                                                   |
| `AgentBuilder` + integrations         | Yes                            | Yes                                                   |
| OpenAI provider                       | Yes                            | Yes                                                   |
| Anthropic provider (experimental/WIP) | Yes                            | Yes                                                   |
| OpenRouter / Kimi / Gemini providers  | Yes (experimental/WIP, native) | Yes (experimental/WIP, via OpenAI-compatible factory) |
| Document RAG / vector store           | Yes                            | No                                                    |
| Tool retriever                        | Yes                            | No                                                    |
| Text modality adapter                 | Yes (non-MVP)                  | No                                                    |
| Voice / TTS                           | Yes (non-MVP)                  | No                                                    |
| Redis realtime bus                    | Yes (non-MVP)                  | No                                                    |
| CLI scaffold                          | Yes                            | Yes                                                   |

## Development

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
cd kaji
uv sync                           # creates .venv, installs deps + dev group
uv run pytest tests/              # no API keys required
uv run python scripts/check_types.py  # static type check for the src/ remap
uv run ruff check src             # lint
```

Release smoke checks the current `src/` package remap in an installed wheel:

```bash
uv run python scripts/clean_caches.py
uv run python scripts/release_smoke.py
```

Live provider tests are opt-in (extras pull in the provider SDK). OpenAI is the
beta-supported live path; the Anthropic command remains a WIP adapter check:

```bash
uv sync --extra openai
OPENAI_API_KEY=... uv run pytest -m integration tests/integration/test_openai_provider.py
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini \
  uv run pytest -m integration tests/integration/test_openai_tools.py

uv sync --extra anthropic
ANTHROPIC_API_KEY=... uv run pytest -m integration tests/integration/test_anthropic_provider.py
```

The SDK test suite needs no environment. The service tests under
`kaji/serve/tests/` cover the FastAPI REST and STT edge; those need Postgres
(see [`kaji/serve/README.md`](https://github.com/enkyuan/alloy/blob/main/kaji/serve/README.md)).

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

### Experimental Redis split adapter

For evaluating cross-process event delivery, replace the in-memory journal with
the Redis-backed `EventBus`:

```bash
uv sync --project kaji --extra realtime
export REDIS_URL=redis://localhost:6379/0
```

```python
from kaji.infra.events.bus import EventBus
bus = EventBus()  # Redis-backed; same interface as InMemoryEventBus
```

This is an experimental SDK building block, not a durability or distributed
coordination claim. The REST/STT reference service in `kaji-serve` does not use
this adapter.

### When to use Redis vs kaji-serve

| Need                                      | Use                               |
| ----------------------------------------- | --------------------------------- |
| Single process, one agent                 | default `InMemoryEventJournal`    |
| Experimental cross-process event delivery | `kaji-sdk[realtime]` + `EventBus` |
| Experimental REST/STT service evaluation  | `kaji-serve`                      |

---

## Reference service architecture

`kaji-serve` is an experimental reference service and is excluded from the 0.2
SDK beta. It currently exposes one FastAPI process for REST routes and a Soniox
STT WebSocket. It does not host `AgentRuntime`, reasoning/tool execution, or
TTS.

```
client -> FastAPI REST + Soniox STT -> Supabase/Postgres adapters
```

FastAPI, Supabase auth, SQLAlchemy/Postgres models, STT/Soniox, and the service
adapters are **not** in the SDK. Before promotion, the service needs a hosted
`AgentRuntime` adapter, persistent `EventStore`, post-turn acknowledgement,
and distributed coordination. See the separate
[`kaji-serve`](https://github.com/enkyuan/alloy/blob/main/kaji/serve/README.md) package.

## Module layout

```
kaji/
├── pyproject.toml
├── src/kaji/         # Python distribution source
│   ├── core/         # foundation: config and safe logging
│   ├── contracts/    # packaged schemas and contract helpers
│   ├── infra/        # events, realtime adapters, observability
│   ├── integrations/ # source-owned integration catalog
│   ├── knowledge/    # experimental retrieval building blocks
│   ├── modalities/   # text and voice modality adapters
│   └── runtime/      # agents, providers, integrations, tools, sessions
├── tests/            # Python SDK tests
├── contracts/        # canonical cross-SDK contracts
├── scripts/          # release and package tooling
├── benchmarks/
│   └── python/       # Python runtime benchmark drivers
├── examples/python/  # Python examples
├── serve/
│   └── src/kaji_serve/
└── ts/
    └── src/
```

## Configuration

Settings load lazily from environment variables (or a `.env` file). No
configuration is needed to `import kaji`.

| Variable                 | Required                            | Purpose                                                        |
| ------------------------ | ----------------------------------- | -------------------------------------------------------------- |
| `OPENAI_API_KEY`         | for openai provider                 | OpenAI LLM                                                     |
| `ANTHROPIC_API_KEY`      | for experimental anthropic provider | Anthropic LLM                                                  |
| `KAJI_MODEL_PROVIDER`    | no                                  | Provider name: `openai`, `anthropic`, `kimi`, `gemini`, `mock` |
| `OPENAI_MODEL`           | no                                  | OpenAI model (default `gpt-5.4-mini`)                          |
| `REDIS_URL`              | for realtime extra                  | Defaults to `redis://localhost:6379/0`                         |
| `GEMINI_API_KEY`         | for gemini provider                 | Gemini LLM + TTS                                               |
| `GEMINI_EMBEDDING_MODEL` | no                                  | Gemini embeddings (default `gemini-embedding-2`)               |
| `OPENROUTER_API_KEY`     | for kimi provider                   | OpenRouter-hosted Kimi                                         |
| `TTS_PROVIDER`           | no                                  | `none` (default), `gemini`, or `openai`                        |

See [`.env.example`](https://github.com/enkyuan/alloy/blob/main/.env.example) for the full list.

## Project layout notes

The repo contains **two Python distributions**: `kaji-sdk` (this SDK, imported
as `kaji`) and
[`kaji-serve`](https://github.com/enkyuan/alloy/blob/main/kaji/serve/README.md) (the reference FastAPI + STT
service). The SDK has no dependency on the service -- the boundary mirrors
langchain / langserve.

## License

Kaji is source-available under the
[Functional Source License 1.1, ALv2 Future License](https://spdx.org/licenses/FSL-1.1-ALv2.html).
It permits internal commercial use, modification, and redistribution for
permitted purposes, but excludes competing commercial products and services;
each version becomes Apache-2.0 after two years. FSL is not an OSI-approved
open-source license.
