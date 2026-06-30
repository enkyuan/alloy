/**
 * Integration smoke test for OpenAIProvider.
 *
 * Requires OPENAI_API_KEY to be set. Skipped automatically when absent.
 *
 * Run manually:
 *   OPENAI_API_KEY=sk-... bun run test:integration
 */
import { describe, expect, it } from "vitest";

import { OpenAIProvider } from "@/providers/openai";
import { hasKey } from "./helpers";

describe.skipIf(!hasKey("OPENAI_API_KEY"))("OpenAIProvider (live)", () => {
  it("generate() returns non-empty content for a simple prompt", async () => {
    const provider = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! });
    const response = await provider.generate(
      [{ role: "user", content: "Say hello in one word." }],
      [],
    );

    expect(typeof response.content).toBe("string");
    expect(response.content.trim().length).toBeGreaterThan(0);
  });

  it("generateStream() yields at least one text delta", async () => {
    const provider = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY! });
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
