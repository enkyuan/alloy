import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");

function readFreshDeclaration(file: string, sourceFiles: string[]): string {
  const declarationPath = resolve(dist, file);
  expect(existsSync(declarationPath), `${file} must exist; run the package build first`).toBe(true);
  const builtAt = statSync(declarationPath).mtimeMs;
  for (const sourceFile of sourceFiles) {
    const sourcePath = resolve(root, sourceFile);
    expect(
      builtAt,
      `${file} is older than ${sourceFile}; rebuild declarations before running this gate`,
    ).toBeGreaterThanOrEqual(statSync(sourcePath).mtimeMs);
  }
  return readFileSync(declarationPath, "utf8");
}

function declarationExportNames(declaration: string): string[] {
  const blocks = [...declaration.matchAll(/^export \{ (.*?) \}(?: from .*?)?;$/gm)];
  expect(blocks.length).toBeGreaterThan(0);
  const names = blocks.flatMap((match) =>
    match[1]!.split(", ").map(
      (item) =>
        item
          .replace(/^type /, "")
          .split(" as ")
          .at(-1)!,
    ),
  );
  expect(new Set(names).size).toBe(names.length);
  return names.sort();
}

describe("public declarations", () => {
  it("matches every non-CLI subpath contract in both module formats", () => {
    const contract = JSON.parse(
      readFileSync(resolve(root, "../contracts/feature-tiers-v1.json"), "utf8"),
    ) as {
      packageSubpaths: {
        typescript: Record<string, { exports: string[] }>;
      };
    };

    for (const [subpath, entry] of Object.entries(contract.packageSubpaths.typescript)) {
      if (subpath === "./cli") continue;
      const stem = subpath.slice(2);
      for (const suffix of [".d.ts", ".d.cts"]) {
        const declaration = readFreshDeclaration(`${stem}${suffix}`, ["tsup.config.ts"]);
        expect(declarationExportNames(declaration)).toEqual(entry.exports);
      }
    }
  });

  it("exposes only the experimental OAuth and Keychain auth surface", () => {
    const sources = ["src/auth/index.ts", "src/auth/oauth.ts", "src/auth/keychain.ts"];
    for (const declaration of [
      readFreshDeclaration("auth.d.ts", sources),
      readFreshDeclaration("auth.d.cts", sources),
    ]) {
      const exports = declarationExportNames(declaration);
      for (const internal of [
        "KeychainProcess",
        "_createGoogleOAuthClientForTest",
        "_createMacOSKeychainTokenStorageForTest",
        "validateOAuthPrincipal",
      ]) {
        expect(exports).not.toContain(internal);
      }
    }
  });

  it("exposes only the experimental fixed-origin integration surface", () => {
    const sources = [
      "src/integrations/public.ts",
      "src/integrations/fixed-origin.ts",
      "src/integrations/safe-fetch.ts",
    ];
    for (const declaration of [
      readFreshDeclaration("integrations.d.ts", sources),
      readFreshDeclaration("integrations.d.cts", sources),
    ]) {
      const exports = declarationExportNames(declaration);
      const executionError = declaration.match(
        /declare class IntegrationExecutionError extends ToolExecutionError \{[\s\S]*?\n\}/,
      )?.[0];
      expect(executionError).toContain('constructor(reasonCode: "api_rejected");');
      expect(executionError).not.toContain("errorCode");
      expect(executionError).not.toContain("retryable");
      for (const internal of [
        "FixedOriginTestTransport",
        "FixedOriginTestResponse",
        "fixedOriginForTest",
        "IntegrationTransportError",
        "IntegrationAuthError",
        "INTEGRATION_RECOVERY",
        "closedRecoveryFields",
        "closedTransportFailureFields",
        "FixedOriginPolicy",
        "NodeHttpsTransport",
        "CERTIFIED_FAILURES",
        "CertifiedIntegrationReason",
      ]) {
        expect(exports).not.toContain(internal);
      }
    }
  });

  it("exposes only safe GitHub package construction options", () => {
    const sources = [
      "src/integrations/github.ts",
      "src/integrations/github-package-internal.ts",
      "registry/github/index.ts",
      "registry/github/client.ts",
    ];
    for (const declaration of [
      readFreshDeclaration("integrations/github.d.ts", sources),
      readFreshDeclaration("integrations/github.d.cts", sources),
    ]) {
      expect(declarationExportNames(declaration)).toEqual([
        "CreateGitHubIntegrationOptions",
        "GitHubIntegration",
        "createGithubIntegration",
        "inspectIntegration",
      ]);
      expect(declaration).toContain("constructor(options: CreateGitHubIntegrationOptions);");
      expect(declaration).toContain('readonly toolExposure?: "read-only" | "all";');
      expect(declaration).not.toMatch(
        /GitHubClient|FixedOriginRequester|GitHubClientOptions|PackageGitHubRuntime|\bhttp\b|\brequester\b|\btransport\b/,
      );
    }
  });

  it("classifies every built root export exactly once and syncs the generated docs", () => {
    const declaration = readFreshDeclaration("index.d.ts", ["src/index.ts"]);
    const declaredExports = declarationExportNames(declaration);
    const exports = new Set(declaredExports);
    const contract = JSON.parse(
      readFileSync(resolve(root, "../contracts/feature-tiers-v1.json"), "utf8"),
    );
    const tiers = contract.publicExports.typescript as Record<string, string[]>;
    const classified = Object.values(tiers).flat();

    expect(new Set(classified).size).toBe(classified.length);
    expect(new Set(classified)).toEqual(exports);

    const fragment = [
      "### TypeScript public exports",
      ...["stable", "experimental", "deprecated"].map((tier) => {
        const exports = tiers[tier]!.map((name) => `\`${name}\``).join(", ") || "none";
        return `- ${tier[0]!.toUpperCase()}${tier.slice(1)}: ${exports}`;
      }),
    ].join("\n");
    const docs = readFileSync(resolve(root, "../../docs/kaji/api-parity.md"), "utf8");
    const actual = docs.match(
      /<!-- public-exports:typescript:start -->\n([\s\S]*?)\n<!-- public-exports:typescript:end -->/,
    )?.[1];
    expect(actual).toBe(fragment);
  });

  it("exposes the bounded network transport contract from the package root", () => {
    const sources = ["src/index.ts", "src/integrations/safe-fetch.ts"];
    for (const declaration of [
      readFreshDeclaration("index.d.ts", sources),
      readFreshDeclaration("index.d.cts", sources),
    ]) {
      expect(declaration).toContain("interface SafeFetchPolicy");
      expect(declaration).toContain("interface BoundNetworkTransport");
      expect(declaration).toContain("function safeRequest(");
    }
  });

  it("exposes frozen successful-turn accounting from both module formats", () => {
    const sources = ["src/index.ts", "src/runtime/runtime.ts"];
    for (const declaration of [
      readFreshDeclaration("index.d.ts", sources),
      readFreshDeclaration("index.d.cts", sources),
    ]) {
      expect(declaration).toContain("interface TurnAccounting");
      expect(declaration).toContain("readonly providerIterations: number");
      expect(declaration).toContain("readonly usage: Readonly<TokenUsage> | null");
      expect(declaration).toContain("readonly usageComplete: boolean");
      expect(declaration).toContain("readonly costUsd: number | null");
      expect(declaration).toContain("readonly costComplete: boolean");
      expect(declaration).toMatch(/interface TurnResult \{[\s\S]*?accounting: TurnAccounting;/);
    }
  });

  it("exposes tool validation classes from both module formats", () => {
    const sources = ["src/index.ts", "src/tools/validation.ts"];
    for (const declaration of [
      readFreshDeclaration("index.d.ts", sources),
      readFreshDeclaration("index.d.cts", sources),
    ]) {
      expect(declaration).toContain("normalizeProviderError");
      expect(declaration).toContain("NormalizedProviderError");
      expect(declaration).toContain("ToolArgumentValidationError");
      expect(declaration).toContain("ToolSchemaValidationError");
      expect(declaration).toContain("ToolSchemaValidator");
      expect(declaration).toContain("ProviderResponseLimits");
      expect(declaration).toContain("ProviderOutputLimitError");
    }

    const declarationGraph = readdirSync(dist)
      .filter((file) => file.endsWith(".d.ts") || file.endsWith(".d.cts"))
      .map((file) => readFileSync(resolve(dist, file), "utf8"))
      .join("\n");
    const providerOptions = declarationGraph.match(
      /interface ModelProviderOptions \{[\s\S]*?\n\}/,
    )?.[0];
    expect(providerOptions).toBeDefined();
    expect(providerOptions).not.toContain("responseDiagnostics");
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
    const openai = readFreshDeclaration("openai.d.ts", ["src/providers/openai.ts"]);
    const anthropic = readFreshDeclaration("anthropic.d.ts", ["src/providers/anthropic.ts"]);

    expect(openai).not.toContain("OpenAIProviderTestHooks");
    expect(anthropic).not.toContain("AnthropicProviderTestHooks");
  });

  it("preserves RetryOptions on the OpenAI provider subpath", () => {
    const openai = readFreshDeclaration("openai.d.ts", ["src/providers/openai.ts"]);
    expect(openai).toContain("RetryOptions");
  });

  it("keeps optional provider peers out of root declarations", () => {
    const sources = ["src/index.ts", "src/providers/openai.ts", "src/providers/anthropic.ts"];
    for (const declaration of [
      readFreshDeclaration("index.d.ts", sources),
      readFreshDeclaration("index.d.cts", sources),
    ]) {
      expect(declaration).not.toMatch(/from ["']openai["']/);
      expect(declaration).not.toMatch(/from ["']@anthropic-ai\/sdk["']/);
      expect(declaration).not.toContain("Promise<OpenAI>");
      expect(declaration).not.toContain("Promise<Anthropic>");
    }
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
