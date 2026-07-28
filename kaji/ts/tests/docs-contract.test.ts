import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../../..");
const packageRoot = resolve(repoRoot, "kaji/ts");

function read(path: string): string {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

function snippet(document: string, name: string, language: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const marker = (edge: "start" | "end") =>
    `(?:<!-- ${escaped}:${edge} -->|\\{/\\* ${escaped}:${edge} \\*/\\})`;
  const pattern =
    marker("start") + "\\s*`{3}" + language + "\\n([\\s\\S]*?)\\n[ \\t]*`{3}\\s*" + marker("end");
  const matches = [...document.matchAll(new RegExp(pattern, "gu"))];
  expect(matches, `expected exactly one ${name}`).toHaveLength(1);
  return matches[0]?.[1] ?? "";
}

function tokenFreeEnvironment(): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {
    ...process.env,
    BUN_CONFIG_REGISTRY: "http://127.0.0.1:9",
    npm_config_registry: "http://127.0.0.1:9",
  };
  for (const name of [
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
  ]) {
    delete environment[name];
  }
  return environment;
}

type GitHubExampleFailure = "build" | "provider-drain" | "unsettled";

async function executeGitHubExampleFailure(
  source: string,
  failure: GitHubExampleFailure,
): Promise<{
  readonly error: unknown;
  readonly githubCloseCalls: number;
  readonly runtimeCloseCalls: number;
  readonly closeEvents: readonly string[];
}> {
  let githubCloseCalls = 0;
  let runtimeCloseCalls = 0;
  const closeEvents: string[] = [];
  const runtime = {
    async turn() {
      return { text: "ok" };
    },
    async drainTools() {
      return failure === "unsettled" ? ["tool-call"] : [];
    },
    async drainProviders() {
      if (failure === "provider-drain") throw new Error("provider drain failed");
      return failure === "unsettled" ? ["session"] : [];
    },
    close() {
      runtimeCloseCalls += 1;
      closeEvents.push("runtime.close");
    },
  };
  class TestAgentBuilder {
    provider(): this {
      return this;
    }
    integration(): this {
      return this;
    }
    defaultContext(): this {
      return this;
    }
    systemPrompt(): this {
      return this;
    }
    build() {
      if (failure === "build") throw new Error("runtime build failed");
      return runtime;
    }
  }
  class TestOpenAIProvider {
    constructor(_options: unknown) {}
  }
  const executable = source
    .replace(/^import .*;\n/gmu, "")
    .replace("process.env.OPENAI_API_KEY!", "process.env.OPENAI_API_KEY");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor as new (
    ...arguments_: string[]
  ) => (...values: unknown[]) => Promise<void>;
  const run = new AsyncFunction(
    "AgentBuilder",
    "OpenAIProvider",
    "deadlineAfter",
    "createGithubIntegration",
    "process",
    "console",
    `"use strict";\n${executable}`,
  );
  let error: unknown;
  try {
    await run(
      TestAgentBuilder,
      TestOpenAIProvider,
      () => Date.now() + 30_000,
      () => ({
        close() {
          githubCloseCalls += 1;
          closeEvents.push("github.close");
        },
      }),
      { env: { OPENAI_API_KEY: "provider-key", GITHUB_TOKEN: "github-token" } },
      { log() {} },
    );
  } catch (caught) {
    error = caught;
  }
  return { error, githubCloseCalls, runtimeCloseCalls, closeEvents };
}

describe("cross-SDK release matrix docs", () => {
  it("executes the exact offline TypeScript examples", () => {
    const gettingStarted = snippet(
      read("apps/docs/content/getting-started.mdx"),
      "getting-started:no-key:typescript",
      "ts",
    );
    const eventDelivery = snippet(
      read("apps/docs/content/concepts/event-bus.mdx"),
      "event-delivery:typescript",
      "ts",
    );
    const onboarding = snippet(
      read("docs/kaji/typescript-onboarding-evidence.md"),
      "tthw-echo:typescript",
      "ts",
    );
    const workdir = mkdtempSync(resolve(packageRoot, ".docs-contract-onboarding-"));
    try {
      mkdirSync(resolve(workdir, "echo"));
      copyFileSync(
        resolve(packageRoot, "registry/echo/index.ts"),
        resolve(workdir, "echo/index.ts"),
      );
      writeFileSync(resolve(workdir, "getting-started.mts"), gettingStarted);
      writeFileSync(resolve(workdir, "event-delivery.mts"), eventDelivery);
      writeFileSync(resolve(workdir, "echo-loop.mts"), onboarding);
      const environment = tokenFreeEnvironment();
      const noKey = execFileSync("bun", ["getting-started.mts"], {
        cwd: workdir,
        env: environment,
        encoding: "utf8",
      });
      const delivery = execFileSync("bun", ["event-delivery.mts"], {
        cwd: workdir,
        env: environment,
        encoding: "utf8",
      });
      const echo = execFileSync("bun", ["echo-loop.mts"], {
        cwd: workdir,
        env: environment,
        encoding: "utf8",
      });
      expect(noKey.trim()).toBe("The mock provider has completed the tool loop.");
      expect(delivery).toContain("agent.message.completed");
      expect(echo.trim()).toBe("PASS: echo requested, started, completed, and observed");
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("limits automated onboarding claims to the two protected Linux cells", () => {
    const guide = read("docs/kaji/typescript-onboarding-evidence.md");
    const normalizedGuide = guide.replace(/\s+/gu, " ");
    const activeDocs = [
      guide,
      read("docs/kaji/testing.md"),
      read("docs/kaji/README.md"),
      read("kaji/RELEASE_MATRIX.md"),
      read("SUPPORT.md"),
    ].join("\n");

    for (const required of [
      "GitHub-hosted Linux/x64",
      "Node 22",
      "`ubuntu-22.04`",
      "Node 24",
      "`ubuntu-24.04`",
      "npm and Bun",
      "scaffold",
      "no-key",
      "Echo",
      "cold",
      "warm",
    ]) {
      expect(activeDocs).toContain(required);
    }

    for (const excludedClaim of [
      "five-user TTHW",
      "five human participants",
      "arm64 macOS users",
      "human TTHW remains",
      "validated TTHW regressions",
      "KAJI_TTHW_EVIDENCE_JSON",
      "approve_tthw_gate.py",
    ]) {
      expect(activeDocs).not.toContain(excludedClaim);
    }

    for (const explicitLimit of [
      "not a five-human measurement",
      "not a macOS or arm64 onboarding claim",
      "not a Windows onboarding claim",
      "not a fully offline dependency-installation claim",
    ]) {
      expect(normalizedGuide).toContain(explicitLimit);
    }
  });

  it("defines privileged journal recovery and disposal boundaries", () => {
    const readme = read("kaji/ts/README.md");
    const production = read("docs/kaji/production-beta.md");
    const ordering = read("docs/kaji/concurrency-and-ordering.md");

    for (const source of [readme, production]) {
      const document = source.replace(/\s+/gu, " ");
      expect(document).toContain("privileged full-fidelity journal");
      expect(document).toContain("not redaction-safe");
      expect(document).toContain("preselected session ID");
      expect(document).toContain("exclusive `afterSequence` cursor");
      expect(document).toContain("page until an empty page");
      expect(document).toContain("reduce to an allowlist");
      expect(document).toContain("best-effort timing and correlation");
      expect(document).toContain("does not delete retained history");
    }

    for (const source of [readme, production, ordering]) {
      const document = source.replace(/\s+/gu, " ");
      expect(document).toContain("VM string zeroization");
      expect(document).toContain("stop ingress");
      expect(document).toContain("process-local");
    }

    const normalizedReadme = readme.replace(/\s+/gu, " ");
    const normalizedProduction = production.replace(/\s+/gu, " ");
    const normalizedOrdering = ordering.replace(/\s+/gu, " ");
    expect(normalizedReadme).toContain("failed turns have no `TurnResult`");
    expect(normalizedReadme).toContain("generic provider failures have no durable recovery code");
    expect(normalizedReadme).toContain("releaseSettled()");
    expect(normalizedReadme).toContain("host ledger cleanup");
    expect(normalizedReadme).toContain("pageHistory");
    expect(normalizedReadme).toContain("safeJournalEvidence");
    expect(normalizedReadme).toContain("append-only while retained");

    const recoveryBlock = [...readme.matchAll(/```ts\n([\s\S]*?)\n```/gu)]
      .map((match) => match[1] ?? "")
      .find((block) => block.includes("stopIngress(sessionId)"));
    expect(recoveryBlock, "missing runnable failure-recovery block").toBeDefined();
    const compactRecovery = recoveryBlock?.replace(/\s+/gu, "") ?? "";
    const recoverySteps = [
      "stopIngress(sessionId)",
      "awaitruntime.drainTools(10_000)",
      "awaitruntime.drainProviders(10_000)",
      "awaitpageHistory(runtime,sessionId)",
      "handleEvidenceExportError(evidenceError)",
      "awaitruntime.purgeSession(sessionId)",
      "handleOriginalError(failure.error)",
    ];
    let priorStep = -1;
    for (const step of recoverySteps) {
      const nextStep = compactRecovery.indexOf(step);
      expect(nextStep, `missing or misordered recovery step: ${step}`).toBeGreaterThan(priorStep);
      priorStep = nextStep;
    }
    expect(compactRecovery).toContain("}finally{awaitruntime.purgeSession(sessionId);}");

    const pythonQuickstart = snippet(production, "installed-quickstart:python", "python");
    const typescriptQuickstart = snippet(production, "installed-quickstart:typescript", "ts");
    expect(pythonQuickstart).toContain("event.turn_id == text.turn_id");
    expect(typescriptQuickstart).toContain("event.turn_id === text.turnId");

    const pythonOutput = pythonQuickstart
      .split("\n")
      .filter((line) => /\bprint\s*\(/u.test(line))
      .join("\n");
    const typescriptOutput = typescriptQuickstart
      .split("\n")
      .filter((line) => /\bconsole\.(?:log|info|debug|warn|error)\s*\(/u.test(line))
      .join("\n");
    expect(pythonOutput).not.toMatch(/session_id|turn_id|\.sequence|\.events/u);
    expect(typescriptOutput).not.toMatch(/sessionId|turnId|\.sequence|\.events/u);

    expect(normalizedProduction).toContain("Provider or timeout failure");
    expect(normalizedProduction).toContain("Ordinary terminal tool failure");
    expect(normalizedProduction).toContain("Mid-provider cooperative cancellation");
    expect(normalizedProduction).toContain("Failure-event append failure");
    expect(normalizedProduction).toContain("## Cross-SDK session purge");
    expect(normalizedProduction).toContain("Both SDKs use the same session lifecycle");
    expect(normalizedProduction).toContain("public one-argument store capability");
    expect(normalizedProduction).toContain("internal coordinated capability");
    expect(normalizedProduction).toContain("cleanup_pending");
    expect(normalizedProduction).toContain("`TurnAccounting` remains TypeScript-only");
    expect(normalizedOrdering).toContain(
      "direct append, event reads, last-sequence reads, transactions, and subscription registration",
    );
    expect(normalizedOrdering).toContain("old subscribers terminate normally");
    expect(normalizedOrdering).toContain("Split delivery remains purge-unsupported");
    expect(normalizedProduction).toContain(
      "ships no persistent event store or distributed coordinator",
    );
    expect(normalizedProduction).toContain("does not release-certify host implementations");
    expect(normalizedProduction).toContain("durability, deletion, and cross-process correctness");

    expect(normalizedOrdering).toContain("cursor did not advance");
    expect(normalizedOrdering).toContain("reset the cursor to `0` after purge");
    expect(normalizedOrdering).toContain("privileged journal warning");
    expect(normalizedOrdering).toContain("does not cancel already-active work");
  });

  it("keeps stable core, experimental, and not-ported surfaces explicit", () => {
    const combined = [
      read("kaji/RELEASE_MATRIX.md"),
      read("kaji/README.md"),
      read("kaji/ts/README.md"),
      read("docs/MVP.md"),
    ].join("\n");

    for (const phrase of [
      "Stable core",
      "Experimental Python-only",
      "TypeScript Not Ported",
      "OpenAI-compatible factories",
      "Redis realtime/history",
      "voice/TTS",
      "DocumentRAG",
      "Keyed OpenAI proof",
      "gpt-5.4-mini",
      "Promotion criteria",
      "TS not ported",
    ]) {
      expect(combined).toContain(phrase);
    }

    const tsReadme = read("kaji/ts/README.md");
    expect(tsReadme).toContain("TS not ported");
    expect(tsReadme).toContain("OpenAI-compatible factories");
  });

  it("does not describe the manifest contract as missing", () => {
    const mvp = read("docs/MVP.md");

    expect(mvp).toContain("Catalog contract implemented");
    expect(mvp).toContain(
      "Plan 3 - Define the first-party integration catalog contract (implemented)",
    );
    expect(mvp).not.toContain("Catalog contract still open");
    expect(mvp).not.toContain("no shared manifest/auth/credential shape");
  });

  it("keeps the two-entry catalog and experimental quarantine explicit", () => {
    const readme = read("kaji/ts/README.md");
    expect(readme).toContain("--allow-experimental");
    expect(readme).toContain("`echo` is the only beta catalog entry");
    expect(readme).toContain("`github` is the only experimental");
  });

  it("documents, typechecks, and failure-tests read-only packaged GitHub wiring", async () => {
    const readme = read("kaji/ts/README.md");
    const guide = read("apps/docs/content/integrations/github.mdx");
    const index = read("apps/docs/content/integrations/index.mdx");
    const readmeExample = snippet(readme, "docs-test:github-read-only", "ts");
    const guideExample = snippet(guide, "docs-test:github-read-only", "ts");

    expect(guideExample).toBe(readmeExample);
    expect(readmeExample).toContain('from "kaji-sdk/integrations/github"');
    expect(readmeExample).toContain('toolExposure: "read-only"');
    expect(readmeExample).toContain("await runtime.drainTools(10_000)");
    expect(readmeExample).toContain("github.close()");
    expect(index).toContain("6 copied / 15 packaged TS");
    const registry = JSON.parse(read("kaji/ts/registry/index.json")) as {
      integrations: Record<string, unknown>;
    };
    const documentedIntegrations = [...index.matchAll(/^\| `([^`]+)`\s+\|/gmu)].map(
      ([, name]) => name,
    );
    expect(documentedIntegrations).toEqual(Object.keys(registry.integrations));
    for (const absent of ["fs", "http", "sqlite", "web"]) {
      expect(index).not.toContain(`| \`${absent}\``);
    }
    expect(guide).toContain('The compatibility default, `toolExposure: "all"`');
    expect(guide).toContain("model-exposure boundary, not a token");
    expect(guide).toContain("raw Actions logs, GraphQL, blame, GitHub Enterprise Server");

    const workdir = mkdtempSync(resolve(packageRoot, ".docs-contract-github-"));
    try {
      writeFileSync(resolve(workdir, "github.mts"), readmeExample);
      writeFileSync(
        resolve(workdir, "tsconfig.json"),
        JSON.stringify({
          extends: "../tsconfig.json",
          compilerOptions: { noEmit: true },
          include: ["*.mts"],
        }),
      );
      execFileSync(
        "node",
        [resolve(packageRoot, "node_modules/typescript/bin/tsc"), "--project", "tsconfig.json"],
        { cwd: workdir, stdio: "inherit" },
      );
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }

    for (const failure of ["build", "provider-drain", "unsettled"] as const) {
      const result = await executeGitHubExampleFailure(readmeExample, failure);
      expect(result.error, failure).toBeInstanceOf(Error);
      expect(result.githubCloseCalls, `${failure}: GitHub close`).toBe(1);
      expect(result.runtimeCloseCalls, `${failure}: runtime close`).toBe(
        failure === "build" ? 0 : 1,
      );
      expect(result.closeEvents, `${failure}: close order`).toEqual(
        failure === "build" ? ["github.close"] : ["runtime.close", "github.close"],
      );
    }
  }, 30_000);

  it("matches the machine-readable beta feature tiers exactly", () => {
    const tiers = JSON.parse(read("kaji/contracts/feature-tiers-v1.json")) as Record<
      "stable" | "experimental",
      Array<{ id: string; surface: string }>
    >;
    const matrix = read("kaji/RELEASE_MATRIX.md");

    for (const tier of ["stable", "experimental"] as const) {
      const marker = matrix.match(new RegExp(`<!-- beta-${tier}:\\s*([^>]*) -->`));
      expect(marker).not.toBeNull();
      const actual = (marker?.[1] ?? "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
        .sort();
      expect(actual).toEqual(tiers[tier].map(({ id }) => id).sort());
    }

    const stableSection = matrix.split("## Stable Core", 2)[1]?.split("\n## ", 1)[0] ?? "";
    for (const { surface } of tiers.stable) {
      expect(stableSection).toContain(`| ${surface} | Stable core | Stable core |`);
    }
  });

  it("matches both integration registry stability indexes", () => {
    const matrix = read("kaji/RELEASE_MATRIX.md");
    const python = JSON.parse(read("kaji/src/kaji/integrations/registry/index.json")) as {
      integrations: Record<string, { stability: string; runtimes: string[] }>;
    };
    const typescript = JSON.parse(read("kaji/ts/registry/index.json")) as {
      integrations: Record<string, { stability: string; runtimes: string[] }>;
    };
    const entries = { ...typescript.integrations, ...python.integrations };

    for (const [name, entry] of Object.entries(entries)) {
      expect(matrix).toContain(`| ${name} | ${entry.stability} | ${entry.runtimes.join(", ")} |`);
    }
  });

  it("typechecks and runs every current TypeScript migration snippet", () => {
    const migration = read("docs/kaji/migrating-to-beta.md");
    const names = [
      "docs-test:typescript-migration-after",
      "docs-test:typescript-approval-after",
      "docs-test:typescript-risk-context-before",
      "docs-test:typescript-risk-context-after",
      "docs-test:typescript-cursor-before",
      "docs-test:typescript-cursor-after",
      "docs-test:typescript-zod-before",
      "docs-test:typescript-zod-after",
    ];
    const workdir = mkdtempSync(resolve(packageRoot, ".docs-contract-"));
    try {
      for (const [index, name] of names.entries()) {
        writeFileSync(resolve(workdir, `${index}.mts`), snippet(migration, name, "ts"));
      }
      writeFileSync(
        resolve(workdir, "tsconfig.json"),
        JSON.stringify({
          extends: "../tsconfig.json",
          compilerOptions: { noEmit: true },
          include: ["*.mts"],
        }),
      );
      execFileSync(
        "node",
        [resolve(packageRoot, "node_modules/typescript/bin/tsc"), "--project", "tsconfig.json"],
        { cwd: workdir, stdio: "inherit" },
      );
      for (const index of names.keys()) {
        execFileSync("bun", [resolve(workdir, `${index}.mts`)], {
          cwd: packageRoot,
          stdio: "pipe",
        });
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("executes manifest and index migrations as invalid/valid schema pairs", () => {
    const migration = read("docs/kaji/migrating-to-beta.md");
    const manifestBefore = JSON.parse(snippet(migration, "docs-test:manifest-before", "json"));
    const manifestAfter = JSON.parse(snippet(migration, "docs-test:manifest-after", "json"));
    const indexBefore = JSON.parse(snippet(migration, "docs-test:index-before", "json"));
    const indexAfter = JSON.parse(snippet(migration, "docs-test:index-after", "json"));
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    const validateManifest = ajv.compile(
      JSON.parse(read("kaji/contracts/integrations/manifest.schema.json")),
    );
    const validateIndex = ajv.compile(
      JSON.parse(read("kaji/contracts/integrations/index.schema.json")),
    );

    expect(validateManifest(manifestBefore)).toBe(false);
    expect(validateManifest(manifestAfter)).toBe(true);
    expect(validateIndex(indexBefore)).toBe(false);
    expect(validateIndex(indexAfter)).toBe(true);
  });
});
