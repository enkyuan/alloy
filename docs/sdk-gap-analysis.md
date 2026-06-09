# AgentKit SDK Gap Analysis: TypeScript vs Python

Date: 2026-06-09

## Scope

Compares the TypeScript SDK (`agentkit/ts/src`) against the reference Python SDK
(`agentkit/sdk/agentkit`). The `serve` reference service is out of scope; only
the embeddable core SDKs are analyzed. Every claim below was verified by reading
the current source on branch `feat/docs-restyle-2`.

## 1. Surface map

Module-by-module. Status: aligned (shapes match modulo language idiom),
partial (exists in TS but reduced), missing (no TS equivalent).

| Concern | Python | TypeScript | Status |
| --- | --- | --- | --- |
| Event types (enum) | `infra/events/types.py` | `events/types.ts` | aligned |
| Event schemas | `infra/events/schemas.py` (Pydantic) | `events/schemas.ts` (Zod) | aligned |
| Event bus (in-mem) | `infra/events/bus.py:InMemoryEventBus` | `events/bus.ts:EventBus` | partial |
| Event bus (Redis) | `infra/events/bus.py:EventBus` | none | missing |
| Event store iface | `infra/events/store/base.py` | `events/store.ts` | aligned |
| Event store (in-mem) | `infra/events/store/inmem.py` | `events/store.ts:InMemoryEventStore` | aligned |
| Replay / projection | `infra/events/replay.py` | `sessions/replay.ts` | partial (diverges) |
| Tool registry | `runtime/tools/registry.py` | `tools/registry.ts` | aligned (naming) |
| Tool payload translators | `runtime/tools/payload.py` | none | missing |
| Tool retriever | `runtime/tools/retriever.py` | none | missing |
| Provider interface | `runtime/providers/base.py` + `types.py` | `providers/base.ts` | partial (reduced) |
| Provider registry | `runtime/providers/registry.py` | `providers/registry.ts` | aligned |
| Mock provider | `runtime/providers/mock.py` | `providers/mock.ts` | aligned |
| OpenAI provider | `runtime/providers/openai.py` | none | missing |
| Kimi provider | `runtime/providers/kimi.py` | none | missing |
| Gemini provider | `runtime/providers/gemini.py` | none | missing |
| Agent runtime | `runtime/agents/runtime.py` | `runtime/runtime.ts` | partial (diverges) |
| Tool planner | `runtime/agents/planner.py` | inlined in `runtime.ts` | partial |
| Agent strategy config | `runtime/agents/strategy.py` | none (hardcoded const) | missing |
| Cancellation | `runtime/agents/cancellation.py` | `runtime/cancellation.ts` | aligned |
| Context builder | `runtime/agents/context.py` | `runtime/context.ts` | aligned |
| Swarm router | `runtime/agents/router.py` | none | missing |
| Session manager | `runtime/sessions/manager.py` | none | missing |
| Session store | `runtime/sessions/store.py` | none | missing |
| Voice STT/TTS | `modalities/voice/**` | none | missing |
| Knowledge / RAG | `knowledge/**` | none | missing |
| Core infra (config/redis/db/auth/observability) | `core/**`, `infra/observability/**` | none | missing |

## 2. Aligned

- **Event taxonomy.** `EventType` in both SDKs has the identical 26 members with
  byte-identical wire strings (`session.created` ... `cancellation.completed`).
  `infra/events/types.py:EventType` vs `events/types.ts:EventType`.
- **Event schema fields and defaults.** Common base fields match: `id`,
  `version` (`"1.0"`), `timestamp`, `session_id`, `metadata`. Default
  generation mirrors: Python `uuid.uuid4()` / `time.time()` /
  `Field(default_factory=dict)` vs TS `crypto.randomUUID()` / `Date.now()/1000`
  / `() => ({})`. Strictness matches: Pydantic `ConfigDict(extra="forbid")` vs
  Zod `.strict()`. Per-event payload fields (e.g. `tool_name`, `tool_args`,
  `tool_call_id`, `result`, `error`) are snake_case on both sides. The TS
  comments explicitly pin snake_case as the shared wire format.
- **Event store interface.** Both expose `append(event)` and
  `get_events`/`getEvents(session_id)`; both in-memory backends sort by
  `timestamp` on append (`store/inmem.py:23`, `store.ts:26`).
- **Tool registry shape.** `ToolSpec` (name, description, parameters, tags,
  enabled), `ToolContext`, `ToolRegistry`, module-level register/list/execute,
  and a schema-to-spec helper all match, modulo the `user_id`/`userId` naming
  (see issue 1) and the spec-from-model source format (Pydantic model vs Zod
  schema; both reduce to `{type, properties, required}`).
- **Cancellation and context builder.** `CancellationToken` (cancel + cancelled
  check) and the system-prompt-plus-history message construction match.
- **Provider registry and mock provider.** Name-keyed map with
  register/get/clear, and a mock that calls the first tool once then returns
  fixed text, are equivalent.

## 3. Missing in TS

Grouped by subsystem. All paths are Python.

- **Real providers.** `runtime/providers/openai.py`, `kimi.py`, `gemini.py`. TS
  ships only `MockProvider`.
- **Tool payload translators.** `runtime/tools/payload.py`
  (`build_tools_payload`, `spec_to_neutral`, `to_openai`, `to_gemini`). TS has
  no neutral-to-provider translation layer.
- **Tool retriever.** `runtime/tools/retriever.py` (`ToolRetriever`,
  `Embedder`/`EmbeddingCache` protocols, `GeminiEmbedder`,
  `InMemoryEmbeddingCache`, `get_tool_retriever`).
- **Agent strategy config.** `runtime/agents/strategy.py:AgentStrategy`
  (`max_iterations`, `allow_tool_calls`, `temperature`). TS hardcodes
  `MAX_TOOL_ITERATIONS = 10`.
- **Tool planner as a unit.** `runtime/agents/planner.py:ToolPlanner` +
  `ToolExecutor` are a separately injectable component in Python. TS inlines the
  scatter-gather directly in `runtime.ts`.
- **Swarm orchestration.** `runtime/agents/router.py:SwarmRouter` plus the
  runtime's handoff emit path. TS projects no swarm events and never emits them.
- **Sessions management.** `runtime/sessions/manager.py:SessionManager`,
  `runtime/sessions/store.py` (`SessionStore`, `SessionRecord`,
  `InMemorySessionStore`).
- **Voice modality.** `modalities/voice/**` (STT handler/Soniox gateway, TTS
  base/adapter/OpenAI/Gemini providers, turn detection, interruption, DTMF).
- **Knowledge / RAG.** `knowledge/rag.py:DocumentRAG`, `knowledge/store.py`
  (`VectorStore`, `InMemoryVectorStore`), `knowledge/chunking.py:chunk_text`,
  `knowledge/types.py` (`Document`, `Chunk`).
- **Core infra.** `core/**` (config, redis, database, auth, crypto, http,
  logging, lifecycle, broker, errors), `infra/observability/**` (metrics,
  tracing, timeline), `infra/realtime/**` (Redis events/history, embedding
  cache). Most of this is server-side and not required for an embedded SDK, but
  the durable Redis `EventBus` is the one item with cross-SDK relevance.

## 4. Alignment issues

Verified divergences in components that exist on both sides.

| # | Component | Python | TypeScript | Impact |
| --- | --- | --- | --- | --- |
| 1 | Tool context naming | `registry.py:ToolContext.user_id`; `execute_tool(user_id=...)` | `registry.ts:ToolContext.userId`; `executeTool(userId, ...)` | Ergonomic only (context is in-process, not on the wire). Convention split between SDKs. |
| 2 | Provider tool-call shape | `providers/openai.py:_parse_tool_calls` emits dicts `{id, name, arguments}` | `providers/base.ts:ToolCall = {id, name, args}` | Cross-SDK: a provider port that follows TS `args` would not feed the Python planner, which reads `call.get("arguments")` (`planner.py:61`). |
| 3 | Provider `generate` signature | `providers/base.py:generate(messages, tools, system_instruction, temperature=0.7, max_tokens, response_format, cancellation_token)` | `providers/base.ts:generate(messages, tools)` | TS providers cannot receive temperature, token caps, structured-output format, or a cancellation handle. |
| 4 | Provider response metrics | `providers/types.py:GenerateResponse` carries `metadata` (`ModelMetadata`) + `metrics` (`TokenMetrics`) | `providers/base.ts:ModelResponse = {content, toolCalls}` | No token accounting or provider/model attribution available in TS. |
| 5 | Replay tool_call_id threading | `replay.py:42` projects tool result with no id | `replay.ts:62` carries `toolCallId` into the message; `context.ts:24` uses it | Differing projected message objects; TS produces provider-valid tool ids, Python does not. |
| 6 | TOOL_CALL_FAILED projection | `replay.py:47` appends a `tool` message `"Error: {error}"` | `replay.ts` intentionally does NOT project FAILED (comment lines 73-78) | Same failure log yields different `SessionState.messages`; a Python-side failure becomes invisible to a TS replay. |
| 7 | Tool result stringification | `replay.py:45` uses `str(result)` (Python repr) | `replay.ts:92` uses `JSON.stringify` for objects, `String` for primitives | Object tool results render to different content strings; replayed histories diverge byte-for-byte. |
| 8 | Tool-event emit ordering | `planner.py:_execute_single` emits REQUESTED then STARTED per call, interleaved inside the gather | `runtime.ts:104` emits ALL REQUESTED first, then a separate gather emits STARTED+COMPLETED/FAILED | Event-log interleaving differs across SDKs for multi-tool turns. |
| 9 | Cancellation primitive | `cancellation.py:CancellationToken` wraps `asyncio.Event`; `is_cancelled` property | `cancellation.ts` wraps a boolean; `isCancelled` getter + `throwIfCancelled()` | Functionally equivalent; TS adds `throwIfCancelled` (raises) vs Python's check-and-emit. Naming split. |
| 10 | EventBus return / subscribe | `bus.py` `publish() -> str` (id); `subscribe(session_id, last_id="0", block_ms=2000)` | `bus.ts` `publish() -> Promise<void>`; `subscribe(sessionId)` (no resume/block params) | TS cannot return a stream id or resume from a `last_id`; no durable cross-process bus. |
| 11 | Runtime `send()` convenience | `runtime.py:send(session_id, content, token)` appends UserMessage then runs | `runtime.ts` has only `runTurn`; caller must append the UserMessage event | Extra boilerplate to start a turn in TS. |
| 12 | Strategy config | `strategy.py:AgentStrategy` (max_iterations=5, allow_tool_calls, temperature) injected into runtime | `runtime.ts:MAX_TOOL_ITERATIONS = 10` constant; no allow_tool_calls / temperature | Iteration cap differs (5 vs 10) and is not configurable in TS. |
| 13 | Planner as component | `runtime.py` depends on injected `ToolPlanner`; executor is pluggable | `runtime.ts` inlines `executeTool("runtime", ...)` with a fixed user id | TS cannot swap the tool executor or scope the registry per agent without editing the runtime. |

## 5. Critical cross-SDK divergences

The subset that breaks byte-for-byte event-log replay or cross-SDK event
exchange. Concrete failure modes:

1. **Tool-call field names (`arguments` vs `args`, issue 2).** Provider output
   is internal, not a wire event, so this does not corrupt the event log
   directly. But it blocks a shared provider contract: a provider written to the
   TS `ToolCall` shape feeds `args`, while the Python planner reads `arguments`
   (`planner.py:61`), so tool args silently arrive empty. A canonical name must
   be picked before any provider is shared or ported.

2. **tool_call_id threading (issue 5).** TS replay carries `tool_call_id` into
   the projected tool message and `buildMessages` emits it to the provider;
   Python drops it. Re-emitted provider requests therefore differ, and a TS
   message stream targeting a real provider is valid where the Python one is not
   (a real provider rejects a tool result whose id does not match the request).

3. **TOOL_CALL_FAILED projection (issue 6).** The same event log replays to
   different `SessionState.messages`: Python inserts an `"Error: ..."` tool
   message that the agent loop can react to; TS skips it entirely. A failed tool
   on the Python side changes the next prompt; on the TS side it does not, so
   the two runtimes can diverge in their next action from an identical log.

4. **Result stringification (issue 7).** `str(result)` (Python dict repr,
   e.g. `{'k': 1}`) vs `JSON.stringify` (`{"k":1}`) produce different tool
   message content for object results. Any cross-SDK replay comparison or
   golden-log test fails on content mismatch.

5. **Emit ordering (issue 8).** For a multi-tool turn, Python interleaves
   REQUESTED/STARTED per call; TS emits all REQUESTED first. The resulting event
   logs are not position-identical, so a strict log-equality check across SDKs
   fails even when every individual event is well-formed.

6. **Event default generation.** Not a divergence but a shared dependency:
   `timestamp` is `time.time()` (Python) and `Date.now()/1000` (TS), both
   fractional Unix seconds, and `id` is uuid4 on both. These agree, which is why
   replay ordering (sort by timestamp) is comparable. Keep them aligned; a
   change to either (e.g. TS switching to integer ms) would silently reorder
   cross-SDK merged logs.

## 6. Prioritized closure plan

### P0: wire compatibility (event-log replay parity)

- **Align tool-call shape (issue 2).** Decision required: canonical field name.
  Recommend `arguments` (matches the wire event field `tool_args` semantics and
  the existing Python provider/planner contract; fewer files change). Change
  `agentkit/ts/src/providers/base.ts:ToolCall.args -> arguments`, then update
  consumers `providers/mock.ts:31` and `runtime/runtime.ts:108,122` (`tc.args`).
- **Unify tool_call_id threading + TOOL_CALL_FAILED projection (issues 5, 6).**
  Decision required: adopt the TS behavior as canonical (it is provider-correct).
  Python side: `infra/events/replay.py` should carry `tool_call_id` into the
  tool message and keep projecting TOOL_CALL_FAILED; TS side `sessions/replay.ts`
  should ALSO project TOOL_CALL_FAILED (add a `case EventType.TOOL_CALL_FAILED`
  that pushes `content: "Error: " + error`, mirroring `replay.py:47`). Both SDKs
  must agree on whether FAILED is projected; today only Python projects it.
- **Align replay result stringification (issue 7).** Decision required: canonical
  serialization. Recommend JSON for both (parseable, stable). Python
  `infra/events/replay.py:45` change `str(event.result)` to a JSON dump with a
  sorted-keys/compact convention matching `replay.ts:92`.
- **Align emit ordering (issue 8).** Decision required: per-call interleave
  (Python) vs requested-first (TS). Recommend per-call interleave to match the
  planner. TS `runtime/runtime.ts` would drop the standalone REQUESTED loop
  (lines 104-111) and emit REQUESTED inside each gather task before STARTED.

### P1: capability parity (providers)

- **Port the OpenAI provider to TS.** New `agentkit/ts/src/providers/openai.ts`
  mirroring `runtime/providers/openai.py` (including `_parse_tool_calls` into the
  canonical tool-call shape from P0).
- **Port the neutral tool-payload translators.** New
  `agentkit/ts/src/tools/payload.ts` with `buildToolsPayload`, `toOpenAI`,
  `toGemini` mirroring `runtime/tools/payload.py`. Required by any real provider.
- **Add provider `generate` params + metrics to the TS interface.** Extend
  `agentkit/ts/src/providers/base.ts:ModelProvider.generate` with
  `systemInstruction`, `temperature`, `maxTokens`, `responseFormat`,
  `cancellationToken`; add `metadata`/`metrics` to `ModelResponse` mirroring
  `providers/types.py:GenerateResponse`. Update `providers/mock.ts` to the new
  signature.

### P2: ergonomics

- **userId/user_id convention (issue 1).** Decision required. Recommend keeping
  each SDK idiomatic (`userId` in TS, `user_id` in Python) since it is
  in-process only; document the equivalence. Files: `tools/registry.ts`,
  `runtime/tools/registry.py`. No code change if documented.
- **AgentStrategy config in TS (issue 12).** Add a strategy/options object to
  `agentkit/ts/src/runtime/runtime.ts` (replace `MAX_TOOL_ITERATIONS` const with
  an option; reconcile default 5 vs 10) mirroring
  `runtime/agents/strategy.py`. Decision required: canonical default iteration
  count.
- **`send()` convenience (issue 11).** Add `AgentRuntime.send(sessionId,
  content, token)` to `runtime/runtime.ts` mirroring `runtime.py:64`.
- **EventBus publish/subscribe parity (issue 10).** Make `bus.ts:publish` return
  the appended id (string) and accept an optional resume position on
  `subscribe`, mirroring `bus.py`. Decision required: id format for the in-memory
  bus (Python uses the log index as a string).

### P3: larger ports (follow-on projects)

- Voice STT/TTS (`modalities/voice/**`).
- Knowledge / RAG (`knowledge/**`: `DocumentRAG`, `VectorStore`, `chunk_text`).
- SessionManager / SessionStore (`runtime/sessions/{manager,store}.py`).
- Swarm orchestration (`runtime/agents/router.py` + runtime handoff path).
- Durable Redis EventBus (`infra/events/bus.py:EventBus`), to give TS a
  cross-process bus with `last_id` resume.
- ToolRetriever (`runtime/tools/retriever.py`) with a pluggable embedder.

## 7. Appendix: file-path reference

Python (`agentkit/sdk/agentkit/`):

- `__init__.py` (lazy public surface)
- `infra/events/types.py`, `schemas.py`, `bus.py`, `replay.py`,
  `store/base.py`, `store/inmem.py`
- `runtime/tools/registry.py`, `payload.py`, `retriever.py`, `planner.py`
- `runtime/providers/base.py`, `types.py`, `openai.py`, `kimi.py`, `gemini.py`,
  `mock.py`, `registry.py`
- `runtime/agents/runtime.py`, `planner.py`, `strategy.py`, `cancellation.py`,
  `context.py`, `router.py`
- `runtime/sessions/manager.py`, `store.py`, `replay.py`, `state.py`
- `knowledge/rag.py`, `store.py`, `chunking.py`, `types.py`
- `modalities/voice/**`
- `core/**`, `infra/observability/**`, `infra/realtime/**`

TypeScript (`agentkit/ts/src/`):

- `index.ts` (public exports)
- `events/types.ts`, `schemas.ts`, `bus.ts`, `store.ts`
- `sessions/replay.ts`
- `tools/registry.ts`
- `providers/base.ts`, `mock.ts`, `registry.ts`, `index.ts`
- `runtime/runtime.ts`, `cancellation.ts`, `context.ts`
