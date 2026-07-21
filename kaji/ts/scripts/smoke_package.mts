import {
  closeSync,
  cpSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, join, relative, resolve } from "node:path";
import { performance } from "node:perf_hooks";

import { assertCliListOutput } from "./cli_assertions";
import { CommandError, runCommand as runBoundedCommand } from "./command";

type PackageManager = "npm" | "bun";
type InstallStage = "package" | "bootstrap" | "generated";
type GitHubTypeModule = "esm" | "cjs";
type GitHubTypeCompilerLine = "5.7" | "current";
type HandoffMode = "artifact-contract" | "node";
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
  | `${PackageManager}:github-types-compiler-version-${GitHubTypeCompilerLine}`
  | `${PackageManager}:github-types-${GitHubTypeModule}-typescript-${GitHubTypeCompilerLine}`
  | `${PackageManager}:lifecycle-run`
  | `${PackageManager}:failure-history-run`
  | `${PackageManager}:cold-run`
  | `${PackageManager}:warm-run`
  | `handoff:${string}`;
interface PackageManifest {
  version: string;
  peerDependencies: Record<string, string>;
  devDependencies: Record<string, string>;
}
interface LocalDependencyManifest {
  name: string;
  version: string;
  dependencies?: Record<string, string>;
  peerDependencies?: Record<string, string>;
  peerDependenciesMeta?: Record<string, { optional?: boolean }>;
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
  forHandoff?: HandoffMode;
  candidateRoot?: string;
  sourceCommit?: string;
  artifactSha256?: string;
  handoffNodeBinary?: string;
  expectedNodeMajor?: 22 | 24;
}

interface GitHubPackageProof {
  readonly schemaVersion: 5;
  readonly evidenceClass: "offline_exact_artifact_smoke";
  readonly integration: "github";
  readonly runtime: "typescript";
  readonly network: "blocked";
  readonly liveProvider: false;
  readonly sharedAbiVersion: "1.0.0";
  readonly packageAbiSchemaVersion: "1.0.0";
  readonly packageCatalogVersion: "0.2.0";
  readonly apiFixtureVersion: "1.0.0";
  readonly sharedFixtureCaseCount: number;
  readonly publicScenarioCount: number;
  readonly packageCatalog: {
    readonly schemaVersion: "1.0.0";
    readonly catalogVersion: "0.2.0";
    readonly toolCount: 15;
    readonly readToolCount: 13;
    readonly tools: readonly string[];
    readonly readTools: readonly string[];
    readonly providerAliases: readonly string[];
    readonly catalogNames: readonly string[];
  };
  readonly cliCopiedCatalog: {
    readonly manifestVersion: "0.1.0";
    readonly toolCount: 6;
    readonly readToolCount: 4;
    readonly tools: readonly string[];
    readonly readTools: readonly string[];
  };
  readonly esmSharedAbiMatched: true;
  readonly cjsSharedAbiMatched: true;
  readonly esmPackageAbiMatched: true;
  readonly cjsPackageAbiMatched: true;
  readonly esmClassIdentityMatched: true;
  readonly cjsClassIdentityMatched: true;
  readonly esmFactoryIdentityMatched: true;
  readonly cjsFactoryIdentityMatched: true;
  readonly esmRuntimeExports: readonly [
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ];
  readonly cjsRuntimeExports: readonly [
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ];
  readonly esmDeclarationExports: readonly [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ];
  readonly cjsDeclarationExports: readonly [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
  ];
  readonly typescriptDeclarationChecks: TypeScriptDeclarationChecks;
  readonly privateGitHubCompositionSourcesPacked: false;
  readonly privateGitHubCompositionSourceImportsRejected: true;
  readonly closedCallsDeniedBeforeCredentialAccess: true;
  readonly approvalDeniedBeforeCredentialAccess: true;
  readonly repositoryDeniedBeforeCredentialAccess: true;
  readonly githubCatalogEventsVerified: readonly ["requested", "started", "failed"];
  readonly genericSyntheticCatalogEventsVerified: readonly ["requested", "started", "completed"];
  readonly githubFailureRecovery: {
    readonly error_code: "INTEGRATION_AUTH_REQUIRED";
    readonly reason_code: "github_token_missing";
    readonly recovery_code: "CONFIGURE_GITHUB_TOKEN";
    readonly doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-token";
  };
  readonly githubObservabilitySinksVerified: true;
  readonly lifecycle: {
    readonly githubFailure: LifecycleProof;
    readonly syntheticCompletion: LifecycleProof;
  };
  readonly policyBeforeRequest: {
    readonly testFile: "kaji/ts/tests/github-registry.test.ts";
    readonly testName: "rejects approval for github_create_issue before token or HTTP";
    readonly tokenLookups: 0;
    readonly requestAttempts: 0;
  };
  readonly aliasCollisionRejected: true;
  readonly conclusion: "passed";
  readonly failureCode: null;
}

interface LifecycleProof {
  readonly stages: readonly string[];
  readonly providerAlias: string;
  readonly catalogName: string;
  readonly sameIdentityAtEveryStage: true;
}

interface TypeScriptDeclarationChecks {
  readonly compilerOptions: {
    readonly module: "NodeNext";
    readonly moduleResolution: "NodeNext";
    readonly skipLibCheck: false;
  };
  readonly typescript57: {
    readonly version: "5.7.3";
    readonly mtsImport: "passed";
    readonly ctsRequire: "passed";
  };
  readonly typescriptCurrent: {
    readonly version: string;
    readonly mtsImport: "passed";
    readonly ctsRequire: "passed";
  };
}

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
const GITHUB_TOOLS = [
  "add_comment",
  "create_issue",
  "get_file",
  "get_issue",
  "list_issues",
  "search_code",
  "get_commit",
  "get_pull_request",
  "list_pull_request_files",
  "list_check_runs",
  "get_workflow_run",
  "list_workflow_jobs",
  "list_file_commits",
  "get_release",
  "list_deployments",
] as const;
const GITHUB_READ_TOOLS = GITHUB_TOOLS.filter(
  (name) => name !== "add_comment" && name !== "create_issue",
);
const SHARED_GITHUB_TOOLS = GITHUB_TOOLS.slice(0, 6);
const SHARED_GITHUB_READ_TOOLS = GITHUB_READ_TOOLS.slice(0, 4);
const GITHUB_PROVIDER_ALIASES = GITHUB_TOOLS.map((name) => `github_${name}`);
const GITHUB_CATALOG_NAMES = GITHUB_TOOLS.map((name) => `github.${name}`);
const GITHUB_PUBLIC_SYMBOLS = [
  "CreateGitHubIntegrationOptions",
  "GitHubIntegration",
  "createGithubIntegration",
  "inspectIntegration",
] as const;
const ARTIFACT_SUBCHECKS = [
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
] as const;
const NODE_HANDOFF_CHECKS = [
  "npm-install",
  "esm-import",
  "commonjs-require",
  "catalog-15-13",
] as const;
const LICENSE_ID = "PolyForm-Noncommercial-1.0.0";
const POLICY_TEST_FILE = "kaji/ts/tests/github-registry.test.ts";
const POLICY_TEST_NAME = "rejects approval for github_create_issue before token or HTTP";
const PRIVATE_GITHUB_COMPOSITION_PATHS = [
  "registry/github/package-tools.ts",
  "registry/github/package.ts",
  "registry/github/package-internal.ts",
  "src/integrations/github.ts",
  "src/integrations/github-package-internal.ts",
] as const;
const EXPECTED_GITHUB_SOURCE_MAPS = [
  "dist/integrations/github.js.map",
  "dist/integrations/github.cjs.map",
] as const;
const PRIVATE_GITHUB_COMPOSITION_SOURCE_CANARIES = [
  "export interface PackageGitHubRuntime",
  "export function createPackageGitHubToolBindings(",
  "readonly createRequester: (observability:",
  "readonly createClient: (options: GitHubClientOptions)",
  "runtime: PackageGitHubRuntime = productionRuntime",
  "Preserve the client construction failure that prevented ownership transfer.",
] as const;

interface SourceMapDocument {
  readonly sources?: unknown;
  readonly sourcesContent?: unknown;
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
const PACKAGE_VERSION = "0.2.0-beta.2";
const EXPECTED_MOCK_REPLY = "The mock provider has completed the tool loop.";
const GITHUB_ESM_TYPES_SOURCE = `import {
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
  tokenFor: async () => "installed-type-proof",
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
direct.close();
created.close();
inspected.close();
`;
const GITHUB_CJS_TYPES_SOURCE = `import sdk = require("@kaji/sdk");
import github = require("@kaji/sdk/integrations/github");

const options: github.CreateGitHubIntegrationOptions = {
  tokenFor: async () => "installed-type-proof",
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
direct.close();
created.close();
inspected.close();
`;
const GITHUB_TYPES_COMPILER_OPTIONS = {
  module: "NodeNext",
  moduleResolution: "NodeNext",
  noEmit: true,
  skipLibCheck: false,
  strict: true,
  target: "ES2022",
  types: [],
} as const;
const GITHUB_TYPE_CONSUMERS = [
  {
    module: "esm",
    source: "github-types.mts",
    config: "tsconfig.github-types-esm.json",
  },
  {
    module: "cjs",
    source: "github-types.cts",
    config: "tsconfig.github-types-cjs.json",
  },
] as const;
const REPLAY_FIXTURE =
  JSON.stringify({
    id: "artifact-event",
    version: "1.0",
    timestamp: 0,
    type: "session.created",
    session_id: "artifact-session",
    sequence: 1,
  }) + "\n";
const LIFECYCLE_SMOKE_SOURCE = `import {
  AgentBuilder,
  InMemoryEventStore,
  type TurnAccounting,
} from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";

const graceMs = 10_000;
const sessionId = "installed-purge-session";
const store = new InMemoryEventStore({ maxSessions: 1, maxEventsPerSession: 100 });
const runtime = new AgentBuilder().provider(new MockProvider()).build({ store });
let failed = false;
let failure: unknown;
try {
  const result = await runtime.turn("Exercise explicit lifecycle cleanup.", { sessionId });
  const accounting: TurnAccounting = result.accounting;
  if (
    accounting.providerIterations !== 1 ||
    accounting.usage !== null ||
    accounting.usageComplete ||
    accounting.costUsd !== null ||
    accounting.costComplete ||
    !Object.isFrozen(accounting)
  ) {
    throw new Error("installed lifecycle fixture received invalid turn accounting");
  }
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
const FAILURE_HISTORY_SMOKE_SOURCE = `import {
  AgentBuilder,
  EventType,
  InMemoryEventStore,
  type AgentRuntime,
  type ModelProvider,
  type ModelResponse,
  type ModelResponseChunk,
  type StoredKajiEvent,
} from "@kaji/sdk";

async function pageHistory(
  runtime: AgentRuntime,
  sessionId: string,
  limit = 2,
): Promise<StoredKajiEvent[]> {
  const events: StoredKajiEvent[] = [];
  let afterSequence = 0;
  for (;;) {
    const page = await runtime.history(sessionId, { afterSequence, limit });
    if (page.length === 0) return events;
    const nextSequence = page.at(-1)!.sequence;
    if (nextSequence <= afterSequence) throw new Error("history cursor did not advance");
    events.push(...page);
    afterSequence = nextSequence;
  }
}

const SAFE_FIELDS = [
  "tool_name",
  "tool_call_id",
  "error_code",
  "phase",
  "retryable",
  "outcome",
  "reason_code",
  "recovery_code",
  "doc_url",
] as const;

function safeJournalEvidence(event: StoredKajiEvent): Record<string, unknown> {
  const safe: Record<string, unknown> = { sequence: event.sequence, type: event.type };
  if (event.turn_id !== undefined) safe.turn_id = event.turn_id;
  for (const field of SAFE_FIELDS) {
    const value = Reflect.get(event, field);
    if (value !== undefined) safe[field] = value;
  }
  return safe;
}

const sessionId = "installed-failure-history-session";
const promptCanary = "installed-private-prompt-canary";
const argumentCanary = "installed-private-argument-canary";
const resultCanary = "installed-private-result-canary";
const providerSecret = "installed-private-provider-canary";
const providerError = new Error(providerSecret);
let providerCalls = 0;
const provider: ModelProvider = {
  async generate(): Promise<ModelResponse> {
    return { content: "", toolCalls: [] };
  },
  async *generateStream(): AsyncGenerator<ModelResponseChunk> {
    providerCalls += 1;
    if (providerCalls === 1) {
      yield {
        delta: "",
        toolCalls: [
          {
            id: "installed-journal-call",
            name: "journal_probe",
            args: { value: argumentCanary },
          },
        ],
      };
      return;
    }
    throw providerError;
  },
};
const store = new InMemoryEventStore({ maxSessions: 1, maxEventsPerSession: 100 });
const runtime = new AgentBuilder()
  .provider(provider)
  .integration({
    register(registry) {
      registry.register(
        {
          name: "journal_probe",
          description: "Return installed journal proof",
          parameters: {},
          risk: "read",
        },
        async () => ({ value: resultCanary }),
      );
    },
  })
  .defaultContext({ principalId: "installed-journal-test" })
  .build({ store });

let proofFailure: unknown;
try {
  let caught: unknown;
  try {
    await runtime.turn(promptCanary, { sessionId });
  } catch (error) {
    caught = error;
  }
  if (caught !== providerError) {
    throw new Error("provider failure identity was not preserved");
  }
  const events = await pageHistory(runtime, sessionId);
  if (!events.some((event) => event.type === EventType.TOOL_CALL_COMPLETED)) {
    throw new Error("installed failure history omitted completed tool work");
  }
  const failure = events.find((event) => event.type === EventType.AGENT_TURN_FAILED);
  if (failure === undefined) throw new Error("installed failure history omitted turn failure");
  if ("error_code" in failure || "recovery_code" in failure) {
    throw new Error("generic provider failure unexpectedly exposed a durable recovery code");
  }
  if (JSON.stringify(failure).includes(providerSecret)) {
    throw new Error("installed failure history retained the private provider exception");
  }
  const safeEvidence = events.map(safeJournalEvidence);
  const safeJson = JSON.stringify(safeEvidence);
  for (const canary of [promptCanary, argumentCanary, resultCanary, providerSecret]) {
    if (safeJson.includes(canary)) {
      throw new Error("installed safe journal evidence leaked privileged content");
    }
  }
} catch (error) {
  proofFailure = error;
} finally {
  try {
    const activeTools = await runtime.drainTools(10_000);
    const activeProviders = await runtime.drainProviders(10_000);
    if (activeTools.length > 0 || activeProviders.length > 0) {
      throw new Error("installed failure-history fixture did not drain owned work");
    }
    await runtime.purgeSession(sessionId);
  } catch (error) {
    proofFailure ??= error;
  } finally {
    runtime.close();
  }
}
if (proofFailure !== undefined) throw proofFailure;
if ((await runtime.history(sessionId)).length !== 0) {
  throw new Error("installed failure-history fixture retained purged history");
}
console.log("failure_history=ok");
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
const HANDOFF_ENVIRONMENT_KEYS = [
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
  "BUN_CONFIG_REGISTRY",
  "BUN_INSTALL_CACHE_DIR",
  "NO_COLOR",
  "npm_config_audit",
  "npm_config_cache",
  "npm_config_fund",
  "npm_config_registry",
  "npm_config_update_notifier",
  "npm_config_userconfig",
] as const;
const PROTECTED_HANDOFF_TOKENS = [
  "GH_TOKEN",
  "GITHUB_TOKEN",
  "NODE_AUTH_TOKEN",
  "NPM_TOKEN",
] as const;

function tokenFreeHandoffEnvironment(source: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const environment = Object.fromEntries(
    HANDOFF_ENVIRONMENT_KEYS.flatMap((name) =>
      source[name] === undefined ? [] : [[name, source[name]]],
    ),
  );
  for (const name of PROTECTED_HANDOFF_TOKENS) delete environment[name];
  return environment;
}

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function filesBelow(directory: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...filesBelow(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

function parseSourceMap(path: string): SourceMapDocument {
  const document = JSON.parse(readFileSync(path, "utf8")) as unknown;
  if (typeof document !== "object" || document === null || Array.isArray(document)) {
    throw new Error(`packed source map is not a JSON object: ${path}`);
  }
  return document as SourceMapDocument;
}

function isGitHubSourceMap(path: string, document: SourceMapDocument): boolean {
  if (/^dist\/integrations\/github(?:\.[^/]+)*\.map$/.test(path)) return true;
  return (
    Array.isArray(document.sources) &&
    document.sources.some(
      (source) =>
        typeof source === "string" &&
        /(?:^|\/)(?:src\/integrations\/github(?:-package-internal)?|registry\/github\/[^/]+)\.ts$/.test(
          source.replaceAll("\\", "/"),
        ),
    )
  );
}

function inspectPrivateGitHubCompositionSources(installedPackageRoot: string): boolean {
  const standaloneSourcePacked = PRIVATE_GITHUB_COMPOSITION_PATHS.some((path) =>
    existsSync(join(installedPackageRoot, path)),
  );
  const sourceMaps = filesBelow(join(installedPackageRoot, "dist"))
    .filter((path) => path.endsWith(".map"))
    .map((absolutePath) => {
      const path = absolutePath.slice(installedPackageRoot.length + 1).replaceAll("\\", "/");
      const document = parseSourceMap(absolutePath);
      return { path, document, encoded: JSON.stringify(document) };
    });
  const githubSourceMaps = sourceMaps.filter(({ path, document }) =>
    isGitHubSourceMap(path, document),
  );
  for (const expected of EXPECTED_GITHUB_SOURCE_MAPS) {
    if (!githubSourceMaps.some(({ path }) => path === expected)) {
      throw new Error(`installed package is missing GitHub source map ${expected}`);
    }
  }
  return (
    standaloneSourcePacked ||
    githubSourceMaps.some(({ document }) => {
      if (!Object.hasOwn(document, "sourcesContent")) return false;
      return (
        !Array.isArray(document.sourcesContent) ||
        document.sourcesContent.some((source) => typeof source === "string")
      );
    }) ||
    sourceMaps.some(({ encoded }) =>
      PRIVATE_GITHUB_COMPOSITION_SOURCE_CANARIES.some((canary) => encoded.includes(canary)),
    )
  );
}

function parseArguments(argv: string[]): SmokeArguments {
  const parsed: SmokeArguments = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]!;
    if (argument === "--release-manifest") {
      if (parsed.releaseManifest !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.releaseManifest = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--expected-commit") {
      if (parsed.expectedCommit !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.expectedCommit = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--output") {
      if (parsed.output !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.output = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--for-handoff") {
      if (parsed.forHandoff !== undefined) throw new Error(`${argument} may be supplied once`);
      const value = requiredFlagValue(argv, index, argument);
      if (value !== "artifact-contract" && value !== "node") {
        throw new Error("--for-handoff must be artifact-contract or node");
      }
      parsed.forHandoff = value;
      index += 1;
    } else if (argument === "--candidate-root") {
      if (parsed.candidateRoot !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.candidateRoot = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--source-commit") {
      if (parsed.sourceCommit !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.sourceCommit = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--artifact-sha256") {
      if (parsed.artifactSha256 !== undefined) throw new Error(`${argument} may be supplied once`);
      parsed.artifactSha256 = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--node-binary") {
      if (parsed.handoffNodeBinary !== undefined)
        throw new Error(`${argument} may be supplied once`);
      parsed.handoffNodeBinary = requiredFlagValue(argv, index, argument);
      index += 1;
    } else if (argument === "--expected-node-major") {
      if (parsed.expectedNodeMajor !== undefined)
        throw new Error(`${argument} may be supplied once`);
      const value = Number(requiredFlagValue(argv, index, argument));
      if (value !== 22 && value !== 24) {
        throw new Error("--expected-node-major must be 22 or 24");
      }
      parsed.expectedNodeMajor = value;
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
  if (parsed.forHandoff === undefined) {
    if (
      parsed.candidateRoot !== undefined ||
      parsed.sourceCommit !== undefined ||
      parsed.artifactSha256 !== undefined ||
      parsed.handoffNodeBinary !== undefined ||
      parsed.expectedNodeMajor !== undefined
    ) {
      throw new Error("handoff-only flags require --for-handoff");
    }
    return parsed;
  }
  if (
    parsed.tarball === undefined ||
    parsed.sourceCommit === undefined ||
    parsed.artifactSha256 === undefined ||
    parsed.output === undefined ||
    parsed.releaseManifest !== undefined ||
    parsed.expectedCommit !== undefined ||
    !/^[0-9a-f]{40}$/.test(parsed.sourceCommit) ||
    !/^[0-9a-f]{64}$/.test(parsed.artifactSha256)
  ) {
    throw new Error("incomplete or invalid supplied-tarball handoff arguments");
  }
  if (
    parsed.forHandoff === "artifact-contract" &&
    (parsed.candidateRoot === undefined ||
      parsed.handoffNodeBinary !== undefined ||
      parsed.expectedNodeMajor !== undefined)
  ) {
    throw new Error("artifact-contract requires only --candidate-root");
  }
  if (
    parsed.forHandoff === "node" &&
    (parsed.candidateRoot !== undefined ||
      parsed.handoffNodeBinary === undefined ||
      parsed.expectedNodeMajor === undefined)
  ) {
    throw new Error("node handoff requires --node-binary and --expected-node-major");
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

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, child]) => [key, stableValue(child)]),
  );
}

function emitHandoffReceipt(receipt: Record<string, unknown>, output: string): void {
  const encoded = `${JSON.stringify(stableValue(receipt), null, 2)}\n`;
  const path = resolve(output);
  mkdirSync(dirname(path), { recursive: true });
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`);
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(descriptor, encoded, "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temporary, path);
    const directoryDescriptor = openSync(dirname(path), "r");
    try {
      fsyncSync(directoryDescriptor);
    } finally {
      closeSync(directoryDescriptor);
    }
  } catch (error) {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
    throw error;
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

function assertGithubPackageProof(
  output: string,
  installedPackageRoot: string,
  typescriptDeclarationChecks: TypeScriptDeclarationChecks,
): GitHubPackageProof {
  let document: unknown;
  try {
    document = JSON.parse(output);
  } catch {
    throw new Error("GitHub package proof emitted invalid JSON");
  }
  const sharedAbi = JSON.parse(
    readFileSync(
      join(installedPackageRoot, "contracts/integrations/github-tool-abi-v1.json"),
      "utf8",
    ),
  ) as {
    version: "1.0.0";
    tools: ReadonlyArray<{ risk?: unknown }>;
  };
  const apiFixture = JSON.parse(
    readFileSync(
      join(installedPackageRoot, "contracts/integrations/github-api-conformance-v1.json"),
      "utf8",
    ),
  ) as { version: "1.0.0"; cases: readonly unknown[] };
  const packageAbi = JSON.parse(
    readFileSync(
      join(installedPackageRoot, "contracts/integrations/github-tool-abi-typescript-v1.json"),
      "utf8",
    ),
  ) as {
    schema_version: "1.0.0";
    catalog_version: "0.2.0";
    tools: ReadonlyArray<{ risk?: unknown }>;
  };
  const copiedManifest = JSON.parse(
    readFileSync(join(installedPackageRoot, "registry/github/manifest.json"), "utf8"),
  ) as {
    version: "0.1.0";
    tools: ReadonlyArray<{ risk?: unknown }>;
  };
  const privateGitHubCompositionSourcesPacked =
    inspectPrivateGitHubCompositionSources(installedPackageRoot);
  if (privateGitHubCompositionSourcesPacked) {
    throw new Error("installed package contains private GitHub composition source");
  }
  const expected: GitHubPackageProof = {
    schemaVersion: 5,
    evidenceClass: "offline_exact_artifact_smoke",
    integration: "github",
    runtime: "typescript",
    network: "blocked",
    liveProvider: false,
    sharedAbiVersion: sharedAbi.version,
    packageAbiSchemaVersion: packageAbi.schema_version,
    packageCatalogVersion: packageAbi.catalog_version,
    apiFixtureVersion: apiFixture.version,
    sharedFixtureCaseCount: apiFixture.cases.length,
    publicScenarioCount: GITHUB_PUBLIC_SCENARIOS.length,
    packageCatalog: {
      schemaVersion: packageAbi.schema_version,
      catalogVersion: packageAbi.catalog_version,
      toolCount: packageAbi.tools.length as 15,
      readToolCount: packageAbi.tools.filter((tool) => tool.risk === "read").length as 13,
      tools: packageAbi.tools.map((tool) => Reflect.get(tool, "name") as string),
      readTools: packageAbi.tools
        .filter((tool) => tool.risk === "read")
        .map((tool) => Reflect.get(tool, "name") as string),
      providerAliases: GITHUB_PROVIDER_ALIASES,
      catalogNames: GITHUB_CATALOG_NAMES,
    },
    cliCopiedCatalog: {
      manifestVersion: copiedManifest.version,
      toolCount: copiedManifest.tools.length as 6,
      readToolCount: copiedManifest.tools.filter((tool) => tool.risk === "read").length as 4,
      tools: copiedManifest.tools.map((tool) => Reflect.get(tool, "name") as string),
      readTools: copiedManifest.tools
        .filter((tool) => tool.risk === "read")
        .map((tool) => Reflect.get(tool, "name") as string),
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
    typescriptDeclarationChecks,
    privateGitHubCompositionSourcesPacked,
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
      testFile: POLICY_TEST_FILE,
      testName: POLICY_TEST_NAME,
      tokenLookups: 0,
      requestAttempts: 0,
    },
    aliasCollisionRejected: true,
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
      const diagnostic = phase.startsWith("handoff:")
        ? safeHandoffDiagnostic(`${completed.stdout}\n${completed.stderr}`)
        : "";
      throw new CommandError(
        `release command exited with status ${completed.status}, expected ${expectedStatus}${diagnostic === "" ? "" : `; child output: ${diagnostic}`}`,
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

function safeHandoffDiagnostic(output: string): string {
  const printable = [...output]
    .filter((character) => {
      const code = character.charCodeAt(0);
      return code === 9 || code === 10 || code === 13 || (code >= 32 && code !== 127);
    })
    .join("");
  return printable
    .replaceAll(/(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+/giu, "[redacted-token]")
    .replaceAll(
      /("(?:authorization|password|secret|token)"\s*:\s*")(?:(?:\\.)|[^"\\\r\n])*"/giu,
      '$1[redacted]"',
    )
    .replaceAll(/\b(authorization\s*[:=]\s*)[^\r\n]*/giu, "$1[redacted]")
    .replaceAll(/\b(authorization|password|secret|token)(\s*[:=]\s*)\S+/giu, "$1$2[redacted]")
    .trim()
    .slice(-4_096);
}

async function runHandoffCommand(
  label: string,
  command: string,
  args: string[],
  cwd: string,
  environment: NodeJS.ProcessEnv = baseEnvironment,
  timeoutMs = PACKAGE_TIMEOUT_MS,
): Promise<string> {
  const executable = basename(command);
  if (
    (executable === "npm" && args[0] === "pack") ||
    (executable === "bun" && args[0] === "run" && args[1] === "build") ||
    args.some((argument, index) => argument === "npm" && args[index + 1] === "pack")
  ) {
    throw new Error("supplied-tarball handoff cannot build or pack");
  }
  const childEnvironment = tokenFreeHandoffEnvironment(environment);
  if (PROTECTED_HANDOFF_TOKENS.some((name) => name in childEnvironment)) {
    throw new Error("supplied-tarball handoff child environment retained a protected token");
  }
  return runCommand(`handoff:${label}`, command, args, cwd, childEnvironment, timeoutMs);
}

function handoffDependencyClosure(
  tarball: string,
  vendorRoot: string,
): {
  dependencies: Record<string, string>;
  installArgs: string[];
} {
  const packages = new Map<string, string>();
  const visit = (name: string, requestedPath: string): void => {
    const path = realpathSync(requestedPath);
    const existing = packages.get(name);
    if (existing !== undefined) {
      if (existing !== path) {
        throw new Error(`handoff dependency graph has conflicting local copies of ${name}`);
      }
      return;
    }
    const manifest = JSON.parse(
      readFileSync(join(path, "package.json"), "utf8"),
    ) as LocalDependencyManifest;
    if (
      manifest.name !== name ||
      semverFromVersionOutput(manifest.version, name) !== manifest.version
    ) {
      throw new Error(`handoff dependency identity changed for ${name}`);
    }
    packages.set(name, path);
    const nodeModules = name.startsWith("@") ? dirname(dirname(path)) : dirname(path);
    for (const dependency of Object.keys(manifest.dependencies ?? {}).sort()) {
      visit(dependency, join(nodeModules, dependency));
    }
    for (const peer of Object.keys(manifest.peerDependencies ?? {}).sort()) {
      if (manifest.peerDependenciesMeta?.[peer]?.optional !== true) {
        visit(peer, join(nodeModules, peer));
      }
    }
  };
  for (const name of ["zod", "ajv", "ajv-formats", "openai", "@anthropic-ai/sdk", "@types/node"]) {
    visit(name, join(packageRoot, "node_modules", name));
  }
  mkdirSync(vendorRoot, { recursive: true });
  const mirrored = [...packages]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([name, source]) => {
      const path = join(vendorRoot, ...name.split("/"));
      mkdirSync(dirname(path), { recursive: true });
      cpSync(source, path, { recursive: true, dereference: true, errorOnExist: true });
      return { name, path };
    });
  const mirroredPaths = new Map(mirrored.map(({ name, path }) => [name, path]));
  for (const { name, path } of mirrored) {
    const manifestPath = join(path, "package.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
    const dependencies = manifest.dependencies as Record<string, string> | undefined;
    if (dependencies !== undefined) {
      for (const dependency of Object.keys(dependencies)) {
        const dependencyPath = mirroredPaths.get(dependency);
        if (dependencyPath === undefined) {
          throw new Error(`handoff runtime closure omitted ${name} dependency ${dependency}`);
        }
        dependencies[dependency] = `file:${dependencyPath}`;
      }
    }
    delete manifest.devDependencies;
    delete manifest.optionalDependencies;
    delete manifest.peerDependencies;
    delete manifest.peerDependenciesMeta;
    delete manifest.workspaces;
    writeFileSync(manifestPath, JSON.stringify(manifest));
  }
  const local = mirrored.map(({ name, path }) => [name, `file:${path}`] as const);
  return {
    dependencies: Object.fromEntries([["@kaji/sdk", `file:${tarball}`], ...local]),
    installArgs: [tarball, ...local.map(([, spec]) => spec)],
  };
}

function assertRealInstalledCopy(root: string): string {
  const path = join(root, "node_modules/@kaji/sdk");
  const stat = lstatSync(path);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error("supplied artifact was not installed as a real package directory");
  }
  const real = realpathSync(path);
  const boundary = realpathSync(root);
  const relation = relative(boundary, real);
  if (
    relation.startsWith("..") ||
    resolve(boundary, relation) !== real ||
    real === realpathSync(packageRoot)
  ) {
    throw new Error("supplied artifact resolved through a link or workspace package");
  }
  const manifest = JSON.parse(readFileSync(join(real, "package.json"), "utf8")) as {
    name?: unknown;
  };
  if (manifest.name !== "@kaji/sdk") throw new Error("installed package identity changed");
  return real;
}

async function installHandoffArtifact(
  manager: PackageManager,
  root: string,
  tarball: string,
): Promise<string> {
  mkdirSync(root, { recursive: true });
  const closure = handoffDependencyClosure(tarball, join(root, "third-party"));
  const overrides = Object.fromEntries(
    Object.entries(closure.dependencies).filter(([name]) => name !== "@kaji/sdk"),
  );
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({
      name: `kaji-handoff-${manager}`,
      version: "1.0.0",
      private: true,
      ...(manager === "bun" ? { dependencies: closure.dependencies, overrides } : {}),
    }),
  );
  const userConfig = join(root, ".npmrc-handoff");
  writeFileSync(userConfig, "");
  const environment = {
    ...baseEnvironment,
    npm_config_userconfig: userConfig,
    npm_config_registry: "http://127.0.0.1:9",
    npm_config_cache: join(root, ".npm-cache"),
    BUN_CONFIG_REGISTRY: "http://127.0.0.1:9",
    BUN_INSTALL_CACHE_DIR: join(root, ".bun-cache"),
  };
  if (manager === "npm") {
    await runHandoffCommand(
      `${manager}-install`,
      "npm",
      ["install", "--ignore-scripts", "--offline", "--install-links=false", ...closure.installArgs],
      root,
      environment,
    );
  } else {
    await runHandoffCommand(
      `${manager}-install`,
      process.execPath,
      ["install", "--production", "--ignore-scripts", "--omit=dev", "--offline"],
      root,
      environment,
    );
  }
  return assertRealInstalledCopy(root);
}

function semverFromVersionOutput(output: string, label: string): string {
  const version = /^(?:Version |v)?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$/u.exec(
    output.trim(),
  )?.[1];
  if (version === undefined) throw new Error(`${label} emitted an invalid semantic version`);
  return version;
}

async function compileHandoffGitHubTypes(
  root: string,
  runtimeBinary: string,
): Promise<TypeScriptDeclarationChecks> {
  writeGitHubTypeConsumerFixtures(root);
  const compilers = [
    {
      name: "typescript57",
      binary: realpathSync(join(packageRoot, "node_modules/typescript57/bin/tsc")),
      extraArgs: ["--ignoreDeprecations", "5.0"],
    },
    {
      name: "typescriptCurrent",
      binary: realpathSync(join(packageRoot, "node_modules/typescript/bin/tsc")),
      extraArgs: [] as string[],
    },
  ] as const;
  const versions = new Map<string, string>();
  for (const compiler of compilers) {
    versions.set(
      compiler.name,
      semverFromVersionOutput(
        await runHandoffCommand(
          `${compiler.name}-version`,
          runtimeBinary,
          [compiler.binary, "--version"],
          root,
        ),
        compiler.name,
      ),
    );
    for (const consumer of GITHUB_TYPE_CONSUMERS) {
      await runHandoffCommand(
        `${compiler.name}-${consumer.module}`,
        runtimeBinary,
        [compiler.binary, "--project", consumer.config, "--noEmit", ...compiler.extraArgs],
        root,
      );
    }
  }
  const minimumVersion = versions.get("typescript57");
  const currentVersion = versions.get("typescriptCurrent");
  if (minimumVersion !== "5.7.3" || currentVersion === undefined || currentVersion === "5.7.3") {
    throw new Error("handoff TypeScript compiler matrix changed");
  }
  return {
    compilerOptions: {
      module: "NodeNext",
      moduleResolution: "NodeNext",
      skipLibCheck: false,
    },
    typescript57: { version: "5.7.3", mtsImport: "passed", ctsRequire: "passed" },
    typescriptCurrent: {
      version: currentVersion,
      mtsImport: "passed",
      ctsRequire: "passed",
    },
  };
}

async function runInstalledHandoffProof(
  manager: PackageManager,
  tarball: string,
  runtimeBinary: string,
): Promise<{ packageRoot: string; proof: GitHubPackageProof }> {
  const root = join(workdir, `handoff-${manager}`);
  const installedPackageRoot = await installHandoffArtifact(manager, root, tarball);
  const declarationChecks = await compileHandoffGitHubTypes(root, runtimeBinary);
  const checksPath = join(root, "typescript-declaration-checks.json");
  writeFileSync(checksPath, JSON.stringify(declarationChecks));
  const runner = join(root, "installed-github-smoke.mts");
  copyFileSync(INSTALLED_GITHUB_SMOKE, runner);
  const output = await runHandoffCommand(
    `${manager}-github-proof`,
    process.execPath,
    [
      "--no-install",
      runner,
      "--sandbox-root",
      root,
      "--package-root",
      installedPackageRoot,
      "--typescript-declaration-checks",
      checksPath,
    ],
    root,
    githubProofEnvironment(baseEnvironment),
  );
  return {
    packageRoot: installedPackageRoot,
    proof: assertGithubPackageProof(output, installedPackageRoot, declarationChecks),
  };
}

function checkedArchiveName(raw: string): string {
  const name = raw.endsWith("/") ? raw.slice(0, -1) : raw;
  if (
    name.length === 0 ||
    name.startsWith("/") ||
    !name.startsWith("package/") ||
    name.includes("\\") ||
    [...name].some((character) => character.charCodeAt(0) > 0x7f)
  ) {
    throw new Error("supplied tarball contains an unsafe archive path");
  }
  const parts = name.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    throw new Error("supplied tarball contains a noncanonical archive path");
  }
  return name;
}

function assertNoLinksBelow(root: string): void {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory())) {
      throw new Error("supplied tarball extracted a link or special file");
    }
    if (stat.isDirectory()) assertNoLinksBelow(path);
  }
}

async function extractCheckedArchive(tarball: string): Promise<{
  root: string;
  members: string[];
  membersSha256: string;
}> {
  const list = (await runHandoffCommand("archive-list", "tar", ["-tzf", tarball], workdir))
    .split("\n")
    .filter(Boolean);
  const verbose = (await runHandoffCommand("archive-types", "tar", ["-tvzf", tarball], workdir))
    .split("\n")
    .filter(Boolean);
  if (list.length === 0 || list.length > 4096 || verbose.length !== list.length) {
    throw new Error("supplied tarball has an invalid member set");
  }
  if (verbose.some((line) => !["-", "d"].includes(line[0] ?? ""))) {
    throw new Error("supplied tarball contains a link or special member");
  }
  const checked = list.map(checkedArchiveName);
  if (new Set(checked).size !== checked.length) {
    throw new Error("supplied tarball contains duplicate archive members");
  }
  const members = checked.sort((left, right) =>
    Buffer.compare(Buffer.from(left, "ascii"), Buffer.from(right, "ascii")),
  );
  const root = join(workdir, "archive");
  mkdirSync(root);
  await runHandoffCommand("archive-extract", "tar", ["-xzf", tarball, "-C", root], workdir);
  assertNoLinksBelow(root);
  return {
    root,
    members,
    membersSha256: createHash("sha256")
      .update(members.map((name) => `${name}\n`).join(""), "ascii")
      .digest("hex"),
  };
}

function exportTargets(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
  return Object.values(value).flatMap(exportTargets);
}

function sourceByteEquality(
  archiveRoot: string,
  members: readonly string[],
  candidateRoot: string,
): void {
  const candidatePackageRoot = realpathSync(join(candidateRoot, "kaji/ts"));
  const candidateDist = realpathSync(join(candidatePackageRoot, "dist"));
  const archiveDistFiles = members.filter(
    (name) => name.startsWith("package/dist/") && lstatSync(join(archiveRoot, name)).isFile(),
  );
  const candidateDistFiles = filesBelow(candidateDist)
    .map((path) => `package/dist/${relative(candidateDist, path).replaceAll("\\", "/")}`)
    .sort((left, right) => Buffer.compare(Buffer.from(left, "ascii"), Buffer.from(right, "ascii")));
  if (JSON.stringify(archiveDistFiles) !== JSON.stringify(candidateDistFiles)) {
    throw new Error("supplied artifact dist member set differs from the staged build");
  }
  for (const member of archiveDistFiles) {
    const relativeDist = member.slice("package/dist/".length);
    if (
      !readFileSync(join(archiveRoot, member)).equals(
        readFileSync(join(candidateDist, relativeDist)),
      )
    ) {
      throw new Error(`supplied artifact byte mismatch: ${member}`);
    }
  }
}

function exactCatalogs(proof: GitHubPackageProof): void {
  if (
    JSON.stringify(proof.packageCatalog.tools) !== JSON.stringify(GITHUB_TOOLS) ||
    JSON.stringify(proof.packageCatalog.readTools) !== JSON.stringify(GITHUB_READ_TOOLS) ||
    JSON.stringify(proof.packageCatalog.providerAliases) !==
      JSON.stringify(GITHUB_PROVIDER_ALIASES) ||
    JSON.stringify(proof.packageCatalog.catalogNames) !== JSON.stringify(GITHUB_CATALOG_NAMES) ||
    JSON.stringify(proof.cliCopiedCatalog.tools) !== JSON.stringify(SHARED_GITHUB_TOOLS) ||
    JSON.stringify(proof.cliCopiedCatalog.readTools) !== JSON.stringify(SHARED_GITHUB_READ_TOOLS)
  ) {
    throw new Error("installed handoff catalog or alias surface changed");
  }
}

async function proveCandidatePolicy(candidateRoot: string): Promise<void> {
  const candidatePackageRoot = realpathSync(join(candidateRoot, "kaji/ts"));
  await runHandoffCommand(
    "policy-before-token",
    process.execPath,
    ["test", "tests/github-registry.test.ts", "-t", POLICY_TEST_NAME],
    candidatePackageRoot,
    githubProofEnvironment(baseEnvironment),
  );
}

async function runArtifactContractHandoff(
  arguments_: SmokeArguments & {
    tarball: string;
    candidateRoot: string;
    sourceCommit: string;
    artifactSha256: string;
    output: string;
  },
): Promise<void> {
  const archive = await extractCheckedArchive(arguments_.tarball);
  const packedRoot = join(archive.root, "package");
  const packedManifest = JSON.parse(readFileSync(join(packedRoot, "package.json"), "utf8")) as {
    name?: unknown;
    license?: unknown;
    exports?: unknown;
  };
  if (
    packedManifest.name !== "@kaji/sdk" ||
    packedManifest.license !== "SEE LICENSE IN LICENSE" ||
    typeof packedManifest.exports !== "object" ||
    packedManifest.exports === null ||
    Array.isArray(packedManifest.exports)
  ) {
    throw new Error("supplied tarball package metadata is invalid");
  }
  const targets = exportTargets(packedManifest.exports);
  if (
    targets.length === 0 ||
    new Set(targets).size !== targets.length ||
    targets.some(
      (target) =>
        !target.startsWith("./dist/") ||
        target.includes("\\") ||
        target
          .slice(2)
          .split("/")
          .some((part) => part === "" || part === "." || part === "..") ||
        !lstatSync(join(packedRoot, target)).isFile(),
    )
  ) {
    throw new Error("supplied tarball export targets are missing or unsafe");
  }
  sourceByteEquality(archive.root, archive.members, arguments_.candidateRoot);
  await proveCandidatePolicy(arguments_.candidateRoot);

  const runtimeBinary = process.env.NODE_BINARY ?? "node";
  const npm = await runInstalledHandoffProof("npm", arguments_.tarball, runtimeBinary);
  const bun = await runInstalledHandoffProof("bun", arguments_.tarball, runtimeBinary);
  exactCatalogs(npm.proof);
  exactCatalogs(bun.proof);
  if (JSON.stringify(npm.proof) !== JSON.stringify(bun.proof)) {
    throw new Error("npm and Bun installed package proofs diverged");
  }
  const proof = npm.proof;
  if (
    proof.schemaVersion !== 5 ||
    proof.policyBeforeRequest.testFile !== POLICY_TEST_FILE ||
    proof.policyBeforeRequest.testName !== POLICY_TEST_NAME ||
    proof.policyBeforeRequest.tokenLookups !== 0 ||
    proof.policyBeforeRequest.requestAttempts !== 0
  ) {
    throw new Error("TypeScript package proof is downgraded or lacks policy evidence");
  }
  for (const declaration of ["dist/integrations/github.d.ts", "dist/integrations/github.d.cts"]) {
    const source = readFileSync(join(packedRoot, declaration), "utf8");
    if (GITHUB_PUBLIC_SYMBOLS.some((symbol) => !source.includes(symbol))) {
      throw new Error("GitHub declaration omits a public package symbol");
    }
  }
  const licenseSha256 = createHash("sha256")
    .update(readFileSync(join(packedRoot, "LICENSE")))
    .digest("hex");
  emitHandoffReceipt(
    {
      id: "artifact-contract",
      result: "passed",
      sourceCommit: arguments_.sourceCommit,
      artifactSha256: arguments_.artifactSha256,
      evidence: {
        subchecks: ARTIFACT_SUBCHECKS.map((id) => ({ id, result: "passed" })),
        packlist: {
          memberCount: archive.members.length,
          membersSha256: archive.membersSha256,
        },
        package: {
          exports: packedManifest.exports,
          publicSymbols: GITHUB_PUBLIC_SYMBOLS,
        },
        typescript: {
          minimumVersion: proof.typescriptDeclarationChecks.typescript57.version,
          currentVersion: proof.typescriptDeclarationChecks.typescriptCurrent.version,
        },
        installs: {
          npm: { artifactSha256: arguments_.artifactSha256, realCopy: true },
          bun: { artifactSha256: arguments_.artifactSha256, realCopy: true },
        },
        catalogs: {
          typescript: {
            schemaVersion: proof.packageCatalog.schemaVersion,
            catalogVersion: proof.packageCatalog.catalogVersion,
            totalCount: proof.packageCatalog.toolCount,
            readCount: proof.packageCatalog.readToolCount,
            tools: proof.packageCatalog.tools,
            readTools: proof.packageCatalog.readTools,
          },
          shared: {
            manifestVersion: proof.cliCopiedCatalog.manifestVersion,
            totalCount: proof.cliCopiedCatalog.toolCount,
            readCount: proof.cliCopiedCatalog.readToolCount,
            tools: proof.cliCopiedCatalog.tools,
            readTools: proof.cliCopiedCatalog.readTools,
          },
        },
        lifecycle: proof.lifecycle,
        policy: proof.policyBeforeRequest,
        license: { id: LICENSE_ID, sha256: licenseSha256 },
      },
    },
    arguments_.output,
  );
}

interface NodeFixtureResult {
  releaseName: string;
  nodeVersion: string;
  importKind: "esm" | "commonjs";
  packageRealpath: string;
  artifactSha256: string;
  toolCount: number;
  readToolCount: number;
  tools: string[];
  readTools: string[];
}

function nodeFixtureSource(kind: "esm" | "commonjs", artifactSha256: string): string {
  if (kind === "esm") {
    return `import { realpathSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectIntegration } from "@kaji/sdk/integrations/github";
const entry = fileURLToPath(import.meta.resolve("@kaji/sdk"));
const integration = inspectIntegration();
const tools = integration.tools().map(([spec]) => spec);
integration.close();
console.log(JSON.stringify({
  releaseName: process.release.name,
  nodeVersion: process.versions.node,
  importKind: "esm",
  packageRealpath: realpathSync(dirname(dirname(entry))),
  artifactSha256: ${JSON.stringify(artifactSha256)},
  toolCount: tools.length,
  readToolCount: tools.filter((spec) => spec.risk === "read").length,
  tools: tools.map((spec) => spec.name),
  readTools: tools.filter((spec) => spec.risk === "read").map((spec) => spec.name),
}));
`;
  }
  return `const { realpathSync } = require("node:fs");
const { dirname } = require("node:path");
const { inspectIntegration } = require("@kaji/sdk/integrations/github");
const entry = require.resolve("@kaji/sdk");
const integration = inspectIntegration();
const tools = integration.tools().map(([spec]) => spec);
integration.close();
console.log(JSON.stringify({
  releaseName: process.release.name,
  nodeVersion: process.versions.node,
  importKind: "commonjs",
  packageRealpath: realpathSync(dirname(dirname(entry))),
  artifactSha256: ${JSON.stringify(artifactSha256)},
  toolCount: tools.length,
  readToolCount: tools.filter((spec) => spec.risk === "read").length,
  tools: tools.map((spec) => spec.name),
  readTools: tools.filter((spec) => spec.risk === "read").map((spec) => spec.name),
}));
`;
}

function parseNodeFixture(output: string, kind: "esm" | "commonjs"): NodeFixtureResult {
  let value: unknown;
  try {
    value = JSON.parse(output.trim());
  } catch {
    throw new Error(`${kind} Node handoff fixture emitted invalid JSON`);
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${kind} Node handoff fixture emitted a non-object`);
  }
  return value as NodeFixtureResult;
}

async function runNodeHandoff(
  arguments_: SmokeArguments & {
    tarball: string;
    sourceCommit: string;
    artifactSha256: string;
    handoffNodeBinary: string;
    expectedNodeMajor: 22 | 24;
    output: string;
  },
): Promise<void> {
  if (!arguments_.handoffNodeBinary.startsWith("/")) {
    throw new Error("--node-binary must be an explicit absolute binary path");
  }
  const runtimeBinary = realpathSync(arguments_.handoffNodeBinary);
  const nodeVersion = semverFromVersionOutput(
    await runHandoffCommand("node-version", runtimeBinary, ["--version"], workdir),
    "Node",
  );
  if (Number(nodeVersion.split(".", 1)[0]) !== arguments_.expectedNodeMajor) {
    throw new Error("explicit Node binary major differs from --expected-node-major");
  }
  const npmVersion = semverFromVersionOutput(
    await runHandoffCommand("npm-version", "npm", ["--version"], workdir),
    "npm",
  );
  const installRoot = join(workdir, `node-${arguments_.expectedNodeMajor}`);
  const installedPackageRoot = await installHandoffArtifact("npm", installRoot, arguments_.tarball);
  const esmPath = join(installRoot, "handoff.mjs");
  const cjsPath = join(installRoot, "handoff.cjs");
  writeFileSync(esmPath, nodeFixtureSource("esm", arguments_.artifactSha256));
  writeFileSync(cjsPath, nodeFixtureSource("commonjs", arguments_.artifactSha256));
  const esm = parseNodeFixture(
    await runHandoffCommand("node-esm", runtimeBinary, [esmPath], installRoot),
    "esm",
  );
  const commonjs = parseNodeFixture(
    await runHandoffCommand("node-commonjs", runtimeBinary, [cjsPath], installRoot),
    "commonjs",
  );
  for (const [kind, result] of [
    ["esm", esm],
    ["commonjs", commonjs],
  ] as const) {
    if (
      result.releaseName !== "node" ||
      result.nodeVersion !== nodeVersion ||
      result.importKind !== kind ||
      realpathSync(result.packageRealpath) !== installedPackageRoot ||
      result.artifactSha256 !== arguments_.artifactSha256 ||
      result.toolCount !== 15 ||
      result.readToolCount !== 13 ||
      JSON.stringify(result.tools) !== JSON.stringify(GITHUB_TOOLS) ||
      JSON.stringify(result.readTools) !== JSON.stringify(GITHUB_READ_TOOLS)
    ) {
      throw new Error(`${kind} Node handoff fixture did not prove the supplied package`);
    }
  }
  emitHandoffReceipt(
    {
      id: `node-${arguments_.expectedNodeMajor}`,
      result: "passed",
      sourceCommit: arguments_.sourceCommit,
      artifactSha256: arguments_.artifactSha256,
      evidence: {
        nodeMajor: arguments_.expectedNodeMajor,
        nodeVersion,
        npmVersion,
        installedArtifactSha256: arguments_.artifactSha256,
        realCopy: true,
        checks: NODE_HANDOFF_CHECKS.map((id) => ({ id, result: "passed" })),
      },
    },
    arguments_.output,
  );
}

async function runSuppliedTarballHandoff(arguments_: SmokeArguments): Promise<void> {
  const requested = arguments_.tarball!;
  const requestedStat = lstatSync(resolve(requested));
  if (requestedStat.isSymbolicLink() || !requestedStat.isFile() || requestedStat.size < 1) {
    throw new Error("supplied npm tarball must be one non-empty regular file");
  }
  const tarball = realpathSync(requested);
  const digest = sha256(tarball);
  if (digest !== arguments_.artifactSha256) {
    throw new Error("supplied npm tarball SHA-256 differs before install");
  }
  if (arguments_.forHandoff === "artifact-contract") {
    await runArtifactContractHandoff({
      ...arguments_,
      tarball,
      candidateRoot: arguments_.candidateRoot!,
      sourceCommit: arguments_.sourceCommit!,
      artifactSha256: digest,
      output: arguments_.output!,
    });
  } else {
    await runNodeHandoff({
      ...arguments_,
      tarball,
      sourceCommit: arguments_.sourceCommit!,
      artifactSha256: digest,
      handoffNodeBinary: arguments_.handoffNodeBinary!,
      expectedNodeMajor: arguments_.expectedNodeMajor!,
      output: arguments_.output!,
    });
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

function assertFailureHistoryOutput(output: string): void {
  const fields = new Map(
    output
      .split("\n")
      .filter((line) => line.includes("="))
      .map((line) => line.split("=", 2) as [string, string]),
  );
  if (fields.get("failure_history") !== "ok") {
    throw new Error("installed failure-history fixture did not prove recovery and purge");
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
    const approvalOptionsBlock = /interface CliApprovalOptions \{[\s\S]*?^\}/mu.exec(
      declaration,
    )?.[0];
    if (approvalOptionsBlock === undefined) {
      throw new Error(`root ${declarationFile} is missing CliApprovalOptions`);
    }
    for (const ambientStream of ["NodeJS.ReadableStream", "NodeJS.WritableStream"]) {
      if (approvalOptionsBlock.includes(ambientStream)) {
        throw new Error(
          `root ${declarationFile} CliApprovalOptions references ambient ${ambientStream}`,
        );
      }
    }
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

function writeGitHubTypeConsumerFixtures(generated: string): void {
  writeFileSync(join(generated, "github-types.mts"), GITHUB_ESM_TYPES_SOURCE);
  writeFileSync(join(generated, "github-types.cts"), GITHUB_CJS_TYPES_SOURCE);
  for (const consumer of GITHUB_TYPE_CONSUMERS) {
    writeFileSync(
      join(generated, consumer.config),
      JSON.stringify(
        {
          compilerOptions: GITHUB_TYPES_COMPILER_OPTIONS,
          files: [consumer.source],
        },
        null,
        2,
      ),
    );
  }
}

async function compileInstalledGitHubTypes(
  manager: PackageManager,
  generated: string,
): Promise<TypeScriptDeclarationChecks> {
  writeGitHubTypeConsumerFixtures(generated);
  const compilers = [
    {
      alias: "typescript57",
      line: "5.7",
      extraArgs: ["--ignoreDeprecations", "5.0"],
    },
    { alias: "typescript", line: "current", extraArgs: [] },
  ] as const;
  const compilerVersions = new Map<string, string>();
  for (const compiler of compilers) {
    const tsc = join(generated, `node_modules/${compiler.alias}/bin/tsc`);
    if (!existsSync(tsc)) throw new Error(`generated scaffold is missing ${compiler.alias}`);
    const versionOutput = (
      await runCommand(
        `${manager}:github-types-compiler-version-${compiler.line}`,
        nodeBinary,
        [tsc, "--version"],
        generated,
      )
    ).trim();
    const compilerVersion = /^Version (\d+\.\d+\.\d+(?:[-+].+)?)$/.exec(versionOutput)?.[1];
    if (compilerVersion === undefined) {
      throw new Error(`generated scaffold has an invalid ${compiler.alias} version`);
    }
    compilerVersions.set(compiler.alias, compilerVersion);
    for (const consumer of GITHUB_TYPE_CONSUMERS) {
      await runCommand(
        `${manager}:github-types-${consumer.module}-typescript-${compiler.line}`,
        nodeBinary,
        [tsc, "--project", consumer.config, "--noEmit", ...compiler.extraArgs],
        generated,
      );
    }
  }
  const typescript57Version = compilerVersions.get("typescript57");
  const typescriptCurrentVersion = compilerVersions.get("typescript");
  if (typescript57Version !== "5.7.3" || typescriptCurrentVersion === undefined) {
    throw new Error("generated scaffold compiler versions do not match the supported matrix");
  }
  return {
    compilerOptions: {
      module: GITHUB_TYPES_COMPILER_OPTIONS.module,
      moduleResolution: GITHUB_TYPES_COMPILER_OPTIONS.moduleResolution,
      skipLibCheck: GITHUB_TYPES_COMPILER_OPTIONS.skipLibCheck,
    },
    typescript57: { version: typescript57Version, mtsImport: "passed", ctsRequire: "passed" },
    typescriptCurrent: {
      version: typescriptCurrentVersion,
      mtsImport: "passed",
      ctsRequire: "passed",
    },
  };
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
  writeFileSync(join(generated, "failure-history.ts"), FAILURE_HISTORY_SMOKE_SOURCE);
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
  const typescriptDeclarationChecks = await compileInstalledGitHubTypes(manager, generated);
  const typescriptDeclarationChecksPath = join(generated, "github-types-declaration-checks.json");
  writeFileSync(
    typescriptDeclarationChecksPath,
    JSON.stringify(typescriptDeclarationChecks, null, 2),
  );
  const githubProof = assertGithubPackageProof(
    await runCommand(
      `${manager}:github-package-proof`,
      "bun",
      [
        "--no-install",
        githubProofRunner,
        "--sandbox-root",
        root,
        "--package-root",
        realpathSync(installedPackageRoot),
        "--typescript-declaration-checks",
        typescriptDeclarationChecksPath,
      ],
      bootstrap,
      githubProofEnvironment(ownerEnvironment),
    ),
    installedPackageRoot,
    typescriptDeclarationChecks,
  );
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
  const failureHistoryOutput = await runCommand(
    `${manager}:failure-history-run`,
    nodeBinary,
    [tsx, "failure-history.ts"],
    generated,
    environment,
  );
  assertFailureHistoryOutput(failureHistoryOutput);

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
if (rawArguments.includes("--for-handoff")) {
  try {
    const handoffArguments = parseArguments(rawArguments);
    workdir = mkdtempSync(join(tmpdir(), "kaji-handoff-smoke-"));
    installRoot = workdir;
    await runSuppliedTarballHandoff(handoffArguments);
  } finally {
    if (workdir !== "") rmSync(workdir, { recursive: true, force: true });
  }
} else {
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
import * as github from "@kaji/sdk/integrations/github";
if (sdk.VERSION !== "${PACKAGE_VERSION}" || !sdk.AgentRuntime || !sdk.supportsSessionPurge || !sdk.SessionPurgeBusyError || !sdk.SessionPurgeUnsupportedError || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
if (JSON.stringify(Object.keys(integrations).sort()) !== JSON.stringify(["INTEGRATION_RECOVERY", "IntegrationAuthRequiredError", "IntegrationExecutionError", "IntegrationPolicyError", "IntegrationRateLimitedError", "IntegrationTransientReadError", "closedRecoveryFields", "createGitHubRequester", "createGmailRequester", "snapshotIntegrationResult"].sort())) process.exit(1);
if (JSON.stringify(Object.keys(github).sort()) !== JSON.stringify(["GitHubIntegration", "createGithubIntegration", "inspectIntegration"].sort()) || github.inspectIntegration().tools().length !== 15) process.exit(1);
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
const github = require("@kaji/sdk/integrations/github");
if (sdk.VERSION !== "${PACKAGE_VERSION}" || !sdk.AgentRuntime || !sdk.supportsSessionPurge || !sdk.SessionPurgeBusyError || !sdk.SessionPurgeUnsupportedError || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
if (JSON.stringify(Object.keys(integrations).sort()) !== JSON.stringify(["INTEGRATION_RECOVERY", "IntegrationAuthRequiredError", "IntegrationExecutionError", "IntegrationPolicyError", "IntegrationRateLimitedError", "IntegrationTransientReadError", "closedRecoveryFields", "createGitHubRequester", "createGmailRequester", "snapshotIntegrationResult"].sort())) process.exit(1);
if (JSON.stringify(Object.keys(github).sort()) !== JSON.stringify(["GitHubIntegration", "createGithubIntegration", "inspectIntegration"].sort()) || github.inspectIntegration().tools().length !== 15) process.exit(1);
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
    if (quickstart === undefined)
      throw new Error("canonical TypeScript quickstart block is missing");
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
}
