/**
 * Integration smoke test for AnthropicProvider.
 *
 * Requires ANTHROPIC_API_KEY to be set. Skipped automatically when absent.
 *
 * Run manually:
 *   ANTHROPIC_API_KEY=sk-ant-... bun run test:integration
 */
import { describe, expect, it } from "vitest";

import { AnthropicProvider } from "@/providers/anthropic";
import { hasKey } from "./helpers";

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

  it("returns one normalized tool call", async () => {
    const marker = "kaji-anthropic-live-marker";
    const provider = new AnthropicProvider({
      apiKey: process.env.ANTHROPIC_API_KEY!,
      model: process.env.KAJI_LIVE_ANTHROPIC_MODEL,
      temperature: 0,
    });
    const response = await provider.generate(
      [
        {
          role: "user",
          content: `Call echo_probe exactly once with marker ${marker}. Do not answer with plain text.`,
        },
      ],
      [
        {
          name: "echo_probe",
          description: "Echo a marker for release verification.",
          parameters: {
            type: "object",
            properties: { marker: { type: "string" } },
            required: ["marker"],
            additionalProperties: false,
          },
          risk: "read",
        },
      ],
    );

    expect(response.toolCalls).toHaveLength(1);
    expect(response.toolCalls[0]!.name).toBe("echo_probe");
    expect(response.toolCalls[0]!.args).toEqual({ marker });
    expect(response.toolCalls[0]!.id).toBeTruthy();
  });
});
