import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  cpSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";

import { assertCliListOutput } from "../scripts/cli_assertions";
import {
  finalizeSmokeRun,
  ordinaryFailureReceipt,
  SmokeCommandError,
  type PendingSmokeReceipt,
  type SmokeFinalizerDependencies,
} from "../scripts/smoke_package.mts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, "..");
const canonicalRoot = resolve(packageRoot, "../contracts");
const repositoryRoot = resolve(packageRoot, "../..");
const SYNC_CHILD_TIMEOUT_MS = 20_000;
const SYNC_CHILD_MAX_BUFFER = 16 * 1024 * 1024;

const CANONICAL_ECHO_ROW = {
  name: "echo",
  version: "0.1.0",
  stability: "beta",
  runtimes: ["python", "typescript"],
  auth: { kind: "none", provider: null },
  experimental_opt_in_required: false,
  next_commands: {
    python: "python -m kaji.cli add echo",
    typescript: "bun --no-install -e 'import(\"@kaji/sdk/cli\")' -- add echo",
  },
};

const CANONICAL_GITHUB_ROW = {
  name: "github",
  version: "0.1.0",
  stability: "experimental",
  runtimes: ["python", "typescript"],
  auth: { kind: "env", provider: null },
  experimental_opt_in_required: true,
  next_commands: {
    python: "python -m kaji.cli add github --allow-experimental",
    typescript:
      "bun --no-install -e 'import(\"@kaji/sdk/cli\")' -- add github --allow-experimental",
  },
};

const GITHUB_SHARED_ABI = JSON.parse(
  readFileSync(join(canonicalRoot, "integrations/github-tool-abi-v1.json"), "utf8"),
) as {
  version: "1.0.0";
  tools: ReadonlyArray<{ name: string; risk?: unknown }>;
};
const GITHUB_PACKAGE_ABI = JSON.parse(
  readFileSync(join(canonicalRoot, "integrations/github-tool-abi-typescript-v1.json"), "utf8"),
) as {
  schema_version: "1.0.0";
  catalog_version: "0.2.0";
  tools: ReadonlyArray<{ name: string; risk?: unknown }>;
};
const GITHUB_COPIED_MANIFEST = JSON.parse(
  readFileSync(join(packageRoot, "registry/github/manifest.json"), "utf8"),
) as {
  version: "0.1.0";
  tools: ReadonlyArray<{ name: string; risk?: unknown }>;
};
const GITHUB_API_FIXTURE = JSON.parse(
  readFileSync(join(canonicalRoot, "integrations/github-api-conformance-v1.json"), "utf8"),
) as { version: "1.0.0"; cases: readonly unknown[] };
const CURRENT_TYPESCRIPT_VERSION = (
  JSON.parse(readFileSync(join(packageRoot, "node_modules/typescript/package.json"), "utf8")) as {
    version: string;
  }
).version;
const GITHUB_PUBLIC_SCENARIOS = [
  "conditional-exports",
  "class-identity",
  "private-source-containment",
  "declaration-privacy",
  "catalog-inspection",
  "public-registration",
  "closed-lifecycle",
  "repository-policy",
  "observability-sinks",
  "approval-rejection",
  "validation-failure",
  "execution-failure",
  "synthetic-completed-event",
  "mock-provider-loop",
  "alias-collision",
] as const;

const PRIVATE_GITHUB_COMPOSITION_SOURCE_CANARIES = [
  "export interface PackageGitHubRuntime",
  "export function createPackageGitHubToolBindings(",
  "readonly createRequester: (observability:",
  "readonly createClient: (options: GitHubClientOptions)",
  "runtime: PackageGitHubRuntime = productionRuntime",
  "Preserve the client construction failure that prevented ownership transfer.",
] as const;

const GITHUB_PACKAGE_PROOF = {
  schemaVersion: 5,
  evidenceClass: "offline_exact_artifact_smoke",
  integration: "github",
  runtime: "typescript",
  network: "blocked",
  liveProvider: false,
  sharedAbiVersion: GITHUB_SHARED_ABI.version,
  packageAbiSchemaVersion: GITHUB_PACKAGE_ABI.schema_version,
  packageCatalogVersion: GITHUB_PACKAGE_ABI.catalog_version,
  apiFixtureVersion: GITHUB_API_FIXTURE.version,
  sharedFixtureCaseCount: GITHUB_API_FIXTURE.cases.length,
  publicScenarioCount: GITHUB_PUBLIC_SCENARIOS.length,
  packageCatalog: {
    schemaVersion: GITHUB_PACKAGE_ABI.schema_version,
    catalogVersion: GITHUB_PACKAGE_ABI.catalog_version,
    toolCount: GITHUB_PACKAGE_ABI.tools.length,
    readToolCount: GITHUB_PACKAGE_ABI.tools.filter((tool) => tool.risk === "read").length,
    tools: GITHUB_PACKAGE_ABI.tools.map((tool) => tool.name),
    readTools: GITHUB_PACKAGE_ABI.tools
      .filter((tool) => tool.risk === "read")
      .map((tool) => tool.name),
    providerAliases: GITHUB_PACKAGE_ABI.tools.map((tool) => `github_${tool.name}`),
    catalogNames: GITHUB_PACKAGE_ABI.tools.map((tool) => `github.${tool.name}`),
  },
  cliCopiedCatalog: {
    manifestVersion: GITHUB_COPIED_MANIFEST.version,
    toolCount: GITHUB_COPIED_MANIFEST.tools.length,
    readToolCount: GITHUB_COPIED_MANIFEST.tools.filter((tool) => tool.risk === "read").length,
    tools: GITHUB_COPIED_MANIFEST.tools.map((tool) => tool.name),
    readTools: GITHUB_COPIED_MANIFEST.tools
      .filter((tool) => tool.risk === "read")
      .map((tool) => tool.name),
  },
  esmSharedAbiMatched: true,
  cjsSharedAbiMatched: true,
  esmPackageAbiMatched: true,
  cjsPackageAbiMatched: true,
  esmClassIdentityMatched: true,
  cjsClassIdentityMatched: true,
  esmFactoryIdentityMatched: true,
  cjsFactoryIdentityMatched: true,
  esmRuntimeExports: ["GitHubIntegration", "createGithubIntegration", "inspectIntegration"],
  cjsRuntimeExports: ["GitHubIntegration", "createGithubIntegration", "inspectIntegration"],
  esmDeclarationExports: [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ],
  cjsDeclarationExports: [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ],
  typescriptDeclarationChecks: {
    compilerOptions: {
      module: "NodeNext",
      moduleResolution: "NodeNext",
      skipLibCheck: false,
    },
    typescript57: { version: "5.7.3", mtsImport: "passed", ctsRequire: "passed" },
    typescriptCurrent: {
      version: CURRENT_TYPESCRIPT_VERSION,
      mtsImport: "passed",
      ctsRequire: "passed",
    },
  },
  privateGitHubCompositionSourcesPacked: false,
  privateGitHubCompositionSourceImportsRejected: true,
  closedCallsDeniedBeforeCredentialAccess: true,
  approvalDeniedBeforeCredentialAccess: true,
  repositoryDeniedBeforeCredentialAccess: true,
  githubCatalogEventsVerified: ["requested", "started", "failed"],
  genericSyntheticCatalogEventsVerified: ["requested", "started", "completed"],
  githubFailureRecovery: {
    error_code: "INTEGRATION_AUTH_REQUIRED",
    reason_code: "github_token_missing",
    recovery_code: "CONFIGURE_GITHUB_TOKEN",
    doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-token",
  },
  githubObservabilitySinksVerified: true,
  unknownMutationPreserved: true,
  mutationRetries: 0,
  lifecycle: {
    githubFailure: {
      stages: ["requested", "started", "failed"],
      providerAlias: "github_get_file",
      catalogName: "github.get_file",
      sameIdentityAtEveryStage: true,
    },
    syntheticCompletion: {
      stages: ["requested", "started", "completed"],
      providerAlias: "synthetic_complete",
      catalogName: "synthetic.complete",
      sameIdentityAtEveryStage: true,
    },
  },
  policyBeforeRequest: {
    testFile: "kaji/ts/tests/github-registry.test.ts",
    testName: "rejects approval for github_create_issue before token or HTTP",
    tokenLookups: 0,
    requestAttempts: 0,
  },
  aliasCollisionRejected: true,
  conclusion: "passed",
  failureCode: null,
};

const EXPECTED_PACKED_REGISTRY_FILES = [
  "registry/echo/index.ts",
  "registry/echo/manifest.json",
  "registry/github/LICENSE",
  "registry/github/client.ts",
  "registry/github/github_vitest.ts",
  "registry/github/index.ts",
  "registry/github/manifest.json",
  "registry/github/owner-fixtures.json",
  "registry/index.json",
  "registry/index.schema.json",
  "registry/schema.json",
] as const;

interface SyncChildOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

function runText(command: string, args: string[], options: SyncChildOptions = {}): string {
  return execFileSync(command, args, {
    ...options,
    encoding: "utf8",
    timeout: SYNC_CHILD_TIMEOUT_MS,
    maxBuffer: SYNC_CHILD_MAX_BUFFER,
  });
}

function runBytes(command: string, args: string[], options: SyncChildOptions = {}): Buffer {
  return execFileSync(command, args, {
    ...options,
    timeout: SYNC_CHILD_TIMEOUT_MS,
    maxBuffer: SYNC_CHILD_MAX_BUFFER,
  });
}

function contractFiles(root: string, directory = root): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...contractFiles(root, path));
    } else if (entry.name.endsWith(".json") || entry.name.endsWith(".md")) {
      files.push(relative(root, path).replaceAll("\\", "/"));
    }
  }
  return files.sort();
}

function exportTargets(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value !== "object" || value === null) return [];
  return Object.values(value).flatMap(exportTargets);
}

describe("npm contract artifact", () => {
  it("pins the installed-release consumer dependency closure", () => {
    const fixture = resolve(repositoryRoot, "kaji/scripts/installed-typescript-runtime");
    const manifest = JSON.parse(readFileSync(join(fixture, "package.json"), "utf8"));
    const lock = JSON.parse(readFileSync(join(fixture, "package-lock.json"), "utf8"));

    expect(lock.lockfileVersion).toBe(3);
    expect(lock.packages[""].dependencies).toEqual(manifest.dependencies);
    expect(manifest.dependencies["@kaji/sdk"]).toBe("file:kaji-sdk-0.2.0-beta.2.tgz");
    expect(lock.packages["node_modules/@kaji/sdk"].version).toBe("0.2.0-beta.2");
    expect(lock.packages["node_modules/@kaji/sdk"].resolved).toBe("file:kaji-sdk-0.2.0-beta.2.tgz");
    expect(manifest.dependencies["@kaji/sdk"]).not.toBe("file:kaji-sdk-0.2.0-beta.1.tgz");
    for (const [name, value] of Object.entries(lock.packages) as Array<
      [string, { resolved?: string; integrity?: string }]
    >) {
      if (name === "" || name === "node_modules/@kaji/sdk") continue;
      expect(value.resolved).toMatch(/^https:\/\/registry\.npmjs\.org\//);
      expect(value.integrity).toMatch(/^sha512-[A-Za-z0-9+/]+={0,2}$/);
    }
  });

  it("keeps the installed provider proof public-only and receipt-redacted", () => {
    const source = readFileSync(join(packageRoot, "scripts/installed-provider-proof.mts"), "utf8");

    expect(source).toContain('from "@kaji/sdk"');
    expect(source).toContain('from "@kaji/sdk/openai"');
    expect(source).toContain('from "@kaji/sdk/anthropic"');
    expect(source).toContain('import.meta.resolve("@kaji/sdk")');
    expect(source).toContain(".build({ store: new InMemoryEventStore() })");
    for (const field of [
      "sdk",
      "provider",
      "proof",
      "status",
      "model",
      "resolvedPackage",
      "requestedToolCalls",
      "completedToolCalls",
      "requestedToolCallIds",
      "completedToolCallIds",
      "echoResultMatched",
      "finalTextPresent",
      "forbiddenTerminalEvents",
    ]) {
      expect(source).toContain(`${field}:`);
    }
    expect(source).not.toContain("../src");
    expect(source).not.toContain("/dist/");
    expect(source).not.toContain("JSON.stringify(result)");
    expect(source).not.toContain("console.error(error");
    expect(source).not.toContain("...process.env");
    expect(source).not.toContain("finalText:");
    expect(source).not.toContain("echoResult:");
  });

  it("runs the source benchmark without consulting clean or stale dist subpaths", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-source-benchmark-"));
    const checkout = join(workdir, "sdk");
    try {
      mkdirSync(join(checkout, "benchmarks"), { recursive: true });
      cpSync(join(packageRoot, "src"), join(checkout, "src"), { recursive: true });
      cpSync(join(packageRoot, "contracts"), join(checkout, "contracts"), { recursive: true });
      cpSync(
        join(packageRoot, "benchmarks/runtime-benchmark.ts"),
        join(checkout, "benchmarks/runtime-benchmark.ts"),
      );
      cpSync(join(packageRoot, "package.json"), join(checkout, "package.json"));
      cpSync(join(packageRoot, "tsconfig.json"), join(checkout, "tsconfig.json"));
      symlinkSync(join(packageRoot, "node_modules"), join(checkout, "node_modules"));
      mkdirSync(join(checkout, "dist"));
      for (const file of ["index.js", "openai.js", "testing.js"]) {
        writeFileSync(join(checkout, "dist", file), 'throw new Error("stale dist loaded");\n');
      }

      const sample = JSON.parse(
        runText(
          "bun",
          ["benchmarks/runtime-benchmark.ts", "--worker-case", "replay10k", "--seed", "13"],
          { cwd: checkout },
        ),
      ) as { case: string; completed: number };

      expect(sample.case).toBe("replay10k");
      expect(sample.completed).toBe(10_000);
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("accepts only the exact canonical Echo list row", () => {
    expect(() =>
      assertCliListOutput(JSON.stringify([CANONICAL_ECHO_ROW, CANONICAL_GITHUB_ROW])),
    ).not.toThrow();
  });

  it.each([
    [
      "experimental Echo",
      JSON.stringify([{ ...CANONICAL_ECHO_ROW, stability: "experimental" }, CANONICAL_GITHUB_ROW]),
    ],
    [
      "wrong Echo version",
      JSON.stringify([{ ...CANONICAL_ECHO_ROW, version: "9.9.9" }, CANONICAL_GITHUB_ROW]),
    ],
    [
      "wrong Echo auth",
      JSON.stringify([
        { ...CANONICAL_ECHO_ROW, auth: { kind: "env", provider: null } },
        CANONICAL_GITHUB_ROW,
      ]),
    ],
    ["incomplete Echo row", JSON.stringify([{ name: "echo" }, CANONICAL_GITHUB_ROW])],
    [
      "duplicate Echo row",
      JSON.stringify([CANONICAL_ECHO_ROW, CANONICAL_ECHO_ROW, CANONICAL_GITHUB_ROW]),
    ],
    ["malformed sibling row", JSON.stringify([CANONICAL_ECHO_ROW, null, CANONICAL_GITHUB_ROW])],
    ["missing GitHub row", JSON.stringify([CANONICAL_ECHO_ROW])],
  ])("rejects the %s", (_label, output) => {
    expect(() => assertCliListOutput(output)).toThrow();
  });

  it("keeps every synchronous artifact child bounded below the test timeout", () => {
    const source = readFileSync(fileURLToPath(import.meta.url), "utf8");

    expect([...source.matchAll(/\bexecFileSync\(/g)]).toHaveLength(2);
    expect(source).toContain("timeout: SYNC_CHILD_TIMEOUT_MS");
    expect(source).toContain("maxBuffer: SYNC_CHILD_MAX_BUFFER");
    expect(SYNC_CHILD_TIMEOUT_MS).toBeLessThan(30_000);
  });

  it("declares the tested runtime/compiler matrix and canonical package URLs", () => {
    const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));

    expect(manifest.engines.node).toBe("22.x || 24.x");
    expect(manifest.devDependencies.typescript57).toBe("npm:typescript@5.7.3");
    expect(manifest.repository).toEqual({
      type: "git",
      url: "https://github.com/enkyuan/alloy.git",
      directory: "kaji/ts",
    });
    expect(manifest.homepage).toBe(
      "https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md",
    );
    expect(manifest.bugs).toEqual({ url: "https://github.com/enkyuan/alloy/issues" });
  });

  it("exports the cwd-independent package-qualified CLI entry", () => {
    const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
    const buildConfig = readFileSync(join(packageRoot, "tsup.config.ts"), "utf8");
    const entry = readFileSync(join(packageRoot, "src/cli/package-entry.ts"), "utf8");

    expect(manifest.exports["./cli"]).toEqual({
      import: {
        types: "./dist/cli/package-entry.d.ts",
        default: "./dist/cli/package-entry.js",
      },
      require: {
        types: "./dist/cli/package-entry-cjs.d.cts",
        default: "./dist/cli/package-entry-cjs.cjs",
      },
    });
    expect(buildConfig).toContain('"src/cli/package-entry.ts"');
    expect(buildConfig).toContain('"src/cli/package-entry-cjs.ts"');
    expect(buildConfig).toContain("dts: true");
    expect(entry).toContain("process.argv.slice(1)");
  });

  it("exports the canonical GitHub package subpath", () => {
    const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
    const buildConfig = readFileSync(join(packageRoot, "tsup.config.ts"), "utf8");

    expect(manifest.exports["./integrations/github"]).toEqual({
      import: {
        types: "./dist/integrations/github.d.ts",
        default: "./dist/integrations/github.js",
      },
      require: {
        types: "./dist/integrations/github.d.cts",
        default: "./dist/integrations/github.cjs",
      },
    });
    expect(buildConfig).toContain('"integrations/github": "src/integrations/github.ts"');
  });

  it("smokes generated npm and Bun projects with both supported compiler lines", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const tiers = JSON.parse(
      readFileSync(join(canonicalRoot, "feature-tiers-v1.json"), "utf8"),
    ) as {
      cliCommands: { typescript: { stable: string[] } };
      packageSubpaths: { typescript: Record<string, unknown> };
    };

    expect(tiers.cliCommands.typescript.stable).toEqual([
      "add",
      "connect",
      "disconnect",
      "init",
      "list-integrations",
      "replay",
    ]);
    expect(tiers.packageSubpaths.typescript["./cli"]).toEqual({
      tier: "stable",
      exports: [],
    });
    expect(Object.keys(tiers.packageSubpaths.typescript).sort()).toEqual([
      "./anthropic",
      "./auth",
      "./cli",
      "./integrations",
      "./integrations/github",
      "./openai",
      "./testing",
    ]);
    expect(tiers.packageSubpaths.typescript["./integrations/github"]).toEqual({
      tier: "experimental",
      exports: [
        "CreateGitHubIntegrationOptions",
        "GitHubIntegration",
        "createGithubIntegration",
        "inspectIntegration",
      ],
    });
    expect(tiers.packageSubpaths.typescript["./openai"]).toEqual({
      tier: "stable",
      exports: ["OpenAIProvider", "OpenAIProviderOptions", "RetryOptions"],
    });
    expect(tiers.packageSubpaths.typescript["./anthropic"]).toEqual({
      tier: "stable",
      exports: ["AnthropicProvider", "AnthropicProviderOptions"],
    });
    expect(tiers.packageSubpaths.typescript["./testing"]).toEqual({
      tier: "experimental",
      exports: [
        "MockProvider",
        "ProviderResponseDiagnostics",
        "createSessionState",
        "withProviderResponseDiagnostics",
      ],
    });

    for (const required of [
      "assertGeneratedVersions",
      'runScaffold("npm"',
      'runScaffold("bun"',
      "typescript57",
      '"typescript"',
      "skipLibCheck: false",
      'types: ["node"]',
      "coldSetupToOutputMs",
      "warmRunMs",
      "assertRootDeclarationsVendorNeutral",
      'generated.devDependencies["@types/node"]',
      'installed.devDependencies["@types/node"]',
      'generated.devDependencies["@dotenvx/dotenvx"]',
      'installed.devDependencies["@dotenvx/dotenvx"]',
      "const nodeTypesPackage = `@types/node@${nodeTypesRange}`",
      "type SmokePhase =",
      "error instanceof CommandError",
      "new SmokeCommandError(phase, classifyCommandFailure(error))",
      "`${manager}:${stage}-install`",
      "`${manager}:cli-init`",
      "`${manager}:cli-owner-conflict`",
      "`${manager}:cli-owner-qualified`",
      "`${manager}:cli-add`",
      "`${manager}:cli-inspect`",
      "`${manager}:cli-list`",
      "`${manager}:cli-replay`",
      "assertCliInitOutput(initOutput, generated)",
      "assertCliAddOutput(addOutput, echo, installedPackageRoot)",
      "assertExperimentalDenial(denialOutput, deniedGithub)",
      "includeStderr = false",
      "includeStderr ? `${completed.stdout}\\n${completed.stderr}` : completed.stdout",
      "assertGithubCliAddOutput(githubOutput, github, installedPackageRoot)",
      "assertGithubPackageProof",
      'const githubProofRunner = join(bootstrap, "installed-github-smoke.mts");',
      "copyFileSync(INSTALLED_GITHUB_SMOKE, githubProofRunner)",
      "`${manager}:github-package-proof`",
      '"--sandbox-root"',
      '"--package-root"',
      'from "@kaji/sdk/integrations/github"',
      'import * as github from "@kaji/sdk/integrations/github";',
      'const github = require("@kaji/sdk/integrations/github");',
      'writeFileSync(join(generated, "github-types.mts"), GITHUB_ESM_TYPES_SOURCE)',
      'writeFileSync(join(generated, "github-types.cts"), GITHUB_CJS_TYPES_SOURCE)',
      "githubPackageProofs: { npm: npmTiming.githubProof, bun: bunTiming.githubProof }",
      "const typescriptDeclarationChecks = await compileInstalledGitHubTypes(manager, generated)",
      "assertCliListOutput(listOutput)",
      "assertCliReplayOutput(replayOutput)",
      "createConflictingKajiFixture(root)",
      "conflicting kaji fixture was not installed",
      'const nestedWorkdir = join(bootstrap, "nested", "deeper")',
      'BUN_CONFIG_REGISTRY: "http://127.0.0.1:9"',
      "nestedConflictProof: true",
      'const cli = ["--no-install", "-e", \'import("@kaji/sdk/cli")\', "--"]',
      "assertCliOwnerOutput(ownerOutput)",
      '[...cli, "--no-color", "add", "echo", "--out", echo]',
      '[...cli, "--no-color", "add", "github", "--out", deniedGithub]',
      '[...cli, "--no-color", "add", "github", "--allow-experimental", "--out", github]',
      '[...cli, "--no-color", "list-integrations", "--json"]',
      '[...cli, "--no-color", "replay", replayFixture, "--format", "summary"]',
      'join(installedPackageRoot, "registry/echo/index.ts")',
      'const github = join(bootstrap, "owner-integrations/github");',
      'const githubModule = JSON.stringify(join(github, "index.ts"));',
      "readFileSync(copied).equals(readFileSync(packaged))",
      'type: "session.created"',
      "sequence: 1",
      "errors=0, seq=1-1",
      "packages.length === 0",
      '["install", "--ignore-scripts"]',
      'await install(manager, "generated"',
      "`${manager}:compile-typescript-5.7`",
      "`${manager}:compile-typescript-current`",
      "`${manager}:cold-run`",
      "`${manager}:warm-run`",
      'const EXPECTED_MOCK_REPLY = "The mock provider has completed the tool loop."',
      'fields.get("text") !== EXPECTED_MOCK_REPLY',
      "`${manager}:lifecycle-run`",
      "`${manager}:failure-history-run`",
      "const LIFECYCLE_SMOKE_SOURCE = `import {",
      "const FAILURE_HISTORY_SMOKE_SOURCE = `import {",
      "type TurnAccounting,",
      "const accounting: TurnAccounting = result.accounting;",
      "accounting.providerIterations !== 1",
      "!Object.isFrozen(accounting)",
      "await runtime.drainTools(graceMs);",
      "await runtime.drainProviders(graceMs);",
      "await runtime.purgeSession(sessionId);",
      "runtime.close();",
      'fields.get("lifecycle_purge") !== "ok"',
      'fields.get("failure_history") !== "ok"',
      "async function pageHistory(",
      "function safeJournalEvidence(",
      "history cursor did not advance",
      "provider failure identity was not preserved",
      "generic provider failure unexpectedly exposed a durable recovery code",
      'writeFileSync(join(generated, "failure-history.ts"), FAILURE_HISTORY_SMOKE_SOURCE);',
      "coldResult.text !== warmResult.text",
      "coldResult.finalSequence !== warmResult.finalSequence",
      "const githubRequester = integrations.createGitHubRequester();",
      "const gmailRequester = integrations.createGmailRequester();",
      "githubRequester.close();",
      "gmailRequester.close();",
    ]) {
      expect(source).toContain(required);
    }

    const scaffoldSource = readFileSync(join(packageRoot, "src/cli/init.ts"), "utf8");
    expect(scaffoldSource).toContain('import { AgentBuilder } from "@kaji/sdk"');
    expect(scaffoldSource).toContain("new AgentBuilder().provider(provider).build()");
    expect(scaffoldSource).not.toContain("supportsSessionPurge");
    expect(scaffoldSource).not.toContain("purgeSession(result.sessionId)");

    expect(source.match(/completed\.stderr/g)).toHaveLength(2);
    expect(source).toContain("const diagnostic = safeHandoffDiagnostic(completed.stderr)");
    expect(source).not.toContain("JSON.stringify(args)");
    expect(source).not.toContain("node_modules/.bin/kaji");
    expect(source).not.toContain(
      'const githubModule = JSON.stringify(join(installedPackageRoot, "registry/github/index.ts"));',
    );
    expect(source).not.toContain("node_modules/@kaji/sdk/dist/cli/bin.js");
    expect(source).not.toContain('if (!fields.get("text")');
    const expectedIntegrationExportList =
      '["INTEGRATION_RECOVERY", "IntegrationAuthRequiredError", "IntegrationExecutionError", "IntegrationPolicyError", "IntegrationRateLimitedError", "IntegrationTransientReadError", "closedRecoveryFields", "createGitHubRequester", "createGmailRequester", "snapshotIntegrationResult"]';
    expect(source.split(expectedIntegrationExportList)).toHaveLength(3);
    expect(source).toMatch(
      /await install\(\s*manager,\s*"bootstrap",[\s\S]*?nodeTypesPackage[\s\S]*?environment,\s*\)/,
    );
  });

  it("runs installed GitHub package proofs under supported Node runtimes", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const handoffStart = source.indexOf("`handoff:${manager}-github-proof`");
    const handoffLaunch = source.slice(
      handoffStart,
      source.indexOf('"--sandbox-root"', handoffStart),
    );
    const ordinaryStart = source.indexOf("`${manager}:github-package-proof`");
    const ordinaryLaunch = source.slice(
      ordinaryStart,
      source.indexOf('"--sandbox-root"', ordinaryStart),
    );

    expect(handoffLaunch).toMatch(
      /`handoff:\$\{manager\}-github-proof`,\s*runtimeBinary,\s*\[\s*"--experimental-strip-types",\s*runner,/,
    );
    expect(ordinaryLaunch).toMatch(
      /`\$\{manager\}:github-package-proof`,\s*nodeBinary,\s*\[\s*"--experimental-strip-types",\s*githubProofRunner,/,
    );
    expect(handoffLaunch).not.toContain('"--no-install"');
    expect(ordinaryLaunch).not.toContain('"--no-install"');
  });

  it("keeps package-smoke phases finite and cleanup inside the receipt boundary", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const handoffValues = source.slice(
      source.indexOf("const HANDOFF_PHASES = ["),
      source.indexOf("] as const;", source.indexOf("const HANDOFF_PHASES = [")),
    );
    expect([...handoffValues.matchAll(/"handoff:([^"]+)"/g)].map((match) => match[1])).toEqual([
      "npm-install",
      "bun-install",
      "typescript57-version",
      "typescriptCurrent-version",
      "typescript57-esm",
      "typescript57-cjs",
      "typescriptCurrent-esm",
      "typescriptCurrent-cjs",
      "npm-github-proof",
      "bun-github-proof",
      "archive-list",
      "archive-types",
      "archive-extract",
      "policy-before-token",
      "node-version",
      "npm-version",
      "node-esm",
      "node-commonjs",
    ]);
    expect(source).toContain('"workspace:cleanup",');
    expect(source).toContain("const SMOKE_PHASES = new Set<string>");
    expect(source).not.toContain("`handoff:${string}`");
    expect(source).toContain("const PACKAGE_TIMEOUT_MS = 300_000");
    expect(source).toContain("finalizeSmokeRun(");
  });

  it("retains only the classified phase and kind on smoke command failures", () => {
    const error = new SmokeCommandError("npm:pack", "exit");
    Reflect.set(error, "message", "sk-package-canary");

    expect(Object.keys(error)).toEqual(["phase", "kind"]);
    expect(JSON.parse(JSON.stringify(error))).toEqual({
      phase: "npm:pack",
      kind: "exit",
    });
    expect(JSON.stringify(error)).not.toContain("sk-package-canary");
  });

  it("rejects forged typed-error fields at the ordinary receipt boundary", () => {
    const canary = "SK_FORGED_ERROR_CANARY";
    const forged = Object.assign(new SmokeCommandError("npm:pack", "exit"), {
      phase: `phase-${canary}`,
      kind: `kind-${canary}`,
      message: `message-${canary}`,
      cause: { secret: `cause-${canary}` },
      stdout: `stdout-${canary}`,
      stderr: `stderr-${canary}`,
      env: { SECRET: `env-${canary}` },
    });
    const forgedReceipt = ordinaryFailureReceipt(forged, {}, null, process.version);

    expect(forgedReceipt).toMatchObject({
      failedPhase: null,
      failureKind: "unknown",
      artifacts: {},
      githubPackageProofs: {},
    });
    expect(JSON.stringify(forgedReceipt)).not.toContain(canary);

    expect(
      ordinaryFailureReceipt(
        new SmokeCommandError("handoff:node-version", "output_limit"),
        {},
        null,
        process.version,
      ),
    ).toMatchObject({
      failedPhase: "handoff:node-version",
      failureKind: "output_limit",
    });
  });

  it("omits absolute workspace paths from raw ordinary failure receipts", () => {
    const state = {
      identity: {
        commit: "a".repeat(40),
        manifestSha256: "b".repeat(64),
        artifactSha256: { "kaji-sdk-0.2.0-beta.2.tgz": "c".repeat(64) },
      },
      receiptTarball: "/private/secret/sk-tarball-canary.tgz",
      installedPackagePath: "/private/secret/sk-package-canary/node_modules/@kaji/sdk",
      nodeVersion: "v24.11.0",
    };
    const receipt = ordinaryFailureReceipt(
      new SmokeCommandError("npm:package-install", "timeout"),
      { expectedCommit: state.identity.commit },
      state.identity,
      state.nodeVersion,
    );
    let stdout = "";
    let output = "";
    finalizeSmokeRun("", { kind: "ordinary", output: "/receipt.json", receipt }, null, {
      removeWorkspace: () => {},
      emitOrdinary: (document) => {
        stdout = JSON.stringify(document);
        output = JSON.stringify(document);
      },
      emitHandoff: () => {
        throw new Error("ordinary failure used the handoff emitter");
      },
      writeDiagnostic: () => {},
    });

    expect(receipt).toMatchObject({
      commit: state.identity.commit,
      releaseManifestSha256: state.identity.manifestSha256,
      artifactSha256: state.identity.artifactSha256,
      artifacts: {},
      conclusion: "failed",
      failureCode: "node_smoke_failed",
      failedPhase: "npm:package-install",
      failureKind: "timeout",
    });
    for (const encoded of [stdout, output]) {
      expect(encoded).not.toContain(state.receiptTarball);
      expect(encoded).not.toContain(state.installedPackagePath);
      expect(encoded).not.toContain("sk-");
    }
    expect(
      ordinaryFailureReceipt(
        new SmokeCommandError("npm:package-install", "timeout"),
        { expectedCommit: "d".repeat(40) },
        null,
        state.nodeVersion,
      ).commit,
    ).toBe("d".repeat(40));

    const unsafeCanary = "SK_RAW_RECEIPT_CANARY";
    const unsafeReceipt = ordinaryFailureReceipt(
      new SmokeCommandError("npm:package-install", "timeout"),
      { expectedCommit: `/private/secret/${unsafeCanary}` },
      {
        commit: `/private/secret/${unsafeCanary}`,
        manifestSha256: unsafeCanary,
        artifactSha256: {
          [`${unsafeCanary}.tgz`]: "c".repeat(64),
          "kaji-sdk-0.2.0-beta.2.tgz": unsafeCanary,
        },
      },
      `v24.0.0\n${unsafeCanary}`,
    );
    expect(unsafeReceipt).toEqual({
      schemaVersion: 1,
      commit: null,
      releaseManifestSha256: null,
      artifactSha256: {},
      runtime: { version: process.version },
      artifacts: {},
      githubPackageProofs: {},
      conclusion: "failed",
      failureCode: "node_smoke_failed",
      failedPhase: "npm:package-install",
      failureKind: "timeout",
    });
    expect(JSON.stringify(unsafeReceipt)).not.toContain(unsafeCanary);
  });

  it("redacts invalid argument and manifest paths from direct failed receipts", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-failed-receipt-"));
    const tarball = join(root, "sk-tarball-canary.tgz");
    const manifest = join(root, "sk-manifest-canary.json");
    const output = join(root, "receipt.json");
    const expectedCommit = "/private/secret/sk-commit-canary";
    writeFileSync(tarball, "artifact");
    const artifactHash = createHash("sha256").update(readFileSync(tarball)).digest("hex");
    writeFileSync(
      manifest,
      JSON.stringify({
        commit: expectedCommit,
        artifacts: [{ file: "sk-tarball-canary.tgz", sha256: artifactHash }],
      }),
    );

    try {
      const completed = spawnSync(
        "bun",
        [
          join(packageRoot, "scripts/smoke_package.mts"),
          tarball,
          "--release-manifest",
          manifest,
          "--expected-commit",
          expectedCommit,
          "--output",
          output,
        ],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: { ...process.env, NODE_BINARY: join(root, "missing-node") },
        },
      );
      expect(completed.status).not.toBe(0);
      const stdoutReceipt = JSON.parse(completed.stdout) as Record<string, unknown>;
      const outputReceipt = JSON.parse(readFileSync(output, "utf8")) as Record<string, unknown>;
      expect(stdoutReceipt).toEqual(outputReceipt);
      expect(outputReceipt).toMatchObject({
        commit: null,
        releaseManifestSha256: null,
        artifactSha256: {},
        artifacts: {},
        conclusion: "failed",
        failureCode: "artifact_identity_failed",
        failedPhase: null,
        failureKind: "unknown",
      });
      for (const encoded of [completed.stdout, readFileSync(output, "utf8")]) {
        expect(encoded).not.toContain(expectedCommit);
        expect(encoded).not.toContain("sk-manifest-canary");
        expect(encoded).not.toContain("sk-tarball-canary");
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("sanitizes environment commit identity before direct failure retention", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-failed-env-"));
    const tarball = join(root, "candidate.tgz");
    const missingNode = join(root, "missing-node");
    writeFileSync(tarball, "artifact");
    const artifactHash = createHash("sha256").update(readFileSync(tarball)).digest("hex");
    const environment = { ...process.env };
    delete environment.KAJI_RELEASE_COMMIT;
    delete environment.GITHUB_SHA;

    const runCase = (name: string, extraEnvironment: NodeJS.ProcessEnv) => {
      const output = join(root, `${name}.json`);
      const completed = spawnSync(
        "bun",
        [join(packageRoot, "scripts/smoke_package.mts"), tarball, "--output", output],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: { ...environment, ...extraEnvironment, NODE_BINARY: missingNode },
        },
      );
      expect(completed.status).not.toBe(0);
      const stdoutReceipt = JSON.parse(completed.stdout) as Record<string, unknown>;
      const outputReceipt = JSON.parse(readFileSync(output, "utf8")) as Record<string, unknown>;
      expect(stdoutReceipt).toEqual(outputReceipt);
      expect(outputReceipt).toMatchObject({
        artifactSha256: { "kaji-sdk-0.2.0-beta.2.tgz": artifactHash },
        artifacts: {},
        conclusion: "failed",
        failureCode: "node_smoke_failed",
        failedPhase: "node:version",
        failureKind: "start",
      });
      return { completed, outputReceipt };
    };

    try {
      const invalidCommit = "/private/secret/sk-env-commit-canary";
      const invalid = runCase("invalid", { KAJI_RELEASE_COMMIT: invalidCommit });
      expect(invalid.outputReceipt.commit).toBeNull();
      expect(invalid.completed.stdout).not.toContain(invalidCommit);

      const releaseCommit = "e".repeat(40);
      expect(runCase("release", { KAJI_RELEASE_COMMIT: releaseCommit }).outputReceipt.commit).toBe(
        releaseCommit,
      );

      const githubCommit = "f".repeat(40);
      expect(runCase("github", { GITHUB_SHA: githubCommit }).outputReceipt.commit).toBe(
        githubCommit,
      );
      expect(
        runCase("fallback", {
          KAJI_RELEASE_COMMIT: invalidCommit,
          GITHUB_SHA: githubCommit,
        }).outputReceipt.commit,
      ).toBe(githubCommit);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("canonicalizes supplied tarball keys in direct failed receipts", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-failed-tarball-key-"));
    const tarballCanary = "SK_TARBALL_PATH_CANARY.tgz";
    const tarball = join(root, tarballCanary);
    const output = join(root, "receipt.json");
    const missingNode = join(root, "missing-node");
    writeFileSync(tarball, "artifact");
    const artifactHash = createHash("sha256").update(readFileSync(tarball)).digest("hex");

    try {
      const completed = spawnSync(
        "bun",
        [join(packageRoot, "scripts/smoke_package.mts"), tarball, "--output", output],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: { ...process.env, NODE_BINARY: missingNode },
        },
      );
      expect(completed.status).not.toBe(0);
      const stdoutReceipt = JSON.parse(completed.stdout) as Record<string, unknown>;
      const outputReceipt = JSON.parse(readFileSync(output, "utf8")) as Record<string, unknown>;
      expect(stdoutReceipt).toEqual(outputReceipt);
      expect(outputReceipt).toMatchObject({
        artifactSha256: { "kaji-sdk-0.2.0-beta.2.tgz": artifactHash },
        artifacts: {},
        conclusion: "failed",
        failureCode: "node_smoke_failed",
        failedPhase: "node:version",
        failureKind: "start",
      });
      for (const encoded of [completed.stdout, readFileSync(output, "utf8")]) {
        expect(encoded).not.toContain(tarballCanary);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("retains direct child Node versions only after exact validation", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-failed-node-version-"));
    const tarball = join(root, "candidate.tgz");
    const fakeBin = join(root, "bin");
    const fakeNode = join(fakeBin, "node");
    const fakeNpm = join(fakeBin, "npm");
    writeFileSync(tarball, "artifact");
    mkdirSync(fakeBin);
    writeFileSync(fakeNpm, "#!/bin/sh\nexit 17\n");
    chmodSync(fakeNpm, 0o755);

    const runCase = (name: string, childOutput: string) => {
      const output = join(root, `${name}.json`);
      writeFileSync(fakeNode, `#!/bin/sh\nprintf '%s\\n' ${JSON.stringify(childOutput)}\n`);
      chmodSync(fakeNode, 0o755);
      const completed = spawnSync(
        "bun",
        [join(packageRoot, "scripts/smoke_package.mts"), tarball, "--output", output],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: {
            ...process.env,
            NODE_BINARY: fakeNode,
            PATH: `${fakeBin}:${process.env.PATH ?? ""}`,
          },
        },
      );
      expect(completed.status).not.toBe(0);
      const stdoutReceipt = JSON.parse(completed.stdout) as Record<string, unknown>;
      const outputReceipt = JSON.parse(readFileSync(output, "utf8")) as Record<string, unknown>;
      expect(stdoutReceipt).toEqual(outputReceipt);
      expect(outputReceipt).toMatchObject({
        artifacts: {},
        conclusion: "failed",
        failureCode: "node_smoke_failed",
      });
      return { completed, outputReceipt };
    };

    try {
      const childOutputCanary = "SK_CHILD_OUTPUT_CANARY";
      const invalid = runCase("invalid", `v24.0.0\n${childOutputCanary}`);
      expect(invalid.outputReceipt.runtime).toEqual({
        version: expect.stringMatching(/^v(?:22|24)\.[0-9]+\.[0-9]+$/),
      });
      expect(invalid.completed.stdout).not.toContain(childOutputCanary);
      expect(readFileSync(join(root, "invalid.json"), "utf8")).not.toContain(childOutputCanary);

      expect(runCase("node-22", "v22.17.1").outputReceipt.runtime).toEqual({
        version: "v22.17.1",
      });
      expect(runCase("node-24", "v24.4.0").outputReceipt.runtime).toEqual({
        version: "v24.4.0",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("cleans before ordinary success and replaces cleanup failures with closed evidence", () => {
    const calls: string[] = [];
    const success: PendingSmokeReceipt = {
      kind: "ordinary",
      output: "/receipt.json",
      diagnostics: ["ready"],
      receipt: { conclusion: "passed" },
    };
    const cleanupFailure: PendingSmokeReceipt = {
      kind: "ordinary",
      output: "/receipt.json",
      receipt: {
        conclusion: "failed",
        failedPhase: "workspace:cleanup",
        failureKind: "cleanup",
      },
    };
    const dependencies: SmokeFinalizerDependencies = {
      removeWorkspace: () => calls.push("cleanup"),
      writeDiagnostic: () => calls.push("diagnostic"),
      emitOrdinary: () => calls.push("ordinary"),
      emitHandoff: () => calls.push("handoff"),
    };

    finalizeSmokeRun("/workspace", success, cleanupFailure, dependencies);
    expect(calls).toEqual(["cleanup", "diagnostic", "ordinary"]);

    calls.length = 0;
    expect(() =>
      finalizeSmokeRun("/workspace", success, cleanupFailure, {
        ...dependencies,
        removeWorkspace: () => {
          calls.push("cleanup");
          throw new Error("cleanup failed");
        },
      }),
    ).toThrowError(
      expect.objectContaining({
        phase: "workspace:cleanup",
        kind: "cleanup",
      }),
    );
    expect(calls).toEqual(["cleanup", "ordinary"]);
  });

  it("does not emit a trusted handoff pass when cleanup fails", () => {
    const calls: string[] = [];
    expect(() =>
      finalizeSmokeRun(
        "/workspace",
        { kind: "handoff", output: "/receipt.json", receipt: { result: "passed" } },
        null,
        {
          removeWorkspace: () => {
            calls.push("cleanup");
            throw new Error("cleanup failed");
          },
          writeDiagnostic: () => calls.push("diagnostic"),
          emitOrdinary: () => calls.push("ordinary"),
          emitHandoff: () => calls.push("handoff"),
        },
      ),
    ).toThrowError(
      expect.objectContaining({
        phase: "workspace:cleanup",
        kind: "cleanup",
      }),
    );
    expect(calls).toEqual(["cleanup"]);
  });

  it("compiles installed GitHub declarations through every NodeNext conditional branch", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const esmFixture = source.slice(
      source.indexOf("const GITHUB_ESM_TYPES_SOURCE = `"),
      source.indexOf("const GITHUB_CJS_TYPES_SOURCE = `"),
    );
    const cjsFixture = source.slice(
      source.indexOf("const GITHUB_CJS_TYPES_SOURCE = `"),
      source.indexOf("const GITHUB_TYPES_COMPILER_OPTIONS ="),
    );
    const declarationGuard = source.slice(
      source.indexOf("function assertRootDeclarationsVendorNeutral("),
      source.indexOf("async function install("),
    );

    for (const required of [
      'writeFileSync(join(generated, "github-types.mts"), GITHUB_ESM_TYPES_SOURCE)',
      'writeFileSync(join(generated, "github-types.cts"), GITHUB_CJS_TYPES_SOURCE)',
      'source: "github-types.mts"',
      'source: "github-types.cts"',
      'config: "tsconfig.github-types-esm.json"',
      'config: "tsconfig.github-types-cjs.json"',
      'import sdk = require("@kaji/sdk");',
      'import github = require("@kaji/sdk/integrations/github");',
      "const roots: Integration[] = [direct, created, inspected]",
      "const roots: sdk.Integration[] = [direct, created, inspected]",
      'module: "NodeNext"',
      'moduleResolution: "NodeNext"',
      "strict: true",
      "types: []",
      "skipLibCheck: false",
      "noEmit: true",
      "files: [consumer.source]",
      'alias: "typescript57"',
      'line: "5.7"',
      'alias: "typescript"',
      'line: "current"',
      '"--ignoreDeprecations", "5.0"',
      "`${manager}:github-types-compiler-version-${compiler.line}`",
      '[tsc, "--version"]',
      "`${manager}:github-types-${consumer.module}-typescript-${compiler.line}`",
      '[tsc, "--project", consumer.config, "--noEmit", ...compiler.extraArgs]',
      'typescript57: { version: typescript57Version, mtsImport: "passed", ctsRequire: "passed" }',
      'mtsImport: "passed"',
      'ctsRequire: "passed"',
      "typescriptDeclarationChecks:",
      '"--typescript-declaration-checks"',
      "typescriptDeclarationChecksPath",
    ]) {
      expect(source).toContain(required);
    }
    for (const required of [
      "type CliApprovalInput,",
      "type CliApprovalOutput,",
      "type CliApprovalOptions,",
      "const approvalInput: CliApprovalInput = {",
      "const approvalOutput: CliApprovalOutput = {",
      "const approvalOptions: CliApprovalOptions = {",
    ]) {
      expect(esmFixture).toContain(required);
    }
    for (const required of [
      'import sdk = require("@kaji/sdk");',
      "const approvalInput: sdk.CliApprovalInput = {",
      "const approvalOutput: sdk.CliApprovalOutput = {",
      "const approvalOptions: sdk.CliApprovalOptions = {",
    ]) {
      expect(cjsFixture).toContain(required);
    }
    for (const fixture of [esmFixture, cjsFixture]) {
      expect(fixture).not.toContain("node:stream");
      expect(fixture).not.toContain("@types/node");
    }
    expect(declarationGuard).toContain("CliApprovalOptions");
    expect(declarationGuard).toContain("NodeJS.ReadableStream");
    expect(declarationGuard).toContain("NodeJS.WritableStream");
    expect(source).not.toContain(
      'writeFileSync(join(generated, "github-types.ts"), GITHUB_TYPES_SOURCE)',
    );
    expect(source).not.toContain("githubTypeCompilations:");
  });

  it("freezes the closed supplied-tarball handoff grammar and downgrade guards", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const validator = source.slice(
      source.indexOf("function assertGithubPackageProof("),
      source.indexOf("async function runCommand("),
    );
    const handoff = source.slice(
      source.indexOf("async function runHandoffCommand("),
      source.indexOf("function readManifest("),
    );
    for (const required of [
      'type HandoffMode = "artifact-contract" | "node"',
      'argument === "--for-handoff"',
      'argument === "--candidate-root"',
      'argument === "--source-commit"',
      'argument === "--artifact-sha256"',
      'argument === "--node-binary"',
      'argument === "--expected-node-major"',
      'id: "artifact-contract"',
      "subchecks: ARTIFACT_SUBCHECKS.map",
      "id: `node-${arguments_.expectedNodeMajor}`",
      "checks: NODE_HANDOFF_CHECKS.map",
      "function safeHandoffDiagnostic(",
      'testFile: "kaji/ts/tests/github-registry.test.ts"',
      'testName: "rejects approval for github_create_issue before token or HTTP"',
      'providerAlias: "github_get_file"',
      'providerAlias: "synthetic_complete"',
      "schemaVersion: 5",
      "githubFailureRecovery:",
      "githubObservabilitySinksVerified: true",
    ]) {
      expect(source).toContain(required);
    }
    expect(validator).toContain("JSON.stringify(document) !== JSON.stringify(expected)");
    expect(validator).toContain("schemaVersion: 5");
    expect(validator).not.toContain("schemaVersion: 4");
    for (const downgraded of [1, 4]) {
      expect({ ...GITHUB_PACKAGE_PROOF, schemaVersion: downgraded }).not.toEqual(
        GITHUB_PACKAGE_PROOF,
      );
    }
    const checkSource = source.slice(
      source.indexOf("const ARTIFACT_SUBCHECKS = ["),
      source.indexOf("] as const;", source.indexOf("const ARTIFACT_SUBCHECKS = [")),
    );
    expect([...checkSource.matchAll(/"([a-z0-9.-]+)"/g)].map((match) => match[1])).toEqual([
      "safe-packlist",
      "source-byte-equality",
      "export-targets",
      "declarations",
      "typescript-5.7.3-mts",
      "typescript-5.7.3-cts",
      "typescript-current-mts",
      "typescript-current-cts",
      "npm-install",
      "bun-install",
      "public-github-surface",
      "typescript-catalog-15-13",
      "shared-python-catalog-6-4",
      "lifecycle-identity",
      "policy-before-token",
      "packaged-license",
    ]);
    expect(handoff).toContain('throw new Error("supplied-tarball handoff cannot build or pack")');
    expect(handoff).toContain("const childEnvironment = tokenFreeHandoffEnvironment(environment)");
    expect(handoff).toContain("PROTECTED_HANDOFF_TOKENS.some");
    expect(handoff).not.toContain('"npm", ["pack"');
    expect(handoff).not.toContain('"run", "build"');
    expect(handoff).toContain('writeFileSync(esmPath, nodeFixtureSource("esm"');
    expect(handoff).toContain('writeFileSync(cjsPath, nodeFixtureSource("commonjs"');
    expect(handoff).toContain("realpathSync(result.packageRealpath) !== installedPackageRoot");
    expect(source).toContain("github.inspectIntegration().tools().length !== 15");
    expect(source).toContain("inspectIntegration().tools().length !== 6");
  });

  it("rejects malformed supplied-artifact invocations before install or output", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-handoff-args-"));
    const tarball = join(root, "candidate.tgz");
    const output = join(root, "receipt.json");
    writeFileSync(tarball, "not-a-tarball");
    const digest = createHash("sha256").update(readFileSync(tarball)).digest("hex");
    const script = join(packageRoot, "scripts/smoke_package.mts");
    const common = [
      script,
      tarball,
      "--source-commit",
      "a".repeat(40),
      "--artifact-sha256",
      digest,
      "--output",
      output,
    ];
    try {
      const forbiddenCandidate = spawnSync(
        "bun",
        [
          ...common,
          "--for-handoff",
          "node",
          "--candidate-root",
          root,
          "--node-binary",
          process.execPath,
          "--expected-node-major",
          "22",
        ],
        { cwd: packageRoot, encoding: "utf8" },
      );
      expect(forbiddenCandidate.status).not.toBe(0);
      expect(forbiddenCandidate.stderr).toContain("node handoff requires");
      expect(existsSync(output)).toBe(false);

      const digestMismatch = spawnSync(
        "bun",
        [
          ...common.slice(0, 5),
          "0".repeat(64),
          ...common.slice(6),
          "--for-handoff",
          "artifact-contract",
          "--candidate-root",
          root,
        ],
        { cwd: packageRoot, encoding: "utf8" },
      );
      expect(digestMismatch.status).not.toBe(0);
      expect(digestMismatch.stderr).toContain("SHA-256 differs before install");
      expect(existsSync(output)).toBe(false);

      const actualMajor = Number(process.versions.node.split(".", 1)[0]);
      const wrongMajor = actualMajor === 22 ? 24 : 22;
      const majorMismatch = spawnSync(
        "bun",
        [
          ...common,
          "--for-handoff",
          "node",
          "--node-binary",
          process.execPath,
          "--expected-node-major",
          String(wrongMajor),
        ],
        { cwd: packageRoot, encoding: "utf8" },
      );
      expect(majorMismatch.status).not.toBe(0);
      expect(majorMismatch.stderr).toContain("major differs");
      expect(existsSync(output)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("strips protected tokens from every supplied-artifact child", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-handoff-env-"));
    const tarball = join(root, "candidate.tgz");
    const output = join(root, "receipt.json");
    const marker = join(root, "child-environment.txt");
    const fakeNode = join(root, "node-22");
    writeFileSync(tarball, "not-a-tarball");
    writeFileSync(
      fakeNode,
      `#!/bin/sh
if [ "\${GH_TOKEN+x}" = x ] || [ "\${GITHUB_TOKEN+x}" = x ] || [ "\${NODE_AUTH_TOKEN+x}" = x ] || [ "\${NPM_TOKEN+x}" = x ]; then
  printf leaked > ${JSON.stringify(marker)}
else
  printf clean > ${JSON.stringify(marker)}
fi
printf 'v24.0.0\\n'
`,
    );
    chmodSync(fakeNode, 0o755);
    const digest = createHash("sha256").update(readFileSync(tarball)).digest("hex");
    try {
      const completed = spawnSync(
        "bun",
        [
          join(packageRoot, "scripts/smoke_package.mts"),
          tarball,
          "--for-handoff",
          "node",
          "--source-commit",
          "a".repeat(40),
          "--artifact-sha256",
          digest,
          "--node-binary",
          fakeNode,
          "--expected-node-major",
          "22",
          "--output",
          output,
        ],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: {
            ...process.env,
            GH_TOKEN: "gh-secret",
            GITHUB_TOKEN: "github-secret",
            NODE_AUTH_TOKEN: "node-secret",
            NPM_TOKEN: "npm-secret",
          },
        },
      );
      expect(completed.status).not.toBe(0);
      expect(readFileSync(marker, "utf8")).toBe("clean");
      expect(existsSync(output)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("retains a redacted child diagnostic when a handoff command fails", () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-handoff-diagnostic-"));
    const tarball = join(root, "candidate.tgz");
    const output = join(root, "receipt.json");
    const fakeNode = join(root, "node-22");
    const secret = "ghp_handoff_diagnostic_secret";
    writeFileSync(tarball, "not-a-tarball");
    writeFileSync(
      fakeNode,
      `#!/bin/sh
printf 'safe-reason=fixture-failed\\n' >&2
printf 'token=${secret}\\n' >&2
printf 'Authorization: Bearer opaque-secret-value\\n' >&2
printf 'authorization=Basic dXNlcjpwYXNz\\n' >&2
printf '{"headers":{"Authorization":"Bearer json-opaque-secret"}}\\n' >&2
printf '{"token":"ordinary-secret"}\\n' >&2
exit 7
`,
    );
    chmodSync(fakeNode, 0o755);
    const digest = createHash("sha256").update(readFileSync(tarball)).digest("hex");
    try {
      const completed = spawnSync(
        "bun",
        [
          join(packageRoot, "scripts/smoke_package.mts"),
          tarball,
          "--for-handoff",
          "node",
          "--source-commit",
          "a".repeat(40),
          "--artifact-sha256",
          digest,
          "--node-binary",
          fakeNode,
          "--expected-node-major",
          "22",
          "--output",
          output,
        ],
        { cwd: packageRoot, encoding: "utf8" },
      );
      expect(completed.status).not.toBe(0);
      expect(completed.stderr).toContain(
        "package smoke child stderr at handoff:node-version: safe-reason=fixture-failed",
      );
      expect(completed.stderr).toContain("token=[redacted]");
      expect(completed.stderr).toContain("Authorization: [redacted]");
      expect(completed.stderr).toContain("authorization=[redacted]");
      expect(completed.stderr).toContain('"Authorization":"[redacted]"');
      expect(completed.stderr).toContain('"token":"[redacted]"');
      expect(completed.stderr).not.toContain(secret);
      expect(completed.stderr).not.toContain("opaque-secret-value");
      expect(completed.stderr).not.toContain("dXNlcjpwYXNz");
      expect(completed.stderr).not.toContain("json-opaque-secret");
      expect(completed.stderr).not.toContain("ordinary-secret");
      expect(existsSync(output)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("keeps the installed GitHub behavior receipt deterministic and non-live", () => {
    const runner = readFileSync(resolve(packageRoot, "scripts/installed-github-smoke.mts"), "utf8");
    for (const required of [
      'evidenceClass: "offline_exact_artifact_smoke"',
      'integration: "github"',
      'runtime: "typescript"',
      'network: "blocked"',
      "liveProvider: false",
      "sharedAbiVersion: abi.version",
      "packageAbiSchemaVersion: packageAbi.schema_version",
      "packageCatalogVersion: packageAbi.catalog_version",
      "apiFixtureVersion: fixture.version",
      "sharedFixtureCaseCount: fixture.cases.length",
      "publicScenarioCount: publicScenarios.length",
      "packageCatalog:",
      "cliCopiedCatalog:",
      'const sdk = await import("@kaji/sdk");',
      'const testing = (await import("@kaji/sdk/testing"))',
      'await import("@kaji/sdk/integrations/github")',
      "const requirePackage = createRequire(import.meta.url);",
      'exactToolSpecs(inspected, packageAbi, "ESM")',
      'exactToolSpecs(requiredInspected, packageAbi, "CommonJS")',
      "declarationExportNames(declaration)",
      'readonly toolExposure?: "read-only" | "all";',
      "readTypeScriptDeclarationChecks(",
      'proofStage = "typescript-declaration-checks"',
      "typescriptDeclarationChecks,",
      "inspectPrivateGitHubCompositionSources(packageRoot)",
      'Object.hasOwn(document, "sourcesContent")',
      "privateSourceContainment.privateGitHubCompositionSourcesPacked",
      "privateSourceContainment.privateGitHubCompositionSourceImportsRejected",
      '"registry/github/package-tools.ts"',
      '"@kaji/sdk/registry/github/package-tools.ts"',
      '"export function createPackageGitHubToolBindings("',
      "closedCallsDeniedBeforeCredentialAccess: true",
      "approvalDeniedBeforeCredentialAccess: true",
      "repositoryDeniedBeforeCredentialAccess: true",
      'githubCatalogEventsVerified: ["requested", "started", "failed"]',
      'genericSyntheticCatalogEventsVerified: ["requested", "started", "completed"]',
      "githubFailureRecovery: GITHUB_TOKEN_RECOVERY",
      "githubObservabilitySinksVerified: true",
      "unknownMutationPreserved: true",
      "mutationRetries: 0",
      'proofStage = "observability-sinks"',
      "metricsSink:",
      "traceSink:",
      "recoveryTuple(execution.results[0])",
      "recoveryTuple(failedEvent)",
      '"github_mutation_unknown"',
      '"RECONCILE_GITHUB_MUTATION"',
      'name: "github_add_comment"',
      "networkAttempts !== 1",
      "aliasCollisionRejected: true",
      'Reflect.set(Socket.prototype, "connect"',
      "createGithubIntegration",
      'toolExposure: "read-only"',
      'error.name !== "IntegrationPolicyError"',
      "new testing.MockProvider",
      "class SyntheticIntegration extends sdk.Integration",
      "class CollidingIntegration extends sdk.Integration",
    ]) {
      expect(runner).toContain(required);
    }
    expect(runner).not.toMatch(/import\s+\{[^}]*\}\s+from "@kaji\/sdk";/);
    expect(runner.indexOf('Reflect.set(Socket.prototype, "connect"')).toBeLessThan(
      runner.indexOf('const sdk = await import("@kaji/sdk");'),
    );
    expect(runner).not.toContain("process.env.GITHUB_TOKEN");
    expect(runner).not.toContain("createGitHubRequester");
    expect(runner).not.toContain("ScriptedRequester");
    expect(runner).not.toContain("GitHubClientLike");
    expect(runner).not.toContain("--bundle-root");
    expect(runner).not.toContain("fetch(");
    expect(runner).not.toContain("privateTransportExposed");
    expect(runner).not.toContain("sourceRuntimeDetected");
    expect(runner).not.toContain("logicalCatalogEventsVerified");
    expect(runner).not.toContain("privateGitHubCompositionSourcesPacked: false");
  });

  it("proves installed ESM and CommonJS GitHub class identity through the package root", () => {
    const runner = readFileSync(resolve(packageRoot, "scripts/installed-github-smoke.mts"), "utf8");
    for (const required of [
      'requirePackage.resolve("@kaji/sdk")',
      'requirePackage.resolve("@kaji/sdk/integrations/github")',
      "esmIdentityInspected instanceof sdk.Integration",
      "cjsIdentityInspected instanceof requiredSdk.Integration",
      "esmIdentityCreated instanceof github.GitHubIntegration",
      "cjsIdentityCreated instanceof requiredGithub.GitHubIntegration",
      "Object.getPrototypeOf(github.GitHubIntegration.prototype) === sdk.Integration.prototype",
      "Object.getPrototypeOf(requiredGithub.GitHubIntegration.prototype) ===",
      "esmClassIdentityMatched",
      "cjsClassIdentityMatched",
      "esmFactoryIdentityMatched",
      "cjsFactoryIdentityMatched",
    ]) {
      expect(runner).toContain(required);
    }
  });

  it("omits embedded private GitHub sources from every packed source map", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-github-sourcemap-pack-"));
    try {
      const packed = JSON.parse(
        runText("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", workdir], {
          cwd: packageRoot,
          env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
        }),
      ) as Array<{ filename: string; files: Array<{ path: string }> }>;
      const tarball = join(workdir, packed[0]!.filename);
      const sourceMaps = packed[0]!.files
        .map(({ path }) => path)
        .filter((path) => path.startsWith("dist/") && path.endsWith(".map"))
        .map((path) => {
          const document = JSON.parse(runText("tar", ["-xOf", tarball, `package/${path}`])) as {
            sources?: unknown;
            sourcesContent?: unknown;
          };
          return { path, document };
        });
      const githubSourceMaps = sourceMaps.filter(
        ({ path, document }) =>
          /^dist\/integrations\/github(?:\.[^/]+)*\.map$/.test(path) ||
          (Array.isArray(document.sources) &&
            document.sources.some(
              (source) =>
                typeof source === "string" &&
                /(?:^|\/)(?:src\/integrations\/github(?:-package-internal)?|registry\/github\/[^/]+)\.ts$/.test(
                  source.replaceAll("\\", "/"),
                ),
            )),
      );

      expect(githubSourceMaps.map(({ path }) => path)).toEqual(
        expect.arrayContaining([
          "dist/integrations/github.js.map",
          "dist/integrations/github.cjs.map",
        ]),
      );
      for (const { path, document } of githubSourceMaps) {
        const embeddedSources = Array.isArray(document.sourcesContent)
          ? document.sourcesContent.filter((source) => typeof source === "string")
          : Object.hasOwn(document, "sourcesContent")
            ? [document.sourcesContent]
            : [];
        expect(embeddedSources, `${path} embeds sourcesContent`).toEqual([]);
      }
      for (const { path, document } of sourceMaps) {
        const encoded = JSON.stringify(document);
        for (const canary of PRIVATE_GITHUB_COMPOSITION_SOURCE_CANARIES) {
          expect(encoded, `${path} embeds private GitHub source canary`).not.toContain(canary);
        }
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("executes every GitHub package-proof case without network access", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-github-proof-"));
    try {
      const packDestination = join(workdir, "pack");
      mkdirSync(packDestination);
      const packed = JSON.parse(
        runText(
          "npm",
          ["pack", "--ignore-scripts", "--json", "--pack-destination", packDestination],
          {
            cwd: packageRoot,
            env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
          },
        ),
      ) as Array<{ filename: string }>;
      const extracted = join(workdir, "artifact");
      mkdirSync(extracted);
      runText("tar", ["-xzf", join(packDestination, packed[0]!.filename), "-C", extracted]);

      const installed = realpathSync(join(extracted, "package"));
      const bootstrap = join(workdir, "bootstrap");
      mkdirSync(join(bootstrap, "node_modules", "@kaji"), { recursive: true });
      symlinkSync(installed, join(bootstrap, "node_modules", "@kaji", "sdk"), "dir");
      symlinkSync(join(packageRoot, "node_modules"), join(installed, "node_modules"), "dir");
      symlinkSync(
        join(packageRoot, "node_modules", "@types"),
        join(bootstrap, "node_modules", "@types"),
        "dir",
      );
      symlinkSync(
        join(packageRoot, "node_modules", "undici-types"),
        join(bootstrap, "node_modules", "undici-types"),
        "dir",
      );
      writeFileSync(
        join(bootstrap, "github-types.mts"),
        `import {
  Integration,
  type CliApprovalInput,
  type CliApprovalOptions,
  type CliApprovalOutput,
} from "@kaji/sdk";
import {
  GitHubIntegration,
  createGithubIntegration,
  inspectIntegration,
  type CreateGitHubIntegrationOptions,
} from "@kaji/sdk/integrations/github";
const options: CreateGitHubIntegrationOptions = {
  tokenFor: async () => "proof",
  repositories: [],
  toolExposure: "read-only",
};
const direct: GitHubIntegration = new GitHubIntegration(options);
const created: GitHubIntegration = createGithubIntegration(options);
const inspected: GitHubIntegration = inspectIntegration();
const roots: Integration[] = [direct, created, inspected];
const approvalInput: CliApprovalInput = {
  readableEnded: false,
  destroyed: false,
  on(_event, _listener) {
    return this;
  },
  once(_event, _listener) {
    return this;
  },
  removeListener(_event, _listener) {
    return this;
  },
  pause() {
    return this;
  },
  resume() {
    return this;
  },
};
const approvalOutput: CliApprovalOutput = {
  write(_chunk) {
    return true;
  },
};
const approvalOptions: CliApprovalOptions = {
  input: approvalInput,
  output: approvalOutput,
  label: "installed-type-proof",
};
void roots;
void approvalOptions;
`,
      );
      writeFileSync(
        join(bootstrap, "github-types.cts"),
        `import sdk = require("@kaji/sdk");
import github = require("@kaji/sdk/integrations/github");
const options: github.CreateGitHubIntegrationOptions = {
  tokenFor: async () => "proof",
  repositories: [],
  toolExposure: "read-only",
};
const direct: github.GitHubIntegration = new github.GitHubIntegration(options);
const created: github.GitHubIntegration = github.createGithubIntegration(options);
const inspected: github.GitHubIntegration = github.inspectIntegration();
const roots: sdk.Integration[] = [direct, created, inspected];
const approvalInput: sdk.CliApprovalInput = {
  readableEnded: false,
  destroyed: false,
  on(_event, _listener) {
    return this;
  },
  once(_event, _listener) {
    return this;
  },
  removeListener(_event, _listener) {
    return this;
  },
  pause() {
    return this;
  },
  resume() {
    return this;
  },
};
const approvalOutput: sdk.CliApprovalOutput = {
  write(_chunk) {
    return true;
  },
};
const approvalOptions: sdk.CliApprovalOptions = {
  input: approvalInput,
  output: approvalOutput,
  label: "installed-type-proof",
};
void roots;
void approvalOptions;
`,
      );
      const compilerOptions = {
        module: "NodeNext",
        moduleResolution: "NodeNext",
        noEmit: true,
        skipLibCheck: false,
        strict: true,
        target: "ES2022",
        types: [],
      };
      for (const [config, source] of [
        ["tsconfig.github-types-esm.json", "github-types.mts"],
        ["tsconfig.github-types-cjs.json", "github-types.cts"],
      ] as const) {
        writeFileSync(
          join(bootstrap, config),
          JSON.stringify({ compilerOptions, files: [source] }),
        );
      }
      for (const [compiler, extraArgs] of [
        [join(packageRoot, "node_modules/typescript57/bin/tsc"), ["--ignoreDeprecations", "5.0"]],
        [join(packageRoot, "node_modules/typescript/bin/tsc"), []],
      ] as const) {
        for (const config of ["tsconfig.github-types-esm.json", "tsconfig.github-types-cjs.json"]) {
          runText("node", [compiler, "--project", config, "--noEmit", ...extraArgs], {
            cwd: bootstrap,
          });
        }
      }
      const declarationChecks = join(bootstrap, "typescript-declaration-checks.json");
      writeFileSync(
        declarationChecks,
        JSON.stringify(GITHUB_PACKAGE_PROOF.typescriptDeclarationChecks),
      );
      const runner = join(bootstrap, "installed-github-smoke.mts");
      copyFileSync(resolve(packageRoot, "scripts/installed-github-smoke.mts"), runner);
      const environment = Object.fromEntries(
        ["HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TEMP", "TMP", "TMPDIR"].flatMap((name) =>
          process.env[name] === undefined ? [] : [[name, process.env[name]]],
        ),
      );
      expect(() =>
        runText("node", [runner, "--sandbox-root", workdir, "--package-root", installed], {
          cwd: bootstrap,
          env: environment,
        }),
      ).toThrow();
      const output = runText(
        "node",
        [
          runner,
          "--sandbox-root",
          workdir,
          "--package-root",
          installed,
          "--typescript-declaration-checks",
          declarationChecks,
        ],
        { cwd: bootstrap, env: environment },
      );

      expect(JSON.parse(output)).toEqual(GITHUB_PACKAGE_PROOF);
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("preserves tool error identity across installed ESM and CommonJS entrypoints", () => {
    const esmRoot = pathToFileURL(resolve(packageRoot, "dist/index.js")).href;
    const esmIntegrations = pathToFileURL(resolve(packageRoot, "dist/integrations.js")).href;
    const esm = runText(
      "node",
      [
        "--input-type=module",
        "--eval",
        `const root=await import(${JSON.stringify(esmRoot)});` +
          `const integrations=await import(${JSON.stringify(esmIntegrations)});` +
          'const error=new integrations.IntegrationAuthRequiredError("github_token_missing");' +
          "console.log(error instanceof root.ToolExecutionError," +
          'new root.ToolExecutionError("x","X",false,"failed") instanceof ' +
          "integrations.IntegrationAuthRequiredError," +
          '({error_code:"X",retryable:false,outcome:"failed"}) instanceof ' +
          "root.ToolExecutionError);",
      ],
      { cwd: packageRoot },
    );
    const cjs = runText(
      "node",
      [
        "--eval",
        `const root=require(${JSON.stringify(resolve(packageRoot, "dist/index.cjs"))});` +
          `const integrations=require(${JSON.stringify(
            resolve(packageRoot, "dist/integrations.cjs"),
          )});` +
          'const error=new integrations.IntegrationAuthRequiredError("github_token_missing");' +
          "console.log(error instanceof root.ToolExecutionError," +
          'new root.ToolExecutionError("x","X",false,"failed") instanceof ' +
          "integrations.IntegrationAuthRequiredError," +
          '({error_code:"X",retryable:false,outcome:"failed"}) instanceof ' +
          "root.ToolExecutionError);",
      ],
      { cwd: packageRoot },
    );

    expect(esm.trim()).toBe("true false false");
    expect(cjs.trim()).toBe("true false false");
  });

  it("exports the closed recovery contract from built ESM and CommonJS entrypoints", () => {
    const esmIntegrations = pathToFileURL(resolve(packageRoot, "dist/integrations.js")).href;
    const script = (specifier: string, loader: "import" | "require") =>
      loader === "import"
        ? `const integrations=await import(${JSON.stringify(specifier)});`
        : `const integrations=require(${JSON.stringify(specifier)});`;
    const proof =
      "const recovery=integrations.INTEGRATION_RECOVERY.github_token_missing;" +
      "console.log(JSON.stringify({" +
      "exports:['INTEGRATION_RECOVERY','closedRecoveryFields'].every(" +
      'name=>typeof integrations[name]!=="undefined"),' +
      'internalAbsent:typeof integrations.isClosedRecoveryTuple==="undefined",' +
      "count:Object.keys(integrations.INTEGRATION_RECOVERY).length," +
      "frozen:Object.isFrozen(integrations.INTEGRATION_RECOVERY)," +
      "github:recovery.docUrl," +
      "rateLimited:integrations.INTEGRATION_RECOVERY.rate_limited.docUrl," +
      "valid:integrations.closedRecoveryFields({" +
      "reason_code:'github_token_missing',recovery_code:recovery.recoveryCode," +
      "doc_url:recovery.docUrl,error_code:recovery.errorCode})," +
      "invalid:integrations.closedRecoveryFields({" +
      "reason_code:'github_token_missing',recovery_code:recovery.recoveryCode," +
      "doc_url:recovery.docUrl,error_code:'WRONG'})" +
      "}));";
    const expected = {
      exports: true,
      internalAbsent: true,
      count: 15,
      frozen: true,
      github: "https://kaji.dev/docs/integrations/recovery-v1#github-token",
      rateLimited: "https://kaji.dev/docs/integrations/recovery-v1#rate-limited",
      valid: {
        reason_code: "github_token_missing",
        recovery_code: "CONFIGURE_GITHUB_TOKEN",
        doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-token",
      },
    };

    const esm = runText(
      "node",
      ["--input-type=module", "--eval", script(esmIntegrations, "import") + proof],
      { cwd: packageRoot },
    );
    const cjs = runText(
      "node",
      ["--eval", script(resolve(packageRoot, "dist/integrations.cjs"), "require") + proof],
      { cwd: packageRoot },
    );

    expect(JSON.parse(esm)).toEqual(expected);
    expect(JSON.parse(cjs)).toEqual(expected);
  });

  it("installs packed benchmark seams through public ESM and CommonJS specifiers", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-testing-pack-"));
    try {
      const packed = JSON.parse(
        runText("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", workdir], {
          cwd: packageRoot,
          env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
        }),
      ) as Array<{ filename: string }>;
      const tarball = join(workdir, packed[0]!.filename);
      const consumer = join(workdir, "consumer");
      mkdirSync(consumer);
      const fixtureLock = JSON.parse(
        readFileSync(
          resolve(repositoryRoot, "kaji/scripts/installed-typescript-runtime/package-lock.json"),
          "utf8",
        ),
      ) as { packages: Record<string, { version?: string }> };
      const localDependency = (name: string): string => {
        const version = fixtureLock.packages[`node_modules/${name}`]?.version;
        if (version === undefined) throw new Error(`missing frozen version for ${name}`);
        const directory = realpathSync(join(packageRoot, "node_modules", name));
        const installedManifest = JSON.parse(
          readFileSync(join(directory, "package.json"), "utf8"),
        ) as { name?: string; version?: string };
        if (installedManifest.name !== name || installedManifest.version !== version) {
          throw new Error(`local ${name} does not match the frozen consumer lock`);
        }
        return `file:${directory}`;
      };
      const localDependencies = {
        "@anthropic-ai/sdk": localDependency("@anthropic-ai/sdk"),
        ajv: localDependency("ajv"),
        "ajv-formats": localDependency("ajv-formats"),
        openai: localDependency("openai"),
        zod: localDependency("zod"),
      };
      const writeConsumerManifest = (dependencies: Record<string, string>): void => {
        writeFileSync(
          join(consumer, "package.json"),
          JSON.stringify({
            name: "kaji-packed-subpath-proof",
            private: true,
            type: "module",
            dependencies,
          }),
        );
      };
      const installHome = join(workdir, "home");
      const installCache = join(workdir, "bun-cache");
      const installTemporary = join(workdir, "bun-tmp");
      for (const directory of [installHome, installCache, installTemporary]) {
        mkdirSync(directory);
      }
      const installOptions = {
        cwd: consumer,
        env: {
          ...process.env,
          HOME: installHome,
          npm_config_cache: installCache,
          npm_config_registry: "http://127.0.0.1:9",
          TEMP: installTemporary,
          TMP: installTemporary,
          TMPDIR: installTemporary,
        },
      };
      writeConsumerManifest(localDependencies);
      runText(
        "npm",
        [
          "install",
          "--offline",
          "--ignore-scripts",
          "--no-audit",
          "--no-fund",
          "--package-lock=false",
        ],
        installOptions,
      );
      writeConsumerManifest({ ...localDependencies, "@kaji/sdk": `file:${tarball}` });
      runText(
        "npm",
        [
          "install",
          "--offline",
          "--ignore-scripts",
          "--no-audit",
          "--no-fund",
          "--package-lock=false",
        ],
        installOptions,
      );
      const installed = join(consumer, "node_modules/@kaji/sdk");
      expect(lstatSync(installed).isSymbolicLink()).toBe(false);
      expect(realpathSync(installed).startsWith(`${realpathSync(consumer)}/`)).toBe(true);
      const exercise = `
class Probe extends openai.OpenAIProvider {
  constructor(outcome) { super({apiKey:"test",retry:{maxAttempts:1}}); this.outcome=outcome; }
  async createClient() { return {chat:{completions:{create:async()=>{
    if (this.outcome?.throws) throw this.outcome.value;
    return this.outcome;
  }}}}; }
}
const response=(content)=>({choices:[{message:{content,tool_calls:[]}}]});
const capture=async(promise)=>{try{await promise;}catch(error){return error;} throw new Error("expected failure");};
let diagnostics;
await new Probe(response("ok")).generate([{role:"user",content:"probe"}],[],testing.withProviderResponseDiagnostics({}, {record(value){diagnostics=value;}}));
let config;
try { new openai.OpenAIProvider({apiKey:""}); } catch (error) { config=error; }
const api=await capture(new Probe({throws:true,value:{status:500}}).generate([{role:"user",content:"probe"}],[]));
const connection=await capture(new Probe({throws:true,value:{code:"ECONNRESET"}}).generate([{role:"user",content:"probe"}],[]));
const rateSource=new root.ProviderRateLimitedError("rate",{retryAfterMs:1,attempts:1});
const rate=await capture(new Probe({throws:true,value:rateSource}).generate([{role:"user",content:"probe"}],[]));
const limit=await capture(new Probe(response("too large")).generate([{role:"user",content:"probe"}],[],{responseLimits:{...root.DEFAULT_PROVIDER_RESPONSE_LIMITS,textMaxBytes:1,responseMaxBytes:1}}));
console.log(JSON.stringify({
  testing:Object.keys(testing),
  root:Object.keys(root),
  diagnostics:diagnostics!==undefined,
  errors:{
    config:config instanceof root.ProviderConfigError,
    api:api instanceof root.ProviderAPIError,
    connection:connection instanceof root.ProviderConnectionError,
    rate:rate instanceof root.ProviderRateLimitedError,
    limit:limit instanceof root.ProviderOutputLimitError,
  },
}));`;
      const esm = JSON.parse(
        runText(
          "node",
          [
            "--input-type=module",
            "--eval",
            `const testing=await import("@kaji/sdk/testing"); const root=await import("@kaji/sdk"); const openai=await import("@kaji/sdk/openai"); ${exercise}`,
          ],
          { cwd: consumer },
        ),
      ) as {
        testing: string[];
        root: string[];
        diagnostics: boolean;
        errors: Record<string, boolean>;
      };
      const cjs = JSON.parse(
        runText(
          "node",
          [
            "--eval",
            `void (async()=>{ const testing=require("@kaji/sdk/testing"); const root=require("@kaji/sdk"); const openai=require("@kaji/sdk/openai"); ${exercise} })();`,
          ],
          { cwd: consumer },
        ),
      ) as {
        testing: string[];
        root: string[];
        diagnostics: boolean;
        errors: Record<string, boolean>;
      };

      const esmCli = runText(
        "node",
        [
          "--input-type=module",
          "--eval",
          'process.argv=["node","--help"]; await import("@kaji/sdk/cli");',
        ],
        { cwd: consumer },
      );
      const cjsCli = runText(
        "node",
        ["--eval", 'process.argv=["node","--help"]; require("@kaji/sdk/cli");'],
        { cwd: consumer },
      );
      expect(esmCli).toContain("usage: kaji");
      expect(cjsCli).toContain("usage: kaji");

      for (const exports of [esm, cjs]) {
        expect(exports.testing).toEqual(
          expect.arrayContaining([
            "MockProvider",
            "createSessionState",
            "withProviderResponseDiagnostics",
          ]),
        );
        expect(exports.root).not.toContain("createSessionState");
        expect(exports.root).not.toContain("withProviderResponseDiagnostics");
        expect(exports.diagnostics).toBe(true);
        expect(exports.errors).toEqual({
          config: true,
          api: true,
          connection: true,
          rate: true,
          limit: true,
        });
      }
      for (const declaration of ["testing.d.ts", "testing.d.cts"]) {
        expect(readFileSync(join(installed, "dist", declaration), "utf8")).toContain(
          "ProviderResponseDiagnostics",
        );
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("contains exactly the canonical contract files and bytes", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-contract-pack-"));
    try {
      const packed = JSON.parse(
        runText("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", workdir], {
          cwd: packageRoot,
          env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
        }),
      ) as Array<{ filename: string; files: Array<{ path: string }> }>;
      const tarball = join(workdir, packed[0]!.filename);
      const paths = new Set(packed[0]!.files.map(({ path }) => path));
      const manifest = JSON.parse(runText("tar", ["-xOf", tarball, "package/package.json"])) as {
        version: string;
        license: string;
        files: string[];
        exports: Record<string, unknown>;
        bin: Record<string, string>;
        dependencies?: Record<string, string>;
        devDependencies?: Record<string, string>;
        peerDependencies?: Record<string, string>;
      };
      const sourceVersion = readFileSync(join(packageRoot, "src/index.ts"), "utf8").match(
        /export const VERSION = "([^"]+)"/,
      );

      expect(sourceVersion).not.toBeNull();
      expect(manifest.version).toBe(sourceVersion![1]);
      expect(manifest.version).toBe("0.2.0-beta.2");
      expect(packed[0]!.filename).toBe(`kaji-sdk-${manifest.version}.tgz`);
      expect(packed[0]!.filename).not.toBe("kaji-sdk-0.2.0-beta.1.tgz");
      expect(manifest.license).toBe("SEE LICENSE IN LICENSE");
      expect(manifest.files).toContain("LICENSE");
      expect(manifest.exports["./cli"]).toEqual({
        import: {
          types: "./dist/cli/package-entry.d.ts",
          default: "./dist/cli/package-entry.js",
        },
        require: {
          types: "./dist/cli/package-entry-cjs.d.cts",
          default: "./dist/cli/package-entry-cjs.cjs",
        },
      });
      expect(paths).toContain("LICENSE");
      expect(paths).toContain("README.md");
      expect(runBytes("tar", ["-xOf", tarball, "package/LICENSE"])).toEqual(
        readFileSync(join(repositoryRoot, "LICENSE")),
      );
      expect(runBytes("tar", ["-xOf", tarball, "package/README.md"])).toEqual(
        readFileSync(join(packageRoot, "README.md")),
      );
      for (const required of [
        "dist/cli/bin.js",
        "dist/cli/package-entry.js",
        "dist/cli/package-entry.d.ts",
        "dist/cli/package-entry-cjs.cjs",
        "dist/cli/package-entry-cjs.d.cts",
        "dist/cli/init-worker.js",
        "dist/integrations.js",
        "dist/integrations.cjs",
        "dist/integrations.d.ts",
        "dist/integrations.d.cts",
        "dist/integrations/github.js",
        "dist/integrations/github.cjs",
        "dist/integrations/github.d.ts",
        "dist/integrations/github.d.cts",
        "registry/index.json",
        "registry/schema.json",
      ]) {
        expect(paths).toContain(required);
      }
      for (const target of exportTargets(manifest.exports)) {
        expect(paths, `missing export target ${target}`).toContain(target.replace(/^\.\//, ""));
      }
      for (const target of Object.values(manifest.bin)) {
        expect(paths, `missing CLI target ${target}`).toContain(target.replace(/^\.\//, ""));
      }
      expect([...paths].filter((path) => path.startsWith("registry/")).sort()).toEqual(
        EXPECTED_PACKED_REGISTRY_FILES,
      );
      for (const privatePath of [
        "registry/_template/manifest.json",
        "registry/github/github_pytest.py",
        "registry/github/package-tools.ts",
        "registry/github/package.ts",
        "registry/github/package-internal.ts",
      ]) {
        expect(paths).not.toContain(privatePath);
      }
      for (const declarationPath of ["dist/index.d.ts", "dist/index.d.cts"]) {
        const declaration = runText("tar", ["-xOf", tarball, `package/${declarationPath}`]);
        const approvalOptions = /interface CliApprovalOptions \{[\s\S]*?^\}/mu.exec(
          declaration,
        )?.[0];
        expect(approvalOptions).toBeDefined();
        expect(approvalOptions).not.toContain("NodeJS.ReadableStream");
        expect(approvalOptions).not.toContain("NodeJS.WritableStream");
        expect(declaration).not.toMatch(/from ["']openai["']/);
        expect(declaration).not.toMatch(/from ["']@anthropic-ai\/sdk["']/);
        expect(declaration).not.toContain("Promise<OpenAI>");
        expect(declaration).not.toContain("Promise<Anthropic>");
      }
      const forbidden = [...paths].filter(
        (path) =>
          /(^|\/)(src|scripts|tests?|__pycache__|logs?|\.cache)(\/|$)/i.test(path) ||
          /(^|\/)(?:tsconfig(?:\.[^/]+)?\.json|tsup\.config\.[cm]?ts|vitest(?:\.[^/]+)?\.config\.[cm]?ts)$/i.test(
            path,
          ) ||
          /\.(?:pyc|pyo|log)$/.test(path),
      );
      expect(forbidden).toEqual([]);

      const registryIndex = JSON.parse(
        runText("tar", ["-xOf", tarball, "package/registry/index.json"]),
      ) as { integrations?: Record<string, { manifest?: string } | string> };
      const integrations = registryIndex.integrations ?? {};
      expect(Object.keys(integrations).length).toBeGreaterThan(0);
      for (const [name, entry] of Object.entries(integrations)) {
        const manifestPath = typeof entry === "string" ? entry : entry.manifest;
        expect(manifestPath, `${name} has no manifest`).toBeTruthy();
        const packedManifest = `registry/${manifestPath!}`;
        expect(paths, `missing ${packedManifest}`).toContain(packedManifest);
        const manifest = JSON.parse(
          runText("tar", ["-xOf", tarball, `package/${packedManifest}`]),
        ) as { files?: string[] };
        expect(manifest.files?.length, `${name} manifest has no files`).toBeGreaterThan(0);
        const manifestDirectory = dirname(packedManifest);
        for (const file of manifest.files ?? []) {
          expect(paths, `missing ${name} manifest file ${file}`).toContain(
            join(manifestDirectory, file).replaceAll("\\", "/"),
          );
        }
      }
      expect(manifest.dependencies).toEqual({
        ajv: "^8.20.0",
        "ajv-formats": "^3.0.1",
      });
      expect(manifest.peerDependencies?.zod).toBe(">=4.3 <5");
      expect(manifest.devDependencies?.zod).toBe("^4.3.6");
      const sourceManifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
      expect(manifest.devDependencies?.["@types/node"]).toBe(
        sourceManifest.devDependencies["@types/node"],
      );
      expect(manifest.dependencies).not.toHaveProperty("zod");
      const prefix = "package/contracts/";
      const actual = runText("tar", ["-tzf", tarball])
        .split("\n")
        .filter((path) => path.startsWith(prefix) && /\.(json|md)$/.test(path))
        .map((path) => path.slice(prefix.length))
        .sort();
      const expected = contractFiles(canonicalRoot);

      expect(actual).toEqual(expected);
      for (const path of expected) {
        const packaged = runBytes("tar", ["-xOf", tarball, `${prefix}${path}`]);
        expect(packaged).toEqual(readFileSync(join(canonicalRoot, path)));
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);
});
