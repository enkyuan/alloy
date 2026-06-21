/**
 * Smoke test for the minimal-agent example.
 *
 * Uses a mocked OpenAI client — no API key required. Verifies the example
 * code path runs end-to-end (imports, wiring, event emission) without a
 * real network call.
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
  it("runs the full agent loop and emits events", async () => {
    const { runAgent } = await import("./index");

    // runAgent imports OpenAIProvider which now uses the mocked openai client
    await expect(runAgent("test-key")).resolves.not.toThrow();
  });

  it("produces AGENT_MESSAGE_COMPLETED in the event log", async () => {
    const {
      AgentBuilder,
      EventBus,
      InMemoryEventStore,
      OpenAIProvider,
      AgentKitEvent,
      EventType: ET,
    } = await import("../../src/index");

    const store = new InMemoryEventStore();
    const bus = new EventBus();

    const runtime = new AgentBuilder()
      .provider(new OpenAIProvider({ apiKey: "test-key" }))
      .systemPrompt("Test")
      .build({ bus, store });

    await store.append(AgentKitEvent.parse({ type: ET.SESSION_CREATED, session_id: "s-smoke" }));
    await runtime.send("s-smoke", "hello");

    const events = await store.getEvents("s-smoke");
    const types = events.map((e) => e.type);
    expect(types).toContain(ET.AGENT_MESSAGE_COMPLETED);
  });
});
