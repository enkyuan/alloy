/**
 * Unit tests for OpenAIProvider — message formatting and streaming.
 * All network calls are mocked; no OPENAI_API_KEY required.
 */
import { describe, expect, it, vi } from "vitest";
import type OpenAI from "openai";

import { ProviderAPIError, ProviderConfigError, ProviderConnectionError } from "@/providers/errors";
import { OpenAIProvider } from "@/providers/openai";
import { toOpenAIChatMessages } from "@/providers/openai-format";
import type { ProviderMessage } from "@/providers/base";
import { TestOpenAIProvider } from "./helpers/provider-clients";

const makeProvider = (client: unknown) =>
  new TestOpenAIProvider({ apiKey: "test-key" }, client as unknown as OpenAI);

// ---------------------------------------------------------------------------
// OpenAI message formatting
// ---------------------------------------------------------------------------

describe("toOpenAIChatMessages", () => {
  const build = (msgs: ProviderMessage[]) => toOpenAIChatMessages(msgs);

  it("maps user messages through unchanged", () => {
    const out = build([{ role: "user", content: "hello" }]);
    expect(out).toEqual([{ role: "user", content: "hello" }]);
  });

  it("maps assistant messages through unchanged", () => {
    const out = build([{ role: "assistant", content: "hi there" }]);
    expect(out).toEqual([{ role: "assistant", content: "hi there" }]);
  });

  it("maps assistant tool calls to OpenAI tool_calls", () => {
    const out = build([
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "call-1", name: "lookup", args: { q: "weather" } }],
      },
      { role: "tool", content: '{"ok":true}', name: "lookup", tool_call_id: "call-1" },
    ]);
    expect(out).toEqual([
      {
        role: "assistant",
        content: "",
        tool_calls: [
          {
            id: "call-1",
            type: "function",
            function: { name: "lookup", arguments: '{"q":"weather"}' },
          },
        ],
      },
      { role: "tool", content: '{"ok":true}', tool_call_id: "call-1" },
    ]);
  });

  it("maps tool messages to OpenAI tool role with tool_call_id", () => {
    const out = build([
      { role: "tool", content: '{"x":1}', name: "lookup", tool_call_id: "call-abc" },
    ]);
    expect(out).toEqual([{ role: "tool", content: '{"x":1}', tool_call_id: "call-abc" }]);
  });

  it("falls back to empty string when tool_call_id is absent", () => {
    const out = build([{ role: "tool", content: "ok", name: "lookup" }]);
    expect((out[0] as any).tool_call_id).toBe("");
  });

  it("strips name from tool messages (OpenAI does not accept it)", () => {
    const out = build([{ role: "tool", content: "result", name: "my_tool", tool_call_id: "c1" }]);
    expect((out[0] as any).name).toBeUndefined();
  });

  it("handles mixed message history correctly", () => {
    const out = build([
      { role: "user", content: "call the tool" },
      { role: "assistant", content: "" },
      { role: "tool", content: '{"ok":true}', name: "search", tool_call_id: "c-x" },
    ]);
    expect(out[0]).toEqual({ role: "user", content: "call the tool" });
    expect(out[1]).toEqual({ role: "assistant", content: "" });
    expect(out[2]).toEqual({ role: "tool", content: '{"ok":true}', tool_call_id: "c-x" });
  });
});

// ---------------------------------------------------------------------------
// generate() — end-to-end via mocked OpenAI client
// ---------------------------------------------------------------------------

describe("OpenAIProvider.generate", () => {
  it("does not create the vendor client during construction", () => {
    let createCalls = 0;
    class LazyProbeProvider extends OpenAIProvider {
      protected override async createClient(): Promise<OpenAI> {
        createCalls++;
        throw new Error("should not be called");
      }
    }

    new LazyProbeProvider({ apiKey: "fixture" });

    expect(createCalls).toBe(0);
  });

  it("throws a config error when apiKey is empty", () => {
    expect(() => new OpenAIProvider({ apiKey: "" })).toThrow(ProviderConfigError);
    expect(() => new OpenAIProvider({ apiKey: "   " })).toThrow(/API key is not configured/);
  });

  it("returns text content from a plain response", async () => {
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [
              {
                message: { content: "Hello there", tool_calls: null },
              },
            ],
          }),
        },
      },
    };
    const provider = makeProvider(fakeClient);

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Hello there");
    expect(result.toolCalls).toHaveLength(0);
  });

  it("parses tool calls from the response", async () => {
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [
              {
                message: {
                  content: "",
                  tool_calls: [
                    {
                      id: "call-1",
                      type: "function",
                      function: { name: "get_weather", arguments: '{"city":"Seattle"}' },
                    },
                  ],
                },
              },
            ],
          }),
        },
      },
    };
    const provider = makeProvider(fakeClient);

    const result = await provider.generate([{ role: "user", content: "weather?" }], []);
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]).toEqual({
      id: "call-1",
      name: "get_weather",
      args: { city: "Seattle" },
    });
  });

  it("handles bad JSON in tool call arguments gracefully", async () => {
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [
              {
                message: {
                  content: "",
                  tool_calls: [
                    {
                      id: "c1",
                      type: "function",
                      function: { name: "bad_tool", arguments: "{not-json}" },
                    },
                  ],
                },
              },
            ],
          }),
        },
      },
    };
    const provider = makeProvider(fakeClient);

    const result = await provider.generate([{ role: "user", content: "go" }], []);
    // Unparseable tool args carry a __parse_error sentinel; planner converts it
    // into TOOL_CALL_FAILED rather than silently passing {} to the handler.
    expect(result.toolCalls[0]?.args).toMatchObject({
      __parse_error: expect.stringContaining("OpenAI tool args were not valid JSON"),
    });
  });

  it("passes tool_call_id in message history to the client", async () => {
    const captured: any[] = [];
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockImplementation((params: any) => {
            captured.push(...params.messages);
            return Promise.resolve({
              choices: [{ message: { content: "done", tool_calls: null } }],
            });
          }),
        },
      },
    };
    const provider = makeProvider(fakeClient);

    await provider.generate(
      [
        { role: "user", content: "call the tool" },
        { role: "tool", content: '{"result":1}', name: "lookup", tool_call_id: "call-abc" },
      ],
      [],
    );

    const toolMsg = captured.find((m: any) => m.role === "tool");
    expect(toolMsg?.tool_call_id).toBe("call-abc");
  });

  it("sends provider-safe tool names to OpenAI", async () => {
    const captured: any = {};
    const fakeClient = {
      chat: {
        completions: {
          create: vi.fn().mockImplementation((params: any) => {
            Object.assign(captured, params);
            return Promise.resolve({
              choices: [{ message: { content: "done", tool_calls: null } }],
            });
          }),
        },
      },
    };
    const provider = makeProvider(fakeClient);

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

    expect(captured.tools[0].function.name).toBe("weather_getWeather");
    expect(captured.tools[0].function.name).not.toContain(".");
  });

  it("wraps client failures in ProviderAPIError", async () => {
    const error = Object.assign(new Error("rate limited"), {
      status: 429,
      response: { text: "too many requests" },
    });
    const provider = makeProvider({
      chat: { completions: { create: vi.fn().mockRejectedValue(error) } },
    });

    const caught = await provider
      .generate([{ role: "user", content: "hi" }], [])
      .catch((err) => err);
    expect(caught).toBeInstanceOf(ProviderAPIError);
    expect(caught).toMatchObject({
      service: "openai",
      action: "request",
      statusCode: 429,
      responseText: undefined,
    });
    expect(String(caught)).not.toContain("too many requests");
    expect((caught as ProviderAPIError).cause).toBeUndefined();
  });

  it("classifies network-coded client failures", async () => {
    const error = Object.assign(new Error("connection reset"), { code: "ECONNRESET" });
    const provider = makeProvider({
      chat: { completions: { create: vi.fn().mockRejectedValue(error) } },
    });

    const caught = await provider
      .generate([{ role: "user", content: "hi" }], [])
      .catch((cause) => cause);

    expect(caught).toBeInstanceOf(ProviderConnectionError);
    expect(caught).toMatchObject({ service: "openai", action: "request" });
    expect((caught as ProviderConnectionError).cause).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// generateStream() — streaming tool-call accumulation across chunks
// ---------------------------------------------------------------------------

describe("OpenAIProvider.generateStream", () => {
  it("recreates a stream after a 429 before the first chunk", async () => {
    async function* successfulStream() {
      yield { choices: [{ delta: { content: "ok" }, finish_reason: "stop" }] };
    }
    const create = vi
      .fn()
      .mockRejectedValueOnce(Object.assign(new Error("rate limited"), { status: 429 }))
      .mockResolvedValueOnce(successfulStream());
    const provider = new TestOpenAIProvider(
      { apiKey: "test-key", retry: { maxAttempts: 2, baseDelayMs: 0 } },
      { chat: { completions: { create } } } as unknown as OpenAI,
    );

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }
    expect(chunks.map((chunk) => chunk.delta).join("")).toBe("ok");
    expect(create).toHaveBeenCalledTimes(2);
  });

  it("yields text chunks as they arrive", async () => {
    async function* fakeStream() {
      yield { choices: [{ delta: { content: "hel" }, finish_reason: null }] };
      yield { choices: [{ delta: { content: "lo" }, finish_reason: "stop" }] };
    }

    const provider = makeProvider({
      chat: { completions: { create: vi.fn().mockResolvedValue(fakeStream()) } },
    });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }

    const text = chunks.map((c) => c.delta).join("");
    expect(text).toBe("hello");
  });

  it("yields a metadata chunk when streaming usage is reported", async () => {
    async function* fakeStream() {
      yield { choices: [{ delta: { content: "hi" }, finish_reason: null }] };
      yield {
        choices: [],
        usage: { prompt_tokens: 3, completion_tokens: 2 },
      };
    }

    const create = vi.fn().mockResolvedValue(fakeStream());
    const provider = makeProvider({
      chat: { completions: { create } },
    });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }

    expect(create.mock.calls[0]?.[0]).toMatchObject({
      stream: true,
      stream_options: { include_usage: true },
    });
    expect(chunks.at(-1)).toMatchObject({
      delta: "",
      toolCalls: [],
      usage: { input: 3, output: 2 },
    });
    expect(chunks.at(-1)?.costUsd).toBeGreaterThan(0);
  });

  it("accumulates fragmented tool-call arguments across chunks", async () => {
    async function* fakeStream() {
      // First chunk: id + name + partial args
      yield {
        choices: [
          {
            delta: {
              tool_calls: [
                { index: 0, id: "call-1", function: { name: "search", arguments: '{"q":' } },
              ],
            },
            finish_reason: null,
          },
        ],
      };
      // Second chunk: rest of args
      yield {
        choices: [
          {
            delta: {
              tool_calls: [{ index: 0, function: { arguments: '"weather"}' } }],
            },
            finish_reason: null,
          },
        ],
      };
      // finish_reason flushes pending tool calls
      yield {
        choices: [{ delta: {}, finish_reason: "tool_calls" }],
      };
    }

    const provider = makeProvider({
      chat: { completions: { create: vi.fn().mockResolvedValue(fakeStream()) } },
    });

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "search" }], [])) {
      chunks.push(chunk);
    }

    const toolChunks = chunks.filter((c) => c.toolCalls.length > 0);
    expect(toolChunks).toHaveLength(1);
    expect(toolChunks[0]?.toolCalls[0]).toEqual({
      id: "call-1",
      name: "search",
      args: { q: "weather" },
    });
  });
});
