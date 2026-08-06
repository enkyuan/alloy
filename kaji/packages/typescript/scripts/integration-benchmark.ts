import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import type { ToolExecutionContext } from "../src/runtime/context";
import {
  fixedOriginForTest,
  type FixedOriginTestResponse,
  type FixedOriginTestTransport,
} from "../src/integrations/fixed-origin";
import { IntegrationPolicyError, IntegrationTransportError } from "../src/integrations/errors";
import {
  _createMacOSKeychainTokenStorageForTest,
  type KeychainProcess,
} from "../src/auth/keychain";
import {
  _createGoogleOAuthClientForTest,
  canonicalOAuthCredentialJson,
  snapshotOAuthCredentialRecord,
  type OAuthCredentialRecord,
  type OAuthTokenStorage,
} from "../src/auth/oauth";
import { GitHubClient } from "../registry/github/client";

export const INTEGRATION_BENCHMARK_CASES = [
  "fixedOriginPreflight",
  "fixedOriginCapRejection",
  "githubDtoMaxBounds",
  "keychainRecordParse",
  "oauthRefreshSingleFlight",
] as const;

export type IntegrationBenchmarkCase = (typeof INTEGRATION_BENCHMARK_CASES)[number];

interface BenchmarkCaseConfig {
  readonly name: IntegrationBenchmarkCase;
  readonly input: Readonly<Record<string, unknown>>;
}

interface BenchmarkBudgets {
  readonly schemaVersion: 1;
  readonly cases: readonly BenchmarkCaseConfig[];
}

export interface BenchmarkCaseResult {
  readonly schemaVersion: 1;
  readonly runtime: "typescript";
  readonly case: IntegrationBenchmarkCase;
  readonly inputSha256: string;
  readonly warmups: number;
  readonly batches: readonly (readonly number[])[];
  readonly semantics: Readonly<Record<string, number>>;
}

type Operation = () => Promise<Readonly<Record<string, number>>>;
type Close = () => Promise<void>;

function normalizedJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizedJson);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, normalizedJson((value as Record<string, unknown>)[key])]),
    );
  }
  return value;
}

export function canonicalBenchmarkJson(value: unknown): string {
  return JSON.stringify(normalizedJson(value));
}

export function benchmarkInputDigest(value: unknown): string {
  return createHash("sha256").update(canonicalBenchmarkJson(value), "utf8").digest("hex");
}

function positiveInteger(value: unknown, label: string, allowZero = false): number {
  const minimum = allowZero ? 0 : 1;
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new Error(`${label} must be an integer >= ${minimum}`);
  }
  return value as number;
}

function stringValue(input: Readonly<Record<string, unknown>>, name: string): string {
  const value = input[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`benchmark input ${name} must be a non-empty string`);
  }
  return value;
}

function integerValue(input: Readonly<Record<string, unknown>>, name: string): number {
  return positiveInteger(input[name], `benchmark input ${name}`);
}

export function loadIntegrationBenchmarkBudgets(
  path: string | URL = new URL("../../../benchmarks/integration-budgets.json", import.meta.url),
): BenchmarkBudgets {
  const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (
    parsed === null ||
    typeof parsed !== "object" ||
    Array.isArray(parsed) ||
    (parsed as { schemaVersion?: unknown }).schemaVersion !== 1 ||
    !Array.isArray((parsed as { cases?: unknown }).cases)
  ) {
    throw new Error("integration benchmark budgets are malformed");
  }
  const budgets = parsed as BenchmarkBudgets;
  const names = budgets.cases.map(({ name }) => name);
  if (JSON.stringify(names) !== JSON.stringify(INTEGRATION_BENCHMARK_CASES)) {
    throw new Error("integration benchmark case order changed");
  }
  return budgets;
}

function caseInput(
  budgets: BenchmarkBudgets,
  name: IntegrationBenchmarkCase,
): Readonly<Record<string, unknown>> {
  const found = budgets.cases.find((candidate) => candidate.name === name);
  if (found === undefined) throw new Error("integration benchmark case is missing");
  return found.input;
}

function context(principalId = "benchmark-principal"): ToolExecutionContext {
  return {
    principalId,
    sessionId: "benchmark-session",
    turnId: "benchmark-turn",
    requestId: "benchmark-request",
    traceId: "benchmark-trace",
    toolCallId: "benchmark-call",
    idempotencyKey: "benchmark-session:benchmark-call",
    signal: new AbortController().signal,
    metadata: {},
  };
}

async function fixedOriginPreflight(
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  let transportCalls = 0;
  const transport: FixedOriginTestTransport = {
    async request(): Promise<FixedOriginTestResponse> {
      transportCalls += 1;
      return {
        status: 200,
        headers: [],
        body: (async function* () {
          yield new TextEncoder().encode("{}");
        })(),
        close: () => {},
      };
    },
  };
  const requester = fixedOriginForTest(stringValue(input, "origin"), transport);
  const operation: Operation = async () => {
    const before = transportCalls;
    const response = await requester.request(
      stringValue(input, "safePath"),
      { method: "GET", headers: {} },
      context(),
    );
    const afterSafe = transportCalls;
    let rejected = 0;
    try {
      await requester.request(
        stringValue(input, "hostilePath"),
        { method: "GET", headers: {} },
        context(),
      );
    } catch (error) {
      if (!(error instanceof IntegrationPolicyError)) throw error;
      rejected = 1;
    }
    return {
      safeRequests: afterSafe - before,
      hostileRequests: transportCalls - afterSafe,
      rejected,
      responseBytes: response.bytes.byteLength,
    };
  };
  return [operation, async () => {}];
}

async function fixedOriginCapRejection(
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  const limitBytes = integerValue(input, "limitBytes");
  const payload = new Uint8Array(limitBytes + integerValue(input, "overflowBytes"));
  let transportCalls = 0;
  let closed = 0;
  const transport: FixedOriginTestTransport = {
    async request(): Promise<FixedOriginTestResponse> {
      transportCalls += 1;
      return {
        status: 200,
        headers: [],
        body: (async function* () {
          yield payload;
        })(),
        close: () => {
          closed += 1;
        },
      };
    },
  };
  const requester = fixedOriginForTest(stringValue(input, "origin"), transport, {
    maxResponseBytes: limitBytes,
  });
  const operation: Operation = async () => {
    const callsBefore = transportCalls;
    const closedBefore = closed;
    let rejected = 0;
    try {
      await requester.request(
        stringValue(input, "path"),
        { method: "GET", headers: {} },
        context(),
      );
    } catch (error) {
      if (
        !(error instanceof IntegrationTransportError) ||
        error.error_code !== "INTEGRATION_RESPONSE_LIMIT"
      ) {
        throw error;
      }
      rejected = 1;
    }
    return {
      requests: transportCalls - callsBefore,
      rejected,
      closed: closed - closedBefore,
      limitBytes,
      observedBytes: payload.byteLength,
    };
  };
  return [operation, async () => {}];
}

async function githubDtoMaxBounds(
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  const repository = stringValue(input, "repository");
  const titleCharacters = integerValue(input, "titleCharacters");
  const bodyBytes = integerValue(input, "bodyBytes");
  const rows = Array.from({ length: integerValue(input, "rowCount") }, (_, index) => ({
    number: index + 1,
    state: "open",
    title: "t".repeat(titleCharacters),
    body: "b".repeat(bodyBytes),
  }));
  const bytes = new TextEncoder().encode(JSON.stringify(rows));
  const client = new GitHubClient({
    tokenFor: async () => "benchmark-token",
    repositories: [repository],
    http: {
      async request() {
        return { status: 200, headers: Object.freeze({}), bytes };
      },
    },
  });
  const operation: Operation = async () => {
    const result = (await client.listIssues(context(), {
      repository,
      state: "all",
      page: 1,
      perPage: 20,
    })) as { readonly items: readonly Record<string, unknown>[] };
    const serialized = new TextEncoder().encode(JSON.stringify(result));
    const first = result.items[0]!;
    return {
      rows: result.items.length,
      titleCharacters: Array.from(first.title as string).length,
      bodyPreviewBytes: new TextEncoder().encode(first.body_preview as string).byteLength,
      serializedBytes: serialized.byteLength,
    };
  };
  return [operation, async () => {}];
}

async function keychainRecordParse(
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  const record = snapshotOAuthCredentialRecord({
    schemaVersion: 1,
    state: "active",
    tokens: {
      accessToken: "a".repeat(integerValue(input, "accessTokenCharacters")),
      refreshToken: "r".repeat(integerValue(input, "refreshTokenCharacters")),
      expiresAtEpochMs: 1_700_003_600_000,
      grantedScopes: ["s".repeat(integerValue(input, "scopeCharacters"))],
      tokenType: "Bearer",
    },
  });
  const encoded = canonicalOAuthCredentialJson(record);
  let processCalls = 0;
  const process: KeychainProcess = {
    async run() {
      processCalls += 1;
      return { code: 0, stdout: `${encoded}\n` };
    },
  };
  const storage = _createMacOSKeychainTokenStorageForTest({
    process,
    platform: "darwin",
    executable: true,
    integrationName: stringValue(input, "integration"),
  });
  const operation: Operation = async () => {
    const before = processCalls;
    const loaded = await storage.load(
      stringValue(input, "principal"),
      new AbortController().signal,
    );
    if (loaded === undefined) throw new Error("Keychain benchmark record disappeared");
    return {
      records: 1,
      processCalls: processCalls - before,
      recordBytes: new TextEncoder().encode(encoded).byteLength,
      scopes: loaded.tokens.grantedScopes.length,
    };
  };
  return [operation, async () => {}];
}

async function oauthRefreshSingleFlight(
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  const principal = stringValue(input, "principal");
  const waiters = integerValue(input, "waiters");
  const scopes = input.scopes;
  if (!Array.isArray(scopes) || scopes.some((scope) => typeof scope !== "string")) {
    throw new Error("benchmark OAuth scopes are malformed");
  }

  const operation: Operation = async () => {
    const oldRecord = snapshotOAuthCredentialRecord({
      schemaVersion: 1,
      state: "active",
      tokens: {
        accessToken: "old",
        refreshToken: "refresh",
        expiresAtEpochMs: 1,
        grantedScopes: scopes,
        tokenType: "Bearer",
      },
    });
    class MemoryStorage implements OAuthTokenStorage {
      loads = 0;
      saves = 0;
      value: OAuthCredentialRecord = oldRecord;

      async load(): Promise<OAuthCredentialRecord> {
        this.loads += 1;
        return this.value;
      }

      async save(_principalId: string, value: OAuthCredentialRecord): Promise<void> {
        this.saves += 1;
        this.value = value;
      }

      async delete(): Promise<void> {
        throw new Error("refresh benchmark unexpectedly deleted the grant");
      }
    }
    const storage = new MemoryStorage();
    const entered = Promise.withResolvers<void>();
    const release = Promise.withResolvers<void>();
    let httpCalls = 0;
    const client = _createGoogleOAuthClientForTest(
      { clientId: "client-id", scopes: scopes as string[], storage },
      {
        http: {
          async postForm() {
            httpCalls += 1;
            entered.resolve();
            await release.promise;
            return {
              status: 200,
              bytes: new TextEncoder().encode(
                '{"access_token":"new","expires_in":3600,"token_type":"Bearer"}',
              ),
            };
          },
        },
        callbackFactory: {
          async open(): Promise<never> {
            throw new Error("refresh benchmark opened a callback listener");
          },
        },
        browser: {
          async open(): Promise<void> {
            throw new Error("refresh benchmark opened a browser");
          },
        },
        clock: { nowWallSeconds: () => 1_700_000_000, nowMonotonic: () => 100_000 },
        randomBytes: (count) => Uint8Array.from({ length: count }, (_, index) => index),
      },
    );
    const pending = Array.from({ length: waiters }, () => client.accessToken(context(principal)));
    await entered.promise;
    for (let attempt = 0; attempt < waiters * 4 && storage.loads !== waiters; attempt += 1) {
      await new Promise<void>((resolve) => setImmediate(resolve));
    }
    if (storage.loads !== waiters)
      throw new Error("refresh waiters did not join deterministically");
    await Promise.resolve();
    release.resolve();
    const tokens = await Promise.all(pending);
    return {
      waiters: tokens.length,
      httpCalls,
      saveCalls: storage.saves,
      uniqueTokens: new Set(tokens).size,
    };
  };
  return [operation, async () => {}];
}

async function operationFor(
  name: IntegrationBenchmarkCase,
  input: Readonly<Record<string, unknown>>,
): Promise<readonly [Operation, Close]> {
  switch (name) {
    case "fixedOriginPreflight":
      return fixedOriginPreflight(input);
    case "fixedOriginCapRejection":
      return fixedOriginCapRejection(input);
    case "githubDtoMaxBounds":
      return githubDtoMaxBounds(input);
    case "keychainRecordParse":
      return keychainRecordParse(input);
    case "oauthRefreshSingleFlight":
      return oauthRefreshSingleFlight(input);
  }
}

export async function runIntegrationBenchmarkCase(options: {
  readonly caseName: IntegrationBenchmarkCase;
  readonly input: Readonly<Record<string, unknown>>;
  readonly warmups: number;
  readonly batches: number;
  readonly samplesPerBatch: number;
}): Promise<BenchmarkCaseResult> {
  const warmups = positiveInteger(options.warmups, "warmups", true);
  const batches = positiveInteger(options.batches, "batches");
  const samplesPerBatch = positiveInteger(options.samplesPerBatch, "samples per batch");
  const [operation, close] = await operationFor(options.caseName, options.input);
  let semantics: Readonly<Record<string, number>> | undefined;
  const invoke = async (measured: boolean): Promise<number> => {
    const started = performance.now();
    const current = await operation();
    const elapsed = performance.now() - started;
    if (semantics === undefined) semantics = current;
    else if (canonicalBenchmarkJson(semantics) !== canonicalBenchmarkJson(current)) {
      throw new Error(`TypeScript ${options.caseName} semantics changed between samples`);
    }
    return measured ? elapsed : 0;
  };
  try {
    for (let index = 0; index < warmups; index += 1) await invoke(false);
    const measured: number[][] = [];
    for (let batch = 0; batch < batches; batch += 1) {
      const samples: number[] = [];
      for (let sample = 0; sample < samplesPerBatch; sample += 1) {
        samples.push(await invoke(true));
      }
      measured.push(samples);
    }
    if (semantics === undefined) throw new Error("benchmark emitted no semantics");
    return {
      schemaVersion: 1,
      runtime: "typescript",
      case: options.caseName,
      inputSha256: benchmarkInputDigest(options.input),
      warmups,
      batches: measured,
      semantics,
    };
  } finally {
    await close();
  }
}

interface CliOptions {
  readonly caseName: IntegrationBenchmarkCase;
  readonly budgetsPath: string;
  readonly warmups: number;
  readonly batches: number;
  readonly samplesPerBatch: number;
}

function parseCli(argv: readonly string[]): CliOptions {
  const values = new Map<string, string>();
  const allowed = new Set([
    "--child-case",
    "--budgets",
    "--warmups",
    "--batches",
    "--samples-per-batch",
  ]);
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === undefined || value === undefined || !allowed.has(flag) || values.has(flag)) {
      throw new Error("invalid integration benchmark arguments");
    }
    values.set(flag, value);
  }
  if (values.size !== allowed.size) throw new Error("incomplete integration benchmark arguments");
  const caseName = values.get("--child-case") as IntegrationBenchmarkCase;
  if (!INTEGRATION_BENCHMARK_CASES.includes(caseName)) {
    throw new Error("unknown integration benchmark case");
  }
  return {
    caseName,
    budgetsPath: values.get("--budgets")!,
    warmups: positiveInteger(Number(values.get("--warmups")), "warmups", true),
    batches: positiveInteger(Number(values.get("--batches")), "batches"),
    samplesPerBatch: positiveInteger(
      Number(values.get("--samples-per-batch")),
      "samples per batch",
    ),
  };
}

async function main(): Promise<number> {
  try {
    const options = parseCli(process.argv.slice(2));
    const budgets = loadIntegrationBenchmarkBudgets(options.budgetsPath);
    const result = await runIntegrationBenchmarkCase({
      caseName: options.caseName,
      input: caseInput(budgets, options.caseName),
      warmups: options.warmups,
      batches: options.batches,
      samplesPerBatch: options.samplesPerBatch,
    });
    process.stdout.write(`${canonicalBenchmarkJson(result)}\n`);
    return 0;
  } catch {
    process.stderr.write("integration benchmark child failed\n");
    return 1;
  }
}

if (import.meta.main) process.exitCode = await main();
