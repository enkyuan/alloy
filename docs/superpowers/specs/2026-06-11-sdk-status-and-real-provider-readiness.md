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

The `ModelProvider` interface is stable (`src/providers/base.ts`). No concrete
providers ship. To run against a real model, implement the interface and
register before running the agent:

```ts
class OpenAIProvider implements ModelProvider {
  async generate(messages: ProviderMessage[], tools: ToolSpec[]): Promise<ModelResponse> {
    // translate to OpenAI format, call SDK, parse response
  }
  async *generateStream(messages, tools): AsyncGenerator<ModelResponseChunk> {
    // stream deltas + tool call chunks
  }
}
registerProvider("openai", new OpenAIProvider());
```

The interface carries `{ content, toolCalls }` out of `generate`. No
temperature, token caps, or cancellation handle yet (diverges from Python
`ModelProvider` signature — see `docs/sdk-gap-analysis.md §4 issue 3`).

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
| `AgentRuntime.send()` convenience | Works | Missing (callers must append UserMessage manually) |

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
- Concrete LLM providers (OpenAI, Kimi, Gemini, Anthropic)
- Neutral tool-payload translators (`to_openai`, `to_gemini`)
- RAG / knowledge retrieval engine
- `ToolRetriever` (semantic tool selection)
- Voice / STT / TTS
- Multi-agent swarm routing
- `SessionManager` / `SessionStore`
- `AgentStrategy` config (TS hardcodes `MAX_TOOL_ITERATIONS = 10`)
- Redis opt-in for bus / store
- `AgentRuntime.send()` convenience method

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
| Tool registry + toolgen | Done | Done |
| Pluggable LLM providers | Partial — Python: OpenAI/Kimi work; Gemini partial; Anthropic missing. TS: interface only. | Achievable — Anthropic (Py) + OpenAI/Anthropic (TS) |
| Text and voice | Partial — text streaming works; voice has 4 blocking gaps | Risky — voice gaps are 3-4 weeks of dedicated work on their own |
| RAG tool retriever | Partial — retrieval works; prompt injection is not wired | Achievable — injection is one focused week |
| In-memory or Redis | Done | Done |
| Replay & projection | Done | Done |
| Python & TypeScript parity | Partial — core loop mirrors; Python is ~6 months ahead on everything else | Partial — provider adapters close the most visible gap; full parity is months |

---

## 10. Ordered work to unblock real-model testing

1. **Anthropic provider (Python)** — `providers/anthropic.py` + add `anthropic` to `pyproject.toml` + `ANTHROPIC_API_KEY` config. ~3h.
2. **Fix Gemini model name** — `providers/gemini.py:42` hardcodes `gemini-2.5-flash`; reconcile with config default. ~30m.
3. **OpenAI + Anthropic provider adapters (TypeScript)** — implement `ModelProvider` interface for both. ~4h each.
4. **Integration test scaffold** — `pytest -m integration` harness (Python) + Vitest integration suite (TS) gated behind env flag. ~1d.
5. **RAG prompt injection** — auto-inject retrieved chunks into `AgentRuntime` prompt (ROADMAP 14). ~half-day.
6. **`agentkit init` CLI** — currently shown on the landing page but not implemented (ROADMAP 29). ~1-2d.
7. **Voice: barge-in + turn detection** — `serve/workers/main.py` + `stt/soniox_gateway.py`. ~1 week.
8. **Auth reconciliation (serve)** — single token model for HTTP and WebSocket. ~half-day once decided.
