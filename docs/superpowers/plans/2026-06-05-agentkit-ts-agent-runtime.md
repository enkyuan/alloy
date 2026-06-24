# Kaji TS Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the Python `AgentRuntime` ReAct loop to TypeScript, giving `@kaji/sdk` a full tool-using agent that runs with no external services, validated by a sample app in `demos/`.

**Architecture:** Settle the `publish` sync/async question first (it stays sync — no change needed), then build the provider layer (interface + mock + OpenAI), then the agent runtime (`runTurn`: replay → call provider → emit events → execute tools → loop), then wire the tool registry into the loop. A minimal demo script in `demos/ts-agent/` validates the full loop end-to-end.

**Tech Stack:** TypeScript, Bun, Vitest, Zod 4, `openai` npm package (for the real provider). All files under `packages/ts/`.

---

## File Map

| file | status | responsibility |
|------|--------|---------------|
| `packages/ts/src/events/bus.ts` | modify | add doc comment clarifying sync `publish` is intentional |
| `packages/ts/src/providers/base.ts` | create | `ModelProvider` interface, `ModelResponseChunk`, `ToolCall` types |
| `packages/ts/src/providers/mock.ts` | create | mock provider: requests first tool, then responds with text |
| `packages/ts/src/providers/openai.ts` | create | OpenAI provider: streaming + tool calls via `openai` npm package |
| `packages/ts/src/providers/registry.ts` | create | provider registry: `registerProvider`, `getProvider` |
| `packages/ts/src/providers/index.ts` | create | re-exports for the provider layer |
| `packages/ts/src/runtime/cancellation.ts` | create | `CancellationToken` class |
| `packages/ts/src/runtime/context.ts` | create | `buildMessages` — converts `SessionState.messages` to provider message format |
| `packages/ts/src/runtime/runtime.ts` | create | `AgentRuntime.runTurn`: the ReAct loop |
| `packages/ts/src/index.ts` | modify | export new provider + runtime surface |
| `packages/ts/tests/providers.mock.test.ts` | create | mock provider unit tests |
| `packages/ts/tests/providers.openai.test.ts` | create | OpenAI provider unit tests (mocked fetch) |
| `packages/ts/tests/runtime.test.ts` | create | full `runTurn` loop tests with mock provider |
| `demos/ts-agent/index.ts` | create | sample app: registers a tool, runs one turn, prints events |
| `demos/ts-agent/package.json` | create | minimal package for the demo |

---

## Task 1: Settle `publish` sync/async — document the decision

**Files:**
- Modify: `packages/ts/src/events/bus.ts:69`

The Python `AgentRuntime` does `await bus.publish(event)` but the Python `EventBus.publish` is a plain synchronous method — the `await` is a no-op. The TS bus's `publish` is also synchronous, and the internal `Subscription.push` bridges to async iterators without needing the caller to await. Keeping it sync is correct and avoids an unnecessary async boundary. This task locks in that decision with a comment so future contributors don't change it by accident.

- [ ] **Step 1: Add the clarifying comment to `publish`**

Edit `packages/ts/src/events/bus.ts`. Replace:

```ts
  /** Publish an event to every subscriber of its session. */
  publish(event: KajiEvent): void {
```

with:

```ts
  /**
   * Publish an event to every subscriber of its session.
   *
   * Intentionally synchronous: `Subscription.push` bridges sync delivery to
   * async iterators internally. The Python runtime calls `await bus.publish`
   * but the Python implementation is also synchronous — the await is a no-op
   * there too. Keeping this sync avoids an unnecessary async boundary and
   * makes the TS runtime port straightforward.
   */
  publish(event: KajiEvent): void {
```

- [ ] **Step 2: Run existing tests to confirm nothing changed**

```bash
cd packages/ts && bun run test
```

Expected: all 26 tests pass, no failures.

- [ ] **Step 3: Commit**

```bash
git add packages/ts/src/events/bus.ts
git commit -m "docs(ts): document publish sync/async decision in EventBus"
```

---

## Task 2: Provider interface and types

**Files:**
- Create: `packages/ts/src/providers/base.ts`
- Create: `packages/ts/src/providers/index.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/ts/tests/providers.mock.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { ModelProvider, ModelResponseChunk } from "../src/providers/base";

describe("ModelProvider interface", () => {
  it("accepts an object that satisfies the interface", () => {
    const provider: ModelProvider = {
      generate: async (_messages, _tools) => ({
        content: "hello",
        toolCalls: [],
      }),
      generateStream: async function* (_messages, _tools) {
        yield { delta: "hello", toolCalls: [] } satisfies ModelResponseChunk;
      },
    };
    expect(provider).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: FAIL — `Cannot find module '../src/providers/base'`

- [ ] **Step 3: Create `packages/ts/src/providers/base.ts`**

```ts
/**
 * Provider interface for LLM backends, mirroring
 * `kaji.runtime.providers.base.ModelProvider`.
 *
 * Each provider translates the neutral message + tool format to its own
 * API at its boundary. The runtime never imports provider-specific types.
 */
import type { ToolSpec } from "../tools/registry";

/** A single message in the conversation history passed to the provider. */
export interface ProviderMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool-result messages. */
  name?: string;
  /** Set only for tool-result messages: the id from the tool call request. */
  tool_call_id?: string;
}

/** A tool call the model wants to make. */
export interface ToolCall {
  /** Unique ID for this call, used to match results back to requests. */
  id: string;
  name: string;
  args: Record<string, unknown>;
}

/** A streaming chunk from the provider. */
export interface ModelResponseChunk {
  /** Text delta, may be empty string during tool-call chunks. */
  delta: string;
  /** Tool calls requested in this chunk (usually present in the final chunk). */
  toolCalls: ToolCall[];
}

/** A complete non-streaming response from the provider. */
export interface ModelResponse {
  content: string;
  toolCalls: ToolCall[];
}

/**
 * Common interface every LLM provider must implement.
 * The runtime calls `generateStream` for normal turns; `generate` is used
 * in tests and when a provider does not support streaming.
 */
export interface ModelProvider {
  generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): Promise<ModelResponse>;
  generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk>;
}
```

- [ ] **Step 4: Create `packages/ts/src/providers/index.ts`**

```ts
export type {
  ProviderMessage,
  ToolCall,
  ModelResponseChunk,
  ModelResponse,
  ModelProvider,
} from "./base";
export { MockProvider } from "./mock";
export { OpenAIProvider } from "./openai";
export { registerProvider, getProvider } from "./registry";
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add packages/ts/src/providers/base.ts packages/ts/src/providers/index.ts packages/ts/tests/providers.mock.test.ts
git commit -m "feat(ts): add ModelProvider interface and types"
```

---

## Task 3: Provider registry

**Files:**
- Create: `packages/ts/src/providers/registry.ts`

- [ ] **Step 1: Write the failing test**

Add to `packages/ts/tests/providers.mock.test.ts` (append below the existing test):

```ts
import { registerProvider, getProvider } from "../src/providers/registry";
import { afterEach } from "vitest";

afterEach(() => {
  // clear registry between tests via the exported clearProviders helper
  clearProviders();
});

describe("provider registry", () => {
  it("registers and retrieves a provider by name", () => {
    const provider: ModelProvider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* () {},
    };
    registerProvider("test", provider);
    expect(getProvider("test")).toBe(provider);
  });

  it("throws on duplicate registration", () => {
    const provider: ModelProvider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* () {},
    };
    registerProvider("dup", provider);
    expect(() => registerProvider("dup", provider)).toThrow(/already registered/);
  });

  it("throws on unknown provider", () => {
    expect(() => getProvider("nope")).toThrow(/Unknown provider/);
  });
});
```

Also add `clearProviders` to the import line from `../src/providers/registry`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: FAIL — `Cannot find module '../src/providers/registry'`

- [ ] **Step 3: Create `packages/ts/src/providers/registry.ts`**

```ts
/**
 * Provider registry: a process-level map from name to `ModelProvider`.
 * Mirrors `kaji.runtime.providers.registry`.
 */
import type { ModelProvider } from "./base";

const providers = new Map<string, ModelProvider>();

/** Register a provider under a name. Throws on duplicate. */
export function registerProvider(name: string, provider: ModelProvider): void {
  if (providers.has(name)) {
    throw new Error(`Provider already registered: ${name}`);
  }
  providers.set(name, provider);
}

/** Retrieve a registered provider. Throws if not found. */
export function getProvider(name: string): ModelProvider {
  const p = providers.get(name);
  if (p === undefined) {
    throw new Error(`Unknown provider: ${name}. Register it with registerProvider() first.`);
  }
  return p;
}

/** Clear all registrations. For tests only. */
export function clearProviders(): void {
  providers.clear();
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/ts/src/providers/registry.ts packages/ts/tests/providers.mock.test.ts
git commit -m "feat(ts): add provider registry"
```

---

## Task 4: Mock provider

**Files:**
- Create: `packages/ts/src/providers/mock.ts`

The mock provider mirrors `kaji.runtime.providers.mock`: on the first call it requests the first available tool; after a tool result is in history it replies with a fixed text response. This drives the full tool loop without a network call.

- [ ] **Step 1: Write the failing test**

Add to `packages/ts/tests/providers.mock.test.ts`:

```ts
import { MockProvider } from "../src/providers/mock";
import type { ProviderMessage } from "../src/providers/base";
import { toolSpecFromSchema } from "../src/tools/registry";
import { z } from "zod";

describe("MockProvider", () => {
  const weatherSpec = toolSpecFromSchema(
    "get_weather",
    "Look up weather",
    z.object({ city: z.string() }),
  );

  it("requests the first tool when no tool result is in history", async () => {
    const provider = new MockProvider();
    const messages: ProviderMessage[] = [
      { role: "user", content: "what is the weather?" },
    ];
    const result = await provider.generate(messages, [weatherSpec]);
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]?.name).toBe("get_weather");
    expect(result.content).toBe("");
  });

  it("returns a text response once a tool result is in history", async () => {
    const provider = new MockProvider();
    const messages: ProviderMessage[] = [
      { role: "user", content: "what is the weather?" },
      { role: "assistant", content: "" },
      { role: "tool", name: "get_weather", content: '{"tempF":68}', tool_call_id: "c1" },
    ];
    const result = await provider.generate(messages, [weatherSpec]);
    expect(result.toolCalls).toHaveLength(0);
    expect(result.content).toBe("The mock provider has completed the tool loop.");
  });

  it("returns text immediately when no tools are registered", async () => {
    const provider = new MockProvider();
    const messages: ProviderMessage[] = [
      { role: "user", content: "hello" },
    ];
    const result = await provider.generate(messages, []);
    expect(result.toolCalls).toHaveLength(0);
    expect(result.content).toBe("The mock provider has completed the tool loop.");
  });

  it("generateStream yields the same result as generate", async () => {
    const provider = new MockProvider();
    const messages: ProviderMessage[] = [
      { role: "user", content: "hello" },
    ];
    const chunks: import("../src/providers/base").ModelResponseChunk[] = [];
    for await (const chunk of provider.generateStream(messages, [])) {
      chunks.push(chunk);
    }
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.delta).toBe("The mock provider has completed the tool loop.");
    expect(chunks[0]?.toolCalls).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: FAIL — `Cannot find module '../src/providers/mock'`

- [ ] **Step 3: Create `packages/ts/src/providers/mock.ts`**

```ts
/**
 * Mock LLM provider for tests, mirroring `kaji.runtime.providers.mock`.
 *
 * Behaviour:
 * - If tools are available and no tool result is yet in history: call the
 *   first tool with empty args and a fixed call id.
 * - Otherwise: return a fixed text response.
 *
 * This drives the full tool loop without a network call.
 */
import type { ModelProvider, ModelResponse, ModelResponseChunk, ProviderMessage } from "./base";
import type { ToolSpec } from "../tools/registry";

const FINAL_TEXT = "The mock provider has completed the tool loop.";

function hasToolResult(messages: ProviderMessage[]): boolean {
  return messages.some((m) => m.role === "tool");
}

export class MockProvider implements ModelProvider {
  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): Promise<ModelResponse> {
    if (tools.length > 0 && !hasToolResult(messages)) {
      const tool = tools[0]!;
      return {
        content: "",
        toolCalls: [{ id: "mock-call-1", name: tool.name, args: {} }],
      };
    }
    return { content: FINAL_TEXT, toolCalls: [] };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk> {
    const result = await this.generate(messages, tools);
    yield { delta: result.content, toolCalls: result.toolCalls };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/ts && bun run test tests/providers.mock.test.ts
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add packages/ts/src/providers/mock.ts packages/ts/tests/providers.mock.test.ts
git commit -m "feat(ts): add MockProvider"
```

---

## Task 5: OpenAI provider

**Files:**
- Create: `packages/ts/src/providers/openai.ts`
- Create: `packages/ts/tests/providers.openai.test.ts`

- [ ] **Step 1: Install the OpenAI package**

```bash
cd packages/ts && bun add openai
```

Expected: `openai` added to `dependencies` in `package.json`.

- [ ] **Step 2: Write the failing test**

Create `packages/ts/tests/providers.openai.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { OpenAIProvider } from "../src/providers/openai";
import { toolSpecFromSchema } from "../src/tools/registry";
import { z } from "zod";

// We test without a real API key by injecting a fake client.
describe("OpenAIProvider", () => {
  const weatherSpec = toolSpecFromSchema(
    "get_weather",
    "Get weather",
    z.object({ city: z.string() }),
  );

  it("throws a clear error when no API key is configured", () => {
    expect(() => new OpenAIProvider({ apiKey: "" })).toThrow(/OPENAI_API_KEY/);
  });

  it("translates tool specs to OpenAI format", () => {
    const provider = new OpenAIProvider({ apiKey: "sk-test" });
    const openAiTools = provider.toOpenAITools([weatherSpec]);
    expect(openAiTools).toEqual([
      {
        type: "function",
        function: {
          name: "get_weather",
          description: "Get weather",
          parameters: {
            type: "object",
            properties: { city: { type: "string" } },
            required: ["city"],
          },
        },
      },
    ]);
  });

  it("parses a text response from a mocked generate call", async () => {
    const provider = new OpenAIProvider({ apiKey: "sk-test" });

    // Inject a fake client that returns a text completion
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [
              {
                message: {
                  content: "sunny",
                  tool_calls: null,
                },
              },
            ],
          }),
        },
      },
    };
    // @ts-expect-error injecting a fake for testing
    provider._client = fakeClient;

    const result = await provider.generate(
      [{ role: "user", content: "weather?" }],
      [],
    );
    expect(result.content).toBe("sunny");
    expect(result.toolCalls).toHaveLength(0);
  });

  it("parses tool calls from a mocked generate call", async () => {
    const provider = new OpenAIProvider({ apiKey: "sk-test" });

    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [
              {
                message: {
                  content: null,
                  tool_calls: [
                    {
                      id: "call_abc",
                      type: "function",
                      function: {
                        name: "get_weather",
                        arguments: '{"city":"Seattle"}',
                      },
                    },
                  ],
                },
              },
            ],
          }),
        },
      },
    };
    // @ts-expect-error injecting a fake for testing
    provider._client = fakeClient;

    const result = await provider.generate(
      [{ role: "user", content: "weather in Seattle?" }],
      [weatherSpec],
    );
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]).toEqual({
      id: "call_abc",
      name: "get_weather",
      args: { city: "Seattle" },
    });
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/providers.openai.test.ts
```

Expected: FAIL — `Cannot find module '../src/providers/openai'`

- [ ] **Step 4: Create `packages/ts/src/providers/openai.ts`**

```ts
/**
 * OpenAI LLM provider, mirroring `kaji.runtime.providers.openai`.
 * Translates the neutral message/tool format to OpenAI's chat completions API.
 */
import OpenAI from "openai";
import type { ModelProvider, ModelResponse, ModelResponseChunk, ProviderMessage, ToolCall } from "./base";
import type { ToolSpec } from "../tools/registry";

export interface OpenAIProviderOptions {
  apiKey: string;
  model?: string;
  baseURL?: string;
}

export class OpenAIProvider implements ModelProvider {
  /** Exposed for test injection only — do not use in production code. */
  _client: OpenAI;
  private readonly model: string;

  constructor(options: OpenAIProviderOptions) {
    if (!options.apiKey) {
      throw new Error(
        "OpenAI provider requires an API key. Set OPENAI_API_KEY or pass apiKey.",
      );
    }
    this._client = new OpenAI({
      apiKey: options.apiKey,
      ...(options.baseURL ? { baseURL: options.baseURL } : {}),
    });
    this.model = options.model ?? "gpt-4o";
  }

  /** Translate neutral ToolSpec[] to the OpenAI tools array format. */
  toOpenAITools(tools: ToolSpec[]): OpenAI.Chat.ChatCompletionTool[] {
    return tools.map((t) => ({
      type: "function" as const,
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));
  }

  private toOpenAIMessages(
    messages: ProviderMessage[],
  ): OpenAI.Chat.ChatCompletionMessageParam[] {
    return messages.map((m) => {
      if (m.role === "tool") {
        return {
          role: "tool" as const,
          content: m.content,
          tool_call_id: m.tool_call_id ?? "",
        };
      }
      return { role: m.role, content: m.content } as OpenAI.Chat.ChatCompletionMessageParam;
    });
  }

  private parseToolCalls(
    raw: OpenAI.Chat.ChatCompletionMessageToolCall[] | null | undefined,
  ): ToolCall[] {
    if (!raw || raw.length === 0) return [];
    return raw.map((tc) => ({
      id: tc.id,
      name: tc.function.name,
      args: JSON.parse(tc.function.arguments) as Record<string, unknown>,
    }));
  }

  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): Promise<ModelResponse> {
    const openAiTools = this.toOpenAITools(tools);
    const response = await this._client.chat.completions.create({
      model: this.model,
      messages: this.toOpenAIMessages(messages),
      ...(openAiTools.length > 0 ? { tools: openAiTools } : {}),
      stream: false,
    });

    const message = response.choices[0]?.message;
    return {
      content: message?.content ?? "",
      toolCalls: this.parseToolCalls(message?.tool_calls),
    };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk> {
    const openAiTools = this.toOpenAITools(tools);
    const stream = await this._client.chat.completions.create({
      model: this.model,
      messages: this.toOpenAIMessages(messages),
      ...(openAiTools.length > 0 ? { tools: openAiTools } : {}),
      stream: true,
    });

    let accumulatedToolCalls: OpenAI.Chat.ChatCompletionMessageToolCall[] = [];

    for await (const chunk of stream) {
      const delta = chunk.choices[0]?.delta;
      if (!delta) continue;

      // Accumulate tool call fragments across chunks
      if (delta.tool_calls) {
        for (const tc of delta.tool_calls) {
          const idx = tc.index;
          if (!accumulatedToolCalls[idx]) {
            accumulatedToolCalls[idx] = {
              id: tc.id ?? "",
              type: "function",
              function: { name: tc.function?.name ?? "", arguments: "" },
            };
          }
          accumulatedToolCalls[idx]!.function.arguments +=
            tc.function?.arguments ?? "";
        }
      }

      yield {
        delta: delta.content ?? "",
        toolCalls: [],  // emit tool calls only in the final chunk below
      };
    }

    // Emit accumulated tool calls as the final chunk
    if (accumulatedToolCalls.length > 0) {
      yield {
        delta: "",
        toolCalls: this.parseToolCalls(accumulatedToolCalls),
      };
    }
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd packages/ts && bun run test tests/providers.openai.test.ts
```

Expected: all 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ts/src/providers/openai.ts packages/ts/tests/providers.openai.test.ts packages/ts/package.json packages/ts/bun.lock
git commit -m "feat(ts): add OpenAIProvider"
```

---

## Task 6: CancellationToken and message context builder

**Files:**
- Create: `packages/ts/src/runtime/cancellation.ts`
- Create: `packages/ts/src/runtime/context.ts`

- [ ] **Step 1: Write the failing tests**

Create `packages/ts/tests/runtime.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { CancellationToken } from "../src/runtime/cancellation";
import { buildMessages } from "../src/runtime/context";
import type { Message } from "../src/sessions/replay";

describe("CancellationToken", () => {
  it("starts not cancelled", () => {
    const token = new CancellationToken();
    expect(token.isCancelled).toBe(false);
  });

  it("becomes cancelled after cancel() is called", () => {
    const token = new CancellationToken();
    token.cancel();
    expect(token.isCancelled).toBe(true);
  });

  it("throws if checked with throwIfCancelled after cancellation", () => {
    const token = new CancellationToken();
    token.cancel();
    expect(() => token.throwIfCancelled()).toThrow(/cancelled/);
  });
});

describe("buildMessages", () => {
  it("prepends a system message when a system prompt is provided", () => {
    const messages: Message[] = [{ role: "user", content: "hello" }];
    const result = buildMessages(messages, "You are a helpful assistant.");
    expect(result[0]).toEqual({ role: "system", content: "You are a helpful assistant." });
    expect(result[1]).toEqual({ role: "user", content: "hello" });
  });

  it("omits the system message when no prompt is provided", () => {
    const messages: Message[] = [{ role: "user", content: "hello" }];
    const result = buildMessages(messages);
    expect(result).toHaveLength(1);
    expect(result[0]?.role).toBe("user");
  });

  it("maps tool messages with name and tool_call_id", () => {
    const messages: Message[] = [
      { role: "tool", content: '{"tempF":68}', name: "get_weather" },
    ];
    const result = buildMessages(messages);
    expect(result[0]).toEqual({
      role: "tool",
      content: '{"tempF":68}',
      name: "get_weather",
      tool_call_id: "get_weather",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/runtime.test.ts
```

Expected: FAIL — `Cannot find module '../src/runtime/cancellation'`

- [ ] **Step 3: Create `packages/ts/src/runtime/cancellation.ts`**

```ts
/**
 * Cancellation token for the agent runtime loop, mirroring
 * `kaji.runtime.agents.runtime.CancellationToken`.
 */
export class CancellationToken {
  private _cancelled = false;

  get isCancelled(): boolean {
    return this._cancelled;
  }

  cancel(): void {
    this._cancelled = true;
  }

  throwIfCancelled(): void {
    if (this._cancelled) {
      throw new Error("Agent run was cancelled");
    }
  }
}
```

- [ ] **Step 4: Create `packages/ts/src/runtime/context.ts`**

```ts
/**
 * Builds the provider message list from replayed session state.
 * Mirrors `kaji.runtime.agents.runtime` message construction.
 */
import type { Message } from "../sessions/replay";
import type { ProviderMessage } from "../providers/base";

/**
 * Convert replayed session messages to provider format, optionally prepending
 * a system prompt. Tool messages get a `tool_call_id` derived from their name
 * (the mock and real providers both use this to match results to requests).
 */
export function buildMessages(
  messages: Message[],
  systemPrompt?: string,
): ProviderMessage[] {
  const result: ProviderMessage[] = [];

  if (systemPrompt) {
    result.push({ role: "system", content: systemPrompt });
  }

  for (const m of messages) {
    if (m.role === "tool") {
      result.push({
        role: "tool",
        content: m.content,
        name: m.name,
        tool_call_id: m.name ?? "unknown",
      });
    } else {
      result.push({ role: m.role, content: m.content });
    }
  }

  return result;
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd packages/ts && bun run test tests/runtime.test.ts
```

Expected: CancellationToken (3) and buildMessages (3) tests all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ts/src/runtime/cancellation.ts packages/ts/src/runtime/context.ts packages/ts/tests/runtime.test.ts
git commit -m "feat(ts): add CancellationToken and buildMessages"
```

---

## Task 7: AgentRuntime — the ReAct loop

**Files:**
- Create: `packages/ts/src/runtime/runtime.ts`

This is the core: `runTurn` replays session state, builds messages, streams from the provider, emits events, executes tool calls concurrently, and loops until the model returns no tool calls.

- [ ] **Step 1: Write the failing tests**

Append to `packages/ts/tests/runtime.test.ts`:

```ts
import { AgentRuntime } from "../src/runtime/runtime";
import { MockProvider } from "../src/providers/mock";
import { InMemoryEventStore } from "../src/events/store";
import { EventBus } from "../src/events/bus";
import { KajiEvent, EventType } from "../src/index";
import { clearTools, registerTool, toolSpecFromSchema } from "../src/tools/registry";
import { afterEach } from "vitest";
import { z } from "zod";

afterEach(() => {
  clearTools();
});

describe("AgentRuntime.runTurn", () => {
  function setup() {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const provider = new MockProvider();
    const runtime = new AgentRuntime({ provider, store, bus });
    return { store, bus, provider, runtime };
  }

  async function seedSession(store: InMemoryEventStore, sessionId: string) {
    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }),
    );
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: sessionId, content: "hello" }),
    );
  }

  it("emits AgentMessageCompleted when no tools are registered", async () => {
    const { store, bus, runtime } = setup();
    const sessionId = "s-no-tools";
    await seedSession(store, sessionId);

    const emitted: KajiEvent[] = [];
    const sub = bus.subscribe(sessionId);
    const collectPromise = (async () => {
      for await (const event of sub) {
        emitted.push(event);
        if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
      }
    })();

    await runtime.runTurn(sessionId);
    await collectPromise;

    expect(emitted.some((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)).toBe(true);
  });

  it("emits ToolCallRequested, ToolCallCompleted, then AgentMessageCompleted for one tool call", async () => {
    const { store, bus, runtime } = setup();
    const sessionId = "s-with-tool";
    await seedSession(store, sessionId);

    registerTool(
      toolSpecFromSchema("get_weather", "Get weather", z.object({ city: z.string() })),
      async (_ctx, _args) => ({ tempF: 68 }),
    );

    const emitted: KajiEvent[] = [];
    const sub = bus.subscribe(sessionId);
    const collectPromise = (async () => {
      for await (const event of sub) {
        emitted.push(event);
        if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
      }
    })();

    await runtime.runTurn(sessionId);
    await collectPromise;

    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_CALL_REQUESTED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(types).toContain(EventType.AGENT_MESSAGE_COMPLETED);
    // ToolCallRequested must come before ToolCallCompleted
    expect(types.indexOf(EventType.TOOL_CALL_REQUESTED)).toBeLessThan(
      types.indexOf(EventType.TOOL_CALL_COMPLETED),
    );
  });

  it("emits ToolCallFailed when a tool throws", async () => {
    const { store, bus, runtime } = setup();
    const sessionId = "s-tool-fail";
    await seedSession(store, sessionId);

    registerTool(
      toolSpecFromSchema("bad_tool", "Always fails", z.object({})),
      async () => { throw new Error("tool error"); },
    );

    const emitted: KajiEvent[] = [];
    const sub = bus.subscribe(sessionId);
    const collectPromise = (async () => {
      for await (const event of sub) {
        emitted.push(event);
        if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
      }
    })();

    await runtime.runTurn(sessionId);
    await collectPromise;

    expect(emitted.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });

  it("respects cancellation before the loop starts", async () => {
    const { store, bus, runtime } = setup();
    const sessionId = "s-cancel";
    await seedSession(store, sessionId);

    const token = new CancellationToken();
    token.cancel();

    await expect(runtime.runTurn(sessionId, { cancellationToken: token })).rejects.toThrow(/cancelled/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/ts && bun run test tests/runtime.test.ts
```

Expected: FAIL — `Cannot find module '../src/runtime/runtime'`

- [ ] **Step 3: Create `packages/ts/src/runtime/runtime.ts`**

```ts
/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `kaji.runtime.agents.runtime.AgentRuntime`.
 *
 * Each `runTurn` call:
 * 1. Replays session state from the event store
 * 2. Builds messages for the provider
 * 3. Streams from the provider
 * 4. Emits events: AgentReasoningStarted, AgentMessageDelta, tool events
 * 5. Executes tool calls concurrently (scatter-gather)
 * 6. Loops until the provider returns no tool calls
 * 7. Emits AgentMessageCompleted with the final text
 */
import { KajiEvent, EventType } from "../events/schemas";
import type { EventStore } from "../events/store";
import { EventBus } from "../events/bus";
import { replaySession } from "../sessions/replay";
import { listToolSpecs, executeTool } from "../tools/registry";
import { buildMessages } from "./context";
import { CancellationToken } from "./cancellation";
import type { ModelProvider, ToolCall } from "../providers/base";

const MAX_TOOL_ITERATIONS = 10;

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  bus: EventBus;
  systemPrompt?: string;
}

export interface RunTurnOptions {
  cancellationToken?: CancellationToken;
}

export class AgentRuntime {
  private readonly provider: ModelProvider;
  private readonly store: EventStore;
  private readonly bus: EventBus;
  private readonly systemPrompt?: string;

  constructor(options: AgentRuntimeOptions) {
    this.provider = options.provider;
    this.store = options.store;
    this.bus = options.bus;
    this.systemPrompt = options.systemPrompt;
  }

  async runTurn(
    sessionId: string,
    options: RunTurnOptions = {},
  ): Promise<void> {
    const token = options.cancellationToken ?? new CancellationToken();
    token.throwIfCancelled();

    const emit = async (input: Parameters<typeof KajiEvent.parse>[0]) => {
      const event = KajiEvent.parse({ ...input, session_id: sessionId });
      await this.store.append(event);
      this.bus.publish(event);
    };

    await emit({ type: EventType.AGENT_REASONING_STARTED });

    const tools = listToolSpecs();
    let iterations = 0;
    let finalContent = "";

    while (iterations < MAX_TOOL_ITERATIONS) {
      token.throwIfCancelled();
      iterations++;

      const events = await this.store.getEvents(sessionId);
      const state = replaySession(events);
      const messages = buildMessages(state.messages, this.systemPrompt);

      let accumulatedContent = "";
      const accumulatedToolCalls: ToolCall[] = [];

      for await (const chunk of this.provider.generateStream(messages, tools)) {
        token.throwIfCancelled();

        if (chunk.delta) {
          accumulatedContent += chunk.delta;
          await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta: chunk.delta });
        }

        for (const tc of chunk.toolCalls) {
          accumulatedToolCalls.push(tc);
        }
      }

      if (accumulatedToolCalls.length === 0) {
        // No tool calls — this is the final response
        finalContent = accumulatedContent;
        break;
      }

      // Emit all tool call requested events
      for (const tc of accumulatedToolCalls) {
        await emit({
          type: EventType.TOOL_CALL_REQUESTED,
          tool_name: tc.name,
          tool_args: tc.args,
          tool_call_id: tc.id,
        });
      }

      // Execute tool calls concurrently (scatter-gather)
      await Promise.all(
        accumulatedToolCalls.map(async (tc) => {
          await emit({
            type: EventType.TOOL_CALL_STARTED,
            tool_name: tc.name,
            tool_call_id: tc.id,
          });
          try {
            const result = await executeTool("runtime", tc.name, tc.args);
            await emit({
              type: EventType.TOOL_CALL_COMPLETED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              result,
            });
          } catch (err) {
            await emit({
              type: EventType.TOOL_CALL_FAILED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              error: err instanceof Error ? err.message : String(err),
            });
          }
        }),
      );
      // Loop: next iteration replays updated state including tool results
    }

    await emit({ type: EventType.AGENT_MESSAGE_COMPLETED, content: finalContent });
  }
}
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
cd packages/ts && bun run test
```

Expected: all tests pass (26 existing + new runtime tests).

- [ ] **Step 5: Commit**

```bash
git add packages/ts/src/runtime/runtime.ts packages/ts/tests/runtime.test.ts
git commit -m "feat(ts): add AgentRuntime ReAct loop"
```

---

## Task 8: Export runtime surface from `index.ts`

**Files:**
- Modify: `packages/ts/src/index.ts`

- [ ] **Step 1: Update `packages/ts/src/index.ts`**

Replace the existing content with:

```ts
/**
 * Kaji: build agents in TypeScript.
 *
 * Infra-free core, mirroring the Python `kaji` SDK's public surface:
 * event-sourced building blocks (events, bus, store, replay), tool registry,
 * provider layer, and agent runtime. Nothing here requires a database, server,
 * or any environment configured.
 */

export const VERSION = "0.1.0";

// Events
export { EventType } from "./events/types";
export {
  KajiEvent,
  type KajiEventInput,
  type BaseEvent,
} from "./events/schemas";
export { EventBus } from "./events/bus";
export {
  type EventStore,
  InMemoryEventStore,
} from "./events/store";

// Sessions
export {
  replaySession,
  ReplaySession,
  type SessionState,
  type Message,
} from "./sessions/replay";

// Tools
export {
  type ToolSpec,
  type ToolContext,
  type ToolHandler,
  type JSONSchema,
  registerTool,
  listToolSpecs,
  toolSpecFromSchema,
  executeTool,
  clearTools,
} from "./tools/registry";

// Providers
export type {
  ProviderMessage,
  ToolCall,
  ModelResponseChunk,
  ModelResponse,
  ModelProvider,
} from "./providers/base";
export { MockProvider } from "./providers/mock";
export { OpenAIProvider, type OpenAIProviderOptions } from "./providers/openai";
export { registerProvider, getProvider, clearProviders } from "./providers/registry";

// Runtime
export { AgentRuntime, type AgentRuntimeOptions, type RunTurnOptions } from "./runtime/runtime";
export { CancellationToken } from "./runtime/cancellation";
export { buildMessages } from "./runtime/context";
```

- [ ] **Step 2: Run all tests and typecheck**

```bash
cd packages/ts && bun run test && bun run typecheck
```

Expected: all tests pass, no type errors.

- [ ] **Step 3: Commit**

```bash
git add packages/ts/src/index.ts
git commit -m "feat(ts): export provider and runtime surface from index"
```

---

## Task 9: Demo app

**Files:**
- Create: `demos/ts-agent/package.json`
- Create: `demos/ts-agent/index.ts`

A minimal script that registers a tool, runs one turn with the mock provider, and prints each emitted event to stdout. Validates the full loop end-to-end without a network call.

- [ ] **Step 1: Create `demos/ts-agent/package.json`**

```json
{
  "name": "@demos/ts-agent",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "start": "bun run index.ts"
  },
  "dependencies": {
    "@kaji/sdk": "workspace:*",
    "zod": "^4.3.6"
  }
}
```

- [ ] **Step 2: Create `demos/ts-agent/index.ts`**

```ts
/**
 * Minimal demo: registers a weather tool, runs one agent turn with the mock
 * provider, prints every event emitted during the turn.
 *
 * Run with: bun run index.ts
 * No API key or external services needed.
 */
import {
  KajiEvent,
  AgentRuntime,
  EventBus,
  EventType,
  InMemoryEventStore,
  MockProvider,
  registerTool,
  toolSpecFromSchema,
} from "@kaji/sdk";
import { z } from "zod";

// 1. Set up infra-free building blocks
const store = new InMemoryEventStore();
const bus = new EventBus();
const provider = new MockProvider();
const runtime = new AgentRuntime({ provider, store, bus, systemPrompt: "You are a helpful assistant." });

// 2. Register a tool
registerTool(
  toolSpecFromSchema(
    "get_weather",
    "Look up the current weather for a city",
    z.object({ city: z.string().describe("The city name") }),
  ),
  async (_ctx, args) => {
    console.log(`  [tool] get_weather called with city="${args.city}"`);
    return { city: args.city, tempF: 68, condition: "sunny" };
  },
);

// 3. Seed a session
const sessionId = `demo-${Date.now()}`;
await store.append(
  KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }),
);
await store.append(
  KajiEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content: "What is the weather in Seattle?",
  }),
);

// 4. Subscribe to events so we can print them as they arrive
const sub = bus.subscribe(sessionId);
const printPromise = (async () => {
  for await (const event of sub) {
    console.log(`[event] ${event.type}`, "content" in event ? `"${event.content}"` : "");
    if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
  }
})();

// 5. Run one turn
console.log("Running agent turn...\n");
await runtime.runTurn(sessionId);
await printPromise;

console.log("\nDone.");
```

- [ ] **Step 3: Install and run the demo**

```bash
cd /path/to/repo && bun install
cd demos/ts-agent && bun run start
```

Expected output (event types in order):
```
Running agent turn...

[event] agent.reasoning.started
[event] tool.call.requested
[event] tool.call.started
  [tool] get_weather called with city=""
[event] tool.call.completed
[event] agent.message.delta "The mock provider has completed the tool loop."
[event] agent.message.completed "The mock provider has completed the tool loop."

Done.
```

- [ ] **Step 4: Commit**

```bash
git add demos/ts-agent/
git commit -m "feat(demos): add ts-agent demo — full tool-using loop with mock provider"
```

---

## Task 10: Update README and ROADMAP

**Files:**
- Modify: `packages/ts/README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update `packages/ts/README.md` status block and exports table**

Replace:
```md
> **Status:** pre-release. This is the runtime core: event-sourced building
> blocks (events, bus, store, replay) and a tool registry. The reasoning loop,
> providers, and voice modalities are not yet ported.
```

with:
```md
> **Status:** pre-release. Core runtime, provider layer, and agent loop are
> complete. Voice modalities are not yet ported.
```

Add new rows to the "What's here" table:
```md
| `ModelProvider`, `MockProvider`, `OpenAIProvider` | Provider interface and built-in providers |
| `registerProvider`, `getProvider` | Provider registry |
| `AgentRuntime` | ReAct tool-using loop: replay → LLM → tool calls → loop |
| `CancellationToken` | Cancel an in-flight agent turn |
```

- [ ] **Step 2: Update ROADMAP.md — mark items 25-28 DONE**

In `docs/ROADMAP.md`, update the TypeScript SDK section:

- `### 25. Provider layer (MISSING)` → `### 25. Provider layer (DONE)`
- `### 26. Agent runtime (MISSING)` → `### 26. Agent runtime (DONE)`
- `### 27. Tool-loop glue (MISSING)` → `### 27. Tool-loop glue (DONE)`
- `### 28. Reconcile sync vs async publish (design)` → `### 28. Reconcile sync vs async publish (DONE — publish stays sync, see bus.ts comment)`

- [ ] **Step 3: Run full test suite one final time**

```bash
cd packages/ts && bun run test && bun run typecheck && bun run build
```

Expected: all tests pass, no type errors, dist/ built cleanly.

- [ ] **Step 4: Commit**

```bash
git add packages/ts/README.md docs/ROADMAP.md
git commit -m "docs: mark TS SDK agent runtime complete in README and ROADMAP"
```

---

## Self-Review

**Spec coverage check:**

| spec item | covered by |
|-----------|-----------|
| publish sync/async decision | Task 1 |
| provider interface + types | Task 2 |
| provider registry | Task 3 |
| mock provider (drives full loop without network) | Task 4 |
| OpenAI provider (streaming + tool calls) | Task 5 |
| CancellationToken | Task 6 |
| buildMessages (context builder) | Task 6 |
| AgentRuntime.runTurn (ReAct loop) | Task 7 |
| public exports | Task 8 |
| sample app in demos/ | Task 9 |
| more tests (user requirement) | Tasks 4, 5, 7 — mock, openai, runtime each get their own test file |
| ROADMAP update | Task 10 |

**Placeholder scan:** No TBDs, no TODOs, no "similar to Task N" references. All code blocks are complete.

**Type consistency check:**
- `ToolCall.id / name / args` — defined in Task 2 (`base.ts`), used in Task 4 (mock), Task 5 (openai), Task 7 (runtime). Consistent.
- `ProviderMessage.role / content / name / tool_call_id` — defined in Task 2, used in Task 6 (`buildMessages`), Task 5 (openai toOpenAIMessages). Consistent.
- `ModelResponseChunk.delta / toolCalls` — defined in Task 2, yielded in Task 4 (mock) and Task 5 (openai), consumed in Task 7 (runtime). Consistent.
- `AgentRuntime` constructor takes `AgentRuntimeOptions` — defined and used in Task 7, exported in Task 8. Consistent.
- `clearProviders` — defined in Task 3 registry, imported in Task 3 test, exported in Task 8. Consistent.
