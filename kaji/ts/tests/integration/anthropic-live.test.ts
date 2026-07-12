/**
 * Integration smoke test for AnthropicProvider.
 *
 * Requires ANTHROPIC_API_KEY to be set. Skipped automatically when absent.
 *
 * Run manually:
 *   ANTHROPIC_API_KEY=sk-ant-... bun run test:integration
 */
import { describe, expect, it } from "vitest";

import { AgentBuilder, EventBus, EventType, InMemoryEventStore, ToolRegistry } from "@/index";
import { AnthropicProvider } from "@/providers/anthropic";
import { hasKey } from "./helpers";

class EchoProbeIntegration {
  register(registry: ToolRegistry): void {
    registry.register(
      {
        name: "probe_echo_probe",
        catalogName: "probe.echo_probe",
        description: "Echo the supplied marker back to the caller.",
        parameters: {
          type: "object",
          properties: { marker: { type: "string" } },
          required: ["marker"],
          additionalProperties: false,
        },
        risk: "read",
      },
      async (args) => ({
        marker: String(args.marker),
        source: "kaji-live-tool-loop",
      }),
    );
  }
}

describe.skipIf(!hasKey("ANTHROPIC_API_KEY"))("AnthropicProvider (live)", () => {
  it("generate() returns non-empty content for a simple prompt", async () => {
    const provider = new AnthropicProvider({ apiKey: process.env.ANTHROPIC_API_KEY! });
    const response = await provider.generate(
      [{ role: "user", content: "Say hello in one word." }],
      [],
    );

    expect(typeof response.content).toBe("string");
    expect(response.content.trim().length).toBeGreaterThan(0);
  });

  it("generateStream() yields at least one text delta", async () => {
    const provider = new AnthropicProvider({ apiKey: process.env.ANTHROPIC_API_KEY! });
    const chunks: string[] = [];

    for await (const chunk of provider.generateStream(
      [{ role: "user", content: "Say hello in one word." }],
      [],
    )) {
      if (chunk.delta) chunks.push(chunk.delta);
    }

    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks.join("").trim().length).toBeGreaterThan(0);
  });

  it("executes a real model-requested tool and then emits final text", async () => {
    const marker = "kaji-anthropic-live-marker";
    const runtime = new AgentBuilder()
      .provider(
        new AnthropicProvider({
          apiKey: process.env.ANTHROPIC_API_KEY!,
          model: process.env.KAJI_LIVE_ANTHROPIC_MODEL,
          temperature: 0,
        }),
      )
      .integration(new EchoProbeIntegration())
      .defaultContext({ principalId: "anthropic-live" })
      .systemPrompt(
        "You are testing SDK tool execution. You must call the `probe_echo_probe` " +
          "tool exactly once with the marker from the user message before giving a final answer.",
      )
      .build({ bus: new EventBus(), store: new InMemoryEventStore() });

    const result = await runtime.turn(
      `Call \`probe_echo_probe\` with marker \`${marker}\`. ` +
        "After the tool returns, answer with the marker value.",
      { sessionId: "anthropic-live-tool-loop" },
    );

    const eventTypes = result.events.map((event) => event.type);
    const requested = result.events.filter((event) => event.type === EventType.TOOL_CALL_REQUESTED);
    const completed = result.events.filter((event) => event.type === EventType.TOOL_CALL_COMPLETED);
    expect(requested).toHaveLength(1);
    expect(completed).toHaveLength(1);
    expect(requested[0]!.tool_call_id).toBe(completed[0]!.tool_call_id);
    expect(eventTypes).toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(eventTypes).not.toContain(EventType.TOOL_CALL_FAILED);
    expect(eventTypes).not.toContain(EventType.AGENT_TURN_EXHAUSTED);
    expect(result.toolCallEvents).toHaveLength(1);
    expect(result.text).toContain(marker);
  });
});
