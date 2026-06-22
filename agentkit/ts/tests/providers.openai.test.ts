/**
 * Unit tests for OpenAIProvider — message formatting and streaming.
 * All network calls are mocked; no OPENAI_API_KEY required.
 */
import { describe, expect, it, vi } from "vitest";

import { ProviderAPIError, ProviderConfigError } from "../src/providers/errors";
import { OpenAIProvider } from "../src/providers/openai";
import type { ProviderMessage } from "../src/providers/base";

// ---------------------------------------------------------------------------
// buildMessages (private) — accessed via cast for targeted unit coverage
// ---------------------------------------------------------------------------

describe("OpenAIProvider.buildMessages", () => {
  const provider = new OpenAIProvider({ apiKey: "test-key" });
  const build = (msgs: ProviderMessage[]) =>
    (provider as unknown as { buildMessages(m: ProviderMessage[]): unknown[] }).buildMessages(msgs);

  it("maps user messages through unchanged", () => {
    const out = build([{ role: "user", content: "hello" }]);
    expect(out).toEqual([{ role: "user", content: "hello" }]);
  });

  it("maps assistant messages through unchanged", () => {
    const out = build([{ role: "assistant", content: "hi there" }]);
    expect(out).toEqual([{ role: "assistant", content: "hi there" }]);
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
  it("throws a config error when apiKey is empty", () => {
    expect(() => new OpenAIProvider({ apiKey: "" })).toThrow(ProviderConfigError);
    expect(() => new OpenAIProvider({ apiKey: "   " })).toThrow(/API key is not configured/);
  });

  it("returns text content from a plain response", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
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
    (provider as any).client = fakeClient;

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Hello there");
    expect(result.toolCalls).toHaveLength(0);
  });

  it("parses tool calls from the response", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
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
    (provider as any).client = fakeClient;

    const result = await provider.generate([{ role: "user", content: "weather?" }], []);
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]).toEqual({
      id: "call-1",
      name: "get_weather",
      args: { city: "Seattle" },
    });
  });

  it("handles bad JSON in tool call arguments gracefully", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
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
    (provider as any).client = fakeClient;

    const result = await provider.generate([{ role: "user", content: "go" }], []);
    // Unparseable tool args carry a __parse_error sentinel; planner converts it
    // into TOOL_CALL_FAILED rather than silently passing {} to the handler.
    expect(result.toolCalls[0]?.args).toMatchObject({
      __parse_error: expect.stringContaining("OpenAI tool args were not valid JSON"),
    });
  });

  it("passes tool_call_id in message history to the client", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
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
    (provider as any).client = fakeClient;

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
    const provider = new OpenAIProvider({ apiKey: "test-key" });
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
    (provider as any).client = fakeClient;

    await provider.generate(
      [{ role: "user", content: "weather?" }],
      [
        {
          name: "weather_getWeather",
          catalogName: "weather.getWeather",
          description: "Get weather",
          parameters: {},
        },
      ],
    );

    expect(captured.tools[0].function.name).toBe("weather_getWeather");
    expect(captured.tools[0].function.name).not.toContain(".");
  });

  it("wraps client failures in ProviderAPIError", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const error = Object.assign(new Error("rate limited"), {
      status: 429,
      response: { text: "too many requests" },
    });
    (provider as any).client = {
      chat: { completions: { create: vi.fn().mockRejectedValue(error) } },
    };

    const caught = await provider
      .generate([{ role: "user", content: "hi" }], [])
      .catch((err) => err);
    expect(caught).toBeInstanceOf(ProviderAPIError);
    expect(caught).toMatchObject({
      service: "openai",
      action: "api call",
      statusCode: 429,
      responseText: "too many requests",
    });
    expect((caught as ProviderAPIError).cause).toBe(error);
  });
});

// ---------------------------------------------------------------------------
// generateStream() — streaming tool-call accumulation across chunks
// ---------------------------------------------------------------------------

describe("OpenAIProvider.generateStream", () => {
  it("yields text chunks as they arrive", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });

    async function* fakeStream() {
      yield { choices: [{ delta: { content: "hel" }, finish_reason: null }] };
      yield { choices: [{ delta: { content: "lo" }, finish_reason: "stop" }] };
    }

    (provider as any).client = {
      chat: { completions: { create: vi.fn().mockResolvedValue(fakeStream()) } },
    };

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(chunk);
    }

    const text = chunks.map((c) => c.delta).join("");
    expect(text).toBe("hello");
  });

  it("accumulates fragmented tool-call arguments across chunks", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });

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

    (provider as any).client = {
      chat: { completions: { create: vi.fn().mockResolvedValue(fakeStream()) } },
    };

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
