/**
 * Smoke test for the minimal-agent example.
 *
 * The first case exercises `runAgent` with a mocked openai client to keep
 * the upstream example file fully exercised end-to-end. The second case
 * exercises the same shape against `MockProvider` directly to keep the
 * provider mocking surface area small.
 */
import { describe, expect, it, vi } from "vitest";

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
  it("runs runAgent end-to-end with a mocked openai client", async () => {
    const { runAgent } = await import("./index");
    await expect(runAgent("test-key")).resolves.not.toThrow();
  });

  it("turn() returns text driven by MockProvider", async () => {
    const { AgentBuilder, EventBus, InMemoryEventStore } = await import("../../src/index");
    const { MockProvider } = await import("../../src/providers/mock");

    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "It is 68F in Seattle." }))
      .systemPrompt("Test")
      .build({ bus: new EventBus(), store: new InMemoryEventStore() });

    const result = await runtime.turn("What's the weather in Seattle?");
    expect(result.text).toBe("It is 68F in Seattle.");
    expect(result.sessionId).toBeTruthy();
  });
});
