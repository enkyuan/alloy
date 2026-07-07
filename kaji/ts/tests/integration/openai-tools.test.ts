/**
 * Live OpenAI agent tool-loop proof.
 *
 * Requires OPENAI_API_KEY. Defaults to gpt-5.4-mini and can be overridden with
 * KAJI_LIVE_OPENAI_MODEL.
 *
 * Run manually:
 *   OPENAI_API_KEY=sk-... bun run test:integration tests/integration/openai-tools.test.ts
 */
import { describe, expect, it } from "vitest";

import { AgentBuilder, EventBus, EventType, InMemoryEventStore, ToolRegistry } from "@/index";
import { OpenAIProvider } from "@/providers/openai";
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
      async (_ctx, args) => ({
        marker: String(args.marker),
        source: "kaji-live-tool-loop",
      }),
    );
  }
}

describe.skipIf(!hasKey("OPENAI_API_KEY"))("OpenAI agent tool loop (live)", () => {
  it("executes a real model-requested tool and then emits final text", async () => {
    const marker = "kaji-live-tool-loop-marker";
    const model = process.env.KAJI_LIVE_OPENAI_MODEL ?? "gpt-5.4-mini";
    const store = new InMemoryEventStore();

    const runtime = new AgentBuilder()
      .provider(
        new OpenAIProvider({
          apiKey: process.env.OPENAI_API_KEY!,
          model,
          temperature: 0,
        }),
      )
      .integration(new EchoProbeIntegration())
      .systemPrompt(
        "You are testing SDK tool execution. You must call the `probe_echo_probe` " +
          "tool exactly once with the marker from the user message before giving a final answer.",
      )
      .build({ bus: new EventBus(), store });

    const result = await runtime.turn(
      `Call \`probe_echo_probe\` with marker \`${marker}\`. ` +
        "After the tool returns, answer with the marker value.",
      { sessionId: "openai-live-tool-loop" },
    );

    const eventTypes = result.events.map((event) => event.type);
    expect(eventTypes).toContain(EventType.TOOL_CALL_REQUESTED);
    expect(eventTypes).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(eventTypes).toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(eventTypes).not.toContain(EventType.AGENT_TURN_EXHAUSTED);
    expect(result.toolCallEvents.length).toBeGreaterThanOrEqual(1);
    expect(result.text).toContain(marker);
  });
});
