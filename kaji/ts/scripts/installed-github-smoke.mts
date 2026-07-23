#!/usr/bin/env bun
/** Prove the installed public GitHub package boundary without private transport injection. */

import { existsSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { Socket } from "node:net";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

import type { ToolExecutionContext } from "@kaji/sdk";

type SdkRuntime = typeof import("@kaji/sdk");
type TestingRuntime = typeof import("@kaji/sdk/testing");
type GitHubRuntime = typeof import("@kaji/sdk/integrations/github");

const EXPECTED_TOOLS = [
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
const EXPECTED_READ_TOOLS = EXPECTED_TOOLS.filter(
  (name) => name !== "add_comment" && name !== "create_issue",
);
const EXPECTED_PROVIDER_ALIASES = EXPECTED_TOOLS.map((name) => `github_${name}`);
const EXPECTED_CATALOG_NAMES = EXPECTED_TOOLS.map((name) => `github.${name}`);
const EXPECTED_RUNTIME_EXPORTS = [
  "GitHubIntegration",
  "createGithubIntegration",
  "inspectIntegration",
] as const;
const EXPECTED_DECLARATION_EXPORTS = [
  "CreateGitHubIntegrationOptions",
  ...EXPECTED_RUNTIME_EXPORTS,
] as const;
const PRIVATE_GITHUB_COMPOSITION_PATHS = [
  "registry/github/package-tools.ts",
  "registry/github/package.ts",
  "registry/github/package-internal.ts",
  "src/integrations/github.ts",
  "src/integrations/github-package-internal.ts",
] as const;
const PRIVATE_GITHUB_COMPOSITION_SPECIFIERS = [
  "@kaji/sdk/registry/github/package-tools.ts",
  "@kaji/sdk/registry/github/package.ts",
  "@kaji/sdk/registry/github/package-internal.ts",
  "@kaji/sdk/src/integrations/github.ts",
  "@kaji/sdk/src/integrations/github-package-internal.ts",
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
const EXPECTED_PUBLIC_SCENARIOS = [
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
const GITHUB_TOKEN_RECOVERY = Object.freeze({
  error_code: "INTEGRATION_AUTH_REQUIRED",
  reason_code: "github_token_missing",
  recovery_code: "CONFIGURE_GITHUB_TOKEN",
  doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-token",
});
const GITHUB_MUTATION_RECOVERY = Object.freeze({
  error_code: "TOOL_EXECUTION_FAILED",
  reason_code: "github_mutation_unknown",
  recovery_code: "RECONCILE_GITHUB_MUTATION",
  doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-mutation-unknown",
});

interface ApiFixture {
  readonly version: "1.0.0";
  readonly repository: string;
  readonly cases: readonly unknown[];
}

interface SharedAbi {
  readonly version: "1.0.0";
  readonly namespace: "github";
  readonly tools: readonly Record<string, unknown>[];
}

interface PackageAbi {
  readonly schema_version: "1.0.0";
  readonly catalog_version: "0.2.0";
  readonly namespace: "github";
  readonly tools: readonly Record<string, unknown>[];
}

interface CopiedManifest {
  readonly version: "0.1.0";
  readonly tools: readonly Record<string, unknown>[];
}

interface SourceMapDocument {
  readonly sources?: unknown;
  readonly sourcesContent?: unknown;
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

type ProofFailureCode =
  | "arguments_incomplete"
  | "arguments_invalid"
  | "environment_not_isolated"
  | "proof_failed";

class ProofFailure extends Error {
  readonly code: ProofFailureCode;

  constructor(code: ProofFailureCode) {
    super("installed GitHub package proof failed");
    this.code = code;
  }
}

function contained(path: string, root: string, label: string): string {
  const resolved = realpathSync(path);
  const boundary = realpathSync(root);
  const relation = relative(boundary, resolved);
  if (relation.startsWith("..") || resolve(boundary, relation) !== resolved) {
    throw new Error(`${label} is outside the installed smoke sandbox`);
  }
  return resolved;
}

function parseArguments(argv: string[]): {
  sandboxRoot: string;
  packageRoot: string;
  typescriptDeclarationChecks: string;
} {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (
      !["--sandbox-root", "--package-root", "--typescript-declaration-checks"].includes(
        flag ?? "",
      ) ||
      value === undefined ||
      value.startsWith("--")
    ) {
      throw new ProofFailure("arguments_invalid");
    }
    values.set(flag!, value);
  }
  if (values.size !== 3) throw new ProofFailure("arguments_incomplete");
  return {
    sandboxRoot: values.get("--sandbox-root")!,
    packageRoot: values.get("--package-root")!,
    typescriptDeclarationChecks: values.get("--typescript-declaration-checks")!,
  };
}

function readTypeScriptDeclarationChecks(
  path: string,
  sandbox: string,
): TypeScriptDeclarationChecks {
  const document = JSON.parse(
    readFileSync(contained(path, sandbox, "TypeScript declaration checks"), "utf8"),
  ) as unknown;
  let currentVersion = "";
  if (typeof document === "object" && document !== null && !Array.isArray(document)) {
    const current = Reflect.get(document, "typescriptCurrent") as unknown;
    if (typeof current === "object" && current !== null && !Array.isArray(current)) {
      const version = Reflect.get(current, "version") as unknown;
      if (typeof version === "string") currentVersion = version;
    }
  }
  if (!/^\d+\.\d+\.\d+(?:[-+].+)?$/.test(currentVersion) || currentVersion === "5.7.3") {
    throw new Error("TypeScript declaration checks contain an invalid current compiler version");
  }
  const expected: TypeScriptDeclarationChecks = {
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
  if (!isDeepStrictEqual(document, expected)) {
    throw new Error("TypeScript declaration checks are invalid or incomplete");
  }
  return document as TypeScriptDeclarationChecks;
}

function context(): ToolExecutionContext {
  return {
    principalId: "installed-proof",
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal: new AbortController().signal,
    metadata: {},
  };
}

function assertToolEvents(
  sdk: SdkRuntime,
  events: ReadonlyArray<{
    type: string;
    tool_name?: string;
    metadata: Readonly<Record<string, unknown>>;
  }>,
  providerAlias: string,
  catalogName: string,
  expectedTypes: readonly string[],
): {
  stages: readonly string[];
  providerAlias: string;
  catalogName: string;
  sameIdentityAtEveryStage: true;
} {
  const toolEvents = events.filter((event) =>
    [
      sdk.EventType.TOOL_CALL_REQUESTED,
      sdk.EventType.TOOL_CALL_STARTED,
      sdk.EventType.TOOL_CALL_COMPLETED,
      sdk.EventType.TOOL_CALL_FAILED,
    ].includes(event.type as never),
  );
  if (
    JSON.stringify(toolEvents.map((event) => event.type)) !== JSON.stringify(expectedTypes) ||
    toolEvents.some(
      (event) => event.tool_name !== providerAlias || event.metadata.catalog_name !== catalogName,
    )
  ) {
    throw new Error(`logical catalog identity failed for ${catalogName}`);
  }
  return {
    stages: toolEvents.map((event) =>
      event.type.replace("tool.call.", "").replace("tool_call_", "").toLowerCase(),
    ),
    providerAlias,
    catalogName,
    sameIdentityAtEveryStage: true,
  };
}

function recoveryTuple(value: unknown): Record<string, unknown> {
  const record =
    typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  return {
    error_code: record.error_code,
    reason_code: record.reason_code,
    recovery_code: record.recovery_code,
    doc_url: record.doc_url,
  };
}

function declarationExportNames(declaration: string): string[] {
  const blocks = [...declaration.matchAll(/^export \{ (.*?) \}(?: from .*?)?;$/gm)];
  if (blocks.length !== 1) throw new Error("GitHub declaration export block is not exact");
  const names = blocks[0]![1]!.split(", ").map(
    (item) =>
      item
        .replace(/^type /, "")
        .split(" as ")
        .at(-1)!,
  );
  if (new Set(names).size !== names.length) {
    throw new Error("GitHub declaration contains duplicate exports");
  }
  return names.sort();
}

function exactToolSpecs(
  integration: InstanceType<GitHubRuntime["GitHubIntegration"]>,
  abi: PackageAbi,
  label: string,
): Record<string, unknown>[] {
  const specs = integration
    .tools()
    .map(([spec]) => JSON.parse(JSON.stringify(spec)) as Record<string, unknown>);
  if (integration.namespace !== abi.namespace || !isDeepStrictEqual(specs, abi.tools)) {
    throw new Error(`${label} GitHub catalog differs from the canonical package ABI`);
  }
  return specs;
}

async function importRejected(specifier: string): Promise<boolean> {
  try {
    await import(specifier);
  } catch {
    return true;
  }
  return false;
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

async function inspectPrivateGitHubCompositionSources(packageRoot: string): Promise<{
  privateGitHubCompositionSourcesPacked: boolean;
  privateGitHubCompositionSourceImportsRejected: boolean;
}> {
  const standaloneSourcePacked = PRIVATE_GITHUB_COMPOSITION_PATHS.some((path) =>
    existsSync(join(packageRoot, path)),
  );
  const sourceMaps = filesBelow(contained(join(packageRoot, "dist"), packageRoot, "Kaji dist"))
    .filter((path) => path.endsWith(".map"))
    .map((absolutePath) => {
      const path = relative(packageRoot, absolutePath).replaceAll("\\", "/");
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
  const embeddedSourceContent = githubSourceMaps.some(({ document }) => {
    if (!Object.hasOwn(document, "sourcesContent")) return false;
    return (
      !Array.isArray(document.sourcesContent) ||
      document.sourcesContent.some((source) => typeof source === "string")
    );
  });
  const embeddedPrivateCanary = sourceMaps.some(({ encoded }) =>
    PRIVATE_GITHUB_COMPOSITION_SOURCE_CANARIES.some((canary) => encoded.includes(canary)),
  );
  const relativeImports = await Promise.all(
    PRIVATE_GITHUB_COMPOSITION_PATHS.map((path) =>
      importRejected(pathToFileURL(join(packageRoot, path)).href),
    ),
  );
  const packageImports = await Promise.all(
    PRIVATE_GITHUB_COMPOSITION_SPECIFIERS.map(importRejected),
  );
  return {
    privateGitHubCompositionSourcesPacked:
      standaloneSourcePacked || embeddedSourceContent || embeddedPrivateCanary,
    privateGitHubCompositionSourceImportsRejected: [...relativeImports, ...packageImports].every(
      Boolean,
    ),
  };
}

async function executeCall(
  sdk: SdkRuntime,
  integration:
    | InstanceType<GitHubRuntime["GitHubIntegration"]>
    | InstanceType<SdkRuntime["Integration"]>,
  call: Readonly<{ id: string; name: string; arguments: Record<string, unknown> }>,
  options: Readonly<{
    policy?: InstanceType<SdkRuntime["ToolPolicy"]>;
    approvalHandler?: { request: () => Promise<Record<string, unknown>> };
  }> = {},
): Promise<{
  results: readonly Record<string, unknown>[];
  events: ReadonlyArray<{
    type: string;
    tool_name?: string;
    outcome?: "not_started" | "failed" | "unknown";
    metadata: Readonly<Record<string, unknown>>;
  }>;
}> {
  const registry = new sdk.ToolRegistry();
  integration.register(registry);
  const store = new sdk.InMemoryEventStore();
  const committer = new sdk.InMemoryEventCommitter(store);
  const planner = new sdk.ToolPlanner({
    specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    executor: (name, args, executionContext) =>
      registry.execute(name, { ...args }, executionContext),
    approvalCommitter: committer,
    ...(options.policy === undefined ? {} : { policy: options.policy }),
    ...(options.approvalHandler === undefined
      ? {}
      : { approvalHandler: options.approvalHandler as never }),
  });
  const results = await planner.executeBatch(
    "installed-proof-session",
    [call],
    sdk.ToolPlanner.committerEmitter(committer),
    "installed-proof-turn",
    { principalId: "principal", requestId: "request", traceId: "trace" },
  );
  return {
    results,
    events: (await store.getEvents("installed-proof-session")) as Array<{
      type: string;
      tool_name?: string;
      outcome?: "not_started" | "failed" | "unknown";
      metadata: Readonly<Record<string, unknown>>;
    }>,
  };
}

async function runProof(argv: string[]) {
  proofStage = "environment";
  if (
    "GH_TOKEN" in process.env ||
    "GITHUB_TOKEN" in process.env ||
    "NODE_AUTH_TOKEN" in process.env ||
    "NPM_TOKEN" in process.env ||
    "NODE_PATH" in process.env
  ) {
    throw new ProofFailure("environment_not_isolated");
  }
  const args = parseArguments(argv);
  const sandbox = realpathSync(args.sandboxRoot);
  const packageRoot = contained(args.packageRoot, sandbox, "Kaji package");
  contained(fileURLToPath(import.meta.url), sandbox, "GitHub proof runner");
  proofStage = "typescript-declaration-checks";
  const typescriptDeclarationChecks = readTypeScriptDeclarationChecks(
    args.typescriptDeclarationChecks,
    sandbox,
  );

  proofStage = "network-guard";
  let networkAttempts = 0;
  const originalFetch = globalThis.fetch;
  const originalConnect = Socket.prototype.connect;
  globalThis.fetch = ((..._args: unknown[]) => {
    networkAttempts += 1;
    return Promise.reject(new Error("external network is disabled in package proof"));
  }) as typeof globalThis.fetch;
  Reflect.set(Socket.prototype, "connect", (..._args: unknown[]) => {
    networkAttempts += 1;
    throw new Error("external network is disabled in package proof");
  });

  try {
    proofStage = "package-identity";
    const requirePackage = createRequire(import.meta.url);
    const sdkEntry = fileURLToPath(import.meta.resolve("@kaji/sdk"));
    const githubEntry = fileURLToPath(import.meta.resolve("@kaji/sdk/integrations/github"));
    const requiredSdkEntry = requirePackage.resolve("@kaji/sdk");
    const requiredGithubEntry = requirePackage.resolve("@kaji/sdk/integrations/github");
    if (
      realpathSync(join(dirname(sdkEntry), "..")) !== packageRoot ||
      realpathSync(join(dirname(requiredSdkEntry), "..")) !== packageRoot
    ) {
      throw new Error("Kaji did not resolve from the npm artifact");
    }
    contained(githubEntry, join(packageRoot, "dist"), "GitHub package export");
    contained(requiredGithubEntry, join(packageRoot, "dist"), "CommonJS GitHub package export");
    const fixture = JSON.parse(
      readFileSync(
        contained(
          join(packageRoot, "contracts/integrations/github-api-conformance-v1.json"),
          packageRoot,
          "GitHub conformance contract",
        ),
        "utf8",
      ),
    ) as ApiFixture;
    const abi = JSON.parse(
      readFileSync(
        contained(
          join(packageRoot, "contracts/integrations/github-tool-abi-v1.json"),
          packageRoot,
          "GitHub shared ABI",
        ),
        "utf8",
      ),
    ) as SharedAbi;
    const packageAbi = JSON.parse(
      readFileSync(
        contained(
          join(packageRoot, "contracts/integrations/github-tool-abi-typescript-v1.json"),
          packageRoot,
          "GitHub TypeScript package ABI",
        ),
        "utf8",
      ),
    ) as PackageAbi;
    const copiedManifest = JSON.parse(
      readFileSync(
        contained(
          join(packageRoot, "registry/github/manifest.json"),
          packageRoot,
          "GitHub copied manifest",
        ),
        "utf8",
      ),
    ) as CopiedManifest;

    proofStage = "public-imports";
    const sdk = await import("@kaji/sdk");
    const testing = (await import("@kaji/sdk/testing")) as TestingRuntime;
    const github = (await import("@kaji/sdk/integrations/github")) as GitHubRuntime;
    const requiredSdk = requirePackage("@kaji/sdk") as SdkRuntime;
    const requiredGithub = requirePackage("@kaji/sdk/integrations/github") as GitHubRuntime;
    const publicScenarios: string[] = [];
    const esmRuntimeExports = Object.keys(github).sort();
    const cjsRuntimeExports = Object.keys(requiredGithub).sort();
    for (const names of [esmRuntimeExports, cjsRuntimeExports]) {
      if (!isDeepStrictEqual(names, [...EXPECTED_RUNTIME_EXPORTS].sort())) {
        throw new Error("GitHub package exposed unexpected runtime symbols");
      }
    }
    publicScenarios.push("conditional-exports");

    proofStage = "class-identity";
    const identityOptions = {
      tokenFor: async () => "artifact-proof-token",
      repositories: [] as const,
    };
    const esmIdentityInspected = github.inspectIntegration();
    const cjsIdentityInspected = requiredGithub.inspectIntegration();
    const esmIdentityCreated = github.createGithubIntegration(identityOptions);
    const cjsIdentityCreated = requiredGithub.createGithubIntegration(identityOptions);
    const esmClassIdentityMatched =
      esmIdentityInspected instanceof github.GitHubIntegration &&
      esmIdentityInspected instanceof sdk.Integration &&
      Object.getPrototypeOf(github.GitHubIntegration.prototype) === sdk.Integration.prototype;
    const cjsClassIdentityMatched =
      cjsIdentityInspected instanceof requiredGithub.GitHubIntegration &&
      cjsIdentityInspected instanceof requiredSdk.Integration &&
      Object.getPrototypeOf(requiredGithub.GitHubIntegration.prototype) ===
        requiredSdk.Integration.prototype;
    const esmFactoryIdentityMatched =
      esmIdentityCreated instanceof github.GitHubIntegration &&
      esmIdentityCreated instanceof sdk.Integration &&
      Object.getPrototypeOf(esmIdentityCreated) === github.GitHubIntegration.prototype;
    const cjsFactoryIdentityMatched =
      cjsIdentityCreated instanceof requiredGithub.GitHubIntegration &&
      cjsIdentityCreated instanceof requiredSdk.Integration &&
      Object.getPrototypeOf(cjsIdentityCreated) === requiredGithub.GitHubIntegration.prototype;
    esmIdentityInspected.close();
    cjsIdentityInspected.close();
    esmIdentityCreated.close();
    cjsIdentityCreated.close();
    if (
      !esmClassIdentityMatched ||
      !cjsClassIdentityMatched ||
      !esmFactoryIdentityMatched ||
      !cjsFactoryIdentityMatched
    ) {
      throw new Error("GitHub package class identity differs from the root Integration export");
    }
    if (
      !/\bfrom\s+["']@kaji\/sdk["']/.test(readFileSync(githubEntry, "utf8")) ||
      !/\brequire\(["']@kaji\/sdk["']\)/.test(readFileSync(requiredGithubEntry, "utf8"))
    ) {
      throw new Error("GitHub package output does not resolve Integration through the root export");
    }
    publicScenarios.push("class-identity");

    proofStage = "private-source-containment";
    const privateSourceContainment = await inspectPrivateGitHubCompositionSources(packageRoot);
    if (
      privateSourceContainment.privateGitHubCompositionSourcesPacked ||
      !privateSourceContainment.privateGitHubCompositionSourceImportsRejected
    ) {
      throw new Error("private GitHub package composition source is present or importable");
    }
    publicScenarios.push("private-source-containment");

    proofStage = "declaration-privacy";
    const declarationExports: string[][] = [];
    for (const declarationPath of [
      "dist/integrations/github.d.ts",
      "dist/integrations/github.d.cts",
    ]) {
      const declaration = readFileSync(
        contained(join(packageRoot, declarationPath), packageRoot, "GitHub declaration"),
        "utf8",
      );
      const exports = declarationExportNames(declaration);
      if (
        !isDeepStrictEqual(exports, [...EXPECTED_DECLARATION_EXPORTS].sort()) ||
        !declaration.includes("constructor(options: CreateGitHubIntegrationOptions);") ||
        !declaration.includes('readonly toolExposure?: "read-only" | "all";') ||
        /GitHubClient|FixedOriginRequester|GitHubClientOptions|PackageGitHubRuntime|\bhttp\b|\brequester\b|\btransport\b/.test(
          declaration,
        )
      ) {
        throw new Error("GitHub declarations expose a private construction seam");
      }
      declarationExports.push(exports);
    }
    const [esmDeclarationExports, cjsDeclarationExports] = declarationExports as [
      string[],
      string[],
    ];
    publicScenarios.push("declaration-privacy");

    proofStage = "catalog";
    const inspected = github.inspectIntegration();
    const packageTools = exactToolSpecs(inspected, packageAbi, "ESM");
    inspected.close();
    const requiredInspected = requiredGithub.inspectIntegration();
    const requiredPackageTools = exactToolSpecs(requiredInspected, packageAbi, "CommonJS");
    requiredInspected.close();
    if (
      packageTools.length !== EXPECTED_TOOLS.length ||
      requiredPackageTools.length !== EXPECTED_TOOLS.length
    ) {
      throw new Error("GitHub package ABI tool count changed");
    }
    if (
      !isDeepStrictEqual(packageTools.slice(0, abi.tools.length), abi.tools) ||
      !isDeepStrictEqual(requiredPackageTools.slice(0, abi.tools.length), abi.tools) ||
      copiedManifest.version !== "0.1.0" ||
      !isDeepStrictEqual(copiedManifest.tools, abi.tools) ||
      packageTools
        .filter((spec) => spec.risk === "read")
        .map((spec) => spec.name)
        .join(",") !== EXPECTED_READ_TOOLS.join(",")
    ) {
      throw new Error("GitHub shared/package catalog boundary changed");
    }
    publicScenarios.push("catalog-inspection");

    proofStage = "registration";
    const registry = new sdk.ToolRegistry();
    github.inspectIntegration().register(registry);
    const registered = registry.listSpecs();
    if (
      JSON.stringify(registered.map((spec) => spec.name)) !==
        JSON.stringify(EXPECTED_TOOLS.map((name) => `github_${name}`)) ||
      registered.some((spec, index) => spec.catalogName !== `github.${EXPECTED_TOOLS[index]}`)
    ) {
      throw new Error("GitHub provider aliases lost catalog identity");
    }
    const readOnlyOptions = {
      tokenFor: async () => "unused-read-only-token",
      repositories: [] as const,
      toolExposure: "read-only" as const,
    };
    const readOnlyEsm = github.createGithubIntegration(readOnlyOptions);
    const readOnlyCjs = requiredGithub.createGithubIntegration(readOnlyOptions);
    for (const [label, integration, RuntimeRegistry] of [
      ["ESM", readOnlyEsm, sdk.ToolRegistry],
      ["CommonJS", readOnlyCjs, requiredSdk.ToolRegistry],
    ] as const) {
      const readOnlyTools = integration.tools().map(([spec]) => spec);
      const readOnlyRegistry = new RuntimeRegistry();
      integration.register(readOnlyRegistry);
      const readOnlyRegistered = readOnlyRegistry.listSpecs();
      if (
        !isDeepStrictEqual(
          readOnlyTools.map((spec) => spec.name),
          EXPECTED_READ_TOOLS,
        ) ||
        readOnlyTools.some((spec) => spec.risk !== "read") ||
        !isDeepStrictEqual(
          readOnlyRegistered.map((spec) => spec.name),
          EXPECTED_READ_TOOLS.map((name) => `github_${name}`),
        ) ||
        readOnlyRegistered.some(
          (spec, index) => spec.catalogName !== `github.${EXPECTED_READ_TOOLS[index]}`,
        )
      ) {
        throw new Error(`${label} GitHub read-only exposure changed`);
      }
      integration.close();
    }
    publicScenarios.push("public-registration");

    proofStage = "closed-lifecycle";
    let closedTokenCalls = 0;
    const closed = github.createGithubIntegration({
      tokenFor: async () => {
        closedTokenCalls += 1;
        return "artifact-proof-token";
      },
      repositories: [fixture.repository],
    });
    closed.close();
    closed.close();
    const closedGetIssue = closed.tools().find(([spec]) => spec.name === "get_issue")?.[1];
    if (closedGetIssue === undefined) throw new Error("GitHub get_issue handler is missing");
    try {
      await closedGetIssue({ repository: fixture.repository, issue_number: 1 }, context());
      throw new Error("closed GitHub integration unexpectedly executed");
    } catch (error) {
      if (!(error instanceof Error) || error.name !== "IntegrationPolicyError") throw error;
    }
    if (closedTokenCalls !== 0) throw new Error("closed GitHub integration read credentials");
    publicScenarios.push("closed-lifecycle");

    proofStage = "repository-policy";
    let repositoryTokenCalls = 0;
    const repositoryDenied = github.createGithubIntegration({
      tokenFor: async () => {
        repositoryTokenCalls += 1;
        return "artifact-proof-token";
      },
      repositories: [fixture.repository],
    });
    const getFile = repositoryDenied.tools().find(([spec]) => spec.name === "get_file")?.[1];
    if (getFile === undefined) throw new Error("GitHub get_file handler is missing");
    try {
      await getFile({ repository: "outside/repository", path: "README.md" }, context());
      throw new Error("repository policy unexpectedly allowed execution");
    } catch (error) {
      if (!(error instanceof Error) || error.name !== "IntegrationPolicyError") throw error;
    } finally {
      repositoryDenied.close();
    }
    if (repositoryTokenCalls !== 0) throw new Error("repository policy read credentials");
    publicScenarios.push("repository-policy");

    proofStage = "observability-sinks";
    const measurements: unknown[] = [];
    const spans: Array<{ name: string; attributes: Record<string, string> }> = [];
    const observabilityIntegration = github.createGithubIntegration({
      tokenFor: async () => "private-observability-token",
      repositories: [fixture.repository],
      metricsSink: {
        record(measurement) {
          measurements.push(measurement);
        },
      },
      traceSink: {
        startSpan(name, attributes = {}) {
          const span = { name, attributes: { ...attributes } };
          spans.push(span);
          return {
            setAttribute(key, value) {
              span.attributes[key] = value;
            },
            recordError() {},
            end() {},
          };
        },
      },
    });
    const observedSearch = observabilityIntegration
      .tools()
      .find(([spec]) => spec.name === "search_code")?.[1];
    if (observedSearch === undefined) throw new Error("GitHub search_code handler is missing");
    let abortReads = 0;
    const signal = {
      get aborted() {
        abortReads += 1;
        return abortReads >= 3;
      },
      reason: new DOMException("cancelled", "AbortError"),
      addEventListener() {},
      removeEventListener() {},
    } as unknown as AbortSignal;
    let observedCancellation = false;
    try {
      await observedSearch(
        { repository: fixture.repository, query: "private-observability-query" },
        { ...context(), principalId: "private-observability-principal", signal },
      );
    } catch (error) {
      observedCancellation = error instanceof DOMException && error.name === "AbortError";
    } finally {
      observabilityIntegration.close();
    }
    const authMeasurement = measurements[0] as
      | { name?: unknown; labels?: Record<string, unknown> }
      | undefined;
    const requestMeasurement = measurements[1] as
      | { name?: unknown; labels?: Record<string, unknown> }
      | undefined;
    const observabilitySnapshot = JSON.stringify({ measurements, spans });
    if (
      !observedCancellation ||
      measurements.length !== 2 ||
      authMeasurement?.name !== "kaji.integration.auth_ms" ||
      !isDeepStrictEqual(authMeasurement.labels, {
        integration: "github",
        operation: "token",
        outcome: "success",
      }) ||
      requestMeasurement?.name !== "kaji.integration.request_ms" ||
      !isDeepStrictEqual(requestMeasurement.labels, {
        integration: "github",
        operation: "read",
        outcome: "cancelled",
      }) ||
      spans.length !== 2 ||
      spans[0]?.name !== "kaji.integration.auth" ||
      spans[0]?.attributes["integration.name"] !== "github" ||
      spans[0]?.attributes["integration.operation"] !== "token" ||
      spans[1]?.name !== "kaji.integration.request" ||
      spans[1]?.attributes["integration.name"] !== "github" ||
      spans[1]?.attributes["integration.operation"] !== "read" ||
      observabilitySnapshot.includes("private-observability") ||
      observabilitySnapshot.includes(fixture.repository)
    ) {
      throw new Error("installed GitHub observability plumbing is incomplete or unsafe");
    }
    publicScenarios.push("observability-sinks");

    proofStage = "approval-rejection";
    let approvalTokenCalls = 0;
    const approvalIntegration = github.createGithubIntegration({
      tokenFor: async () => {
        approvalTokenCalls += 1;
        return "artifact-proof-token";
      },
      repositories: [fixture.repository],
    });
    const approval = await executeCall(
      sdk,
      approvalIntegration,
      {
        id: "approval",
        name: "github_create_issue",
        arguments: { repository: fixture.repository, title: "title", body: "body" },
      },
      {
        policy: new sdk.ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
        approvalHandler: {
          request: async () => ({
            granted: false,
            code: "rejected",
            reason: "Rejected by installed package proof",
          }),
        },
      },
    );
    approvalIntegration.close();
    if (approvalTokenCalls !== 0 || approval.results[0]?.error_code !== "APPROVAL_REJECTED") {
      throw new Error("approval rejection reached credentials");
    }
    assertToolEvents(sdk, approval.events, "github_create_issue", "github.create_issue", [
      sdk.EventType.TOOL_CALL_REQUESTED,
      sdk.EventType.TOOL_CALL_FAILED,
    ]);
    publicScenarios.push("approval-rejection");
    const policyBeforeRequest = {
      testFile: "kaji/ts/tests/github-registry.test.ts" as const,
      testName: "rejects approval for github_create_issue before token or HTTP" as const,
      tokenLookups: approvalTokenCalls,
      requestAttempts: networkAttempts,
    };

    proofStage = "validation-failure";
    let validationTokenCalls = 0;
    const validationIntegration = github.createGithubIntegration({
      tokenFor: async () => {
        validationTokenCalls += 1;
        return "artifact-proof-token";
      },
      repositories: [fixture.repository],
    });
    const validation = await executeCall(sdk, validationIntegration, {
      id: "validation",
      name: "github_get_issue",
      arguments: { repository: fixture.repository },
    });
    validationIntegration.close();
    if (
      validationTokenCalls !== 0 ||
      validation.results[0]?.error_code !== "INVALID_TOOL_ARGUMENTS"
    ) {
      throw new Error("validation failure reached credentials");
    }
    assertToolEvents(sdk, validation.events, "github_get_issue", "github.get_issue", [
      sdk.EventType.TOOL_CALL_REQUESTED,
      sdk.EventType.TOOL_CALL_FAILED,
    ]);
    publicScenarios.push("validation-failure");

    proofStage = "execution-failure";
    const executionIntegration = github.createGithubIntegration({
      tokenFor: async () => {
        throw new Error("credential provider unavailable");
      },
      repositories: [fixture.repository],
    });
    const execution = await executeCall(sdk, executionIntegration, {
      id: "execution",
      name: "github_get_file",
      arguments: { repository: fixture.repository, path: "README.md" },
    });
    executionIntegration.close();
    const githubFailureLifecycle = assertToolEvents(
      sdk,
      execution.events,
      "github_get_file",
      "github.get_file",
      [
        sdk.EventType.TOOL_CALL_REQUESTED,
        sdk.EventType.TOOL_CALL_STARTED,
        sdk.EventType.TOOL_CALL_FAILED,
      ],
    );
    const failedEvent = execution.events.find(
      (event) => event.type === sdk.EventType.TOOL_CALL_FAILED,
    );
    if (
      !isDeepStrictEqual(recoveryTuple(execution.results[0]), GITHUB_TOKEN_RECOVERY) ||
      !isDeepStrictEqual(recoveryTuple(failedEvent), GITHUB_TOKEN_RECOVERY)
    ) {
      throw new Error("installed GitHub failure lost its certified recovery tuple");
    }
    const mutationAttemptsBefore = networkAttempts;
    const mutationIntegration = github.createGithubIntegration({
      tokenFor: async () => "artifact-proof-token",
      repositories: [fixture.repository],
    });
    const mutation = await executeCall(sdk, mutationIntegration, {
      id: "mutation",
      name: "github_add_comment",
      arguments: {
        repository: fixture.repository,
        issue_number: 1,
        body: "installed artifact mutation ambiguity proof",
      },
    });
    mutationIntegration.close();
    const mutationFailedEvent = mutation.events.find(
      (event) => event.type === sdk.EventType.TOOL_CALL_FAILED,
    );
    if (
      networkAttempts - mutationAttemptsBefore !== 1 ||
      !isDeepStrictEqual(recoveryTuple(mutation.results[0]), GITHUB_MUTATION_RECOVERY) ||
      !isDeepStrictEqual(recoveryTuple(mutationFailedEvent), GITHUB_MUTATION_RECOVERY) ||
      mutation.results[0]?.outcome !== "unknown" ||
      mutationFailedEvent?.outcome !== "unknown"
    ) {
      throw new Error("installed GitHub mutation ambiguity was not preserved");
    }
    assertToolEvents(sdk, mutation.events, "github_add_comment", "github.add_comment", [
      sdk.EventType.TOOL_CALL_REQUESTED,
      sdk.EventType.TOOL_CALL_STARTED,
      sdk.EventType.TOOL_CALL_FAILED,
    ]);
    publicScenarios.push("execution-failure");

    proofStage = "completed-event";
    class SyntheticIntegration extends sdk.Integration {
      readonly namespace = "synthetic";

      override tools() {
        return [
          [
            { name: "complete", description: "complete", parameters: {}, risk: "read" as const },
            async () => ({ ok: true }),
          ],
        ] as never;
      }
    }
    const completed = await executeCall(sdk, new SyntheticIntegration(), {
      id: "completed",
      name: "synthetic_complete",
      arguments: {},
    });
    const syntheticCompletionLifecycle = assertToolEvents(
      sdk,
      completed.events,
      "synthetic_complete",
      "synthetic.complete",
      [
        sdk.EventType.TOOL_CALL_REQUESTED,
        sdk.EventType.TOOL_CALL_STARTED,
        sdk.EventType.TOOL_CALL_COMPLETED,
      ],
    );
    publicScenarios.push("synthetic-completed-event");

    proofStage = "mock-provider";
    const mockStore = new sdk.InMemoryEventStore();
    const mockIntegration = github.createGithubIntegration({
      tokenFor: async () => {
        throw new Error("credential provider unavailable");
      },
      repositories: [fixture.repository],
    });
    const runtime = new sdk.AgentBuilder()
      .provider(
        new testing.MockProvider({
          toolCall: {
            name: "github_get_issue",
            args: { repository: fixture.repository, issue_number: 1 },
          },
        }),
      )
      .integration(mockIntegration)
      .build({ store: mockStore });
    const turn = await runtime.turn("inspect the issue", {
      context: { principalId: "installed-proof" },
    });
    const mockEvents = (await mockStore.getEvents(turn.sessionId)) as Array<{
      type: string;
      metadata: Readonly<Record<string, unknown>>;
    }>;
    runtime.close();
    mockIntegration.close();
    if (turn.text !== "The mock provider has completed the tool loop.") {
      throw new Error("MockProvider did not terminate deterministically");
    }
    assertToolEvents(sdk, mockEvents, "github_get_issue", "github.get_issue", [
      sdk.EventType.TOOL_CALL_REQUESTED,
      sdk.EventType.TOOL_CALL_STARTED,
      sdk.EventType.TOOL_CALL_FAILED,
    ]);
    publicScenarios.push("mock-provider-loop");

    proofStage = "alias-collision";
    class CollidingIntegration extends sdk.Integration {
      readonly namespace = "github_get";

      override tools() {
        return [
          [
            { name: "file", description: "collision", parameters: {}, risk: "read" as const },
            async () => ({}),
          ],
        ] as never;
      }
    }
    const collisionRegistry = new sdk.ToolRegistry();
    github.inspectIntegration().register(collisionRegistry);
    try {
      new CollidingIntegration().register(collisionRegistry);
      throw new Error("provider alias collision was accepted");
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes("github_get_file")) throw error;
    }
    publicScenarios.push("alias-collision");

    proofStage = "assertions";
    if (
      JSON.stringify(publicScenarios) !== JSON.stringify(EXPECTED_PUBLIC_SCENARIOS) ||
      networkAttempts !== 1 ||
      policyBeforeRequest.requestAttempts !== 0
    ) {
      throw new Error("installed GitHub public proof assertions failed");
    }
    return {
      schemaVersion: 5,
      evidenceClass: "offline_exact_artifact_smoke",
      integration: "github",
      runtime: "typescript",
      network: "blocked",
      liveProvider: false,
      sharedAbiVersion: abi.version,
      packageAbiSchemaVersion: packageAbi.schema_version,
      packageCatalogVersion: packageAbi.catalog_version,
      apiFixtureVersion: fixture.version,
      sharedFixtureCaseCount: fixture.cases.length,
      publicScenarioCount: publicScenarios.length,
      packageCatalog: {
        schemaVersion: packageAbi.schema_version,
        catalogVersion: packageAbi.catalog_version,
        toolCount: packageTools.length,
        readToolCount: packageTools.filter((spec) => spec.risk === "read").length,
        tools: packageTools.map((spec) => spec.name),
        readTools: packageTools.filter((spec) => spec.risk === "read").map((spec) => spec.name),
        providerAliases: EXPECTED_PROVIDER_ALIASES,
        catalogNames: EXPECTED_CATALOG_NAMES,
      },
      cliCopiedCatalog: {
        manifestVersion: copiedManifest.version,
        toolCount: copiedManifest.tools.length,
        readToolCount: copiedManifest.tools.filter((spec) => spec.risk === "read").length,
        tools: copiedManifest.tools.map((spec) => spec.name),
        readTools: copiedManifest.tools
          .filter((spec) => spec.risk === "read")
          .map((spec) => spec.name),
      },
      esmSharedAbiMatched: true,
      cjsSharedAbiMatched: true,
      esmPackageAbiMatched: true,
      cjsPackageAbiMatched: true,
      esmClassIdentityMatched,
      cjsClassIdentityMatched,
      esmFactoryIdentityMatched,
      cjsFactoryIdentityMatched,
      esmRuntimeExports,
      cjsRuntimeExports,
      esmDeclarationExports,
      cjsDeclarationExports,
      typescriptDeclarationChecks,
      privateGitHubCompositionSourcesPacked:
        privateSourceContainment.privateGitHubCompositionSourcesPacked,
      privateGitHubCompositionSourceImportsRejected:
        privateSourceContainment.privateGitHubCompositionSourceImportsRejected,
      closedCallsDeniedBeforeCredentialAccess: true,
      approvalDeniedBeforeCredentialAccess: true,
      repositoryDeniedBeforeCredentialAccess: true,
      githubCatalogEventsVerified: ["requested", "started", "failed"],
      genericSyntheticCatalogEventsVerified: ["requested", "started", "completed"],
      githubFailureRecovery: GITHUB_TOKEN_RECOVERY,
      githubObservabilitySinksVerified: true,
      unknownMutationPreserved: true,
      mutationRetries: 0,
      lifecycle: {
        githubFailure: githubFailureLifecycle,
        syntheticCompletion: syntheticCompletionLifecycle,
      },
      policyBeforeRequest,
      aliasCollisionRejected: true,
      conclusion: "passed",
      failureCode: null,
    } as const;
  } finally {
    globalThis.fetch = originalFetch;
    Reflect.set(Socket.prototype, "connect", originalConnect);
  }
}

let proofStage = "startup";

async function main(): Promise<number> {
  try {
    console.log(JSON.stringify(await runProof(process.argv.slice(2))));
    return 0;
  } catch (error) {
    const code = error instanceof ProofFailure ? error.code : "proof_failed";
    console.error(`installed GitHub package proof failed at ${proofStage} code=${code}`);
    return 1;
  }
}

process.exitCode = await main();
