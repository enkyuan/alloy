import { describe, expect, it } from "vitest";

import { generateText, streamText } from "@/runtime/oneshot";
import { MockProvider } from "@/providers/mock";
import { openai, anthropic, openrouter, kimi, gemini } from "@/providers/factory";
import { OpenAIProvider } from "@/providers/openai";
import { AnthropicProvider } from "@/providers/anthropic";
import type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "@/providers/base";
import type { ToolSpec } from "@/tools/registry";

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
          risk: "read",
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
  it("openai('gpt-5.4-mini') builds an OpenAIProvider with that model", () => {
    const prev = process.env.OPENAI_API_KEY;
    process.env.OPENAI_API_KEY = "test-key";
    try {
      const p = openai("gpt-5.4-mini");
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
      expect(() => openai("gpt-5.4-mini")).toThrow(/not configured/i);
    } finally {
      if (prev !== undefined) process.env.OPENAI_API_KEY = prev;
    }
  });
});

type ResolvedOpts = {
  apiKey: string;
  model: string;
  baseURL: string;
  defaultHeaders: Record<string, string> | undefined;
};

function readOpts(p: OpenAIProvider): ResolvedOpts {
  return (p as unknown as { opts: ResolvedOpts }).opts;
}

describe("openrouter factory", () => {
  it("points at the OpenRouter base URL and accepts a model string", () => {
    const prev = process.env.OPENROUTER_API_KEY;
    process.env.OPENROUTER_API_KEY = "or-key";
    try {
      const p = openrouter("meta-llama/llama-3.1-70b-instruct");
      expect(p).toBeInstanceOf(OpenAIProvider);
      const opts = readOpts(p);
      expect(opts.baseURL).toBe("https://openrouter.ai/api/v1");
      expect(opts.model).toBe("meta-llama/llama-3.1-70b-instruct");
      expect(opts.apiKey).toBe("or-key");
    } finally {
      if (prev === undefined) delete process.env.OPENROUTER_API_KEY;
      else process.env.OPENROUTER_API_KEY = prev;
    }
  });

  it("falls back to OPENAI_API_KEY when OPENROUTER_API_KEY is unset", () => {
    const prevOR = process.env.OPENROUTER_API_KEY;
    const prevOA = process.env.OPENAI_API_KEY;
    delete process.env.OPENROUTER_API_KEY;
    process.env.OPENAI_API_KEY = "fallback-key";
    try {
      const p = openrouter("anthropic/claude-3.5-sonnet");
      expect(readOpts(p).apiKey).toBe("fallback-key");
    } finally {
      if (prevOR !== undefined) process.env.OPENROUTER_API_KEY = prevOR;
      if (prevOA === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = prevOA;
    }
  });

  it("attaches HTTP-Referer and X-Title headers when provided", () => {
    const prev = process.env.OPENROUTER_API_KEY;
    process.env.OPENROUTER_API_KEY = "or-key";
    try {
      const p = openrouter({
        model: "openai/gpt-5.4-mini",
        httpReferer: "https://example.com",
        appTitle: "My Agent",
      });
      const headers = readOpts(p).defaultHeaders;
      expect(headers).toBeDefined();
      expect(headers!["HTTP-Referer"]).toBe("https://example.com");
      expect(headers!["X-Title"]).toBe("My Agent");
    } finally {
      if (prev === undefined) delete process.env.OPENROUTER_API_KEY;
      else process.env.OPENROUTER_API_KEY = prev;
    }
  });
});

describe("kimi factory", () => {
  it("defaults to the Moonshot Kimi model on OpenRouter", () => {
    const prev = process.env.OPENROUTER_API_KEY;
    process.env.OPENROUTER_API_KEY = "or-key";
    try {
      const p = kimi();
      const opts = readOpts(p);
      expect(opts.baseURL).toBe("https://openrouter.ai/api/v1");
      expect(opts.model).toMatch(/^moonshotai\/kimi/);
    } finally {
      if (prev === undefined) delete process.env.OPENROUTER_API_KEY;
      else process.env.OPENROUTER_API_KEY = prev;
    }
  });

  it("accepts a model-string override", () => {
    const prev = process.env.OPENROUTER_API_KEY;
    process.env.OPENROUTER_API_KEY = "or-key";
    try {
      const p = kimi("moonshotai/kimi-k2.6");
      expect(readOpts(p).model).toBe("moonshotai/kimi-k2.6");
    } finally {
      if (prev === undefined) delete process.env.OPENROUTER_API_KEY;
      else process.env.OPENROUTER_API_KEY = prev;
    }
  });
});

describe("gemini factory", () => {
  it("defaults to gemini-2.5-flash on the OpenAI-compatible endpoint", () => {
    const prev = process.env.GEMINI_API_KEY;
    process.env.GEMINI_API_KEY = "g-key";
    try {
      const p = gemini();
      const opts = readOpts(p);
      expect(opts.baseURL).toBe("https://generativelanguage.googleapis.com/v1beta/openai/");
      expect(opts.model).toBe("gemini-2.5-flash");
      expect(opts.apiKey).toBe("g-key");
    } finally {
      if (prev === undefined) delete process.env.GEMINI_API_KEY;
      else process.env.GEMINI_API_KEY = prev;
    }
  });

  it("accepts a model-string override", () => {
    const prev = process.env.GEMINI_API_KEY;
    process.env.GEMINI_API_KEY = "g-key";
    try {
      const p = gemini("gemini-2.5-pro");
      expect(readOpts(p).model).toBe("gemini-2.5-pro");
    } finally {
      if (prev === undefined) delete process.env.GEMINI_API_KEY;
      else process.env.GEMINI_API_KEY = prev;
    }
  });

  it("falls back to GOOGLE_API_KEY when GEMINI_API_KEY is unset", () => {
    const prevG = process.env.GEMINI_API_KEY;
    const prevGoog = process.env.GOOGLE_API_KEY;
    delete process.env.GEMINI_API_KEY;
    process.env.GOOGLE_API_KEY = "google-key";
    try {
      const p = gemini("gemini-2.5-flash");
      expect(readOpts(p).apiKey).toBe("google-key");
    } finally {
      if (prevG !== undefined) process.env.GEMINI_API_KEY = prevG;
      if (prevGoog === undefined) delete process.env.GOOGLE_API_KEY;
      else process.env.GOOGLE_API_KEY = prevGoog;
    }
  });

  it("respects an explicit apiKey over the environment", () => {
    const prev = process.env.GEMINI_API_KEY;
    process.env.GEMINI_API_KEY = "from-env";
    try {
      const p = gemini({ apiKey: "explicit", model: "gemini-2.5-flash" });
      expect(readOpts(p).apiKey).toBe("explicit");
    } finally {
      if (prev === undefined) delete process.env.GEMINI_API_KEY;
      else process.env.GEMINI_API_KEY = prev;
    }
  });
});
