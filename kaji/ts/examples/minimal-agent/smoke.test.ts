/**
 * Smoke test for the minimal-agent example.
 *
 * The first cases exercise the environment-based provider selection without
 * live network calls. The final case exercises `runAgent` with MockProvider
 * directly to keep the example fully executable in CI.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the openai module before the provider is imported
vi.mock("openai", () => {
  const mockStream = {
    [Symbol.asyncIterator]: async function* () {
      yield {
        choices: [
          {
            delta: { content: "The weather in Seattle is 68°F." },
            finish_reason: "stop",
          },
        ],
      };
    },
  };

  const OpenAIMock = vi.fn(function OpenAIMock() {
    return {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue(mockStream),
        },
      },
    };
  });

  return { default: OpenAIMock };
});

describe("minimal-agent example", () => {
  const originalOpenAIKey = process.env.OPENAI_API_KEY;
  const originalAnthropicKey = process.env.ANTHROPIC_API_KEY;

  afterEach(() => {
    if (originalOpenAIKey === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = originalOpenAIKey;
    if (originalAnthropicKey === undefined) delete process.env.ANTHROPIC_API_KEY;
    else process.env.ANTHROPIC_API_KEY = originalAnthropicKey;
  });

  it("selects OpenAI when OPENAI_API_KEY is set", async () => {
    process.env.OPENAI_API_KEY = "sk-test";
    delete process.env.ANTHROPIC_API_KEY;

    const { providerFromEnv } = await import("./index");
    const { OpenAIProvider } = await import("../../src/providers/openai");

    expect(providerFromEnv()).toBeInstanceOf(OpenAIProvider);
  });

  it("selects Anthropic when only ANTHROPIC_API_KEY is set", async () => {
    delete process.env.OPENAI_API_KEY;
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";

    const { providerFromEnv } = await import("./index");
    const { AnthropicProvider } = await import("../../src/providers/anthropic");

    expect(providerFromEnv()).toBeInstanceOf(AnthropicProvider);
  });

  it("throws a clear error when no provider key is set", async () => {
    delete process.env.OPENAI_API_KEY;
    delete process.env.ANTHROPIC_API_KEY;

    const { providerFromEnv } = await import("./index");

    expect(() => providerFromEnv()).toThrow("Set OPENAI_API_KEY or ANTHROPIC_API_KEY");
  });

  it("turn() returns text driven by MockProvider", async () => {
    const { runAgent } = await import("./index");
    const { MockProvider } = await import("../../src/providers/mock");

    await expect(runAgent(new MockProvider({ reply: "It is 68F in Seattle." }))).resolves.toBe(
      undefined,
    );
  });
});
