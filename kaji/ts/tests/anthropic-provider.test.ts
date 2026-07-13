/**
 * Unit tests for AnthropicProvider — message formatting and streaming.
 * All network calls are mocked; no ANTHROPIC_API_KEY required.
 */
import { describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";

import {
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderOutputLimitError,
} from "@/providers/errors";
import { AnthropicProvider } from "@/providers/anthropic";
import {
  withProviderResponseDiagnostics,
  type ProviderResponseDiagnostics,
  type ProviderResponseLimits,
} from "@/providers/base";
import { CancellationToken } from "@/runtime/cancellation";
import { TestAnthropicProvider } from "./helpers/provider-clients";

function makeProvider(client?: unknown) {
  return client === undefined
    ? new AnthropicProvider({ apiKey: "test-key" })
    : new TestAnthropicProvider({ apiKey: "test-key" }, client as unknown as Anthropic);
}

const responseLimits = (
  overrides: Partial<ProviderResponseLimits> = {},
): ProviderResponseLimits => ({
  textMaxBytes: 262_144,
  toolArgumentsMaxBytes: 65_536,
  responseMaxBytes: 524_288,
  toolCallsMax: 64,
  ...overrides,
});

// ---------------------------------------------------------------------------
// splitMessages (module-local helper) — tested via generate() with mocked client
// and also by inspecting the captured params sent to the fake client.
// ---------------------------------------------------------------------------

describe("AnthropicProvider message formatting (via captured params)", () => {
  it("does not create the vendor client during construction", () => {
    let createCalls = 0;
    class LazyProbeProvider extends AnthropicProvider {
      protected override async createClient(): Promise<Anthropic> {
        createCalls++;
        throw new Error("should not be called");
      }
    }

    new LazyProbeProvider({ apiKey: "fixture" });

    expect(createCalls).toBe(0);
  });

  it("extracts system messages to the top-level system param", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate(
      [
        { role: "system", content: "Be brief." },
        { role: "user", content: "hi" },
      ],
      [],
    );

    expect(captured.system).toBe("Be brief.");
    expect(captured.messages.every((m: any) => m.role !== "system")).toBe(true);
  });

  it("maps tool results to Anthropic tool_result content blocks inside a user turn", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate(
      [
        { role: "user", content: "call lookup" },
        { role: "tool", content: '{"result":42}', name: "lookup", tool_call_id: "c-abc" },
      ],
      [],
    );

    const toolMsg = captured.messages.find(
      (m: any) => Array.isArray(m.content) && m.content[0]?.type === "tool_result",
    );
    expect(toolMsg).toBeDefined();
    expect(toolMsg.role).toBe("user");
    expect(toolMsg.content[0].type).toBe("tool_result");
    expect(toolMsg.content[0].tool_use_id).toBe("c-abc");
    expect(toolMsg.content[0].content).toBe('{"result":42}');
  });

  it("maps assistant tool calls to Anthropic tool_use content blocks", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate(
      [
        {
          role: "assistant",
          content: "Checking.",
          toolCalls: [{ id: "call-1", name: "lookup", args: { q: "weather" } }],
        },
        { role: "tool", content: '{"result":42}', name: "lookup", tool_call_id: "call-1" },
      ],
      [],
    );

    expect(captured.messages[0]).toEqual({
      role: "assistant",
      content: [
        { type: "text", text: "Checking." },
        { type: "tool_use", id: "call-1", name: "lookup", input: { q: "weather" } },
      ],
    });
    expect(captured.messages[1].content[0]).toMatchObject({
      type: "tool_result",
      tool_use_id: "call-1",
    });
  });

  it("uses empty string for tool_use_id when tool_call_id is missing", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate([{ role: "tool", content: "ok", name: "anon_tool" }], []);

    const toolMsg = captured.messages[0];
    expect(toolMsg.content[0].tool_use_id).toBe("");
  });

  it("does not include system in messages array", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate(
      [
        { role: "system", content: "You are helpful." },
        { role: "user", content: "hi" },
      ],
      [],
    );

    const systemMsgs = captured.messages.filter((m: any) => m.role === "system");
    expect(systemMsgs).toHaveLength(0);
  });

  it("sends provider-safe tool names to Anthropic", async () => {
    const captured: any = {};

    const provider = makeProvider({
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    });

    await provider.generate(
      [{ role: "user", content: "weather?" }],
      [
        {
          name: "weather_getWeather",
          catalogName: "weather.getWeather",
          description: "Get weather",
          parameters: {},
          risk: "read",
        },
      ],
    );

    expect(captured.tools[0].name).toBe("weather_getWeather");
    expect(captured.tools[0].name).not.toContain(".");
  });
});

// ---------------------------------------------------------------------------
// generate() — response parsing
// ---------------------------------------------------------------------------

describe("AnthropicProvider.generate", () => {
  it("throws a config error when apiKey is empty", () => {
    expect(() => new AnthropicProvider({ apiKey: "" })).toThrow(ProviderConfigError);
    expect(() => new AnthropicProvider({ apiKey: "   " })).toThrow(/API key is not configured/);
  });

  it.each([0, -1, 1.5, Number.POSITIVE_INFINITY, Number.NaN])(
    "rejects invalid requestTimeoutMs %s",
    (requestTimeoutMs) => {
      expect(() => new AnthropicProvider({ apiKey: "test-key", requestTimeoutMs })).toThrowError(
        new RangeError("requestTimeoutMs must be a positive finite integer"),
      );
    },
  );

  it("forwards requestTimeoutMs and the cancellation signal", async () => {
    const create = vi.fn().mockResolvedValue({ content: [] });
    const provider = new TestAnthropicProvider({ apiKey: "test-key", requestTimeoutMs: 2_500 }, {
      messages: { create },
    } as unknown as Anthropic);
    const token = new CancellationToken();

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledWith(expect.any(Object), {
      signal: token.signal,
      timeout: 2_500,
    });
  });

  it("returns text from a text content block", async () => {
    const provider = makeProvider({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Hello!" }],
          usage: { input_tokens: 5, output_tokens: 3 },
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Hello!");
    expect(result.toolCalls).toHaveLength(0);
    expect(result.costUsd).toBe(0.00006);
  });

  it("parses tool_use blocks into ToolCall shape", async () => {
    const provider = makeProvider({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "tool_use", id: "tu-1", name: "get_weather", input: { city: "NYC" } }],
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "weather?" }], []);
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]).toEqual({ id: "tu-1", name: "get_weather", args: { city: "NYC" } });
    expect(result.costUsd).toBeUndefined();
  });

  it("handles mixed text + tool_use content blocks", async () => {
    const provider = makeProvider({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "text", text: "Let me check." },
            { type: "tool_use", id: "tu-2", name: "lookup", input: {} },
          ],
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Let me check.");
    expect(result.toolCalls[0]?.name).toBe("lookup");
  });

  it("wraps client failures in ProviderAPIError", async () => {
    const error = Object.assign(new Error("overloaded"), {
      statusCode: 529,
      response: "try later",
    });
    const provider = makeProvider({
      messages: { create: vi.fn().mockRejectedValue(error) },
    });

    const caught = await provider
      .generate([{ role: "user", content: "hi" }], [])
      .catch((err) => err);
    expect(caught).toBeInstanceOf(ProviderAPIError);
    expect(caught).toMatchObject({
      service: "anthropic",
      action: "request",
      statusCode: 529,
      responseText: undefined,
    });
    expect(String(caught)).not.toContain("try later");
    expect((caught as ProviderAPIError).cause).toBeUndefined();
  });

  it("classifies network-coded client failures", async () => {
    const error = Object.assign(new Error("connection reset"), { code: "ECONNRESET" });
    const provider = makeProvider({
      messages: { create: vi.fn().mockRejectedValue(error) },
    });

    const caught = await provider
      .generate([{ role: "user", content: "hi" }], [])
      .catch((cause) => cause);

    expect(caught).toBeInstanceOf(ProviderConnectionError);
    expect(caught).toMatchObject({ service: "anthropic", action: "request" });
    expect((caught as ProviderConnectionError).cause).toBeUndefined();
  });

  it("enforces exact and one-byte-over canonical tool argument limits", async () => {
    const overhead = new TextEncoder().encode('{"value":""}').byteLength;
    const exactInput = { value: "é".repeat((65_536 - overhead) / 2) };
    const providerFor = (input: Record<string, unknown>) =>
      makeProvider({
        messages: {
          create: vi.fn().mockResolvedValue({
            content: [{ type: "tool_use", id: "i", name: "n", input }],
          }),
        },
      });

    await expect(
      providerFor(exactInput).generate([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits(),
      }),
    ).resolves.toMatchObject({ toolCalls: [{ id: "i", name: "n" }] });
    await expect(
      providerFor({ value: `${exactInput.value}a` }).generate(
        [{ role: "user", content: "go" }],
        [],
        { responseLimits: responseLimits() },
      ),
    ).rejects.toMatchObject({
      code: "PROVIDER_OUTPUT_LIMIT",
      dimension: "tool_arguments",
      limit: 65_536,
    });
  });

  it("shares the total budget and enforces the 64-call boundary", async () => {
    const providerFor = (count: number) =>
      makeProvider({
        messages: {
          create: vi.fn().mockResolvedValue({
            content: [
              { type: "text", text: "a" },
              ...Array.from({ length: count }, (_, index) => ({
                type: "tool_use",
                id: `i${index}`,
                name: "n",
                input: {},
              })),
            ],
          }),
        },
      });

    await expect(
      providerFor(1).generate([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits({ responseMaxBytes: 6 }),
      }),
    ).resolves.toBeDefined();
    await expect(
      providerFor(1).generate([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits({ responseMaxBytes: 5 }),
      }),
    ).rejects.toMatchObject({ dimension: "total_response", limit: 5 });
    await expect(
      providerFor(64).generate([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits({ responseMaxBytes: 1_024 }),
      }),
    ).resolves.toMatchObject({ toolCalls: expect.any(Array) });
    await expect(
      providerFor(65).generate([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits({ responseMaxBytes: 1_024 }),
      }),
    ).rejects.toMatchObject({ dimension: "tool_calls", limit: 64 });
  });
});

// ---------------------------------------------------------------------------
// generateStream() — fragmented tool-call accumulation
// ---------------------------------------------------------------------------

describe("AnthropicProvider.generateStream", () => {
  it("forwards requestTimeoutMs and the cancellation signal", async () => {
    const stream = vi.fn().mockReturnValue({
      [Symbol.asyncIterator]: async function* () {
        yield { type: "message_stop" };
      },
    });
    const provider = new TestAnthropicProvider({ apiKey: "test-key", requestTimeoutMs: 2_500 }, {
      messages: { stream },
    } as unknown as Anthropic);
    const token = new CancellationToken();

    for await (const _chunk of provider.generateStream([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    })) {
      // Exhaust the stream so the vendor call completes.
    }

    expect(stream).toHaveBeenCalledWith(expect.any(Object), {
      signal: token.signal,
      timeout: 2_500,
    });
  });

  it("recreates a stream after a 429 before the first event", async () => {
    const stream = vi
      .fn()
      .mockReturnValueOnce({
        [Symbol.asyncIterator]: async function* () {
          throw Object.assign(new Error("rate limited"), { status: 429 });
        },
      })
      .mockReturnValueOnce({
        [Symbol.asyncIterator]: async function* () {
          yield { type: "content_block_delta", delta: { type: "text_delta", text: "ok" } };
        },
      });
    const provider = new TestAnthropicProvider(
      { apiKey: "test-key", retry: { maxAttempts: 2, baseDelayMs: 0 } },
      { messages: { stream } } as unknown as Anthropic,
    );

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }
    expect(chunks.map((chunk) => chunk.delta).join("")).toBe("ok");
    expect(stream).toHaveBeenCalledTimes(2);
  });

  it("yields text deltas from text_delta events", async () => {
    const events = [
      { type: "content_block_delta", delta: { type: "text_delta", text: "hel" } },
      { type: "content_block_delta", delta: { type: "text_delta", text: "lo" } },
    ];

    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        for (const e of events) yield e;
      },
    };

    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(fakeStream) } });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }

    expect(
      chunks
        .filter((c) => c.delta)
        .map((c) => c.delta)
        .join(""),
    ).toBe("hello");
  });

  it("yields a metadata chunk when streaming usage is reported", async () => {
    const events = [
      { type: "message_start", usage: { input_tokens: 5, output_tokens: 0 } },
      { type: "content_block_delta", delta: { type: "text_delta", text: "hi" } },
      { type: "message_delta", usage: { output_tokens: 3 } },
    ];

    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        for (const e of events) yield e;
      },
    };

    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(fakeStream) } });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }

    expect(chunks.at(-1)).toMatchObject({
      delta: "",
      toolCalls: [],
      usage: { input: 5, output: 3 },
    });
    expect(chunks.at(-1)?.costUsd).toBeGreaterThan(0);
  });

  it("reassembles fragmented input_json_delta into a single ToolCall", async () => {
    const events = [
      {
        type: "content_block_start",
        content_block: { type: "tool_use", id: "tu-s", name: "search" },
      },
      { type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '{"q":' } },
      { type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '"test"}' } },
      { type: "content_block_stop" },
    ];

    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        for (const e of events) yield e;
      },
    };

    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(fakeStream) } });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "search" }], [])) {
      chunks.push(chunk);
    }

    const toolChunks = chunks.filter((c) => c.toolCalls.length > 0);
    expect(toolChunks).toHaveLength(1);
    expect(toolChunks[0]?.toolCalls[0]).toEqual({
      id: "tu-s",
      name: "search",
      args: { q: "test" },
    });
  });

  it("handles bad JSON in streaming tool args gracefully", async () => {
    const events = [
      {
        type: "content_block_start",
        content_block: { type: "tool_use", id: "tu-bad", name: "bad" },
      },
      {
        type: "content_block_delta",
        delta: { type: "input_json_delta", partial_json: "{invalid" },
      },
      { type: "content_block_stop" },
    ];

    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        for (const e of events) yield e;
      },
    };

    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(fakeStream) } });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "go" }], [])) {
      chunks.push(chunk);
    }

    const toolChunk = chunks.find((c) => c.toolCalls.length > 0);
    // Unparseable tool args carry a __parse_error sentinel; planner converts it
    // into TOOL_CALL_FAILED rather than silently passing {} to the handler.
    expect(toolChunk?.toolCalls[0]?.args).toMatchObject({
      __parse_error: expect.stringContaining("Anthropic tool args were not valid JSON"),
    });
  });

  it("assembles 10k argument fragments with one join and per-call diagnostics", async () => {
    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        yield {
          type: "content_block_start",
          index: 0,
          content_block: { type: "tool_use", id: "call", name: "lookup" },
        };
        yield {
          type: "content_block_delta",
          index: 0,
          delta: { type: "input_json_delta", partial_json: '{"value":"' },
        };
        for (let index = 0; index < 9_998; index += 1) {
          yield {
            type: "content_block_delta",
            index: 0,
            delta: { type: "input_json_delta", partial_json: "x" },
          };
        }
        yield {
          type: "content_block_delta",
          index: 0,
          delta: { type: "input_json_delta", partial_json: '"}' },
        };
        yield { type: "content_block_stop", index: 0 };
      },
    };
    let diagnostics: Readonly<ProviderResponseDiagnostics> | undefined;
    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(fakeStream) } });
    const chunks = [];
    const options = withProviderResponseDiagnostics(
      {},
      {
        record(value) {
          diagnostics = Object.freeze({ ...value });
        },
      },
    );
    for await (const chunk of provider.generateStream(
      [{ role: "user", content: "go" }],
      [],
      options,
    )) {
      chunks.push(chunk);
    }

    expect(chunks.find((chunk) => chunk.toolCalls.length > 0)?.toolCalls[0]?.args).toEqual({
      value: "x".repeat(9_998),
    });
    expect(diagnostics).toEqual({
      rawFragments: 10_002,
      toolArgumentJoinOperations: 1,
    });
    expect(Object.isFrozen(diagnostics)).toBe(true);
  });

  it("closes before propagating an unparsed typed output-limit error", async () => {
    const parse = vi.spyOn(JSON, "parse");
    let returned = false;
    let parseCallsWhenClosed = -1;
    let next = 0;
    const events = [
      {
        type: "content_block_start",
        index: 0,
        content_block: { type: "tool_use", id: "call", name: "lookup" },
      },
      {
        type: "content_block_delta",
        index: 0,
        delta: { type: "input_json_delta", partial_json: "xx" },
      },
    ];
    const iterator: AsyncIterableIterator<unknown> = {
      async next() {
        const value = events[next++];
        return value === undefined ? { done: true, value: undefined } : { done: false, value };
      },
      async return() {
        parseCallsWhenClosed = parse.mock.calls.length;
        returned = true;
        return { done: true, value: undefined };
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
    const provider = makeProvider({ messages: { stream: vi.fn().mockReturnValue(iterator) } });

    const consume = async () => {
      for await (const _chunk of provider.generateStream([{ role: "user", content: "go" }], [], {
        responseLimits: responseLimits({ toolArgumentsMaxBytes: 1 }),
      })) {
        // The oversized fragment must be rejected before yielding a tool call.
      }
    };
    await expect(consume()).rejects.toBeInstanceOf(ProviderOutputLimitError);
    expect(returned).toBe(true);
    expect(parseCallsWhenClosed).toBe(0);
    expect(parse).not.toHaveBeenCalled();
    parse.mockRestore();
  });

  it("accepts exact multibyte text and closes on one byte over", async () => {
    const providerFor = (text: string) =>
      makeProvider({
        messages: {
          stream: vi.fn().mockReturnValue({
            [Symbol.asyncIterator]: async function* () {
              yield {
                type: "content_block_delta",
                index: 0,
                delta: { type: "text_delta", text },
              };
            },
          }),
        },
      });
    const exact = [];
    for await (const chunk of providerFor("😀").generateStream(
      [{ role: "user", content: "go" }],
      [],
      { responseLimits: responseLimits({ textMaxBytes: 4, responseMaxBytes: 4 }) },
    )) {
      exact.push(chunk.delta);
    }
    expect(exact.join("")).toBe("😀");

    await expect(async () => {
      for await (const _chunk of providerFor("😀a").generateStream(
        [{ role: "user", content: "go" }],
        [],
        { responseLimits: responseLimits({ textMaxBytes: 4, responseMaxBytes: 5 }) },
      )) {
        // Consume the stream.
      }
    }).rejects.toMatchObject({ dimension: "text", limit: 4 });
  });
});
