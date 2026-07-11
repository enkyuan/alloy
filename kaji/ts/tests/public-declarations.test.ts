import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");

describe("public declarations", () => {
  it("exposes the bounded network transport contract from the package root", () => {
    const esm = resolve(dist, "index.d.ts");
    const cjs = resolve(dist, "index.d.cts");
    if (!existsSync(esm) || !existsSync(cjs)) return;
    if (statSync(esm).mtimeMs < statSync(resolve(root, "src/integrations/safe-fetch.ts")).mtimeMs)
      return;

    for (const declaration of [readFileSync(esm, "utf8"), readFileSync(cjs, "utf8")]) {
      expect(declaration).toContain("interface SafeFetchPolicy");
      expect(declaration).toContain("interface BoundNetworkTransport");
      expect(declaration).toContain("function safeRequest(");
    }
  });

  it("exposes tool validation classes from both module formats", () => {
    const esm = resolve(dist, "index.d.ts");
    const cjs = resolve(dist, "index.d.cts");
    if (!existsSync(esm) || !existsSync(cjs)) return;
    if (statSync(esm).mtimeMs < statSync(resolve(root, "src/tools/validation.ts")).mtimeMs) return;

    for (const declaration of [readFileSync(esm, "utf8"), readFileSync(cjs, "utf8")]) {
      expect(declaration).toContain("ToolArgumentValidationError");
      expect(declaration).toContain("ToolSchemaValidationError");
      expect(declaration).toContain("ToolSchemaValidator");
    }

    const declarationGraph = readdirSync(dist)
      .filter((file) => file.endsWith(".d.ts") || file.endsWith(".d.cts"))
      .map((file) => readFileSync(resolve(dist, file), "utf8"))
      .join("\n");
    expect(declarationGraph).toContain("interface TurnContext");
    expect(declarationGraph).toContain("interface ToolExecutionContext");
    expect(declarationGraph).toContain(
      "type ToolExecutor = (name: string, args: Readonly<Record<string, unknown>>, context: ToolExecutionContext)",
    );
    expect(declarationGraph).toContain("readonly risk: ToolRisk");
    expect(declarationGraph).toContain(
      "type ToolHandler = (args: Record<string, unknown>, context: ToolExecutionContext)",
    );
    expect(declarationGraph).not.toContain("ToolValidationReceipt");
    expect(declarationGraph).not.toContain("claim(receipt");
    expect(declarationGraph).not.toContain("claimActive(");
    expect(declarationGraph).not.toContain("revokeValidationReceipt");
    expect(declarationGraph).not.toContain("validateAsync(");
  });

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
