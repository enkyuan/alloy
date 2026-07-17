import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, join, resolve } from "node:path";
import { performance } from "node:perf_hooks";

import { assertCliListOutput } from "./cli_assertions";
import { CommandError, runCommand as runBoundedCommand } from "./command";

type PackageManager = "npm" | "bun";
type InstallStage = "package" | "bootstrap" | "generated";
type SmokePhase =
  | "npm:pack"
  | "node:version"
  | "npm:audit"
  | "exports:esm"
  | "exports:cjs"
  | "cli:help"
  | "cli:help-cjs"
  | "docs:compile-typescript-current"
  | "docs:run"
  | `${PackageManager}:${InstallStage}-install`
  | `${PackageManager}:cli-init`
  | `${PackageManager}:cli-owner-conflict`
  | `${PackageManager}:cli-owner-qualified`
  | `${PackageManager}:cli-add`
  | `${PackageManager}:cli-inspect`
  | `${PackageManager}:github-package-proof`
  | `${PackageManager}:cli-list`
  | `${PackageManager}:cli-replay`
  | `${PackageManager}:compile-typescript-5.7`
  | `${PackageManager}:compile-typescript-current`
  | `${PackageManager}:lifecycle-run`
  | `${PackageManager}:cold-run`
  | `${PackageManager}:warm-run`;
interface PackageManifest {
  version: string;
  peerDependencies: Record<string, string>;
  devDependencies: Record<string, string>;
}
interface ArtifactIdentity {
  commit: string | null;
  manifestSha256: string | null;
  artifactSha256: Record<string, string>;
}
interface SmokeArguments {
  tarball?: string;
  releaseManifest?: string;
  expectedCommit?: string;
  output?: string;
}

interface GitHubPackageProof {
  readonly schemaVersion: 1;
  readonly evidenceClass: "offline_exact_artifact_smoke";
  readonly integration: "github";
  readonly runtime: "typescript";
  readonly network: "scripted";
  readonly liveProvider: false;
  readonly contractVersion: "1.0.0";
  readonly caseCount: 23;
  readonly toolCount: 6;
  readonly approvalDeniedBeforeCredentialAccess: true;
  readonly mutationRetries: 0;
  readonly unknownMutationPreserved: true;
  readonly sourceRuntimeDetected: false;
  readonly conclusion: "passed";
  readonly failureCode: null;
}

const packageRoot = resolve(import.meta.dir, "..");
const repositoryRoot = resolve(packageRoot, "../..");
const INSTALLED_GITHUB_SMOKE = resolve(import.meta.dir, "installed-github-smoke.mts");
let workdir = "";
let installRoot = "";
const nodeBinary = process.env.NODE_BINARY ?? "node";
const LOCAL_TIMEOUT_MS = 60_000;
const PACKAGE_TIMEOUT_MS = 300_000;
const MAX_OUTPUT_BYTES = 1024 * 1024;
const PACKAGE_VERSION = "0.2.0-beta.1";
const EXPECTED_MOCK_REPLY = "The mock provider has completed the tool loop.";
const REPLAY_FIXTURE =
  JSON.stringify({
    id: "artifact-event",
    version: "1.0",
    timestamp: 0,
    type: "session.created",
    session_id: "artifact-session",
    sequence: 1,
  }) + "\n";
const LIFECYCLE_SMOKE_SOURCE = `import { AgentBuilder, InMemoryEventStore } from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";

const graceMs = 10_000;
const sessionId = "installed-purge-session";
const store = new InMemoryEventStore({ maxSessions: 1, maxEventsPerSession: 100 });
const runtime = new AgentBuilder().provider(new MockProvider()).build({ store });
let failed = false;
let failure: unknown;
try {
  await runtime.turn("Exercise explicit lifecycle cleanup.", { sessionId });
} catch (error) {
  failed = true;
  failure = error;
} finally {
  try {
    const activeTools = await runtime.drainTools(graceMs);
    const activeProviders = await runtime.drainProviders(graceMs);
    if (activeTools.length > 0 || activeProviders.length > 0) {
      throw new Error("installed lifecycle fixture did not drain owned work");
    }
    await runtime.purgeSession(sessionId);
  } catch (error) {
    if (!failed) {
      failed = true;
      failure = error;
    }
  } finally {
    runtime.close();
  }
}
if (failed) throw failure;
if ((await store.getEvents(sessionId)).length !== 0) {
  throw new Error("installed lifecycle fixture retained purged history");
}
console.log("lifecycle_purge=ok");
`;
const LEGACY_LEDGER_TYPES_SOURCE = `import {
  InMemoryToolIdempotencyLedger,
  type ToolIdempotencyLedger,
} from "@kaji/sdk";

const backing = new InMemoryToolIdempotencyLedger();
const legacyLedger: ToolIdempotencyLedger = {
  claim: (...args) => backing.claim(...args),
  complete: (...args) => backing.complete(...args),
  retryableFailure: (...args) => backing.retryableFailure(...args),
  unknownOutcome: (...args) => backing.unknownOutcome(...args),
  releaseCompleted: (...args) => backing.releaseCompleted(...args),
};
void legacyLedger;
`;
const baseEnvironment = {
  ...process.env,
  npm_config_audit: "false",
  npm_config_fund: "false",
  npm_config_update_notifier: "false",
};

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function parseArguments(argv: string[]): SmokeArguments {
  const parsed: SmokeArguments = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]!;
    if (argument === "--release-manifest") {
      parsed.releaseManifest = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--expected-commit") {
      parsed.expectedCommit = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--output") {
      parsed.output = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument.startsWith("--") || parsed.tarball !== undefined) {
      throw new Error(`unexpected package smoke argument: ${argument}`);
    } else {
      parsed.tarball = argument;
    }
  }
  if ((parsed.releaseManifest === undefined) !== (parsed.expectedCommit === undefined)) {
    throw new Error("--release-manifest and --expected-commit must be supplied together");
  }
  return parsed;
}

function requiredFlagValue(argv: string[], index: number, flag: string): string {
  const value = argv[index + 1];
  if (value === undefined || value === "" || value.startsWith("--")) {
    throw new Error(`${flag} requires a value`);
  }
  return value;
}

function requestedOutput(argv: string[]): string | undefined {
  const index = argv.indexOf("--output");
  const output = index === -1 ? undefined : argv[index + 1];
  if (output === undefined || output === "" || output.startsWith("--")) return undefined;
  return output;
}

function artifactIdentity(
  tarball: string,
  releaseManifest: string | undefined,
  expectedCommit: string | undefined,
): ArtifactIdentity {
  const artifactHash = sha256(tarball);
  if (releaseManifest === undefined || expectedCommit === undefined) {
    return {
      commit: process.env.KAJI_RELEASE_COMMIT ?? process.env.GITHUB_SHA ?? null,
      manifestSha256: null,
      artifactSha256: { [basename(tarball)]: artifactHash },
    };
  }
  const manifestPath = resolve(releaseManifest);
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
    commit?: unknown;
    artifacts?: Array<{ file?: unknown; sha256?: unknown }>;
  };
  if (manifest.commit !== expectedCommit) {
    throw new Error("release manifest commit differs from the expected commit");
  }
  const entry = manifest.artifacts?.find((candidate) => candidate.file === basename(tarball));
  if (entry?.sha256 !== artifactHash) {
    throw new Error("supplied npm tarball differs from its release manifest identity");
  }
  return {
    commit: expectedCommit,
    manifestSha256: sha256(manifestPath),
    artifactSha256: { [basename(tarball)]: artifactHash },
  };
}

function emitReceipt(receipt: Record<string, unknown>, output: string | undefined): void {
  const encoded = `${JSON.stringify(receipt)}\n`;
  if (output !== undefined) {
    const path = resolve(output);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, encoded);
  }
  process.stdout.write(encoded);
}

function githubProofEnvironment(environment: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const allowed = [
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TEMP",
    "TMP",
    "TMPDIR",
  ];
  const proof = Object.fromEntries(
    allowed.flatMap((name) => (environment[name] === undefined ? [] : [[name, environment[name]]])),
  );
  return {
    ...proof,
    BUN_CONFIG_REGISTRY: "http://127.0.0.1:9",
    NO_COLOR: "1",
  };
}

function assertGithubPackageProof(output: string): GitHubPackageProof {
  let document: unknown;
  try {
    document = JSON.parse(output);
  } catch {
    throw new Error("GitHub package proof emitted invalid JSON");
  }
  const expected: GitHubPackageProof = {
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
  if (
    typeof document !== "object" ||
    document === null ||
    Array.isArray(document) ||
    JSON.stringify(document) !== JSON.stringify(expected)
  ) {
    throw new Error("GitHub package proof receipt is invalid");
  }
  return document as GitHubPackageProof;
}

async function runCommand(
  phase: SmokePhase,
  command: string,
  args: string[],
  cwd = installRoot,
  environment: NodeJS.ProcessEnv = baseEnvironment,
  timeoutMs = LOCAL_TIMEOUT_MS,
  expectedStatus = 0,
): Promise<string> {
  try {
    const completed = await runBoundedCommand({
      command,
      args,
      cwd,
      env: environment,
      timeoutMs,
      maxOutputBytes: MAX_OUTPUT_BYTES,
      check: false,
    });
    if (completed.status !== expectedStatus) {
      throw new CommandError(
        `release command exited with status ${completed.status}, expected ${expectedStatus}`,
      );
    }
    return completed.stdout;
  } catch (error) {
    if (error instanceof CommandError) {
      error.message = `package smoke failed at phase ${phase}: ${error.message}`;
    }
    throw error;
  }
}

function readManifest(path: string): PackageManifest {
  return JSON.parse(readFileSync(path, "utf8")) as PackageManifest;
}

function assertGeneratedVersions(
  generated: PackageManifest & { dependencies?: Record<string, string> },
  installed: PackageManifest,
): void {
  const expected = {
    "@kaji/sdk": installed.version,
    zod: installed.peerDependencies.zod,
  };
  if (JSON.stringify(generated.dependencies) !== JSON.stringify(expected)) {
    throw new Error("generated mock dependency versions do not match installed package metadata");
  }
  if (generated.dependencies?.["@kaji/sdk"] !== PACKAGE_VERSION) {
    throw new Error("generated scaffold did not use the exact installed prerelease version");
  }
  if (generated.dependencies["@kaji/sdk"].startsWith("^") || "openai" in generated.dependencies) {
    throw new Error("generated mock scaffold added an unrequested provider or version caret");
  }
  if (generated.devDependencies.typescript57 !== "npm:typescript@5.7.3") {
    throw new Error("generated scaffold did not pin the TypeScript 5.7.3 compiler alias");
  }
  if (generated.devDependencies["@types/node"] !== installed.devDependencies["@types/node"]) {
    throw new Error("generated scaffold did not use the installed @types/node range");
  }
  if (
    generated.devDependencies["@dotenvx/dotenvx"] !== installed.devDependencies["@dotenvx/dotenvx"]
  ) {
    throw new Error("generated scaffold did not use the installed dotenvx version");
  }
  const currentCompiler = generated.devDependencies.typescript;
  if (typeof currentCompiler !== "string" || !currentCompiler.includes("6.")) {
    throw new Error("generated scaffold did not declare the current TypeScript 6.x compiler");
  }
}

function assertScaffoldOutput(output: string): { text: string; finalSequence: number } {
  const fields = new Map(
    output
      .split("\n")
      .filter((line) => line.includes("="))
      .map((line) => line.split("=", 2) as [string, string]),
  );
  if (fields.get("text") !== EXPECTED_MOCK_REPLY) {
    throw new Error("generated scaffold omitted the exact deterministic mock reply");
  }
  if (!fields.get("turn_id")) {
    throw new Error("generated scaffold omitted a non-empty turn id");
  }
  const sequence = Number(fields.get("final_sequence"));
  if (!Number.isSafeInteger(sequence) || sequence <= 0) {
    throw new Error("generated scaffold omitted a positive final sequence");
  }
  return { text: EXPECTED_MOCK_REPLY, finalSequence: sequence };
}

function assertLifecycleOutput(output: string): void {
  const fields = new Map(
    output
      .split("\n")
      .filter((line) => line.includes("="))
      .map((line) => line.split("=", 2) as [string, string]),
  );
  if (fields.get("lifecycle_purge") !== "ok") {
    throw new Error("installed lifecycle fixture did not prove explicit purge");
  }
}

function assertCliInitOutput(output: string, generated: string): void {
  for (const name of ["package.json", "tsconfig.json", "agent.ts", ".env.example"]) {
    const path = join(generated, name);
    if (!existsSync(path) || !output.includes(`wrote ${path}`)) {
      throw new Error("installed init did not report and write every scaffold file");
    }
  }
}

function assertCliOwnerOutput(output: string): void {
  if (!output.split("\n").includes(`kaji (@kaji/sdk) ${PACKAGE_VERSION}`)) {
    throw new Error("qualified TypeScript CLI owner/version mismatch");
  }
}

function createConflictingKajiFixture(root: string): string {
  const fixture = join(root, "conflicting-kaji-cli");
  mkdirSync(fixture, { recursive: true });
  writeFileSync(
    join(fixture, "package.json"),
    JSON.stringify({
      name: "conflicting-kaji-cli",
      version: "9.9.9",
      bin: { kaji: "./kaji.mjs" },
    }),
  );
  writeFileSync(
    join(fixture, "kaji.mjs"),
    '#!/usr/bin/env node\nconsole.log("kaji (conflicting fixture) 9.9.9");\n',
    { mode: 0o755 },
  );
  return fixture;
}

function assertCliAddOutput(
  output: string,
  destination: string,
  installedPackageRoot: string,
): void {
  const copied = join(destination, "index.ts");
  const packaged = join(installedPackageRoot, "registry/echo/index.ts");
  if (!existsSync(copied) || !readFileSync(copied).equals(readFileSync(packaged))) {
    throw new Error("installed add did not copy the packaged Echo asset");
  }
  if (!output.includes(`Wrote 1 file(s) to ${realpathSync(destination)}`)) {
    throw new Error("installed add did not report the copied Echo asset");
  }
}

function assertExperimentalDenial(output: string, destination: string): void {
  if (!output.includes("experimental") || !output.includes("--allow-experimental")) {
    throw new Error("installed add did not explain the experimental opt-in");
  }
  if (existsSync(destination)) {
    throw new Error("denied experimental add created its destination");
  }
}

function assertGithubCliAddOutput(
  output: string,
  destination: string,
  installedPackageRoot: string,
): void {
  const packagedRoot = join(installedPackageRoot, "registry/github");
  const manifest = JSON.parse(readFileSync(join(packagedRoot, "manifest.json"), "utf8")) as {
    files: string[];
  };
  for (const name of manifest.files) {
    const copied = join(destination, name);
    const packaged = join(packagedRoot, name);
    if (!existsSync(copied) || !readFileSync(copied).equals(readFileSync(packaged))) {
      throw new Error("installed add did not copy the packaged GitHub assets");
    }
  }
  const provenance = JSON.parse(
    readFileSync(join(destination, ".kaji-integration-provenance.json"), "utf8"),
  ) as {
    integration?: string;
    runtime?: string;
    abiSha256?: string | null;
    files?: Record<string, string>;
  };
  if (
    provenance.integration !== "github" ||
    provenance.runtime !== "typescript" ||
    !provenance.abiSha256 ||
    JSON.stringify(Object.keys(provenance.files ?? {}).sort()) !==
      JSON.stringify([...manifest.files].sort())
  ) {
    throw new Error("installed GitHub provenance is incomplete");
  }
  if (!output.includes(`Wrote ${manifest.files.length} file(s) to ${realpathSync(destination)}`)) {
    throw new Error("installed add did not report the copied GitHub assets");
  }
}

function assertCliReplayOutput(output: string): void {
  if (
    !/^Session session_[a-f0-9]{16}\s+turns=0\s+tool_calls=0\s+errors=0, seq=1-1$/u.test(
      output.trim(),
    ) ||
    output.includes("\u001b[")
  ) {
    throw new Error("installed replay did not render the canonical JSONL fixture");
  }
}

function assertRootDeclarationsVendorNeutral(installedPackageRoot: string): void {
  for (const declarationFile of ["index.d.ts", "index.d.cts"]) {
    const declaration = readFileSync(join(installedPackageRoot, "dist", declarationFile), "utf8");
    if (
      /from ["']openai["']/.test(declaration) ||
      /from ["']@anthropic-ai\/sdk["']/.test(declaration) ||
      declaration.includes("Promise<OpenAI>") ||
      declaration.includes("Promise<Anthropic>")
    ) {
      throw new Error(`root ${declarationFile} references an optional provider peer`);
    }
  }
}

async function install(
  manager: PackageManager,
  stage: InstallStage,
  cwd: string,
  packages: string[],
  environment: NodeJS.ProcessEnv,
): Promise<void> {
  if (manager === "npm") {
    await runCommand(
      `${manager}:${stage}-install`,
      "npm",
      ["install", "--ignore-scripts", ...packages],
      cwd,
      environment,
      PACKAGE_TIMEOUT_MS,
    );
  } else {
    await runCommand(
      `${manager}:${stage}-install`,
      "bun",
      packages.length === 0
        ? ["install", "--ignore-scripts"]
        : ["add", "--ignore-scripts", ...packages],
      cwd,
      environment,
      PACKAGE_TIMEOUT_MS,
    );
  }
}

async function runScaffold(
  manager: PackageManager,
  tarball: string,
  nodeTypesPackage: string,
): Promise<{
  coldSetupToOutputMs: number;
  warmRunMs: number;
  githubProof: GitHubPackageProof;
}> {
  const started = performance.now();
  const root = join(workdir, `${manager}-scaffold`);
  const bootstrap = join(root, "bootstrap");
  const generated = join(root, "generated");
  mkdirSync(bootstrap, { recursive: true });
  writeFileSync(
    join(bootstrap, "package.json"),
    JSON.stringify({ name: `kaji-${manager}-bootstrap`, version: "1.0.0", private: true }),
  );
  const environment = {
    ...baseEnvironment,
    npm_config_cache: join(root, "npm-cache"),
    BUN_INSTALL_CACHE_DIR: join(root, "bun-cache"),
  };
  const conflictingPackage = createConflictingKajiFixture(root);
  await install(
    manager,
    "bootstrap",
    bootstrap,
    [tarball, "zod@4.3.6", nodeTypesPackage, conflictingPackage],
    environment,
  );

  const installedConflict = join(bootstrap, "node_modules/conflicting-kaji-cli/kaji.mjs");
  if (!existsSync(installedConflict)) {
    throw new Error("conflicting kaji fixture was not installed");
  }
  const ownerCheckBin = join(root, "owner-check-bin");
  mkdirSync(ownerCheckBin);
  symlinkSync(installedConflict, join(ownerCheckBin, "kaji"));
  const ownerEnvironment = {
    ...environment,
    BUN_CONFIG_REGISTRY: "http://127.0.0.1:9",
    PATH: `${ownerCheckBin}${delimiter}${environment.PATH ?? ""}`,
  };
  const nestedWorkdir = join(bootstrap, "nested", "deeper");
  mkdirSync(nestedWorkdir, { recursive: true });
  const conflictOutput = await runCommand(
    `${manager}:cli-owner-conflict`,
    "kaji",
    ["--help"],
    nestedWorkdir,
    ownerEnvironment,
  );
  if (conflictOutput.trim() !== "kaji (conflicting fixture) 9.9.9") {
    throw new Error("bare TypeScript CLI did not select the conflicting fixture");
  }

  const cliCommand = "bun";
  const cli = ["--no-install", "-e", 'import("@kaji/sdk/cli")', "--"];
  const ownerOutput = await runCommand(
    `${manager}:cli-owner-qualified`,
    cliCommand,
    [...cli, "--help"],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertCliOwnerOutput(ownerOutput);
  console.log(
    JSON.stringify({ manager, nestedConflictProof: true, owner: `@kaji/sdk ${PACKAGE_VERSION}` }),
  );
  const initOutput = await runCommand(
    `${manager}:cli-init`,
    cliCommand,
    [...cli, "--no-color", "init", generated, "--provider", "mock", "--yes"],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertCliInitOutput(initOutput, generated);

  const installedPackageRoot = join(bootstrap, "node_modules/@kaji/sdk");
  const echo = join(root, "echo");
  const addOutput = await runCommand(
    `${manager}:cli-add`,
    cliCommand,
    [...cli, "--no-color", "add", "echo", "--out", echo],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertCliAddOutput(addOutput, echo, installedPackageRoot);

  const deniedGithub = join(root, "denied-github");
  const denialOutput = await runCommand(
    `${manager}:cli-add`,
    cliCommand,
    [...cli, "--no-color", "add", "github", "--out", deniedGithub],
    nestedWorkdir,
    ownerEnvironment,
    LOCAL_TIMEOUT_MS,
    1,
  );
  assertExperimentalDenial(denialOutput, deniedGithub);

  const github = join(bootstrap, "owner-integrations/github");
  const githubOutput = await runCommand(
    `${manager}:cli-add`,
    cliCommand,
    [...cli, "--no-color", "add", "github", "--allow-experimental", "--out", github],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertGithubCliAddOutput(githubOutput, github, installedPackageRoot);
  const githubProofRunner = join(bootstrap, "installed-github-smoke.mts");
  copyFileSync(INSTALLED_GITHUB_SMOKE, githubProofRunner);
  const githubProof = assertGithubPackageProof(
    await runCommand(
      `${manager}:github-package-proof`,
      "bun",
      [
        "--no-install",
        githubProofRunner,
        "--sandbox-root",
        root,
        "--bundle-root",
        github,
        "--package-root",
        realpathSync(installedPackageRoot),
      ],
      bootstrap,
      githubProofEnvironment(ownerEnvironment),
    ),
  );
  const githubModule = JSON.stringify(join(github, "index.ts"));
  await runCommand(
    `${manager}:cli-inspect`,
    "bun",
    [
      "--eval",
      `const { inspectIntegration } = await import(${githubModule}); if (inspectIntegration().tools().length !== 6) process.exit(1);`,
    ],
    bootstrap,
    ownerEnvironment,
  );

  const listOutput = await runCommand(
    `${manager}:cli-list`,
    cliCommand,
    [...cli, "--no-color", "list-integrations", "--json"],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertCliListOutput(listOutput);

  const replayFixture = join(root, "session.jsonl");
  writeFileSync(replayFixture, REPLAY_FIXTURE);
  const replayOutput = await runCommand(
    `${manager}:cli-replay`,
    cliCommand,
    [...cli, "--no-color", "replay", replayFixture, "--format", "summary"],
    nestedWorkdir,
    ownerEnvironment,
  );
  assertCliReplayOutput(replayOutput);

  const installed = readManifest(join(installedPackageRoot, "package.json"));
  const generatedManifestPath = join(generated, "package.json");
  const generatedManifest = readManifest(generatedManifestPath) as PackageManifest & {
    dependencies: Record<string, string>;
  };

  // Validate the registry-facing versions before replacing only the SDK entry
  // with the exact local tarball used by this release smoke.
  assertGeneratedVersions(generatedManifest, installed);
  generatedManifest.dependencies["@kaji/sdk"] = tarball;
  writeFileSync(generatedManifestPath, JSON.stringify(generatedManifest, null, 2));
  await install(manager, "generated", generated, [], environment);
  writeFileSync(join(generated, "lifecycle.ts"), LIFECYCLE_SMOKE_SOURCE);
  writeFileSync(join(generated, "legacy-ledger-types.ts"), LEGACY_LEDGER_TYPES_SOURCE);

  const config = JSON.parse(readFileSync(join(generated, "tsconfig.json"), "utf8")) as {
    compilerOptions?: { skipLibCheck?: boolean; types?: unknown };
  };
  if (config.compilerOptions?.skipLibCheck !== false) {
    throw new Error("generated scaffold must compile with skipLibCheck disabled");
  }
  if (JSON.stringify(config.compilerOptions.types) !== JSON.stringify(["node"])) {
    throw new Error("generated scaffold must load Node ambient declarations explicitly");
  }
  for (const compiler of ["typescript57", "typescript"] as const) {
    const tsc = join(generated, `node_modules/${compiler}/bin/tsc`);
    if (!existsSync(tsc)) throw new Error(`generated scaffold is missing ${compiler}`);
    const phase =
      compiler === "typescript57"
        ? `${manager}:compile-typescript-5.7`
        : `${manager}:compile-typescript-current`;
    await runCommand(phase, nodeBinary, [tsc, "--project", "tsconfig.json", "--noEmit"], generated);
  }
  const tsx = join(generated, "node_modules/tsx/dist/cli.mjs");
  if (!existsSync(tsx)) throw new Error("generated scaffold is missing the tsx runner");
  const lifecycleOutput = await runCommand(
    `${manager}:lifecycle-run`,
    nodeBinary,
    [tsx, "lifecycle.ts"],
    generated,
    environment,
  );
  assertLifecycleOutput(lifecycleOutput);

  const run = (phase: SmokePhase) =>
    manager === "npm"
      ? runCommand(phase, "npm", ["run", "start", "--silent"], generated, environment)
      : runCommand(phase, "bun", ["run", "start"], generated, environment);
  const coldOutput = await run(`${manager}:cold-run`);
  const coldResult = assertScaffoldOutput(coldOutput);
  const coldSetupToOutputMs = Math.round((performance.now() - started) * 1000) / 1000;
  const warmStarted = performance.now();
  const warmOutput = await run(`${manager}:warm-run`);
  const warmResult = assertScaffoldOutput(warmOutput);
  if (
    coldResult.text !== warmResult.text ||
    coldResult.finalSequence !== warmResult.finalSequence
  ) {
    throw new Error("cold and warm generated scaffold outputs differed");
  }
  const warmRunMs = Math.round((performance.now() - warmStarted) * 1000) / 1000;
  return { coldSetupToOutputMs, warmRunMs, githubProof };
}

const rawArguments = process.argv.slice(2);
const fallbackOutput = requestedOutput(rawArguments);
let arguments_: SmokeArguments = {};
let receiptIdentity: ArtifactIdentity | null = null;
let receiptTarball: string | null = null;
let installedPackagePath: string | null = null;
let receiptNodeVersion = process.version;

try {
  arguments_ = parseArguments(rawArguments);
  workdir = mkdtempSync(join(tmpdir(), "kaji-installed-smoke-"));
  installRoot = join(workdir, "project");
  mkdirSync(installRoot, { recursive: true });
  const requestedTarball = arguments_.tarball;
  let tarball: string;
  if (requestedTarball === undefined) {
    const environment = {
      ...baseEnvironment,
      npm_config_cache: join(workdir, "pack-cache"),
    };
    const packed = JSON.parse(
      await runCommand(
        "npm:pack",
        "npm",
        ["pack", "--json", "--ignore-scripts", "--pack-destination", workdir],
        packageRoot,
        environment,
      ),
    ) as Array<{ filename: string }>;
    const filename = packed[0]?.filename;
    if (!filename) throw new Error("npm pack did not report a tarball");
    tarball = join(workdir, filename);
  } else {
    tarball = resolve(requestedTarball);
    if (!existsSync(tarball)) throw new Error("supplied npm tarball does not exist");
  }
  tarball = realpathSync(tarball);
  receiptTarball = tarball;
  receiptIdentity = artifactIdentity(
    tarball,
    arguments_.releaseManifest,
    arguments_.expectedCommit,
  );

  const nodeVersion = (await runCommand("node:version", nodeBinary, ["--version"])).trim();
  receiptNodeVersion = nodeVersion;
  const nodeMajor = Number(/^v(\d+)/.exec(nodeVersion)?.[1]);
  if (nodeMajor !== 22 && nodeMajor !== 24) {
    throw new Error(
      `package smoke requires the tested Node 22 or 24 line, received ${nodeVersion}`,
    );
  }

  const npmEnvironment = {
    ...baseEnvironment,
    npm_config_cache: join(workdir, "npm-cache"),
  };
  writeFileSync(
    join(installRoot, "package.json"),
    JSON.stringify({ name: "kaji-package-smoke", version: "1.0.0", private: true }),
  );
  const packageManifest = readManifest(join(packageRoot, "package.json"));
  const nodeTypesRange = packageManifest.devDependencies["@types/node"];
  if (nodeTypesRange === undefined) {
    throw new Error("package metadata has no supported @types/node range");
  }
  const nodeTypesPackage = `@types/node@${nodeTypesRange}`;
  await install(
    "npm",
    "package",
    installRoot,
    [tarball, "zod@4.3.6", "openai@6.42.0", "@anthropic-ai/sdk@0.104.1", nodeTypesPackage],
    npmEnvironment,
  );
  if (!existsSync(join(installRoot, "node_modules/@kaji/sdk/dist/cli/init-worker.js"))) {
    throw new Error("installed package is missing the pinned init worker");
  }
  installedPackagePath = realpathSync(join(installRoot, "node_modules/@kaji/sdk"));
  await runCommand(
    "npm:audit",
    "npm",
    ["audit", "--omit=dev", "--audit-level=high"],
    installRoot,
    { ...npmEnvironment, npm_config_audit: "true" },
    PACKAGE_TIMEOUT_MS,
  );

  const esm = `
import * as sdk from "@kaji/sdk";
import * as testing from "@kaji/sdk/testing";
import * as openai from "@kaji/sdk/openai";
import * as anthropic from "@kaji/sdk/anthropic";
import * as integrations from "@kaji/sdk/integrations";
if (sdk.VERSION !== "${PACKAGE_VERSION}" || !sdk.AgentRuntime || !sdk.supportsSessionPurge || !sdk.SessionPurgeBusyError || !sdk.SessionPurgeUnsupportedError || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
if (JSON.stringify(Object.keys(integrations).sort()) !== JSON.stringify(["IntegrationAuthRequiredError", "IntegrationExecutionError", "IntegrationPolicyError", "IntegrationRateLimitedError", "IntegrationTransientReadError", "createGitHubRequester", "createGmailRequester", "snapshotIntegrationResult"].sort())) process.exit(1);
const githubRequester = integrations.createGitHubRequester();
const gmailRequester = integrations.createGmailRequester();
githubRequester.close();
githubRequester.close();
gmailRequester.close();
gmailRequester.close();
`;
  const cjs = `
const sdk = require("@kaji/sdk");
const testing = require("@kaji/sdk/testing");
const openai = require("@kaji/sdk/openai");
const anthropic = require("@kaji/sdk/anthropic");
const integrations = require("@kaji/sdk/integrations");
if (sdk.VERSION !== "${PACKAGE_VERSION}" || !sdk.AgentRuntime || !sdk.supportsSessionPurge || !sdk.SessionPurgeBusyError || !sdk.SessionPurgeUnsupportedError || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
if (JSON.stringify(Object.keys(integrations).sort()) !== JSON.stringify(["IntegrationAuthRequiredError", "IntegrationExecutionError", "IntegrationPolicyError", "IntegrationRateLimitedError", "IntegrationTransientReadError", "createGitHubRequester", "createGmailRequester", "snapshotIntegrationResult"].sort())) process.exit(1);
const githubRequester = integrations.createGitHubRequester();
const gmailRequester = integrations.createGmailRequester();
githubRequester.close();
githubRequester.close();
gmailRequester.close();
gmailRequester.close();
`;
  writeFileSync(join(installRoot, "smoke.mjs"), esm);
  writeFileSync(join(installRoot, "smoke.cjs"), cjs);
  await runCommand("exports:esm", nodeBinary, ["smoke.mjs"]);
  await runCommand("exports:cjs", nodeBinary, ["smoke.cjs"]);
  const ownerOutput = await runCommand(
    "cli:help",
    "bun",
    ["--no-install", "-e", 'import("@kaji/sdk/cli")', "--", "--help"],
    installRoot,
    { ...npmEnvironment, BUN_CONFIG_REGISTRY: "http://127.0.0.1:9" },
  );
  assertCliOwnerOutput(ownerOutput);
  const cjsOwnerOutput = await runCommand(
    "cli:help-cjs",
    nodeBinary,
    ["--eval", 'process.argv=[process.execPath,"--help"]; require("@kaji/sdk/cli");'],
    installRoot,
    npmEnvironment,
  );
  assertCliOwnerOutput(cjsOwnerOutput);

  const docs = readFileSync(join(repositoryRoot, "docs/kaji/production-beta.md"), "utf8");
  const quickstart = docs.match(
    /<!-- installed-quickstart:typescript:start -->\s*```ts\n([\s\S]*?)\n```\s*<!-- installed-quickstart:typescript:end -->/,
  )?.[1];
  if (quickstart === undefined) throw new Error("canonical TypeScript quickstart block is missing");
  writeFileSync(join(installRoot, "docs-quickstart.mts"), quickstart);
  writeFileSync(
    join(installRoot, "tsconfig.docs.json"),
    JSON.stringify({
      compilerOptions: {
        module: "NodeNext",
        moduleResolution: "NodeNext",
        noEmit: false,
        outDir: "compiled-docs",
        skipLibCheck: false,
        strict: true,
        target: "ES2022",
        types: ["node"],
      },
      include: ["docs-quickstart.mts"],
    }),
  );
  const tsc = join(packageRoot, "node_modules/typescript/bin/tsc");
  if (!existsSync(tsc)) throw new Error("current TypeScript compiler is missing");
  await runCommand("docs:compile-typescript-current", nodeBinary, [
    tsc,
    "--project",
    "tsconfig.docs.json",
  ]);
  await runCommand("docs:run", nodeBinary, ["compiled-docs/docs-quickstart.mjs"]);

  const npmTiming = await runScaffold("npm", tarball, nodeTypesPackage);
  const bunTiming = await runScaffold("bun", tarball, nodeTypesPackage);
  assertRootDeclarationsVendorNeutral(join(installRoot, "node_modules/@kaji/sdk"));
  console.log(JSON.stringify({ npm: npmTiming, bun: bunTiming }));
  console.log(
    "PASS: exact npm tarball resolves exports and no-key npm/Bun scaffolds under TypeScript 5.7/current 6",
  );
  emitReceipt(
    {
      schemaVersion: 1,
      commit: receiptIdentity.commit,
      releaseManifestSha256: receiptIdentity.manifestSha256,
      artifactSha256: receiptIdentity.artifactSha256,
      runtime: { version: receiptNodeVersion },
      artifacts: { tarball: receiptTarball, package: installedPackagePath },
      githubPackageProofs: { npm: npmTiming.githubProof, bun: bunTiming.githubProof },
      conclusion: "passed",
      failureCode: null,
    },
    arguments_.output,
  );
} catch (error) {
  emitReceipt(
    {
      schemaVersion: 1,
      commit: receiptIdentity?.commit ?? arguments_.expectedCommit ?? null,
      releaseManifestSha256: receiptIdentity?.manifestSha256 ?? null,
      artifactSha256: receiptIdentity?.artifactSha256 ?? {},
      runtime: { version: receiptNodeVersion },
      artifacts: { tarball: receiptTarball, package: installedPackagePath },
      githubPackageProofs: {},
      conclusion: "failed",
      failureCode: receiptIdentity === null ? "artifact_identity_failed" : "node_smoke_failed",
    },
    arguments_.output ?? fallbackOutput,
  );
  throw error;
} finally {
  if (workdir !== "") rmSync(workdir, { recursive: true, force: true });
}
