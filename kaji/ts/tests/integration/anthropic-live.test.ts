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
});
