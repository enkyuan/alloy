# SDK Status and Real-Provider Readiness

Date: 2026-06-11

## Scope

Current implementation state across both SDKs — what runs against a real model
today, what is partial, what is missing, and what the 6-week feasibility window
looks like against the features advertised on the landing page. Verified by
reading current source on `main`.

---

## Quick start: real providers today (no code changes)

**Python — OpenAI:**
```bash
AGENTKIT_MODEL_PROVIDER=openai OPENAI_API_KEY=sk-... python -c "import agentkit"
```

**Python — Kimi / OpenRouter:**
```bash
OPENROUTER_API_KEY=sk-or-... python -c "import agentkit"  # provider defaults to kimi
```

**Python — Gemini:**
```bash
AGENTKIT_MODEL_PROVIDER=gemini GEMINI_API_KEY=... python -c "import agentkit"
# Note: model hardcoded to gemini-2.5-flash regardless of GEMINI_MODEL config
```

**TypeScript:** No concrete providers ship. Must implement `ModelProvider` first
(see §3).

---

## 1. Provider status

### Python (`agentkit/sdk`)

| Provider | Status | Env vars | Notes |
| --- | --- | --- | --- |
| `kimi` | Works | `OPENROUTER_API_KEY` or `KIMI_API_KEY` | Default. OpenRouter + Cloudflare backends. |
| `openai` | Works | `OPENAI_API_KEY` | `gpt-4o` default, configurable. |
| `gemini` | Partial | `GEMINI_API_KEY` | Model hardcoded to `gemini-2.5-flash` in `providers/gemini.py:42`; config default says `gemini-3-flash-preview` — mismatch. Heavy use of `asyncio.to_thread`. |
| `anthropic` | Missing | — | No implementation. Not in `pyproject.toml`. ~3h to add, same shape as `providers/openai.py`. |
| `mock` | Works | none | Drives full tool loop with no network. All unit tests use it. |

### TypeScript (`agentkit/ts`)

**Updated 2026-06-11:** `OpenAIProvider` and `AnthropicProvider` now ship and
are exported from the top-level `@agentkit/sdk` package. Both are optional-dep
lazy-loaded (tree-shake safe). Quick start:

```ts
import { OpenAIProvider, registerProvider, AgentRuntime } from "@agentkit/sdk";
registerProvider("openai", new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY }));
```

The `ModelProvider` interface now carries optional `ModelProviderOptions`
(`temperature`, `maxTokens`, `cancellationToken`) on both `generate` and
`generateStream`, matching the Python signature. The asymmetry noted in
`docs/sdk-gap-analysis.md §4 issue 3` is resolved.

---

## 2. Core runtime

Both SDKs implement the same ReAct loop: project session state → build messages
→ stream from provider → emit events → scatter-gather tool calls → repeat until
final response.

| Capability | Python | TypeScript |
| --- | --- | --- |
| Agent loop (ReAct) | Works | Works |
| Tool registry + Zod/Pydantic spec | Works | Works |
| Scatter-gather tool execution | Works | Works |
| Event bus (in-memory) | Works | Works |
| Event store (in-memory) | Works | Works |
| Session replay / projection | Works | Works |
| `TOOL_CALL_FAILED` projection | Works | Missing (TS skips it intentionally — divergence) |
| Cancellation | Works | Works |
| Redis event bus (opt-in) | Works | — |
| `InMemoryHistoryStore` | Works | — |
| `AgentRuntime.send()` convenience | Works | Works |
| `AgentStrategy` (configurable loop limits) | Works | Works (`maxToolIterations`) |

---

## 3. RAG / knowledge retrieval

**Python:** `DocumentRAG` (`knowledge/rag.py`) handles chunking, embedding, and
in-memory cosine search. `ToolRetriever` (`runtime/tools/retriever.py`) selects
tools by semantic similarity. Both share the pluggable `Embedder` protocol;
Gemini embedder is the default, infra-free.

**Gap:** retrieved chunks are not auto-injected into the agent prompt. Callers
pass chunks manually today. ROADMAP item 14 owns the injection design.

**TypeScript:** not implemented. Memory retrieval event types are defined
(`MEMORY_RETRIEVAL_STARTED`, `MEMORY_RETRIEVAL_COMPLETED`) but no retrieval
engine exists.

---

## 4. Voice

The Python voice path (audio → Soniox STT → reasoning node → TTS → audio)
exists in `modalities/voice/` and `serve/workers/`. Known gaps that block
production use:

| Gap | Location | Severity |
| --- | --- | --- |
| Barge-in / interruption — no speech-activity events produced anywhere in the STT/worker path | `serve/workers/main.py:_synthesize_and_publish` | High |
| Turn / endpoint detection — `resolve_turn_policy` has zero consumers; endpoint detection hardcoded off | `modalities/voice/turn_detection.py`, `stt/soniox_gateway.py:52` | High |
| Dual auth — HTTP uses local HS256; STT WebSocket validates against Supabase | `serve/server/deps.py`, `stt/handler.py:209` | High |
| `AgentReasoningNode.process_context` — abstract stub, not implemented | `runtime/agents/nodes/reasoning.py:148` | High |
| TTS default is a no-op — `TTS_PROVIDER=none` raises `TTSNotConfiguredError` | `modalities/voice/tts/adapter.py:23` | Medium |

Basic turn-based exchanges work when TTS is configured and auth is set up. All
five gaps above need to close before voice agents are production-ready.

**TypeScript:** voice event types are defined; no audio I/O, STT, or TTS code
exists.

---

## 5. Multi-agent / swarms

**Python:** `determine_handoff` in `runtime/agents/router.py:13` unconditionally
returns `None`. The routing surface exists but is a stub.

**TypeScript:** five swarm event types are defined (`SWARM_RUN_STARTED`,
`SWARM_AGENT_SPAWNED`, etc.) but no swarm runtime exists.

---

## 6. agentkit-serve gaps

| Item | Status | Notes |
| --- | --- | --- |
| Durable chat persistence | Partial | Postgres models exist; nothing writes to them. History is Redis-only, trimmed to `AGENT_HISTORY_LIMIT`. |
| `/sessions` endpoint | Partial | Backed by in-memory store; lost on restart. |
| Dead code | Pending cleanup | `workers/tasks/memory.py` is empty. `helpers/llm_response.py` and `response_text.py` are written but never imported. |

---

## 7. TypeScript parity delta

The TS SDK is the Python core loop without the features that came after it. The
event wire format (type strings, field names) is identical between SDKs.

Missing from TS vs Python:
- Kimi and Gemini providers (OpenAI and Anthropic now ship)
- Neutral tool-payload translators (`to_openai`, `to_gemini`)
- RAG / knowledge retrieval engine
- `ToolRetriever` (semantic tool selection)
- Voice / STT / TTS
- Multi-agent swarm routing
- `SessionManager` / `SessionStore`
- Redis opt-in for bus / store

Resolved since initial draft:
- `AgentRuntime.send()` — now implemented
- `AgentStrategy.maxToolIterations` — now configurable (was hardcoded to 10)
- `ModelProvider` interface — `temperature`, `maxTokens`, `cancellationToken` added
- `OpenAIProvider`, `AnthropicProvider` — now shipped and exported

Divergences that break cross-SDK event-log replay — see `docs/sdk-gap-analysis.md §5`.

---

## 8. Test coverage

| SDK | Test files | Tests | Type | Integration tests |
| --- | --- | --- | --- | --- |
| Python | 30 | ~200 | Unit, all mocked | None |
| TypeScript | 7 | 119 | Unit, all mocked | None |

No `pytest -m integration` harness exists. Testing against real providers today
means running manually with real API keys.

---

## 9. Landing page features vs reality (6-week window)

| Feature (landing page) | Today | 6 weeks |
| --- | --- | --- |
| Works with your stack (Python + TS) | Partial — TS has no providers; no CLI scaffold | Achievable — TS providers + `agentkit init` |
| Event-sourced runtime | Done | Done |
| Tool registry + toolgen | Partial — registry done; ToolGen (build-time code generation) not implemented | Partial — ToolGen V0 (OpenAPI source) is ~1 week; full pipeline is months |
| Pluggable LLM providers | Partial — Python: OpenAI/Kimi work; Gemini partial; Anthropic missing. TS: interface only. | Achievable — Anthropic (Py) + OpenAI/Anthropic (TS) |
| Text and voice | Partial — text streaming works; voice has 4 blocking gaps | Risky — voice gaps are 3-4 weeks of dedicated work on their own |
| RAG tool retriever | Partial — retrieval works; prompt injection is not wired | Achievable — injection is one focused week |
| In-memory or Redis | Done | Done |
| Replay & projection | Done | Done |
| Python & TypeScript parity | Partial — core loop mirrors; Python is ~6 months ahead on everything else | Partial — provider adapters close the most visible gap; full parity is months |

---

## 10. Ordered work to unblock real-model testing

~~1. **Anthropic provider (Python)**~~ — Done. `providers/anthropic.py` ships; `anthropic` in `pyproject.toml`.
~~2. **Fix Gemini model name**~~ — Done. Reads `GEMINI_MODEL` from config.
~~3. **OpenAI + Anthropic provider adapters (TypeScript)**~~ — Done. Both ship and export from `@agentkit/sdk`.
~~4a. **`AgentRuntime.send()` (TypeScript)**~~ — Done.
~~4b. **`AgentStrategy.maxToolIterations` (TypeScript)**~~ — Done. Was hardcoded to 10.
~~4c. **`ModelProvider` interface hardening**~~ — Done. `temperature`, `maxTokens`, `cancellationToken` added.
~~5. **RAG prompt injection**~~ — Done. Auto-injected in `runtime.py:108-135`.

~~4. **Auth reconciliation (serve)**~~ — Done. `decode_bearer_token()` shared between HTTP deps and WebSocket `authenticate_ws()`; both now do local HS256 decode instead of the WS path calling Supabase over HTTP.
~~5. **Integration base class + namespaced tools + risk labels**~~ — Done. `Integration` ABC (Python + TS), `ToolSpec.risk` field, namespace-prefix registration via `register(registry)`. Tests: 4 Python + 4 TS.
~~6. **Approval events + `ToolPolicy` upgrade**~~ — Done. `ToolPolicy` (Python + TS) with allow/deny lists + risk-gated approval. `ToolPlanner` emits `TOOL_APPROVAL_REQUESTED/APPROVED/REJECTED`; fail-safe: no handler = rejected.
~~7. **`Agent` facade**~~ — Done as `AgentBuilder` (builder pattern, cleaner long-term than constructor params). Fluent `.provider().integration().policy().build()` in both SDKs. Tests: 4 Python + 4 TS.
~~8. **ToolGen V0**~~ — Done as `agentkit gen --spec <openapi.json> --out <dir>` in `@agentkit/cli`. Emits `ToolSpec[]` + fetch-based stub handlers. Risk inferred from HTTP method. Zero new runtime deps.

~~3. **`@tool` decorator**~~ — Done. `tool(meta, fn)` in `integrations/base.ts`; overload on `ToolRegistry.register` + `registerTool` auto-derives spec from tagged handler.
~~4. **`TOOL_CALL_FAILED` projection (TS)**~~ — Done. Replay projects failed tool calls; `AgentRuntime` emits `TOOL_CALL_FAILED` on execution errors.
~~5. **`SessionManager` / `SessionStore` (TS)**~~ — Done. `sessions/store.ts` (`InMemorySessionStore`) + `sessions/manager.ts` with `getState`/`recordSession`/`listActive`.

Also resolved (not originally tracked):
- `AgentRuntime` bypassed `ToolPolicy` entirely — now enforces deny-list + risk-based approval in scatter-gather before execution.
- `SessionManager.getState` threw on empty event log — now returns empty `SessionState` (both SDKs).
- Gemini provider dropped `tools`/`system_instruction` in cached path — fixed in `providers/gemini.py`.
- Shared `normalize_role` / `to_gemini_role` translator in `providers/_translate.py` — OpenAI, Kimi, Gemini now use it.
- `userId` was hardcoded as `"runtime"` in TS `AgentRuntime` — now threaded from `AgentRuntimeOptions.userId`.

Remaining:
1. **Integration test scaffold** — `pytest -m integration` harness (Python) + Vitest integration suite (TS) gated behind env flag. ~1d.
2. **`agentkit init` CLI** — scaffold exists (`apps/cli/src/commands/init.ts`) but is a stub (no file writes, no real setup). ~1-2d.

<!-- TODO(task-12): Voice — Deepgram STT + barge-in
     Why Deepgram over Soniox for barge-in: Deepgram emits structured VAD events
     (SpeechStarted) server-side over the same WebSocket during TTS playback, so
     barge-in is 3 lines of event handling rather than a local amplitude-threshold
     VAD pipeline. The newer Flux model adds StartOfTurn/EndOfTurn events that are
     semantically aware (not silence-only), reducing false positives on mid-sentence
     pauses. The current Soniox path has no VAD event surface at all.
     
     Scope when ready:
     - STT provider interface (swappable, same shape as ModelProvider)
     - DeepgramSTTProvider: stream PCM, parse VAD events, emit SpeechStarted
     - SpeechStarted during TTS playback = barge-in signal: cancel in-flight LLM
       turn (via CancellationToken) + stop TTS output
     - Turn-end via speech_final:true or EndOfTurn (Flux model)
     - Replace Soniox gateway in serve/server/v1/voice.py
     - Est: ~1 week including integration tests against Deepgram sandbox
-->

---

## 11. Integration layer status

Introduced by the integrations/toolgen design doc. This entire layer sits above the runtime kernel and is currently absent. The runtime kernel (§2) is the correct foundation; none of these items require changes to it.

| Concept | Status | Blocking on | Est. |
| --- | --- | --- | --- |
| `Integration` base class / protocol | Done (Python + TS) | — | — |
| Namespaced tool names (`gmail.search_emails`) | Done (Python + TS) | — | — |
| Risk classification (`read`, `write`, `external_effect`, `financial`, `destructive`, `admin`) | Done (`ToolSpec.risk`, Python + TS) | — | — |
| `ToolPolicy` upgrade (risk-driven, not just allow/deny) | Done (Python + TS) | — | — |
| Approval events (`approval.requested/approved/rejected`) | Done (Python + TS via `ToolPlanner`) | — | — |
| `AgentBuilder` facade | Done (Python + TS) | — | — |
| `@tool(risk=..., require_approval=...)` decorator | Missing | `Integration` base | 0.5d |
| Integration manifests (YAML per integration) | Missing | `Integration` base | 1d |
| OAuth / ConnectedAccounts (tool-level auth) | Missing | manifests | 1-2d |
| Sync/indexing adapters | Missing | OAuth layer | weeks |
| Capability abstraction (`Email()`, `CRM()`) | Missing | official integrations | weeks |
| Official connectors (Gmail, Slack, Airtable, etc.) | Missing | all of the above | weeks each |

The first six rows of the critical path are now done. Remaining integration-layer items fan out from the `@tool` decorator and official connectors.

**Current `ToolPolicy` state** (`runtime/tools/policies.py`): risk-gated allow/deny with approval hooks in `ToolPlanner`. `ToolSpec.risk` field added in both SDKs.

---

## 12. ToolGen status

ToolGen is the build-time pipeline that converts APIs, schemas, and app metadata into agent-ready `Integration` packages. It is not a runtime concept.

**Current state: not started.** The landing page lists "toolgen" as a shipped feature — this is incorrect. The tool *registry* is done; ToolGen (the code generator) does not exist.

**What ToolGen produces** (target output, none exists today):

```
agentkit_billing/
  pyproject.toml
  integration.yaml        ← manifest
  agentkit_billing/
    integration.py        ← Integration subclass
    tools.py              ← @tool handlers (stubs, ready to fill)
    schemas.py            ← Pydantic request/response models
    auth.py               ← auth config
    policies.py           ← risk + approval defaults
  tests/
    test_customers.py
    test_payments.py
```

**Planned sources** (in priority order):

| Source | CLI | Status | Notes |
| --- | --- | --- | --- |
| OpenAPI spec | `agentkit toolgen from-openapi ./spec.yaml` | Missing | Highest leverage; most APIs have one |
| MCP server | `agentkit toolgen from-mcp github` | Missing | Wraps MCP as an Integration, adds policy/approval layer |
| Postgres schema | `agentkit toolgen from-postgres $DATABASE_URL` | Missing | Infers business entities from table/column names |
| Airtable base | `agentkit toolgen from-airtable --base app123` | Missing | SaaS-specific; generates domain tools from base schema |
| Docs / runbooks | `agentkit toolgen from-docs ./docs` | Missing | Advanced; requires human review before use |

**Pipeline stages** (target, none implemented):

```
Source → Introspect → Normalize → Select → Group → Name → Schema → Policy → Generate → Test → Publish
```

The key design constraint (from the doc, §19): ToolGen generates at **build time**, reviewed by the developer before use. Runtime tool invention by the LLM is explicitly out of scope — it creates security, auditability, and versioning problems.

**V0 scope** (what makes ToolGen useful enough to ship): OpenAPI source only, include/exclude filters, risk inference from HTTP method + path keywords, review YAML output, generated `Integration` subclass with typed handler stubs, basic schema validation tests. Everything else is V1+.
