/**
 * Integration smoke test for AnthropicProvider.
 *
 * Requires ANTHROPIC_API_KEY to be set. The entire suite is skipped when the
 * key is absent so CI stays green without credentials.
 *
 * Run manually:
 *   ANTHROPIC_API_KEY=sk-ant-... bun run test:integration
 */
import { describe, expect, it } from "vitest";

import { AnthropicProvider } from "@/providers/anthropic";

const apiKey = process.env.ANTHROPIC_API_KEY;

describe.skipIf(!apiKey)("AnthropicProvider integration", () => {
  it("generate() returns a non-empty content string for a simple prompt", async () => {
    const provider = new AnthropicProvider({ apiKey: apiKey! });

    const response = await provider.generate(
      [{ role: "user", content: "Say hello in one word." }],
      [],
    );

    expect(typeof response.content).toBe("string");
    expect(response.content.trim().length).toBeGreaterThan(0);
  });
});
