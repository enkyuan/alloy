import { execFileSync } from "node:child_process";
import {
  cpSync,
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

const GITHUB_PACKAGE_PROOF = {
  schemaVersion: 1,
  evidenceClass: "offline_exact_artifact_smoke",
  integration: "github",
  runtime: "typescript",
  network: "scripted",
  liveProvider: false,
  contractVersion: "1.0.0",
  caseCount: 23,
  toolCount: 6,
  approvalDeniedBeforeCredentialAccess: true,
  mutationRetries: 0,
  unknownMutationPreserved: true,
  sourceRuntimeDetected: false,
  conclusion: "passed",
  failureCode: null,
};

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
    expect(lock.packages["node_modules/@kaji/sdk"].resolved).toBe("file:kaji-sdk-0.2.0-beta.1.tgz");
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
  });

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
      "./openai",
      "./testing",
    ]);
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
      "const nodeTypesPackage = `@types/node@${nodeTypesRange}`",
      "type SmokePhase =",
      "error instanceof CommandError",
      "package smoke failed at phase ${phase}",
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
      "assertGithubCliAddOutput(githubOutput, github, installedPackageRoot)",
      "assertGithubPackageProof",
      'const githubProofRunner = join(bootstrap, "installed-github-smoke.mts");',
      "copyFileSync(INSTALLED_GITHUB_SMOKE, githubProofRunner)",
      "`${manager}:github-package-proof`",
      '"--sandbox-root"',
      '"--bundle-root"',
      '"--package-root"',
      "githubPackageProofs: { npm: npmTiming.githubProof, bun: bunTiming.githubProof }",
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
      "coldResult.text !== warmResult.text",
      "coldResult.finalSequence !== warmResult.finalSequence",
      "const githubRequester = integrations.createGitHubRequester();",
      "const gmailRequester = integrations.createGmailRequester();",
      "githubRequester.close();",
      "gmailRequester.close();",
    ]) {
      expect(source).toContain(required);
    }

    expect(source).not.toContain("completed.stderr");
    expect(source).not.toContain("JSON.stringify(args)");
    expect(source).not.toContain("node_modules/.bin/kaji");
    expect(source).not.toContain(
      'const githubModule = JSON.stringify(join(installedPackageRoot, "registry/github/index.ts"));',
    );
    expect(source).not.toContain("node_modules/@kaji/sdk/dist/cli/bin.js");
    expect(source).not.toContain('if (!fields.get("text")');
    expect(source).toMatch(
      /await install\(\s*manager,\s*"bootstrap",[\s\S]*?nodeTypesPackage[\s\S]*?environment,\s*\)/,
    );
  });

  it("keeps the installed GitHub behavior receipt deterministic and non-live", () => {
    const runner = readFileSync(resolve(packageRoot, "scripts/installed-github-smoke.mts"), "utf8");
    for (const required of [
      'evidenceClass: "offline_exact_artifact_smoke"',
      'integration: "github"',
      'runtime: "typescript"',
      'network: "scripted"',
      "liveProvider: false",
      "caseCount: fixture.cases.length",
      "toolCount: executedTools.size",
      "approvalDeniedBeforeCredentialAccess: true",
      "mutationRetries: 0",
      "unknownMutationPreserved: true",
      "sourceRuntimeDetected: false",
      'const sdk = await import("@kaji/sdk");',
      'Reflect.set(Socket.prototype, "connect"',
      "factoryClosesOwnedTransport",
      "createGithubIntegration",
      "factoryLifecycleClosed",
      'error.name === "IntegrationPolicyError"',
    ]) {
      expect(runner).toContain(required);
    }
    expect(runner).not.toMatch(/import\s+\{[^}]*\}\s+from "@kaji\/sdk";/);
    expect(runner.indexOf('Reflect.set(Socket.prototype, "connect"')).toBeLessThan(
      runner.indexOf('const sdk = await import("@kaji/sdk");'),
    );
    expect(runner).not.toContain("process.env.GITHUB_TOKEN");
    expect(runner).not.toContain("createGitHubRequester");
    expect(runner).not.toContain("fetch(");
  });

  it("executes every GitHub package-proof case without network access", () => {
    const runner = resolve(packageRoot, "scripts/installed-github-smoke.mts");
    const environment = Object.fromEntries(
      ["HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TEMP", "TMP", "TMPDIR"].flatMap((name) =>
        process.env[name] === undefined ? [] : [[name, process.env[name]]],
      ),
    );
    const output = runText(
      "bun",
      [
        "--no-install",
        runner,
        "--sandbox-root",
        repositoryRoot,
        "--bundle-root",
        resolve(packageRoot, "registry/github"),
        "--package-root",
        packageRoot,
      ],
      { cwd: packageRoot, env: environment },
    );

    expect(JSON.parse(output)).toEqual(GITHUB_PACKAGE_PROOF);
  });

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
      expect(manifest.version).toBe("0.2.0-beta.1");
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
      expect(runBytes("tar", ["-xOf", tarball, "package/LICENSE"])).toEqual(
        readFileSync(join(repositoryRoot, "LICENSE")),
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
      for (const declarationPath of ["dist/index.d.ts", "dist/index.d.cts"]) {
        const declaration = runText("tar", ["-xOf", tarball, `package/${declarationPath}`]);
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
