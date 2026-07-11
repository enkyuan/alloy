/**
 * Unit tests for AnthropicProvider — message formatting and streaming.
 * All network calls are mocked; no ANTHROPIC_API_KEY required.
 */
import { describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";

import { ProviderAPIError, ProviderConfigError } from "@/providers/errors";
import { AnthropicProvider } from "@/providers/anthropic";
import { TestAnthropicProvider } from "./helpers/provider-clients";

function makeProvider(client?: unknown) {
  return client === undefined
    ? new AnthropicProvider({ apiKey: "test-key" })
    : new TestAnthropicProvider({ apiKey: "test-key" }, client as unknown as Anthropic);
}

// ---------------------------------------------------------------------------
// splitMessages (module-local helper) — tested via generate() with mocked client
// and also by inspecting the captured params sent to the fake client.
// ---------------------------------------------------------------------------

describe("AnthropicProvider message formatting (via captured params)", () => {
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

  it("returns text from a text content block", async () => {
    const provider = makeProvider({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Hello!" }],
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Hello!");
    expect(result.toolCalls).toHaveLength(0);
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
      action: "api call",
      statusCode: 529,
      responseText: "try later",
    });
    expect((caught as ProviderAPIError).cause).toBe(error);
  });
});

// ---------------------------------------------------------------------------
// generateStream() — fragmented tool-call accumulation
// ---------------------------------------------------------------------------

describe("AnthropicProvider.generateStream", () => {
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
});
