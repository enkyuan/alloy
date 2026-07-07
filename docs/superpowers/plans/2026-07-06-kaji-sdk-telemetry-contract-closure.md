# Kaji SDK Telemetry And Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Kaji SDK and TS release gaps by making docs match the manifest reality, propagating provider usage/cost metadata through streamed runtime events, removing TS public declaration leaks, replacing private-test casts with explicit internal seams, and keeping non-core Python surfaces experimental with promotion criteria.

**Architecture:** Keep the current `AgentBuilder -> ToolRegistry -> ToolPlanner -> AgentRuntime -> ModelProvider` shape. Add optional telemetry metadata to provider stream chunks and completed agent events without changing text/tool-call semantics. Use protected provider client factories and internal pure helpers for tests so public constructors and declaration files stay clean.

**Tech Stack:** Python/Pydantic/pytest/ruff/ty/uv, TypeScript/Vitest/tsc/tsup/Bun, OpenAI and Anthropic provider adapters, JSON Schema integration manifests.

## Global Constraints

- Do not rewrite providers, service runtime, voice, RAG, Redis, or integration catalog internals.
- Do not promote Redis realtime/history, voice/TTS, DocumentRAG, native Gemini/Kimi, or tool retrieval to beta in this plan.
- Preserve no-key integration skip behavior and the existing `gpt-5.4-mini` live-readiness default.
- Runtime behavior changes are metadata-only: existing content deltas, completed messages, tool-call replay, and cancellation semantics must remain unchanged.
- Test-only TS seams must not appear in built `dist/*.d.ts` files.
- Use GitButler for version-control write operations per `AGENTS.md`; do not use raw `git commit`.

---

## Review Fold-In

- **Plan-tune:** The user has repeatedly asked for complete edge coverage with low question overhead. The plan makes defaults and scope decisions directly instead of stopping for obvious implementation choices.
- **CEO review:** Hold scope. The release trust problem is not more SDK features; it is clear proof of what works, honest status for what does not, and no stale product claims.
- **Engineering review:** The main risk is widening architecture while fixing metadata. The plan keeps metadata at provider/runtime boundaries, removes leaked test APIs, and uses tests that fail on stale docs and public declarations.
- **Interactive review note:** The native gstack plan review skills require `AskUserQuestion` gates. This Default-mode Codex session does not expose that gate safely, and the user already supplied the review target. Review findings are therefore applied as non-interactive recommendations and recorded here.

## File Structure

- `docs/MVP.md`: release narrative and manifest status.
- `kaji/RELEASE_MATRIX.md`: stability tiers and promotion criteria.
- `kaji/sdk/README.md`, `kaji/ts/README.md`: short status links and first-run truthfulness.
- `kaji/sdk/src/runtime/providers/types.py`: Python streaming chunk telemetry fields.
- `kaji/sdk/src/runtime/providers/costs.py`: Python cost calculation parity for models already priced in repo metadata.
- `kaji/sdk/src/runtime/providers/openai.py`, `kaji/sdk/src/runtime/providers/anthropic.py`: provider stream usage capture.
- `kaji/sdk/src/runtime/agents/runtime.py`: attach stream telemetry to `AgentMessageCompleted`.
- `kaji/ts/src/providers/base.ts`: TS streaming chunk telemetry fields.
- `kaji/ts/src/providers/openai-format.ts`: internal OpenAI message/tool formatting helpers.
- `kaji/ts/src/providers/openai.ts`, `kaji/ts/src/providers/anthropic.ts`: protected client factories, streaming usage capture.
- `kaji/ts/src/providers/factory.ts`: internal option resolver helpers for factory tests.
- `kaji/ts/src/runtime/runtime.ts`: attach stream telemetry to `AGENT_MESSAGE_COMPLETED`.
- `kaji/ts/tsconfig.json`, `kaji/ts/tsup.config.ts`: declaration hygiene, if needed after build inspection.
- `kaji/sdk/tests/*`, `kaji/ts/tests/*`: docs, telemetry, provider, declaration, and factory coverage.

## System Diagram

```text
Provider stream
  |
  | ModelResponseChunk(delta/toolCalls, optional usage/cost)
  v
AgentRuntime.turn()
  |
  | stores latest usage/cost seen during this model iteration
  v
AgentMessageCompleted(content, optional tokens/cost_usd)
  |
  v
Event schema + replay totals + release proof
```

The invariant is strict: usage/cost fields are optional metadata. A tool-only turn must still avoid emitting a phantom assistant text message.

## Task 1: Refresh MVP Manifest Status

**Files:**
- Modify: `docs/MVP.md`
- Modify: `kaji/sdk/tests/test_docs_sync.py`
- Modify: `kaji/sdk/tests/test_manifest_registry.py`
- Create or modify: `kaji/ts/tests/docs-contract.test.ts`

**Interfaces:**
- Consumes: existing Python and TS manifest schema files:
  - `kaji/sdk/src/integrations/registry/schema.json`
  - `kaji/ts/registry/schema.json`
- Produces: docs that no longer claim the shared manifest contract is absent.

- [ ] **Step 1: Add failing docs assertions**

In `kaji/sdk/tests/test_docs_sync.py`, add assertions equivalent to:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_mvp_manifest_status_is_current() -> None:
    mvp = (ROOT / "docs" / "MVP.md").read_text()
    assert "Catalog contract implemented" in mvp
    assert "Plan 3 - Define the first-party integration catalog contract (implemented)" in mvp
    assert "no shared manifest/auth/credential shape" not in mvp
    assert "Catalog contract still open" not in mvp
```

In `kaji/ts/tests/docs-contract.test.ts`, add the TS-side guard:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "../..");

describe("docs contract", () => {
  it("does not describe the manifest contract as missing", () => {
    const mvp = readFileSync(resolve(root, "../docs/MVP.md"), "utf8");
    expect(mvp).toContain("Catalog contract implemented");
    expect(mvp).not.toContain("Catalog contract still open");
    expect(mvp).not.toContain("no shared manifest/auth/credential shape");
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_docs_sync.py tests/test_manifest_registry.py -q

cd ../ts
bun run test tests/docs-contract.test.ts
```

Expected: docs-contract assertions fail before the doc update.

- [ ] **Step 3: Update `docs/MVP.md`**

Change the feature table row from:

```markdown
| First-party integration catalog | Python ships the `echo` proof integration. | TypeScript ships local/dev examples such as echo, HTTP, filesystem, web, and SQLite. | Catalog contract still open. |
```

to:

```markdown
| First-party integration catalog | Python ships the `echo` proof integration and validates manifests against the shared schema. | TypeScript ships local/dev examples and validates manifests against the same schema. | Catalog contract implemented; production third-party integrations remain out of MVP. |
```

Replace the stale gap paragraph with:

```markdown
The first-party integration manifest contract is implemented for the current
pre-beta scope. Both SDKs validate the same v0 manifest shape, including
`extras`, `peerDeps`, and non-empty `tools`. The remaining integration work is
not schema design; it is adding production integrations, auth flows, credential
storage, and scraper fallback policy when those surfaces enter scope.
```

Rename the Plan 3 heading to:

```markdown
### Plan 3 - Define the first-party integration catalog contract (implemented)
```

Keep the production Gmail/Spotify/auth discussion, but mark it as future integration expansion, not an open SDK-core release blocker.

- [ ] **Step 4: Verify**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_docs_sync.py tests/test_manifest_registry.py -q

cd ../ts
bun run test tests/docs-contract.test.ts tests/manifest-validate.test.ts
```

- [ ] **Step 5: Checkpoint**

Use GitButler to checkpoint only Task 1 changes:

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "docs(kaji): refresh manifest contract status"
```

## Task 2: Add Stream Telemetry To Cross-SDK Provider Contracts

**Files:**
- Modify: `kaji/sdk/src/runtime/providers/types.py`
- Create: `kaji/sdk/src/runtime/providers/costs.py`
- Create: `kaji/sdk/tests/test_providers_costs.py`
- Modify: `kaji/ts/src/providers/base.ts`
- Modify: `kaji/ts/tests/provider-cost.test.ts`

**Interfaces:**
- Python `ModelResponseChunk` gains:

```python
metrics: Optional[TokenMetrics] = None
cost_usd: Optional[float] = None
```

- TS `ModelResponseChunk` gains:

```ts
usage?: TokenUsage;
costUsd?: number;
```

- Python cost helper:

```python
def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    entry = lookup_cost(model)
    if entry is None:
        return 0
    return round(
        (input_tokens / 1_000_000) * entry.input_per_1m
        + (output_tokens / 1_000_000) * entry.output_per_1m,
        10,
    )
```

- [ ] **Step 1: Add failing Python cost tests**

Create `kaji/sdk/tests/test_providers_costs.py`:

```python
from kaji.runtime.providers.costs import calculate_cost_usd, lookup_cost


def test_calculate_cost_usd_for_gpt_54_mini_is_nonzero() -> None:
    assert calculate_cost_usd("gpt-5.4-mini", 1_000_000, 1_000_000) == 5.25


def test_unknown_model_cost_is_zero() -> None:
    assert lookup_cost("unknown-model") is None
    assert calculate_cost_usd("unknown-model", 1_000_000, 1_000_000) == 0
```

- [ ] **Step 2: Add contract fields**

In `kaji/sdk/src/runtime/providers/types.py`, change `ModelResponseChunk` to:

```python
class ModelResponseChunk(BaseModel):
    """A generic output chunk from an LLM provider."""

    delta: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Optional[TokenMetrics] = None
    cost_usd: Optional[float] = None
```

In `kaji/ts/src/providers/base.ts`, change `ModelResponseChunk` to:

```ts
export interface ModelResponseChunk {
  delta: string;
  toolCalls: ToolCall[];
  /** Token usage, if the provider reported it during streaming. */
  usage?: TokenUsage;
  /** Estimated cost in USD, if the model is in the cost table. */
  costUsd?: number;
}
```

- [ ] **Step 3: Add Python cost helper**

Create `kaji/sdk/src/runtime/providers/costs.py` with prices copied from the existing repo TS cost table, not from a fresh web lookup:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CostEntry:
    input_per_1m: float
    output_per_1m: float


COST_TABLE: dict[str, CostEntry] = {
    "gpt-5.4": CostEntry(input_per_1m=1.25, output_per_1m=10.0),
    "gpt-5.4-mini": CostEntry(input_per_1m=0.75, output_per_1m=4.5),
    "gpt-5.4-nano": CostEntry(input_per_1m=0.15, output_per_1m=0.6),
    "gpt-5.5": CostEntry(input_per_1m=2.5, output_per_1m=20.0),
}


def lookup_cost(model: str) -> Optional[CostEntry]:
    if model in COST_TABLE:
        return COST_TABLE[model]
    best_key = ""
    best: Optional[CostEntry] = None
    for key, entry in COST_TABLE.items():
        if model.startswith(key) and len(key) > len(best_key):
            best_key = key
            best = entry
    return best


def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    entry = lookup_cost(model)
    if entry is None:
        return 0
    return round(
        (input_tokens / 1_000_000) * entry.input_per_1m
        + (output_tokens / 1_000_000) * entry.output_per_1m,
        10,
    )
```

- [ ] **Step 4: Verify**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_providers_costs.py -q
uv run python scripts/typecheck_ty.py --output-format concise

cd ../ts
bun run test tests/provider-cost.test.ts
node_modules/.bin/tsc --noEmit
```

- [ ] **Step 5: Checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "feat(sdk): add streaming telemetry contract"
```

## Task 3: Populate Stream Usage And Cost In Providers And Runtime

**Files:**
- Modify: `kaji/sdk/src/runtime/providers/openai.py`
- Modify: `kaji/sdk/src/runtime/providers/anthropic.py`
- Modify: `kaji/sdk/src/runtime/agents/runtime.py`
- Modify: `kaji/sdk/tests/test_providers_openai.py`
- Modify: `kaji/sdk/tests/test_providers_anthropic.py`
- Modify: `kaji/sdk/tests/test_agents_runtime.py`
- Modify: `kaji/ts/src/providers/openai.ts`
- Modify: `kaji/ts/src/providers/anthropic.ts`
- Modify: `kaji/ts/src/runtime/runtime.ts`
- Modify: `kaji/ts/tests/openai-provider.test.ts`
- Modify: `kaji/ts/tests/anthropic-provider.test.ts`
- Modify: `kaji/ts/tests/runtime.test.ts`

**Interfaces:**
- Providers may yield a final metadata-only chunk:

```python
ModelResponseChunk(delta="", tool_calls=[], metrics=metrics, cost_usd=cost)
```

```ts
yield { delta: "", toolCalls: [], usage, costUsd };
```

- Runtime copies metadata to completed message events:

```python
AgentMessageCompleted(
    session_id=session_id,
    content=full_response,
    tokens={"input": 3, "output": 2},
    cost_usd=0.00001125,
)
```

```ts
await emit({ type: EventType.AGENT_MESSAGE_COMPLETED, content, tokens, cost_usd });
```

- [ ] **Step 1: Add runtime failing tests**

In `kaji/sdk/tests/test_agents_runtime.py`, add a provider fixture that yields one text chunk and one telemetry chunk:

```python
async def generate_stream(self, *_a, **_kw):
    yield ModelResponseChunk(delta="hello")
    yield ModelResponseChunk(
        metrics=TokenMetrics(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        cost_usd=0.00001125,
    )
```

Assert the emitted `AgentMessageCompleted` has:

```python
assert completed.tokens is not None
assert completed.tokens.input == 3
assert completed.tokens.output == 2
assert completed.cost_usd == 0.00001125
```

In `kaji/ts/tests/runtime.test.ts`, add the equivalent mock provider:

```ts
generateStream: async function* () {
  yield { delta: "hello", toolCalls: [] };
  yield { delta: "", toolCalls: [], usage: { input: 3, output: 2 }, costUsd: 0.00001125 };
}
```

Assert the completed event contains:

```ts
expect(completed.tokens).toEqual({ input: 3, output: 2 });
expect(completed.cost_usd).toBe(0.00001125);
```

- [ ] **Step 2: Implement runtime metadata propagation**

In Python runtime, initialize metadata per model iteration:

```python
stream_metrics: TokenMetrics | None = None
stream_cost_usd: float | None = None
```

Inside the chunk loop:

```python
if chunk.metrics is not None:
    stream_metrics = chunk.metrics
if chunk.cost_usd is not None:
    stream_cost_usd = chunk.cost_usd
```

When emitting `AgentMessageCompleted`, map token field names to event schema names:

```python
tokens = None
if stream_metrics is not None:
    tokens = {"input": stream_metrics.prompt_tokens, "output": stream_metrics.completion_tokens}
await self._emit(
    AgentMessageCompleted(
        session_id=session_id,
        content=full_response,
        tokens=tokens,
        cost_usd=stream_cost_usd,
    )
)
```

In TS runtime, initialize:

```ts
let usage: TokenUsage | undefined;
let costUsd: number | undefined;
```

Inside the chunk loop:

```ts
if (chunk.usage) usage = chunk.usage;
if (chunk.costUsd !== undefined) costUsd = chunk.costUsd;
```

Emit:

```ts
await emit({
  type: EventType.AGENT_MESSAGE_COMPLETED,
  content,
  ...(usage ? { tokens: usage } : {}),
  ...(costUsd !== undefined ? { cost_usd: costUsd } : {}),
});
```

- [ ] **Step 3: Implement OpenAI streaming telemetry**

In TS OpenAI streaming params, add:

```ts
stream_options: { include_usage: true },
```

When a chunk has `usage`, compute:

```ts
const usage = chunk.usage
  ? { input: chunk.usage.prompt_tokens, output: chunk.usage.completion_tokens }
  : undefined;
if (usage) {
  yield {
    delta: "",
    toolCalls: [],
    usage,
    costUsd: calculateCostUsd(this.opts.model, usage.input, usage.output),
  };
}
```

In Python OpenAI, add:

```python
kwargs["stream_options"] = {"include_usage": True}
```

For chunks without choices but with `usage`, yield:

```python
usage = getattr(chunk, "usage", None)
if usage is not None:
    metrics = TokenMetrics(
        prompt_tokens=getattr(usage, "prompt_tokens", 0),
        completion_tokens=getattr(usage, "completion_tokens", 0),
        total_tokens=getattr(usage, "total_tokens", 0),
    )
    yield ModelResponseChunk(
        metrics=metrics,
        cost_usd=calculate_cost_usd(self.model_name, metrics.prompt_tokens, metrics.completion_tokens),
    )
    continue
```

- [ ] **Step 4: Implement Anthropic streaming telemetry**

Capture Anthropic usage conservatively from stream events that expose `usage`:

```ts
let latestUsage: TokenUsage | undefined;
const rawUsage = "usage" in event ? event.usage : undefined;
if (rawUsage) {
  latestUsage = {
    input: rawUsage.input_tokens ?? latestUsage?.input ?? 0,
    output: rawUsage.output_tokens ?? latestUsage?.output ?? 0,
  };
}
if (latestUsage) {
  yield {
    delta: "",
    toolCalls: [],
    usage: latestUsage,
    costUsd: calculateCostUsd(this.opts.model, latestUsage.input, latestUsage.output),
  };
}
```

In Python Anthropic, track `latest_metrics` from event `usage` when present and yield a final metadata-only chunk. If no stream usage is present, yield no metadata chunk.

- [ ] **Step 5: Add provider tests**

Add fake OpenAI stream tests that include a final usage chunk:

```ts
async function* stream() {
  yield { choices: [{ delta: { content: "hi" } }] };
  yield { choices: [], usage: { prompt_tokens: 3, completion_tokens: 2 } };
}
```

Assert the chunks include one with:

```ts
expect(chunks.at(-1)).toMatchObject({
  delta: "",
  toolCalls: [],
  usage: { input: 3, output: 2 },
});
expect(chunks.at(-1)?.costUsd).toBeGreaterThan(0);
```

Add equivalent Python provider tests with `SimpleNamespace`.

- [ ] **Step 6: Verify**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_agents_runtime.py tests/test_providers_openai.py tests/test_providers_anthropic.py tests/test_events_schemas.py -q
uv run python scripts/typecheck_ty.py --output-format concise

cd ../ts
bun run test tests/runtime.test.ts tests/openai-provider.test.ts tests/anthropic-provider.test.ts tests/schema-parity.test.ts
node_modules/.bin/tsc --noEmit
```

- [ ] **Step 7: Checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "feat(kaji): emit streamed usage metadata"
```

## Task 4: Remove TS Provider Test Hook Declaration Leaks

**Files:**
- Modify: `kaji/ts/src/providers/openai.ts`
- Modify: `kaji/ts/src/providers/anthropic.ts`
- Create: `kaji/ts/tests/helpers/provider-clients.ts`
- Modify: `kaji/ts/tests/openai-provider.test.ts`
- Modify: `kaji/ts/tests/anthropic-provider.test.ts`
- Modify: `kaji/ts/tests/cancellation.test.ts`
- Create: `kaji/ts/tests/public-declarations.test.ts`

**Interfaces:**
- Remove `OpenAIProviderTestHooks` and `AnthropicProviderTestHooks`.
- Provider constructors return to one app-facing argument:

```ts
constructor(opts: OpenAIProviderOptions)
constructor(opts: AnthropicProviderOptions)
```

- Tests inject fake clients by subclassing protected factories:

```ts
protected override createClient(): Promise<OpenAI> | OpenAI
```

- [ ] **Step 1: Add declaration failing test**

Create `kaji/ts/tests/public-declarations.test.ts`:

```ts
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const dist = resolve(import.meta.dirname, "../dist");

describe("public declarations", () => {
  it("does not expose provider test hooks after build", () => {
    if (!existsSync(resolve(dist, "openai.d.ts"))) return;
    const openai = readFileSync(resolve(dist, "openai.d.ts"), "utf8");
    const anthropic = readFileSync(resolve(dist, "anthropic.d.ts"), "utf8");
    expect(openai).not.toContain("OpenAIProviderTestHooks");
    expect(anthropic).not.toContain("AnthropicProviderTestHooks");
  });
});
```

- [ ] **Step 2: Add protected client factories**

In `OpenAIProvider`:

```ts
constructor(opts: OpenAIProviderOptions) {
  if (!opts.apiKey?.trim()) {
    throw new ProviderConfigError("OpenAI API key is not configured.", { service: "openai" });
  }
  this.opts = {
    apiKey: opts.apiKey,
    model: opts.model ?? "gpt-5.4-mini",
    baseURL: opts.baseURL ?? "",
    temperature: opts.temperature ?? 0.7,
    maxTokens: opts.maxTokens ?? 4096,
    defaultHeaders:
      opts.defaultHeaders && Object.keys(opts.defaultHeaders).length > 0
        ? opts.defaultHeaders
        : undefined,
    retry: {
      maxAttempts: opts.retry?.maxAttempts ?? 3,
      baseDelayMs: opts.retry?.baseDelayMs ?? 1000,
    },
  };
}

protected async createClient(): Promise<OpenAI> {
  const { default: OpenAIDefault } = await import("openai");
  return new OpenAIDefault({
    apiKey: this.opts.apiKey,
    ...(this.opts.baseURL ? { baseURL: this.opts.baseURL } : {}),
    ...(this.opts.defaultHeaders ? { defaultHeaders: this.opts.defaultHeaders } : {}),
  });
}

private async getClient(): Promise<OpenAI> {
  if (this.client !== null) return this.client;
  try {
    this.client = await this.createClient();
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    throw new ProviderConfigError("OpenAI provider requires the openai package.", {
      service: "openai",
      cause: error,
    });
  }
  return this.client;
}
```

Apply the same pattern in `AnthropicProvider`.

- [ ] **Step 3: Add test helper subclasses**

Create `kaji/ts/tests/helpers/provider-clients.ts`:

```ts
import type OpenAI from "openai";
import type Anthropic from "@anthropic-ai/sdk";
import { OpenAIProvider, type OpenAIProviderOptions } from "@/providers/openai";
import { AnthropicProvider, type AnthropicProviderOptions } from "@/providers/anthropic";

export class TestOpenAIProvider extends OpenAIProvider {
  constructor(opts: OpenAIProviderOptions, private readonly fakeClient: OpenAI) {
    super(opts);
  }

  protected override async createClient(): Promise<OpenAI> {
    return this.fakeClient;
  }
}

export class TestAnthropicProvider extends AnthropicProvider {
  constructor(opts: AnthropicProviderOptions, private readonly fakeClient: Anthropic) {
    super(opts);
  }

  protected override async createClient(): Promise<Anthropic> {
    return this.fakeClient;
  }
}
```

- [ ] **Step 4: Update tests**

Replace:

```ts
new OpenAIProvider({ apiKey: "test-key" }, { client: fakeClient as OpenAI })
```

with:

```ts
new TestOpenAIProvider({ apiKey: "test-key" }, fakeClient as OpenAI)
```

Do the same for Anthropic tests and cancellation tests.

- [ ] **Step 5: Verify declarations**

Run:

```bash
cd kaji/ts
bun run test tests/openai-provider.test.ts tests/anthropic-provider.test.ts tests/cancellation.test.ts
bun run build
bun run test tests/public-declarations.test.ts
node_modules/.bin/tsc --noEmit
bun run scripts/smoke.mts
```

- [ ] **Step 6: Checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "test(ts-sdk): remove provider hook declarations"
```

## Task 5: Replace TS Private-Internal Test Casts

**Files:**
- Create: `kaji/ts/src/providers/openai-format.ts`
- Modify: `kaji/ts/src/providers/openai.ts`
- Modify: `kaji/ts/src/providers/factory.ts`
- Modify: `kaji/ts/tests/openai-provider.test.ts`
- Modify: `kaji/ts/tests/provider-factory.test.ts`
- Modify: `kaji/ts/tests/public-declarations.test.ts`
- Modify: `kaji/ts/tsconfig.json` or `kaji/ts/tsup.config.ts` if declaration stripping is required.

**Interfaces:**
- Internal OpenAI formatting helper:

```ts
/** @internal */
export function toOpenAIChatMessages(messages: ProviderMessage[]): ChatMessage[];
```

- Internal provider factory option helpers:

```ts
/** @internal */
export function resolveOpenAIOptions(arg?: ModelOrOptions<OpenAIProviderOptions>): OpenAIProviderOptions;
/** @internal */
export function resolveAnthropicOptions(arg?: ModelOrOptions<AnthropicProviderOptions>): AnthropicProviderOptions;
/** @internal */
export function resolveOpenRouterOptions(arg?: string | OpenRouterFactoryOptions): OpenAIProviderOptions;
/** @internal */
export function resolveGeminiOptions(arg?: string | GeminiFactoryOptions): OpenAIProviderOptions;
```

- [ ] **Step 1: Add failing cast scan**

Add to `kaji/ts/tests/public-declarations.test.ts` or create `kaji/ts/tests/test-hygiene.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");

describe("test hygiene", () => {
  it("provider tests do not cast into private provider internals", () => {
    const files = ["tests/openai-provider.test.ts", "tests/provider-factory.test.ts"];
    for (const file of files) {
      const source = readFileSync(resolve(root, file), "utf8");
      expect(source).not.toContain("buildMessages(m:");
      expect(source).not.toContain("{ opts:");
      expect(source).not.toContain("}).opts");
    }
  });
});
```

- [ ] **Step 2: Extract OpenAI formatting helper**

Move the existing private `buildMessages` logic into `kaji/ts/src/providers/openai-format.ts`:

```ts
import type OpenAI from "openai";
import type { ProviderMessage } from "@/providers/base";

type ChatMessage = OpenAI.Chat.Completions.ChatCompletionMessageParam;

/** @internal */
export function toOpenAIChatMessages(messages: ProviderMessage[]): ChatMessage[] {
  return messages.map<ChatMessage>((m) => {
    if (m.role === "tool") {
      return { role: "tool", content: m.content, tool_call_id: m.tool_call_id ?? "" };
    }
    if (m.role === "assistant" && m.toolCalls?.length) {
      return {
        role: "assistant",
        content: m.content,
        tool_calls: m.toolCalls.map((tc) => ({
          id: tc.id,
          type: "function" as const,
          function: { name: tc.name, arguments: JSON.stringify(tc.args ?? {}) },
        })),
      };
    }
    return { role: m.role, content: m.content };
  });
}
```

In `openai.ts`, import and use `toOpenAIChatMessages(messages)` instead of `this.buildMessages(messages)`. Delete the private `buildMessages` method.

- [ ] **Step 3: Replace provider factory casts**

In `factory.ts`, split option resolution into internal pure helpers:

```ts
/** @internal */
export function resolveOpenAIOptions(arg?: ModelOrOptions<OpenAIProviderOptions>): OpenAIProviderOptions {
  return resolveOptions<OpenAIProviderOptions>("OPENAI_API_KEY", {}, arg);
}

export function openai(arg?: ModelOrOptions<OpenAIProviderOptions>): OpenAIProvider {
  return new OpenAIProvider(resolveOpenAIOptions(arg));
}
```

Add matching helpers for Anthropic, OpenRouter, Kimi, and Gemini. Update tests to assert helper outputs rather than casting providers to private `opts`.

- [ ] **Step 4: Ensure internal helpers do not become public API**

First run build and inspect declarations:

```bash
cd kaji/ts
bun run build
rg -n "toOpenAIChatMessages|resolveOpenAIOptions|resolveOpenRouterOptions|TestHooks" dist
```

If internal helpers appear in public `.d.ts`, set declaration stripping. Preferred first attempt:

```json
{
  "compilerOptions": {
    "stripInternal": true
  }
}
```

If tsup still emits internal exports, add a declaration smoke assertion and keep the helpers under a non-exported module that tests import through source path only if TS build supports it. Do not publish `*ForTest` names.

- [ ] **Step 5: Verify**

Run:

```bash
cd kaji/ts
bun run test tests/openai-provider.test.ts tests/provider-factory.test.ts tests/public-declarations.test.ts
node_modules/.bin/tsc --noEmit
bun run build
bun run scripts/smoke.mts
```

- [ ] **Step 6: Checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "test(ts-sdk): replace private provider assertions"
```

## Task 6: Codify Non-Core Promotion Criteria

**Files:**
- Modify: `kaji/RELEASE_MATRIX.md`
- Modify: `docs/MVP.md`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `kaji/sdk/tests/test_stability_contract.py`
- Modify or create: `kaji/ts/tests/docs-contract.test.ts`

**Interfaces:**
- Stable release promise remains core agent loop parity.
- Experimental surfaces get explicit promotion criteria, not implementation work.

- [ ] **Step 1: Add docs tests**

In `kaji/sdk/tests/test_stability_contract.py`, assert:

```python
def test_release_matrix_lists_non_core_promotion_criteria() -> None:
    matrix = (ROOT / "kaji" / "RELEASE_MATRIX.md").read_text()
    required = [
        "Promotion criteria",
        "Redis realtime/history",
        "voice/TTS",
        "DocumentRAG",
        "native Gemini/Kimi",
        "tool retrieval",
        "not a beta release gate",
    ]
    for phrase in required:
        assert phrase in matrix
```

In TS docs contract tests, assert TS still states:

```ts
expect(readme).toContain("TS not ported");
expect(readme).toContain("OpenAI-compatible factories");
```

- [ ] **Step 2: Update `kaji/RELEASE_MATRIX.md`**

Add:

```markdown
## Promotion criteria

| Surface | Promotion requirement before beta claim |
| --- | --- |
| Redis realtime/history | Fake-Redis unit tests, keyed Redis integration tests, reconnect/backlog behavior tests, and documented durability limits. |
| voice/TTS | Event registry tests, configured TTS adapter smoke tests, interruption/cancellation tests, and explicit fallback behavior for unconfigured adapters. |
| DocumentRAG | Deterministic retrieval tests, fixture-based indexing tests, eval set for answer grounding, and documented storage requirements. |
| native Gemini/Kimi | Native keyed provider smoke tests, tool-call tests where supported, error mapping tests, and cost metadata tests. |
| tool retrieval | Ranking fixture tests, policy interaction tests, and runtime integration tests proving retrieved tools are callable. |
```

- [ ] **Step 3: Update README summaries**

Add one paragraph in both SDK READMEs pointing to `kaji/RELEASE_MATRIX.md`. Keep wording explicit:

```markdown
The beta promise is the core agent loop. Redis realtime/history, voice/TTS,
DocumentRAG, native Gemini/Kimi, and tool retrieval remain outside the beta
gate until the promotion criteria in `kaji/RELEASE_MATRIX.md` are met.
```

In TS README, include:

```markdown
Gemini and Kimi are OpenAI-compatible factories in TypeScript, not native
provider implementations.
```

- [ ] **Step 4: Verify**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_stability_contract.py tests/test_docs_sync.py -q

cd ../ts
bun run test tests/docs-contract.test.ts
```

- [ ] **Step 5: Checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "docs(kaji): codify non-core promotion criteria"
```

## Task 7: Full Verification And Release Gate

**Files:**
- No source edits unless verification exposes a defect. Fix defects in the task that introduced them.

- [ ] **Step 1: Run TS full local verification**

```bash
cd kaji/ts
bun run test
node_modules/.bin/tsc --noEmit
bun run build
bun run validate:registry
bun run scripts/smoke.mts
bun run test:integration
```

Expected:
- Unit tests pass.
- `tsc` passes.
- Build succeeds.
- Smoke install passes.
- No-key integration tests skip cleanly.

- [ ] **Step 2: Run Python full local verification**

```bash
cd kaji/sdk
uv run pytest -m "not integration"
uv run python scripts/typecheck_ty.py --output-format concise
uv run ruff check src tests
bash scripts/release_smoke.sh
```

Expected:
- Unit tests pass.
- `ty` passes through the shim.
- Ruff passes.
- Wheel smoke passes.

- [ ] **Step 3: Run combined no-key live gate**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
bash kaji/scripts/live-openai-tool-loop.sh
KAJI_REQUIRE_LIVE_KEYS=1 bash kaji/scripts/live-openai-tool-loop.sh
```

Expected:
- First command exits `0` with `SKIP: OPENAI_API_KEY not set`.
- Second command exits `2` with `FAIL: OPENAI_API_KEY required for live readiness`.

- [ ] **Step 4: Optional keyed live gate**

Only run when a real key is intentionally supplied:

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
OPENAI_API_KEY="$OPENAI_API_KEY" KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```

Expected:
- Python OpenAI tool-loop passes.
- TS OpenAI tool-loop passes.
- Both assert tool requested, tool completed, final assistant text, and no exhausted turn.

- [ ] **Step 5: Final checkpoint**

```bash
but diff
```

Then commit the current branch checkpoint with GitButler:

```bash
but commit codex/kaji-sdk-telemetry-contract -m "chore(kaji): close sdk telemetry release gates"
```

## Failure Modes Registry

| Codepath | Failure mode | Mitigation | Test |
| --- | --- | --- | --- |
| `docs/MVP.md` | Stale docs say manifest contract is missing | Negative docs assertions for stale phrases | Python docs sync + TS docs contract |
| Provider stream chunks | Usage exists in provider SDK but is dropped | Add optional usage/cost fields to stream chunk types | Provider streaming tests |
| Runtime completed events | Schemas accept tokens/cost but runtime emits content only | Capture latest stream metadata and attach to completed events | Python and TS runtime tests |
| Tool-only turns | Metadata chunk causes phantom assistant message | Emit telemetry only when current content is non-empty | Runtime tool-loop regression tests |
| TS declarations | Test hooks leak into `dist/*.d.ts` | Protected client factories and declaration assertions | Build + public declaration test |
| TS tests | Tests read private `opts` or `buildMessages` | Internal pure helpers or behavior assertions | Test hygiene scan |
| Cost metadata | Unknown model silently appears priced | Unknown model returns `0`; known default has direct nonzero test | Cost tests |
| Non-core surfaces | Docs imply beta support for experimental Python-only features | Promotion criteria and stability contract tests | Release matrix tests |

## NOT In Scope

- Production-hardening Redis realtime/history, voice/TTS, DocumentRAG, native Gemini/Kimi, or tool retrieval.
- Rewriting providers or changing the runtime architecture.
- Changing Python package layout or removing the `ty` shim.
- Publishing to PyPI/npm or adding CI workflows.
- New third-party production integrations.
- Web lookup or repricing of model costs. This plan mirrors model cost metadata already present in the repo.

## What Already Exists

- Shared event schemas already accept `tokens` and `cost_usd`.
- Shared fixtures already prove schema parse parity for usage/cost events.
- TS replay already aggregates usage/cost when events contain those fields.
- Python and TS live OpenAI tool-loop tests already prove tool use when keyed.
- Shared integration manifest schemas already exist and are tested for parity.
- Release matrix already marks non-core Python surfaces experimental.

## Worktree Strategy

Use one GitButler branch: `codex/kaji-sdk-telemetry-contract`.

Implementation order is sequential:

1. Docs manifest truthfulness.
2. Cross-SDK stream telemetry types and cost helper.
3. Provider/runtime telemetry propagation.
4. TS provider test seam cleanup.
5. TS private-test cast cleanup.
6. Non-core promotion criteria.
7. Full verification.

Do not parallelize Tasks 2 and 3 because they share provider/runtime contracts. Do not parallelize Tasks 4 and 5 because they share TS provider tests and declaration output.

## Acceptance Criteria

- `docs/MVP.md` no longer says the shared manifest contract is missing or open.
- Streamed Python and TS runtime paths populate `tokens` and `cost_usd` on completed assistant messages when providers report usage.
- OpenAI streaming requests include usage reporting where supported.
- Anthropic streaming captures usage when stream events expose it and otherwise preserves current behavior.
- `OpenAIProviderTestHooks` and `AnthropicProviderTestHooks` are removed from source exports and built declarations.
- TS provider tests no longer cast into private `buildMessages` or `opts`.
- Non-core Python-only surfaces remain explicitly experimental with promotion criteria.
- Full Python and TS unit/static/build/smoke checks pass.
- No-key live readiness still skips cleanly; require-key mode still fails loudly without a key.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Plan Tune | `/plan-tune` | User preference and question sensitivity | 1 | APPLIED | Prefer complete edge coverage with low question overhead; no unresolved scope questions. |
| CEO Review | `/plan-ceo-review` | Scope and product trust | 1 | HOLD SCOPE | Do not expand into non-core hardening; focus on truthful proof and release gates. |
| Eng Review | `/plan-eng-review` | Architecture, contracts, tests | 1 | APPLIED | Add metadata at provider/runtime seams, remove public test hooks, add declaration and docs regression tests. |
| Design Review | N/A | No UI scope | 0 | SKIPPED | Backend/SDK docs and tests only. |
| DX Review | N/A | No new setup flow | 0 | SKIPPED | Existing first-run/live gates remain in scope through verification only. |

NO UNRESOLVED DECISIONS
