/**
 * Unit tests for AnthropicProvider — message formatting and streaming.
 * All network calls are mocked; no ANTHROPIC_API_KEY required.
 */
import { describe, expect, it, vi } from "vitest";

import { AnthropicProvider } from "../src/providers/anthropic";
import type { ProviderMessage } from "../src/providers/base";

// ---------------------------------------------------------------------------
// splitMessages (module-local helper) — tested via generate() with mocked client
// and also by inspecting the captured params sent to the fake client.
// ---------------------------------------------------------------------------

describe("AnthropicProvider message formatting (via captured params)", () => {
  function makeProvider() {
    return new AnthropicProvider({ apiKey: "test-key" });
  }

  it("extracts system messages to the top-level system param", async () => {
    const provider = makeProvider();
    const captured: any = {};

    (provider as any).client = {
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    };

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
    const provider = makeProvider();
    const captured: any = {};

    (provider as any).client = {
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    };

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

  it("uses empty string for tool_use_id when tool_call_id is missing", async () => {
    const provider = makeProvider();
    const captured: any = {};

    (provider as any).client = {
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    };

    await provider.generate([{ role: "tool", content: "ok", name: "anon_tool" }], []);

    const toolMsg = captured.messages[0];
    expect(toolMsg.content[0].tool_use_id).toBe("");
  });

  it("does not include system in messages array", async () => {
    const provider = makeProvider();
    const captured: any = {};

    (provider as any).client = {
      messages: {
        create: vi.fn().mockImplementation((params: any) => {
          Object.assign(captured, params);
          return Promise.resolve({ content: [{ type: "text", text: "ok" }] });
        }),
      },
    };

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
});

// ---------------------------------------------------------------------------
// generate() — response parsing
// ---------------------------------------------------------------------------

describe("AnthropicProvider.generate", () => {
  it("returns text from a text content block", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Hello!" }],
        }),
      },
    };

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Hello!");
    expect(result.toolCalls).toHaveLength(0);
  });

  it("parses tool_use blocks into ToolCall shape", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "tool_use", id: "tu-1", name: "get_weather", input: { city: "NYC" } }],
        }),
      },
    };

    const result = await provider.generate([{ role: "user", content: "weather?" }], []);
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]).toEqual({ id: "tu-1", name: "get_weather", args: { city: "NYC" } });
  });

  it("handles mixed text + tool_use content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "text", text: "Let me check." },
            { type: "tool_use", id: "tu-2", name: "lookup", input: {} },
          ],
        }),
      },
    };

    const result = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(result.content).toBe("Let me check.");
    expect(result.toolCalls[0]?.name).toBe("lookup");
  });
});

// ---------------------------------------------------------------------------
// generateStream() — fragmented tool-call accumulation
// ---------------------------------------------------------------------------

describe("AnthropicProvider.generateStream", () => {
  it("yields text deltas from text_delta events", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    const events = [
      { type: "content_block_delta", delta: { type: "text_delta", text: "hel" } },
      { type: "content_block_delta", delta: { type: "text_delta", text: "lo" } },
    ];

    const fakeStream = {
      [Symbol.asyncIterator]: async function* () {
        for (const e of events) yield e;
      },
    };

    (provider as any).client = { messages: { stream: vi.fn().mockReturnValue(fakeStream) } };

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

  it("reassembles fragmented input_json_delta into a single ToolCall", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

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

    (provider as any).client = { messages: { stream: vi.fn().mockReturnValue(fakeStream) } };

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
    const provider = new AnthropicProvider({ apiKey: "test-key" });

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

    (provider as any).client = { messages: { stream: vi.fn().mockReturnValue(fakeStream) } };

    const chunks = [];
    for await (const chunk of provider.generateStream([{ role: "user", content: "go" }], [])) {
      chunks.push(chunk);
    }

    const toolChunk = chunks.find((c) => c.toolCalls.length > 0);
    // Bad JSON falls back to empty args rather than throwing.
    expect(toolChunk?.toolCalls[0]?.args).toEqual({});
  });
});
