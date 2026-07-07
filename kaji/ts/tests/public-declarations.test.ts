import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");

describe("public declarations", () => {
  it("does not expose provider test hooks after build", () => {
    const openaiDts = resolve(dist, "openai.d.ts");
    const anthropicDts = resolve(dist, "anthropic.d.ts");
    if (!existsSync(openaiDts) || !existsSync(anthropicDts)) return;
    const newestProviderSource = Math.max(
      statSync(resolve(root, "src/providers/openai.ts")).mtimeMs,
      statSync(resolve(root, "src/providers/anthropic.ts")).mtimeMs,
    );
    const oldestProviderDts = Math.min(statSync(openaiDts).mtimeMs, statSync(anthropicDts).mtimeMs);
    if (oldestProviderDts < newestProviderSource) return;

    const openai = readFileSync(openaiDts, "utf8");
    const anthropic = readFileSync(anthropicDts, "utf8");

    expect(openai).not.toContain("OpenAIProviderTestHooks");
    expect(anthropic).not.toContain("AnthropicProviderTestHooks");
  });
});

describe("test hygiene", () => {
  it("provider tests do not cast into private provider internals", () => {
    const files = ["tests/openai-provider.test.ts", "tests/provider-factory.test.ts"];

    for (const file of files) {
      const source = readFileSync(resolve(root, file), "utf8");
      expect(source).not.toContain("buildMessages(m:");
      expect(source).not.toContain("{ opts:");
      expect(source).not.toContain("}).opts");
    }
  });
});
