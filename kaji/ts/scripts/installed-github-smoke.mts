#!/usr/bin/env bun
/** Exercise one CLI-copied GitHub bundle against an installed npm artifact. */

import { readFileSync, realpathSync } from "node:fs";
import { Socket } from "node:net";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

import type { ToolExecutionContext, ToolRegistry } from "@kaji/sdk";
import type { BoundedResponse, FixedOriginRequester } from "@kaji/sdk/integrations";

type SdkRuntime = typeof import("@kaji/sdk");

const EXPECTED_TOOLS = new Set([
  "add_comment",
  "create_issue",
  "get_file",
  "get_issue",
  "list_issues",
  "search_code",
]);

interface FixtureCase {
  readonly name: string;
  readonly operation: string;
  readonly input: Readonly<Record<string, unknown>>;
  readonly responses: readonly Readonly<Record<string, unknown>>[];
  readonly expected_requests: readonly unknown[];
  readonly expected_sleeps?: readonly number[];
  readonly expected_token_calls?: number;
  readonly expected: Readonly<Record<string, unknown>>;
}

interface Fixture {
  readonly version: string;
  readonly repository: string;
  readonly token: string;
  readonly cases: readonly FixtureCase[];
}

interface GitHubClientLike {
  new (
    options: Readonly<{
      tokenFor: (context: ToolExecutionContext) => Promise<string>;
      repositories: readonly string[];
      http: FixedOriginRequester;
    }>,
    runtime?: Readonly<{
      sleep: (delayMs: number, signal: AbortSignal) => Promise<void>;
      monotonicNow: () => number;
    }>,
  ): object;
}

interface GitHubIntegrationInstance {
  tools(): Array<
    [
      Readonly<{ name: string }>,
      (args: Record<string, unknown>, context: ToolExecutionContext) => Promise<unknown>,
    ]
  >;
  register(registry: ToolRegistry): void;
  close(): void;
}

interface GitHubIntegrationLike {
  new (client: object, closeOwnedRequester?: () => void): GitHubIntegrationInstance;
}

interface GitHubIntegrationModule {
  GitHubIntegration: GitHubIntegrationLike;
  createGithubIntegration(options: {
    tokenFor: (context: ToolExecutionContext) => Promise<string>;
    repositories: readonly string[];
  }): GitHubIntegrationInstance;
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
  bundleRoot: string;
  packageRoot: string;
} {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (
      !["--sandbox-root", "--bundle-root", "--package-root"].includes(flag ?? "") ||
      value === undefined ||
      value.startsWith("--")
    ) {
      throw new Error("invalid installed GitHub proof arguments");
    }
    values.set(flag!, value);
  }
  if (values.size !== 3) throw new Error("incomplete installed GitHub proof arguments");
  return {
    sandboxRoot: values.get("--sandbox-root")!,
    bundleRoot: values.get("--bundle-root")!,
    packageRoot: values.get("--package-root")!,
  };
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

class ScriptedRequester implements FixedOriginRequester {
  readonly requests: unknown[] = [];
  readonly contexts: ToolExecutionContext[] = [];
  readonly responses: Readonly<Record<string, unknown>>[];

  constructor(responses: readonly Readonly<Record<string, unknown>>[]) {
    this.responses = [...responses];
  }

  async request(
    pathAndQuery: string,
    init: Readonly<{
      method: "GET" | "POST";
      headers: ConstructorParameters<typeof Headers>[0];
      body?: Uint8Array;
    }>,
    executionContext: ToolExecutionContext,
  ): Promise<BoundedResponse> {
    this.requests.push({
      method: init.method,
      path_and_query: pathAndQuery,
      headers: Object.fromEntries(new Headers(init.headers).entries()),
      body: init.body === undefined ? null : new TextDecoder().decode(init.body),
    });
    this.contexts.push(executionContext);
    const response = this.responses.shift();
    if (response === undefined) throw new Error("scripted GitHub response queue was exhausted");
    if (response.transport_error === "response_limit") {
      throw new Error("private response limit detail");
    }
    if (response.transport_error === "cancelled") {
      throw new DOMException("private cancellation detail", "AbortError");
    }
    if (response.transport_error === "connection") {
      throw new Error("private connection detail");
    }
    const bytes =
      "json" in response
        ? new TextEncoder().encode(JSON.stringify(response.json))
        : new TextEncoder().encode(String(response.body ?? ""));
    return {
      status: response.status as number,
      headers: Object.freeze({
        ...(response.headers as Record<string, string> | undefined),
      }),
      bytes,
    };
  }
}

async function runCases(
  sdk: SdkRuntime,
  Client: GitHubClientLike,
  Integration: GitHubIntegrationLike,
  fixture: Fixture,
): Promise<{
  executedTools: Set<string>;
  unknownMutationPreserved: boolean;
  mutationRetries: number;
}> {
  const executedTools = new Set<string>();
  let unknownMutationPreserved = false;
  let mutationRetries = -1;

  for (const [caseIndex, testCase] of fixture.cases.entries()) {
    proofStage = `conformance-case-${caseIndex + 1}`;
    const http = new ScriptedRequester(testCase.responses);
    const tokenContexts: ToolExecutionContext[] = [];
    const sleeps: number[] = [];
    const client = new Client(
      {
        tokenFor: async (executionContext) => {
          tokenContexts.push(executionContext);
          return fixture.token;
        },
        repositories: [fixture.repository],
        http,
      },
      {
        sleep: async (delayMs) => {
          sleeps.push(delayMs / 1_000);
        },
        monotonicNow: () => 0,
      },
    );
    const integration = new Integration(client);
    const handlers = new Map(integration.tools().map(([spec, handler]) => [spec.name, handler]));
    if (
      handlers.size !== EXPECTED_TOOLS.size ||
      [...EXPECTED_TOOLS].some((name) => !handlers.has(name))
    ) {
      throw new Error("copied GitHub integration exposed an unexpected tool set");
    }
    const handler = handlers.get(testCase.operation);
    if (handler === undefined) throw new Error("conformance case references an unknown tool");
    const executionContext = context();
    let actual: Record<string, unknown>;
    try {
      actual = {
        result: await handler(
          { repository: fixture.repository, ...testCase.input },
          executionContext,
        ),
      };
    } catch (error) {
      if (error instanceof sdk.ToolExecutionError) {
        actual = {
          error: {
            code: error.error_code,
            outcome: error.outcome,
            retryable: error.retryable,
          },
        };
      } else if (error instanceof DOMException && error.name === "AbortError") {
        actual = { exception: "cancelled" };
      } else {
        if (String(error).toLowerCase().includes("private")) {
          throw new Error("private transport detail escaped");
        }
        actual = { exception: "unknown" };
      }
    }
    if (
      !isDeepStrictEqual(actual, testCase.expected) ||
      !isDeepStrictEqual(http.requests, testCase.expected_requests) ||
      !isDeepStrictEqual(sleeps, testCase.expected_sleeps ?? []) ||
      tokenContexts.length !== (testCase.expected_token_calls ?? 1) ||
      tokenContexts.some((seen) => seen !== executionContext) ||
      http.contexts.some((seen) => seen !== executionContext) ||
      http.responses.length !== 0
    ) {
      throw new Error("installed GitHub conformance case failed");
    }
    executedTools.add(testCase.operation);
    if (testCase.name === "connection loss after write dispatch is unknown") {
      unknownMutationPreserved = isDeepStrictEqual(actual, { exception: "unknown" });
      mutationRetries = Math.max(0, http.requests.length - 1);
    }
  }
  return { executedTools, unknownMutationPreserved, mutationRetries };
}

async function approvalPrecedesCredentials(
  sdk: SdkRuntime,
  Client: GitHubClientLike,
  Integration: GitHubIntegrationLike,
  repository: string,
): Promise<boolean> {
  let credentialCalls = 0;
  let requestCalls = 0;
  const integration = new Integration(
    new Client({
      tokenFor: async () => {
        credentialCalls += 1;
        throw new Error("credential access must not run");
      },
      repositories: [repository],
      http: {
        request: async () => {
          requestCalls += 1;
          throw new Error("HTTP must not run");
        },
      },
    }),
  );
  const registry = new sdk.ToolRegistry();
  integration.register(registry);
  const specs = new Map(registry.listSpecs().map((spec) => [spec.name, spec]));
  const store = new sdk.InMemoryEventStore();
  const committer = new sdk.InMemoryEventCommitter(store);
  const planner = new sdk.ToolPlanner({
    specs,
    policy: new sdk.ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
    approvalHandler: {
      request: async () => ({
        granted: false,
        code: "rejected",
        reason: "Rejected by installed package proof",
      }),
    },
    approvalCommitter: committer,
    executor: async (toolName, args, executionContext) =>
      registry.execute(toolName, { ...args }, executionContext),
  });
  const calls = [
    {
      id: "create",
      name: "github_create_issue",
      arguments: { repository, title: "title", body: "body" },
    },
    {
      id: "comment",
      name: "github_add_comment",
      arguments: { repository, issue_number: 1, body: "body" },
    },
  ];
  for (const [index, call] of calls.entries()) {
    const results = await planner.executeBatch(
      "session",
      [call],
      sdk.ToolPlanner.committerEmitter(committer),
      `turn-${index}`,
      { principalId: "principal", requestId: "request", traceId: "trace" },
    );
    if (results[0]?.error_code !== "APPROVAL_REJECTED") return false;
  }
  const events = await store.getEvents("session");
  return (
    credentialCalls === 0 &&
    requestCalls === 0 &&
    !events.some((event) => event.type === sdk.EventType.TOOL_CALL_STARTED)
  );
}

async function factoryClosesOwnedTransport(
  integrationModule: GitHubIntegrationModule,
  repository: string,
): Promise<boolean> {
  let closeCalls = 0;
  const direct = new integrationModule.GitHubIntegration({}, () => {
    closeCalls += 1;
  });
  direct.close();
  direct.close();

  const integration = integrationModule.createGithubIntegration({
    tokenFor: async () => "artifact-proof-token",
    repositories: [repository],
  });
  integration.close();
  integration.close();
  const getIssue = integration.tools().find(([spec]) => spec.name === "get_issue")?.[1];
  if (getIssue === undefined) return false;
  try {
    await getIssue({ repository, issue_number: 1 }, context());
  } catch (error) {
    return closeCalls === 1 && error instanceof Error && error.name === "IntegrationPolicyError";
  }
  return false;
}

async function runProof(argv: string[]) {
  proofStage = "environment";
  if ("GITHUB_TOKEN" in process.env || "NODE_PATH" in process.env) {
    throw new Error("installed TypeScript proof environment is not isolated");
  }
  proofStage = "containment";
  const args = parseArguments(argv);
  const sandbox = realpathSync(args.sandboxRoot);
  const bundle = contained(args.bundleRoot, sandbox, "GitHub bundle");
  const packageRoot = contained(args.packageRoot, sandbox, "Kaji package");
  contained(fileURLToPath(import.meta.url), sandbox, "GitHub proof runner");
  proofStage = "package-identity";
  const sdkEntry = fileURLToPath(import.meta.resolve("@kaji/sdk"));
  const resolvedSdk = realpathSync(join(dirname(sdkEntry), ".."));
  if (resolvedSdk !== packageRoot) throw new Error("Kaji did not resolve from the npm artifact");
  proofStage = "contract";
  const fixturePath = contained(
    join(packageRoot, "contracts/integrations/github-api-conformance-v1.json"),
    packageRoot,
    "GitHub conformance contract",
  );
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as Fixture;

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
    proofStage = "sdk-import";
    const sdk = await import("@kaji/sdk");
    proofStage = "bundle-import";
    const clientUrl = pathToFileURL(contained(join(bundle, "client.ts"), bundle, "GitHub client"));
    const integrationUrl = pathToFileURL(
      contained(join(bundle, "index.ts"), bundle, "GitHub integration"),
    );
    const clientModule = (await import(clientUrl.href)) as { GitHubClient: GitHubClientLike };
    const integrationModule = (await import(integrationUrl.href)) as GitHubIntegrationModule;
    proofStage = "conformance";
    const { executedTools, unknownMutationPreserved, mutationRetries } = await runCases(
      sdk,
      clientModule.GitHubClient,
      integrationModule.GitHubIntegration,
      fixture,
    );
    proofStage = "approval";
    const approvalFirst = await approvalPrecedesCredentials(
      sdk,
      clientModule.GitHubClient,
      integrationModule.GitHubIntegration,
      fixture.repository,
    );
    proofStage = "lifecycle";
    const factoryLifecycleClosed = await factoryClosesOwnedTransport(
      integrationModule,
      fixture.repository,
    );
    proofStage = "assertions";
    if (
      executedTools.size !== EXPECTED_TOOLS.size ||
      [...EXPECTED_TOOLS].some((name) => !executedTools.has(name)) ||
      !unknownMutationPreserved ||
      mutationRetries !== 0 ||
      !approvalFirst ||
      !factoryLifecycleClosed ||
      networkAttempts !== 0
    ) {
      throw new Error("installed GitHub proof assertions failed");
    }
    return {
      schemaVersion: 1,
      evidenceClass: "offline_exact_artifact_smoke",
      integration: "github",
      runtime: "typescript",
      network: "scripted",
      liveProvider: false,
      contractVersion: fixture.version,
      caseCount: fixture.cases.length,
      toolCount: executedTools.size,
      approvalDeniedBeforeCredentialAccess: true,
      mutationRetries: 0,
      unknownMutationPreserved: true,
      sourceRuntimeDetected: false,
      conclusion: "passed",
      failureCode: null,
    };
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
  } catch {
    console.error(`installed GitHub package proof failed at ${proofStage}`);
    return 1;
  }
}

process.exitCode = await main();
