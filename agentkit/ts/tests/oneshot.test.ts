import { describe, expect, it } from "vitest";

import { generateText, streamText } from "../src/runtime/oneshot";
import { MockProvider } from "../src/providers/mock";
import { openai, anthropic } from "../src/providers/factory";
import { OpenAIProvider } from "../src/providers/openai";
import { AnthropicProvider } from "../src/providers/anthropic";
import type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "../src/providers/base";
import type { ToolSpec } from "../src/tools/registry";

class FixedProvider implements ModelProvider {
  constructor(
    private readonly text: string,
    private readonly deltas: string[] = [],
  ) {}

  async generate(): Promise<ModelResponse> {
    return { content: this.text, toolCalls: [] };
  }

  async *generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk> {
    for (const d of this.deltas.length > 0 ? this.deltas : [this.text]) {
      yield { delta: d, toolCalls: [] };
    }
  }
}

describe("generateText", () => {
  it("returns text and tool calls from a single provider call", async () => {
    const messages: ProviderMessage[] = [{ role: "user", content: "Hi" }];
    const result = await generateText({
      provider: new FixedProvider("hello"),
      messages,
    });
    expect(result.content).toBe("hello");
    expect(result.toolCalls).toEqual([]);
  });

  it("surfaces tool calls when the provider emits them", async () => {
    const messages: ProviderMessage[] = [{ role: "user", content: "weather?" }];
    const result = await generateText({
      provider: new MockProvider(),
      messages,
      tools: [
        {
          name: "get_weather",
          description: "weather",
          parameters: {
            type: "object",
            properties: { city: { type: "string" } },
            required: ["city"],
          },
        },
      ],
    });
    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls[0]!.name).toBe("get_weather");
  });
});

describe("streamText", () => {
  it("yields deltas and resolves text to the concatenation", async () => {
    const provider = new FixedProvider("", ["a", "b", "c"]);
    const { textStream, text, toolCalls } = streamText({
      provider,
      messages: [{ role: "user", content: "stream" }],
    });
    const chunks: string[] = [];
    for await (const c of textStream) chunks.push(c);
    expect(chunks).toEqual(["a", "b", "c"]);
    expect(await text).toBe("abc");
    expect(await toolCalls).toEqual([]);
  });
});

describe("provider factories", () => {
  it("openai('gpt-4o') builds an OpenAIProvider with that model", () => {
    const prev = process.env.OPENAI_API_KEY;
    process.env.OPENAI_API_KEY = "test-key";
    try {
      const p = openai("gpt-4o");
      expect(p).toBeInstanceOf(OpenAIProvider);
    } finally {
      if (prev === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = prev;
    }
  });

  it("openai({ apiKey }) takes an explicit key over the environment", () => {
    const prev = process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_KEY;
    try {
      const p = openai({ apiKey: "explicit", model: "gpt-4o-mini" });
      expect(p).toBeInstanceOf(OpenAIProvider);
    } finally {
      if (prev !== undefined) process.env.OPENAI_API_KEY = prev;
    }
  });

  it("anthropic() reads ANTHROPIC_API_KEY", () => {
    const prev = process.env.ANTHROPIC_API_KEY;
    process.env.ANTHROPIC_API_KEY = "test-key";
    try {
      const p = anthropic("claude-sonnet-4-6");
      expect(p).toBeInstanceOf(AnthropicProvider);
    } finally {
      if (prev === undefined) delete process.env.ANTHROPIC_API_KEY;
      else process.env.ANTHROPIC_API_KEY = prev;
    }
  });

  it("openai() throws ProviderConfigError when no key is configured", () => {
    const prev = process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_KEY;
    try {
      expect(() => openai("gpt-4o")).toThrow(/not configured/i);
    } finally {
      if (prev !== undefined) process.env.OPENAI_API_KEY = prev;
    }
  });
});
