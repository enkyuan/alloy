/**
 * Integration smoke test for OpenAIProvider.
 *
 * Requires OPENAI_API_KEY to be set. The entire suite is skipped when the key
 * is absent so CI stays green without credentials.
 *
 * Run manually:
 *   OPENAI_API_KEY=sk-... bun run test:integration
 */
import { describe, expect, it } from "vitest";

import { OpenAIProvider } from "@/providers/openai";

const apiKey = process.env.OPENAI_API_KEY;

describe.skipIf(!apiKey)("OpenAIProvider integration", () => {
  it("generate() returns a non-empty content string for a simple prompt", async () => {
    const provider = new OpenAIProvider({ apiKey: apiKey! });

    const response = await provider.generate(
      [{ role: "user", content: "Say hello in one word." }],
      [],
    );

    expect(typeof response.content).toBe("string");
    expect(response.content.trim().length).toBeGreaterThan(0);
  });
});
