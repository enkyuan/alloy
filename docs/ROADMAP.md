# Roadmap

What remains before the packages can be actively used to build agentic
platforms. Ordered by leverage: the P0 block is the shortest path to a developer
being able to `pip install` and run a tool-using agent with no external
services. Each item lists the concrete files involved.

Status legend: **DONE** / **PARTIAL** / **MISSING** reflects the current state of
the thing the issue addresses, not the issue itself.

---

## P0 — Unblock the core promise (public, infra-free agent loop) — DONE

The SDK's defining capability is to run a tool-using, multi-turn agent.
Completed 2026-05-31: `import agentkit` -> run an agent -> call a tool now works
end-to-end with zero external services, through the documented public API. The
quick-start in `packages/sdk/agentkit/README.md` runs verbatim with no Redis and
no API key; 83 SDK tests pass.

### 1. Wire tools into `AgentRuntime` (DONE)
Was: `AgentRuntime` hardcoded an empty tool list (`runtime.py:75`), so the tool
branch was dead.

- `packages/sdk/agentkit/runtime/agents/runtime.py` — added an optional `tools:
  List[ToolSpec]` constructor arg (empty default, so a no-tool agent still runs)
  and a provider-neutral payload (`{name, description, parameters}`) surfaced to
  `generate_stream` each turn.
- Tests added in `packages/sdk/tests/test_agents_runtime.py`: a full
  request -> execute -> continue loop, and a no-tools clean run.
- The neutral payload still needs per-provider translation at the boundary
  (issue #7) before real providers can consume it for tool calls.

### 2. Register the mock provider (DONE)
Was: `get_provider("mock")` raised because the mock never self-registered.

- `packages/sdk/agentkit/runtime/providers/registry.py` — loads
  `agentkit.runtime.providers.mock` in `_ensure_builtin_providers_loaded`.
- `packages/sdk/agentkit/runtime/providers/mock.py` — calls `register_provider`
  at module load and now requests the first offered tool (then replies with text
  once a tool result is in history), so it drives the full loop with no network.

### 3. Export the agent loop from the public API (DONE)
- `packages/sdk/agentkit/__init__.py` — added `AgentRuntime`, `AgentStrategy`,
  `ToolPlanner`, `CancellationToken`, `ModelProvider`, `UserMessage`, and
  `InMemoryEventBus` (see #3b) to the lazy map.
- `packages/sdk/agentkit/runtime/agents/__init__.py` — populated with the agent
  surface; `runtime/providers/__init__.py` now exports `ModelProvider`;
  `infra/events/__init__.py` exports `UserMessage` + `InMemoryEventBus`.
- `packages/sdk/agentkit/README.md` — added a runnable "Run an agent" snippet
  using the mock provider (no env, no Redis), with a self-contained no-arg tool.

### 3b. In-memory `EventBus` (DONE — discovered during P0)
The base `EventBus` was Redis-only (`infra/events/bus.py` `publish` calls
`redis.xadd`), so the "infra-free" agent loop actually required Redis the moment
it emitted an event — the README's "all in-memory by default" claim was false.
The audit had only flagged the `AgentReasoningNode` Redis coupling (#9), not the
base bus.

- `packages/sdk/agentkit/infra/events/bus.py` — added `InMemoryEventBus`
  (per-session log + live fan-out via `asyncio.Queue`), mirroring the Redis bus's
  `publish`/`subscribe` surface and the TS port's in-memory bus. The Redis
  `EventBus` is unchanged, so `agentkit-serve` is unaffected.
- Tests in `packages/sdk/tests/test_events_bus.py` (backlog replay, live
  fan-out, session isolation).
- Nothing in non-test code instantiated `EventBus()` directly, so blast radius
  was limited to the runtime (duck-typed) and tests.

---

## P1 — Providers: fill the obvious holes

### 4. Add an OpenAI LLM provider (DONE)
Done 2026-05-31. OpenAI was only a TTS key; now it's a first-class LLM provider.

- `packages/sdk/agentkit/runtime/providers/openai.py` — implements
  `ModelProvider` (`generate` + `generate_stream`, both with tool calls) via the
  official async `openai` SDK (lazy client, mirrors the OpenAI TTS service).
  Consumes the neutral tool payload through `to_openai` (#7).
- Self-registers; loaded in `registry.py` builtins. `get_provider("openai")`
  fails clearly with no key.
- `OPENAI_MODEL` (default `gpt-4o`) and `OPENAI_BASE_URL` added to config.
- **Kimi stays the default** (`AGENTKIT_MODEL_PROVIDER = "kimi"`) — unchanged.
- Tests in `packages/sdk/tests/test_providers_openai.py` (loadable, no-key,
  message build, tool-call parsing for object + dict forms, and a mocked
  `generate` proving neutral->OpenAI tool translation + response normalization).
- `.env.example` is in a permission-denied directory in this environment; its
  `OPENAI_MODEL` line was not added. Add it there when accessible.

### 5. Add an Anthropic provider (MISSING)
There is no way to talk to Claude. For a general SDK this is the most visible
provider gap.

- New `packages/sdk/agentkit/runtime/providers/anthropic.py` implementing the
  protocol with streaming + tool use.
- Add `anthropic` as a dependency in `packages/sdk/pyproject.toml` and an
  `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` to config.
- Self-register in `registry.py`.

### 6. Fix Gemini streaming (DONE)
Done 2026-05-31. `generate_stream` now has parity with `generate`: full history
and tool calls, instead of collapsing to the last message with `tool_calls=[]`.

- Added `GeminiService.generate_chat_stream` — mirrors `generate_chat_response`
  (full history + system instruction + tools) but uses `generate_content_stream`
  and yields raw chunk objects. Context caching is intentionally not applied on
  the streaming path (kept simple; the non-stream path retains it).
- `GeminiProvider.generate_stream` rewritten: passes `to_gemini(tools)`, extracts
  text deltas (guarded — `chunk.text` raises on function-call chunks) and
  function-call parts via `extract_response_function_calls`, emits
  `ModelResponseChunk` with both `delta` and `tool_calls`.
- The old prompt-only `GeminiService.generate_streaming_response` is untouched —
  still used by the serve REST route `agentkit_serve/server/v1/providers.py:120`,
  so it is not dead code.
- Tests in `packages/sdk/tests/test_providers_gemini_stream.py` (text deltas,
  full-history + tool-translation passthrough, tool-call surfacing, cancellation),
  using an injected fake service (no key/network).

---

## P2 — Decouple the building blocks from infra

### 7. Provider-neutral tool payloads (DONE)
Done 2026-05-31. The neutral format is a flat
`[{name, description, parameters}]` list (what the registry and `AgentRuntime`
already produced in P0); each provider translates at its boundary.

- `packages/sdk/agentkit/runtime/tools/payload.py` — `build_tools_payload` now
  returns the flat neutral list (was wrapped in `function_declarations`). Added
  `to_gemini` (wraps in `function_declarations`) and `to_openai` (wraps each in
  `{type: function, function: {...}}`). `tools_fingerprint` kept as an alias.
- `gemini.py` calls `to_gemini`; `agentic.py` dropped its unwrap dance (it was
  wrapping then immediately unwrapping the Gemini shape) and passes the flat list
  straight through.
- `function_calls.py` (`extract_response_function_calls`) is Gemini-only and
  only imported by the Gemini provider, so it was left in place (no leak into the
  runtime). The runtime-neutrality guard test still passes.
- Tests in `packages/sdk/tests/test_tools_payload.py`.

**Discovery:** Kimi was **broken** for tool calls — it passed the flat list
straight into OpenAI's `payload["tools"]`, which is invalid OpenAI format (see
#7b below).

### 7b. Fix Kimi tool translation (DONE — discovered during #7)
`KimiProvider._prepare_payload` set `payload["tools"] = tools` with the neutral
(or previously Gemini-wrapped) list, neither of which is valid OpenAI tool
format, so tool calls to Kimi/OpenRouter would have failed.

- `packages/sdk/agentkit/runtime/providers/kimi.py` — now translates via
  `to_openai` at the boundary. Verified it emits
  `{type: function, function: {...}}`.

### 8. Decouple `ToolRetriever` from Gemini + Redis (DONE)
Done 2026-05-31. Both the embedder and the cache are now pluggable; the default
path is infra-free.

- `packages/sdk/agentkit/runtime/tools/retriever.py` — added `Embedder` and
  `EmbeddingCache` protocols. `ToolRetriever(embedder=..., cache=...)` injects
  them. Defaults: `GeminiEmbedder` (constructs the Gemini service *lazily* on
  first `embed`, and returns `[]` instead of raising if `GEMINI_API_KEY` is
  missing) and `InMemoryEmbeddingCache`. Importing the module touches no Gemini
  and no Redis. With no embedder available the retriever falls back to returning
  all tool names, so retrieval never blocks tool use.
- `packages/sdk/agentkit/infra/realtime/embedding_cache.py` — `RedisEmbeddingCache`
  (opt-in) lives in the Redis layer so the retriever module stays Redis-free.
  The reference service can wire it via `ToolRetriever(cache=RedisEmbeddingCache())`.
- Verified infra-free: from a clean env (no key, no Redis) `get_top_tools`
  returns all tools without raising. Tests in
  `packages/sdk/tests/test_tools_retriever.py`.

**Carried-over bug (pre-existing, now documented):** `RedisEmbeddingCache`
stores msgpack (binary), but the shared `get_redis_client()` uses
`decode_responses=True`, so `load` can't unpack and silently cold-recomputes.
The old code had the same issue (wrapped in a try/except), so the Redis cache
never actually worked. Needs a bytes-mode Redis client to be effective; noted in
the class docstring. (Tracked as a follow-up, not fixed here.)

### 9. In-memory fallback for `AgentReasoningNode` (DONE)
Done 2026-05-31. The node's only infra coupling was conversation-history
read/write (the reasoning logic itself — RAG, scatter-gather, the loop — was
already Redis-independent). Abstracted behind a pluggable history store.

- `packages/sdk/agentkit/runtime/agents/history.py` — `HistoryStore` protocol
  (`append`/`get`) + `InMemoryHistoryStore` (dedup-consecutive + trim, matching
  the Redis semantics). The node defaults to in-memory: no `get_redis_client()`,
  no Redis import anywhere in `agentic.py`.
- `packages/sdk/agentkit/infra/realtime/redis_history.py` — `RedisHistoryStore`
  (opt-in) adapts the existing `redis_events` helpers; lazy client.
- `AgentReasoningNode.__init__` gained `history_store=` (mirrors the existing
  `session_factory=` injection). The serve worker
  (`agentkit_serve/workers/main.py`) now passes `history_store=RedisHistoryStore()`
  so its durable cross-process history is preserved.
- Tests: `packages/sdk/tests/test_agents_history.py` (store semantics) and
  `packages/sdk/tests/test_agents_node_infra_free.py` (node `generate()` runs
  end-to-end with no infra — `agentic.py` previously had zero tests).

**Two-loop decision (deliberate, NOT converged):** `AgentRuntime` (event-sourced,
streaming, provider-neutral, public) and `AgentReasoningNode` (voice-pipeline
node: non-streaming, scatter-gather in-node, bound to the messaging `Bus`/`Bridge`
and voice `event_models`, invoked by the serve worker) have genuinely different
shapes and call sites. Converging them is a large refactor that would ripple into
the serve worker topology, so it was scoped out. Both are now infra-free; if
convergence happens later it should fold `AgentReasoningNode`'s scatter-gather +
RAG into `AgentRuntime` and retire the node. Note an asymmetry: the node records
tool results as `assistant` summaries (not `role: tool`), so with the mock
provider its loop runs to `MAX_TOOL_ITERATIONS` rather than terminating after one
tool call the way `AgentRuntime` does post-#9b.

### 9b. Project `TOOL_CALL_FAILED` into session state (DONE)
Done 2026-05-31. The replay projection ignored `TOOL_CALL_FAILED`, so a failed
tool vanished from history and the loop re-requested it every iteration until
`max_iterations` (observed with the mock provider when a tool raised).

- `packages/sdk/agentkit/infra/events/replay.py` — added a `TOOL_CALL_FAILED`
  branch appending `{role: tool, name, content: "Error: <error>"}`.
- Verified: a tool that always raises now produces exactly 1 `tool.call.requested`
  (was 5) and the loop terminates with a final message. Test in
  `packages/sdk/tests/test_events_replay.py`.

---

## P3 — Capabilities promised but absent

### 10. General document / knowledge RAG (MISSING)
The only retrieval that exists is tool-selection RAG. There is no document
ingestion, chunking, vector store, or retrieval-over-corpus. If RAG is a
promised building block, design and build it (or remove the claim from docs).

### 11. Multi-agent / swarm handoff (MISSING — stub)
- `packages/sdk/agentkit/runtime/agents/router.py:13` —
  `determine_handoff` unconditionally returns `None`, so the `SwarmRunStarted` /
  `SwarmAgentSpawned` emit path in `runtime.py:105-117` is unreachable. Implement
  routing logic or drop the swarm surface until it's real.

### 12. Durable session persistence (MISSING)
- `packages/sdk/agentkit/runtime/sessions/manager.py` — `list_active` returns
  `[]` ("Placeholder until session persistence is wired").
- Only `InMemoryEventStore` ships in the SDK core; there is no durable store. A
  durable backend likely belongs in `agentkit-serve`, but the SDK needs the
  store interface to support it.

---

## Voice / `agentkit-serve` — for the reference service

The STT -> LLM -> TTS happy path works end-to-end via Redis. These are the gaps
before the reference voice service is production-usable.

### 13. Barge-in / interruption (MISSING)
The event models (`AgentStartedSpeaking`, `UserStartedSpeaking`, etc.) are
defined and registered but nothing emits or consumes them; while the agent is
speaking, user speech will not stop playback.

- No speech-activity events are produced anywhere in the STT/voice/worker path.
- `_synthesize_and_publish` in `packages/serve/agentkit_serve/workers/main.py`
  streams TTS chunks with no cancellation hook.
- The DTMF look-ahead parser
  (`packages/sdk/agentkit/modalities/voice/utils/dtmf_lookahead_buffer.py`) is
  fully written but never fed by the pipeline.

### 14. Automatic turn / endpoint detection (MISSING)
A turn only ends when the client sends a literal `"END"` frame.

- `packages/sdk/agentkit/modalities/voice/turn_detection.py` —
  `resolve_turn_policy` has zero consumers.
- `packages/sdk/agentkit/modalities/voice/stt/soniox_gateway.py:52` —
  `enable_endpoint_detection=False` is hardcoded; the service already supports
  enabling it.

### 15. Durable chat persistence (PARTIAL)
- Postgres `Conversation` / `Message` models and migrations exist
  (`packages/serve/agentkit_serve/server/models/`) but nothing writes to them;
  history lives only in Redis, trimmed to `AGENT_HISTORY_LIMIT`.
- `packages/serve/agentkit_serve/server/v1/sessions.py:10` — the `/sessions`
  endpoint is backed by an in-memory store, lost on restart, read-only.

### 16. Reconcile the two auth paths (PARTIAL)
- HTTP validates Bearer tokens locally via HS256
  (`packages/serve/agentkit_serve/server/deps.py`,
  `get_current_supabase_user`).
- The STT WebSocket validates remotely against Supabase
  (`packages/sdk/agentkit/modalities/voice/stt/handler.py:209`).
- Pick one canonical token model so REST and the socket validate consistently.

### 17. Remove dead code (cleanup)
- `packages/serve/agentkit_serve/workers/tasks/memory.py` — empty, "reserved for
  future use." Either implement memory indexing or delete.
- `packages/serve/agentkit_serve/workers/helpers/llm_response.py` and
  `response_text.py` — fully written but never imported; the live worker uses the
  `AgentReasoningNode` bridge instead.

---

## TypeScript SDK (`packages/ts`) — to make it drive an agent

The event-sourcing + tool-registry core is complete and well-tested (all 26
event schemas, in-memory bus/store, replay projection, tool registry). It is not
yet an agent SDK. To make it drive an agent, build these in order:

### 18. Provider layer (MISSING)
- A `ModelProvider` interface (`generate` + `generate_stream` returning a chunk
  stream with `delta` + `tool_calls`), a provider registry, a mock provider for
  tests, and at least one real provider. Mirror
  `packages/sdk/agentkit/runtime/providers/base.py`.

### 19. Agent runtime (MISSING)
- Port `AgentRuntime.run_turn` (`packages/sdk/agentkit/runtime/agents/runtime.py`):
  load state via replay -> build messages (`ContextBuilder` + `SystemPrompt`) ->
  stream from provider -> emit `AgentMessageDelta` / `AgentMessageCompleted` ->
  execute tool calls and loop. Needs an `AgentStrategy` and a `CancellationToken`.

### 20. Tool-loop glue (MISSING)
- A planner/runner that turns provider `tool_calls` into `executeTool`
  (`packages/ts/src/tools/registry.ts`) calls and emits the
  `ToolCallRequested/Started/Completed/Failed` events so the loop can re-read
  state. The registry exists; the orchestration does not.

### 21. Reconcile sync vs async `publish` (design)
- `packages/ts/src/events/bus.ts:69` — `EventBus.publish` is synchronous, but the
  Python runtime awaits `bus.publish`. Settle the signature before porting the
  runtime, or the loop won't translate cleanly.

---

## Notes

- Two disconnected agent loops (`AgentRuntime` and `AgentReasoningNode`) is the
  root architectural issue behind P0 and #9 — converging on one is the cleanest
  fix.
- The README status line ("the core SDK is usable today",
  `README.md:14-16`) overstates the current state while the agent loop is not
  reachably wired; update it once P0 lands.
