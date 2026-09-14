import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "../..");
const dist = resolve(root, "dist");
const legacyTaskSymbols = [
  "InvalidTaskTransitionError",
  "PendingApproval",
  "PendingApprovalSummary",
  "TaskCancelled",
  "TaskCompleted",
  "TaskCreated",
  "TaskFailed",
  "TaskHandle",
  "TaskNotFoundError",
  "TaskProjectionError",
  "TaskResumed",
  "TaskRuntime",
  "TaskSnapshot",
  "TaskState",
  "TaskSuspended",
  "projectTask",
] as const;

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
      readFileSync(resolve(root, "../../contracts/tiers/v1/features.json"), "utf8"),
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

  it("keeps the removed auth adapter surface out of the package", () => {
    expect(existsSync(resolve(root, "src/auth"))).toBe(false);
    expect(existsSync(resolve(dist, "auth.d.ts"))).toBe(false);
    expect(existsSync(resolve(dist, "auth.d.cts"))).toBe(false);
    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      const exports = declarationExportNames(declaration);
      expect(
        exports.filter((name) => /OAuth|Keychain|TokenStorage|TokenSet|Credential/u.test(name)),
      ).toEqual([]);
    }
  });

  it("keeps the removed integration adapter surface out of the package", () => {
    expect(existsSync(resolve(root, "src/integrations"))).toBe(false);
    expect(existsSync(resolve(dist, "integrations.d.ts"))).toBe(false);
    expect(existsSync(resolve(dist, "integrations.d.cts"))).toBe(false);
    expect(existsSync(resolve(dist, "integrations/github.d.ts"))).toBe(false);
    expect(existsSync(resolve(dist, "integrations/github.d.cts"))).toBe(false);
    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      const exports = declarationExportNames(declaration);
      for (const removed of [
        "INTEGRATION_RECOVERY",
        "IntegrationRecoveryFields",
        "IntegrationRecoveryReason",
        "closedRecoveryFields",
        "IntegrationAuthRequiredError",
        "IntegrationExecutionError",
        "IntegrationPolicyError",
        "IntegrationRateLimitedError",
        "IntegrationTransientReadError",
        "GitHubIntegration",
        "createGithubIntegration",
        "inspectIntegration",
        "snapshotIntegrationResult",
        "formatIntegrationError",
      ]) {
        expect(exports).not.toContain(removed);
      }
    }
    // The relocated recovery module keeps the closed recovery tuple internal
    // for the Postgres idempotency and event schema seams.
    const recovery = readFileSync(resolve(root, "src/recovery.ts"), "utf8");
    expect(recovery).toContain("export function closedRecoveryFields");
    expect(recovery).toContain("export function isClosedRecoveryTuple");
  });

  it("classifies every built root export exactly once and syncs the generated docs", () => {
    const declaration = readFreshDeclaration("index.d.ts", ["src/index.ts"]);
    const declaredExports = declarationExportNames(declaration);
    const exports = new Set(declaredExports);
    const contract = JSON.parse(
      readFileSync(resolve(root, "../../contracts/tiers/v1/features.json"), "utf8"),
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
    const docs = readFileSync(resolve(root, "../../../docs/kaji/api-parity.md"), "utf8");
    const actual = docs.match(
      /<!-- public-exports:typescript:start -->\n([\s\S]*?)\n<!-- public-exports:typescript:end -->/,
    )?.[1];
    expect(actual).toBe(fragment);
  });

  it("classifies retained features as core capability-execution surfaces", () => {
    const contract = JSON.parse(
      readFileSync(resolve(root, "../../contracts/tiers/v1/features.json"), "utf8"),
    );
    const byId: Map<string, { role?: unknown }> = new Map();
    for (const tier of ["stable", "experimental"] as const) {
      const entries = contract[tier] as Array<{ id: string; role?: unknown }>;
      for (const feature of entries) {
        byId.set(feature.id, feature);
      }
    }
    // The capability product has no compatibility lane: removed agent surfaces
    // must not be reintroduced as classified exports.
    expect(byId.get("kaji-execute")?.role).toBe("core");
    expect(byId.has("agent-builder")).toBe(false);
    expect(byId.has("runtime-turn-loop")).toBe(false);
    for (const feature of byId.values()) {
      expect(feature.role).toBe("core");
    }
  });

  it("keeps legacy Task symbols out of TypeScript source and root declarations", () => {
    expect(existsSync(resolve(root, "src/tasks"))).toBe(false);

    for (const source of ["src/index.ts", "src/events/schemas.ts", "src/events/types.ts"]) {
      const contents = readFileSync(resolve(root, source), "utf8");
      for (const symbol of legacyTaskSymbols) {
        expect(contents).not.toMatch(new RegExp(`\\b${symbol}\\b`));
      }
    }

    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      const exports = declarationExportNames(declaration);
      for (const symbol of legacyTaskSymbols) {
        expect(exports).not.toContain(symbol);
        expect(declaration).not.toMatch(new RegExp(`\\b${symbol}\\b`));
      }
    }
  });

  it("keeps the removed network transport and turn-loop surfaces out of root declarations", () => {
    expect(existsSync(resolve(root, "src/runtime/runtime.ts"))).toBe(false);
    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      for (const removed of [
        "SafeFetchPolicy",
        "BoundNetworkTransport",
        "safeRequest",
        "TurnAccounting",
        "TurnResult",
        "TurnOptions",
        "TokenUsage",
        "AgentBuilder",
        "AgentRuntime",
        "AgentStrategy",
        "RunTurnOptions",
        "StreamTextResult",
        "ModelResponse",
      ]) {
        expect(declaration).not.toMatch(new RegExp(`\\b${removed}\\b`));
      }
    }
  });

  it("exposes tool validation classes from both module formats", () => {
    const sources = ["src/index.ts", "src/tools/validation.ts"];
    for (const declaration of [
      readFreshDeclaration("index.d.ts", sources),
      readFreshDeclaration("index.d.cts", sources),
    ]) {
      expect(declaration).toContain("ToolArgumentValidationError");
      expect(declaration).toContain("ToolSchemaValidationError");
      expect(declaration).toContain("ToolSchemaValidator");
      for (const removed of [
        "normalizeProviderError",
        "NormalizedProviderError",
        "ProviderResponseLimits",
        "ProviderOutputLimitError",
      ]) {
        expect(declaration).not.toContain(removed);
      }
    }

    const declarationGraph = readdirSync(dist)
      .filter((file) => file.endsWith(".d.ts") || file.endsWith(".d.cts"))
      .map((file) => readFileSync(resolve(dist, file), "utf8"))
      .join("\n");
    expect(declarationGraph).not.toContain("interface ModelProviderOptions");
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

  it("keeps provider subpaths and test hooks out of the build", () => {
    expect(existsSync(resolve(root, "src/providers"))).toBe(false);
    for (const removed of [
      "openai.d.ts",
      "openai.d.cts",
      "anthropic.d.ts",
      "anthropic.d.cts",
      "testing.d.ts",
      "testing.d.cts",
      "openai.js",
      "testing.js",
    ]) {
      expect(existsSync(resolve(dist, removed)), `${removed} must stay removed`).toBe(false);
    }
    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      expect(declaration).not.toContain("OpenAIProviderTestHooks");
      expect(declaration).not.toContain("AnthropicProviderTestHooks");
      expect(declaration).not.toContain("RetryOptions");
    }
  });

  it("keeps every classified feature in the retained core", () => {
    const contract = JSON.parse(
      readFileSync(resolve(root, "../../contracts/tiers/v1/features.json"), "utf8"),
    ) as {
      stable: Array<{ id: string; surface: string; role?: string }>;
      experimental: Array<{ id: string; surface: string; role?: string }>;
    };

    for (const tier of ["stable", "experimental"] as const) {
      for (const feature of contract[tier]) {
        expect(feature.role, `${tier}/${feature.id} missing core role`).toBe("core");
      }
    }

    const roles = new Map(contract.stable.map((f) => [f.id, f.role] as const));
    expect(roles.get("kaji-execute")).toBe("core");
    expect(roles.has("agent-builder")).toBe(false);
    expect(roles.has("runtime-turn-loop")).toBe(false);
  });

  it("keeps optional provider peers out of root declarations", () => {
    for (const declaration of [
      readFreshDeclaration("index.d.ts", ["src/index.ts"]),
      readFreshDeclaration("index.d.cts", ["src/index.ts"]),
    ]) {
      expect(declaration).not.toMatch(/from ["']openai["']/);
      expect(declaration).not.toMatch(/from ["']@anthropic-ai\/sdk["']/);
      expect(declaration).not.toContain("Promise<OpenAI>");
      expect(declaration).not.toContain("Promise<Anthropic>");
    }
  });
});

describe("test hygiene", () => {
  it("keeps removed provider test subjects out of the tree", () => {
    expect(existsSync(resolve(root, "tests/providers"))).toBe(false);
    const source = readFileSync(resolve(root, "src/index.ts"), "utf8");
    expect(source).not.toContain("ForTest");
  });
});
