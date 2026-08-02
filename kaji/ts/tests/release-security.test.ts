import { describe, expect, it, vi } from "vitest";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { inspect } from "node:util";
import Ajv2020 from "ajv/dist/2020";

import { startSpan, type TraceSink } from "@/observability";
import { providerAPIErrorFromUnknown } from "@/providers/errors";
import { AgentBuilder } from "@/runtime/builder";
import { ToolExecutionController } from "@/tools/execution";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";
import {
  assertClosedOrdinaryReceipt,
  ordinaryFailureReceipt,
  SmokeCommandError,
} from "../scripts/smoke_package.mts";

const handoffSchemaRelative = "contracts/release/kaji-ts-consumer-handoff-v1.schema.json";
const canonicalHandoffSchemaRelative =
  "../contracts/release/kaji-ts-consumer-handoff-v1.schema.json";

type HandoffSchemaRule = {
  type?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  not?: { pattern: string };
  allOf?: Array<{ not?: { pattern: string } }>;
};

type HandoffSchema = {
  $defs: Record<string, HandoffSchemaRule>;
  "x-kajiConformance": {
    semverBasename: Array<{
      value: string;
      valid: boolean;
      basename?: string;
    }>;
    aliases: Record<string, Array<{ value: unknown; valid: boolean }>>;
    tagSourceRefs: Array<{ tag: string; valid: boolean; ref?: string }>;
    signerWorkflowIdentities: Array<{
      value: {
        repository: string;
        filePath: string;
        digest: string;
        ref: string;
      };
      schemaValid: boolean;
      relationValid: boolean;
    }>;
  };
};

function handoffSchema(): HandoffSchema {
  return JSON.parse(readFileSync(resolve(handoffSchemaRelative), "utf8")) as HandoffSchema;
}

function compileHandoffFragment(schema: HandoffSchema, definition: string) {
  return new Ajv2020({ allErrors: true, strict: false }).compile({
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $defs: schema.$defs,
    $ref: `#/$defs/${definition}`,
  });
}

function independentAliasValid(schema: HandoffSchema, definition: string, value: unknown): boolean {
  const rule = schema.$defs[definition];
  if (rule === undefined) throw new Error(`unknown schema definition: ${definition}`);
  if (definition === "positiveInt") {
    return (
      typeof value === "number" &&
      Number.isInteger(value) &&
      value >= (rule.minimum ?? Number.NEGATIVE_INFINITY) &&
      value <= (rule.maximum ?? Number.POSITIVE_INFINITY)
    );
  }
  if (typeof value !== "string") return false;
  const codePoints = [...value].length;
  if (codePoints < (rule.minLength ?? 0) || codePoints > (rule.maxLength ?? Infinity)) {
    return false;
  }
  if (rule.pattern !== undefined && !new RegExp(rule.pattern, "u").test(value)) return false;
  const negativeRules = [rule.not, ...(rule.allOf ?? []).map((item) => item.not)].filter(
    (item): item is { pattern: string } => item !== undefined,
  );
  return !negativeRules.some((negative) => new RegExp(negative.pattern, "u").test(value));
}

function npmPackBasenameV1(schema: HandoffSchema, name: string, version: string): string {
  if (name !== "kaji-sdk") throw new Error("unexpected package name");
  if (!independentAliasValid(schema, "semver", version)) {
    throw new Error("invalid package version");
  }
  return `${name}-${version}.tgz`;
}

describe("TypeScript consumer handoff schema", () => {
  it("ships a valid byte-identical Draft 2020-12 package mirror", () => {
    const packaged = readFileSync(resolve(handoffSchemaRelative));
    const canonical = readFileSync(resolve(canonicalHandoffSchemaRelative));
    expect(packaged.equals(canonical)).toBe(true);
    expect(() =>
      new Ajv2020({ allErrors: true, strict: false }).compile(handoffSchema()),
    ).not.toThrow();
  });

  it("shares exact dependency-free SemVer, basename, and alias fixtures", () => {
    const schema = handoffSchema();
    const semver = compileHandoffFragment(schema, "semver");
    const basename = compileHandoffFragment(schema, "basename");

    for (const testCase of schema["x-kajiConformance"].semverBasename) {
      expect(semver(testCase.value), testCase.value).toBe(testCase.valid);
      if (testCase.valid) {
        expect(independentAliasValid(schema, "semver", testCase.value)).toBe(true);
        const derived = npmPackBasenameV1(schema, "kaji-sdk", testCase.value);
        expect(derived).toBe(testCase.basename);
        expect(basename(derived), derived).toBe(true);
      } else {
        expect(testCase.basename).toBeUndefined();
        expect(independentAliasValid(schema, "semver", testCase.value)).toBe(false);
        expect(() => npmPackBasenameV1(schema, "kaji-sdk", testCase.value)).toThrow(
          "invalid package version",
        );
      }
    }

    for (const [definition, cases] of Object.entries(schema["x-kajiConformance"].aliases)) {
      const validate = compileHandoffFragment(schema, definition);
      for (const testCase of cases) {
        expect(validate(testCase.value), `${definition}: ${JSON.stringify(testCase.value)}`).toBe(
          testCase.valid,
        );
        expect(independentAliasValid(schema, definition, testCase.value)).toBe(testCase.valid);
      }
    }

    const tagName = compileHandoffFragment(schema, "tagName");
    for (const testCase of schema["x-kajiConformance"].tagSourceRefs) {
      expect(tagName(testCase.tag), testCase.tag).toBe(testCase.valid);
      if (testCase.valid) expect(`refs/tags/${testCase.tag}`).toBe(testCase.ref);
    }

    const signerWorkflowIdentity = compileHandoffFragment(schema, "signerWorkflowIdentity");
    for (const testCase of schema["x-kajiConformance"].signerWorkflowIdentities) {
      expect(signerWorkflowIdentity(testCase.value)).toBe(testCase.schemaValid);
      const canonicalRef = `${testCase.value.repository}/${testCase.value.filePath}@${testCase.value.digest}`;
      const relationValid = testCase.schemaValid && testCase.value.ref === canonicalRef;
      expect(relationValid).toBe(testCase.relationValid);
    }
  });
});

describe("release redaction boundaries", () => {
  it.each(["tests/integration/openai-tools.test.ts", "tests/integration/anthropic-live.test.ts"])(
    "keeps %s on the stable event committer path",
    (relativePath) => {
      const source = readFileSync(resolve(relativePath), "utf8");

      expect(source).not.toContain("import { EventBus }");
      expect(source).not.toMatch(/\.build\(\{[^}]*\bbus:/s);
      expect(source).toMatch(/\.build\(\{\s*store(?:\s*:|\s*\})/s);
    },
  );

  it("keeps OAuth and Keychain production boundaries fixed and shell-free", async () => {
    const oauthSource = readFileSync(resolve("src/auth/oauth.ts"), "utf8");
    const keychainSource = readFileSync(resolve("src/auth/keychain.ts"), "utf8");

    expect(oauthSource).toContain("https://accounts.google.com/o/oauth2/v2/auth");
    expect(oauthSource).toContain("https://oauth2.googleapis.com/token");
    expect(oauthSource).toContain("https://oauth2.googleapis.com/revoke");
    expect(oauthSource).not.toMatch(/authorizationEndpoint|tokenEndpoint|revocationEndpoint/);
    expect(keychainSource).toContain('const SECURITY = "/usr/bin/security"');
    expect(keychainSource).toContain("shell: false");
    expect(keychainSource).toContain('new TextDecoder("utf-8", { fatal: true })');
    expect(keychainSource).not.toContain("shell: true");
    expect(keychainSource).not.toMatch(/\bexec(?:File)?\s*\(/);

    const publicAuth = await import("@/auth");
    expect(Object.keys(publicAuth).sort()).toEqual([
      "GoogleOAuthClient",
      "MacOSKeychainTokenStorage",
      "canonicalOAuthCredentialJson",
      "snapshotOAuthCredentialRecord",
    ]);
  });

  it("redacts provider details from public exception strings", () => {
    const secret = "sk-provider-key-secret";
    const error = providerAPIErrorFromUnknown(
      "openai",
      new Error(`request failed with ${secret}`),
      "request",
    );

    expect(String(error)).toBe("ProviderAPIError: openai request failed");
    expect(String(error)).not.toContain(secret);
    expect(error.cause).toBeUndefined();
    expect("responseText" in error).toBe(false);
    expect(inspect(error, { depth: 5 })).not.toContain(secret);
    expect(JSON.stringify(error)).not.toContain(secret);
  });

  it("redacts error details before handing them to trace sinks", () => {
    const recorded: unknown[] = [];
    const sink: TraceSink = {
      startSpan: () => ({
        setAttribute() {},
        recordError(error) {
          recorded.push(error);
        },
        end() {},
      }),
    };
    const secret = "sk-trace-secret";

    startSpan(sink, "kaji.turn").recordError(new Error(secret));

    expect(recorded).toHaveLength(1);
    expect(String(recorded[0])).toBe("Error: Error: details redacted");
    expect(String(recorded[0])).not.toContain(secret);
  });

  it("redacts provider, tool, and start-callback failures at the trace boundary", async () => {
    const recorded: unknown[] = [];
    const sink: TraceSink = {
      startSpan: () => ({
        setAttribute() {},
        recordError(error) {
          recorded.push(error);
        },
        end() {},
      }),
    };
    const providerFailure = new Error("sk-provider-runtime-secret");
    class FailingProvider {
      readonly providerFamily = "custom" as const;

      async generate(): Promise<never> {
        throw providerFailure;
      }

      // oxlint-disable-next-line require-yield -- the failure occurs when the stream is consumed.
      async *generateStream(): AsyncGenerator<never> {
        throw providerFailure;
      }
    }

    const runtime = new AgentBuilder().provider(new FailingProvider()).traceSink(sink).build();
    await expect(runtime.turn("hello")).rejects.toBe(providerFailure);

    const context = (toolCallId: string) => ({
      principalId: "principal",
      sessionId: `session-${toolCallId}`,
      turnId: "turn",
      requestId: "request",
      traceId: "trace",
      toolCallId,
      idempotencyKey: `session-${toolCallId}:${toolCallId}`,
      signal: new AbortController().signal,
      metadata: {},
    });
    const toolFailure = new Error("sk-tool-runtime-secret");
    const controller = new ToolExecutionController({ traceSink: sink });
    const failed = await controller.execute({
      name: "failing-tool",
      args: {},
      context: context("tool-failure"),
      exclusive: false,
      onStarted: async () => {},
      execute: async () => {
        throw toolFailure;
      },
    });
    expect(failed).toMatchObject({ status: "failed", error: { outcome: "unknown" } });
    if (failed.status !== "failed") throw new Error("expected a failed tool outcome");
    expect(failed.error.cause).toBeUndefined();
    expect(inspect(failed, { depth: 5 })).not.toContain(toolFailure.message);

    const startFailure = new Error("sk-start-callback-secret");
    await expect(
      controller.execute({
        name: "start-failure",
        args: {},
        context: context("start-failure"),
        exclusive: false,
        onStarted: async () => {
          throw startFailure;
        },
        execute: async () => ({ ok: true }),
      }),
    ).rejects.toBe(startFailure);

    const rendered = recorded.map(String).join(" ");
    expect(rendered).not.toContain(providerFailure.message);
    expect(rendered).not.toContain(toolFailure.message);
    expect(rendered).not.toContain(startFailure.message);
    expect(rendered).toContain("details redacted");
  });

  it("redacts late durable-claim cleanup failures", async () => {
    const secret = "sk-late-cleanup-secret";
    const backing = new InMemoryToolIdempotencyLedger();
    let releaseClaim!: () => void;
    const gate = new Promise<void>((resolve) => {
      releaseClaim = resolve;
    });
    let entered!: () => void;
    const claimEntered = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let attempted!: () => void;
    const cleanupAttempted = new Promise<void>((resolve) => {
      attempted = resolve;
    });
    const ledger: ToolIdempotencyLedger = {
      async claim(...args) {
        entered();
        await gate;
        return backing.claim(...args);
      },
      complete: (...args) => backing.complete(...args),
      async retryableFailure() {
        attempted();
        throw new Error(secret);
      },
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
    };
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const controller = new ToolExecutionController({ ledger, limits: { timeoutMs: 1 } });
    const abort = new AbortController();
    const pending = controller.execute({
      name: "late-claim",
      args: {},
      context: {
        principalId: "principal",
        sessionId: "session",
        turnId: "turn",
        requestId: "request",
        traceId: "trace",
        toolCallId: "call",
        idempotencyKey: "session:call",
        signal: abort.signal,
        metadata: {},
      },
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({}),
    });

    await claimEntered;
    await expect(pending).resolves.toMatchObject({ status: "failed" });
    releaseClaim();
    await cleanupAttempted;
    await Promise.resolve();

    expect(JSON.stringify(logged.mock.calls)).not.toContain(secret);
    expect(logged).toHaveBeenCalledWith(
      "[kaji] late claim cleanup failed (Error; details redacted)",
    );
    logged.mockRestore();
  });
});

type PermissionMap = Record<string, string>;
type WorkflowStep = {
  id?: string;
  name?: string;
  uses?: string;
  run?: string;
  with?: Record<string, unknown>;
  env?: Record<string, unknown>;
  if?: unknown;
  "continue-on-error"?: unknown;
};
type WorkflowJob = {
  name?: string;
  uses?: string;
  "runs-on"?: string | string[];
  "timeout-minutes"?: number;
  if?: unknown;
  "continue-on-error"?: unknown;
  strategy?: Record<string, unknown>;
  permissions?: PermissionMap;
  env?: Record<string, unknown>;
  environment?: string;
  needs?: string | string[];
  defaults?: { run?: { "working-directory"?: string } };
  outputs?: Record<string, unknown>;
  with?: Record<string, unknown>;
  secrets?: Record<string, unknown> | "inherit";
  steps?: WorkflowStep[];
};
type Workflow = {
  name?: string;
  on?: Record<string, unknown>;
  permissions?: PermissionMap;
  env?: Record<string, unknown>;
  jobs?: Record<string, WorkflowJob>;
};

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const workflowFiles = [
  "python.test.yml",
  "python.lint.yml",
  "python.format.yml",
  "ts.test.yml",
  "ts.lint.yml",
  "ts.format.yml",
  "ast-grep.test.yml",
  "kaji.benchmark.yml",
  "kaji.performance.yml",
  "kaji.gate.yml",
  "kaji.rehearsal.yml",
  "kaji.publish.yml",
  "kaji.handoff.trusted.yml",
] as const;
const expectedKajiWorkflowNames = {
  "kaji.benchmark.yml": "benchmark / kaji",
  "kaji.performance.yml": "performance / kaji",
  "kaji.gate.yml": "gate / kaji",
  "kaji.rehearsal.yml": "rehearsal / kaji",
  "kaji.publish.yml": "publish / kaji",
  "kaji.handoff.trusted.yml": "handoff / kaji",
} as const;
type KajiWorkflowFile = keyof typeof expectedKajiWorkflowNames;
const expectedKajiJobNames = {
  "kaji.benchmark.yml": {
    "release-artifacts": "release artifacts",
    performance: "performance evidence",
  },
  "kaji.performance.yml": {
    "candidate-artifact": "candidate artifact",
    "paired-replica": "paired benchmark ${{ matrix.replica }}",
    "paired-aggregate": "paired benchmark aggregate",
    soak: "30-minute soak",
    "performance-evidence": "performance evidence",
  },
  "kaji.gate.yml": {
    "kaji-beta-pr-gate": "beta release gate",
  },
  "kaji.rehearsal.yml": {
    "offline-release": "offline release",
    performance: "performance evidence",
    "python-compat": "Python ${{ matrix.python-version }} compatibility",
    "node-compat": "Node ${{ matrix.node-version }} compatibility",
    "typescript-onboarding-archive-calibration": "TypeScript onboarding archive calibration",
    "typescript-onboarding-evidence": "TypeScript onboarding evidence",
    "keyed-proof": "keyed provider proof",
    "candidate-evidence": "release candidate evidence",
  },
  "kaji.publish.yml": {
    "verify-tag": "verify release tag",
    "offline-gates": "offline release gates",
    performance: "performance evidence",
    "python-compat": "Python ${{ matrix.python-version }} compatibility",
    "node-compat": "Node ${{ matrix.node-version }} compatibility",
    "typescript-onboarding-archive-calibration": "TypeScript onboarding archive calibration",
    "typescript-onboarding-evidence": "TypeScript onboarding evidence",
    "keyed-proof": "keyed provider proof",
    "supply-chain": "supply-chain evidence",
    "registry-preflight": "registry preflight",
    "publish-npm": "publish npm package",
    "publication-status": "verify publication",
    "publication-incident": "publication incident",
    "release-evidence": "release evidence",
  },
  "kaji.handoff.trusted.yml": {
    stage: "trusted source, stage, and artifact contract",
    node: "Node ${{ matrix.node }} handoff receipt",
    finalize: "finalize and attest consumer handoff",
  },
} as const satisfies Record<KajiWorkflowFile, Readonly<Record<string, string>>>;
const sharedBetaPaths = [
  "kaji/contracts/**",
  "kaji/scripts/**",
  "kaji/benchmarks/**",
  "kaji/RELEASE_MATRIX.md",
  "docs/kaji/**",
  "tools/ast-grep/**",
  "sgconfig.yml",
  "package.json",
  "bun.lock",
  "kaji/uv.lock",
  ...workflowFiles
    .filter((name) => name !== "kaji.handoff.trusted.yml")
    .map((name) => `.github/workflows/${name}`),
];
const reviewedActionPins: Record<string, string> = {
  "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
  "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
  "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
  "actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093",
  "actions/github-script": "f28e40c7f34bde8b3046d885e986cb6290c5673b",
  "actions/attest-build-provenance": "e8998f949152b193b063cb0ec769d69d929409be",
  "anchore/sbom-action": "fbfd9c6c189226748411491745178e0c2017392d",
  "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
  "astral-sh/setup-uv": "caf0cab7a618c569241d31dcd442f54681755d39",
  "oven-sh/setup-bun": "0c5077e51419868618aeaa5fe8019c62421857d6",
  "actions/cache": "0057852bfaa89a56745cba8c7296529d2fc39830",
};
const reviewedActionReleases: Record<string, string> = {
  "actions/checkout": "v4.3.1",
  "actions/setup-node": "v4.4.0",
  "actions/upload-artifact": "v4.6.2",
  "actions/download-artifact": "v4.3.0",
  "actions/github-script": "v7.1.0",
  "actions/attest-build-provenance": "v2.4.0",
  "anchore/sbom-action": "v0.20.10",
  "actions/setup-python": "v5.6.0",
  "astral-sh/setup-uv": "v3.2.4",
  "oven-sh/setup-bun": "v2.2.0",
  "actions/cache": "v4.3.0",
};
const readOnlyPermissions: PermissionMap = { contents: "read" };
const expectedJobPermissionDeclarations: Partial<
  Record<(typeof workflowFiles)[number], Record<string, PermissionMap>>
> = {
  "kaji.benchmark.yml": {
    performance: { actions: "read", contents: "read" },
  },
  "kaji.performance.yml": {
    "candidate-artifact": { actions: "read", contents: "read" },
    "paired-replica": { actions: "read", contents: "read" },
  },
  "kaji.rehearsal.yml": {
    performance: { actions: "read", contents: "read" },
    "node-compat": { actions: "read", contents: "read" },
    "typescript-onboarding-archive-calibration": { actions: "read", contents: "read" },
    "typescript-onboarding-evidence": { actions: "read", contents: "read" },
    "candidate-evidence": { actions: "read", contents: "read" },
  },
  "kaji.publish.yml": {
    "verify-tag": { actions: "read", contents: "read" },
    "offline-gates": { actions: "read", contents: "read" },
    performance: { actions: "read", contents: "read" },
    "node-compat": { actions: "read", contents: "read" },
    "typescript-onboarding-archive-calibration": { actions: "read", contents: "read" },
    "typescript-onboarding-evidence": { actions: "read", contents: "read" },
    "supply-chain": {
      actions: "read",
      contents: "read",
      "id-token": "write",
      attestations: "write",
    },
    "publish-npm": { actions: "read", contents: "read", "id-token": "write" },
    "publication-status": { actions: "read", contents: "read", attestations: "read" },
    "publication-incident": { contents: "write" },
    "release-evidence": { actions: "read", contents: "write" },
  },
  "kaji.handoff.trusted.yml": {
    stage: { contents: "read" },
    node: { contents: "read" },
    finalize: {
      contents: "read",
      "id-token": "write",
      attestations: "write",
    },
  },
};
const requiredGateCommand =
  "uv run --project kaji --no-sync python kaji/scripts/beta_release_check.py --gate";

function readYaml(
  relativePath: string,
  root = repositoryRoot,
): {
  source: string;
  value: Record<string, unknown>;
} {
  const source = readFileSync(resolve(root, relativePath), "utf8");
  const parsed = spawnSync(
    "bun",
    [
      "-e",
      "const source = await Bun.stdin.text(); process.stdout.write(JSON.stringify(Bun.YAML.parse(source)));",
    ],
    { encoding: "utf8", input: source },
  );
  if (parsed.status !== 0) {
    throw new Error(`Bun.YAML.parse failed for ${relativePath}: ${parsed.stderr}`);
  }
  return { source, value: JSON.parse(parsed.stdout) as Record<string, unknown> };
}

function readWorkflow(name: (typeof workflowFiles)[number]): {
  source: string;
  workflow: Workflow;
} {
  const { source, value } = readYaml(`.github/workflows/${name}`);
  return { source, workflow: value as Workflow };
}

function bunExecutableFromParentPath(): string {
  if (basename(process.execPath) === "bun") return process.execPath;
  const lookup = spawnSync("sh", ["-c", "command -v bun"], {
    encoding: "utf8",
    env: process.env,
  });
  if (lookup.status !== 0 || lookup.stdout.trim() === "") {
    throw new Error(`Bun is unavailable on the parent PATH: ${lookup.stderr}`);
  }
  return lookup.stdout.trim();
}

function effectivePermissions(workflow: Workflow, job: WorkflowJob): PermissionMap {
  return job.permissions ?? workflow.permissions ?? {};
}

function effectiveEnvironment(workflow: Workflow, job: WorkflowJob): Record<string, unknown> {
  return { ...workflow.env, ...job.env };
}

function dependencyClosure(workflow: Workflow, jobId: string): Set<string> {
  const closure = new Set<string>();
  const pending = [jobId];
  while (pending.length > 0) {
    const current = pending.pop()!;
    const needs = workflow.jobs?.[current]?.needs;
    for (const dependency of typeof needs === "string" ? [needs] : (needs ?? [])) {
      if (closure.has(dependency)) continue;
      closure.add(dependency);
      pending.push(dependency);
    }
  }
  return closure;
}

function workflowSteps(value: Record<string, unknown>): WorkflowStep[] {
  const workflow = value as Workflow;
  const jobSteps = Object.values(workflow.jobs ?? {}).flatMap((job) => [
    ...(job.uses ? [{ uses: job.uses }] : []),
    ...(job.steps ?? []),
  ]);
  const compositeSteps = (value.runs as { steps?: WorkflowStep[] } | undefined)?.steps ?? [];
  return [...jobSteps, ...compositeSteps];
}

function actionSteps(value: Record<string, unknown>): WorkflowStep[] {
  return workflowSteps(value).filter((step) => step.uses !== undefined);
}

function isTrustedHandoffCall(reference: string): boolean {
  return /^enkyuan\/alloy\/\.github\/workflows\/kaji\.handoff\.trusted\.yml@[0-9a-f]{40}$/.test(
    reference,
  );
}

function localActionDocument(root: string, reference: string): string {
  const target = resolve(root, reference);
  const fromRoot = relative(root, target);
  if (fromRoot === ".." || fromRoot.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`)) {
    throw new Error(`local action escapes the repository: ${reference}`);
  }
  if (
    reference.startsWith("./.github/workflows/") &&
    /\.ya?ml$/u.test(reference) &&
    existsSync(target)
  ) {
    return fromRoot.replaceAll("\\", "/");
  }
  const candidates = [resolve(target, "action.yml"), resolve(target, "action.yaml")].filter(
    existsSync,
  );
  if (candidates.length !== 1) {
    throw new Error(`local action must resolve to exactly one action file: ${reference}`);
  }
  return relative(root, candidates[0]!).replaceAll("\\", "/");
}

function assertReviewedActionDocuments(entryPaths: string[], root = repositoryRoot): Set<string> {
  const visited = new Set<string>();
  const visiting = new Set<string>();

  const visit = (relativePath: string): void => {
    if (visiting.has(relativePath)) {
      throw new Error(`local action cycle: ${relativePath}`);
    }
    if (visited.has(relativePath)) return;
    visiting.add(relativePath);

    const { source, value } = readYaml(relativePath, root);
    const steps = actionSteps(value);
    const reusableCalls = steps.filter((step) => isTrustedHandoffCall(step.uses!));
    for (const step of reusableCalls) {
      expect(step.uses).not.toContain("@main");
      expect(step.uses).not.toContain("${{");
    }
    const externalSteps = steps.filter(
      (step) => !step.uses!.startsWith("./") && !isTrustedHandoffCall(step.uses!),
    );
    for (const step of externalSteps) {
      const [action, revision] = step.uses!.split("@");
      expect(revision, `${relativePath}:${step.uses}`).toMatch(/^[0-9a-f]{40}$/);
      expect(revision, `${relativePath}:${step.uses}`).toBe(reviewedActionPins[action!]);
    }
    const annotatedExternalReferences = [
      ...source.matchAll(/^\s*(?:-\s*)?uses:\s+([^\s#]+)(?:\s+#\s+([^\s]+))?\s*$/gm),
    ].filter(([, reference]) => !reference!.startsWith("./") && !isTrustedHandoffCall(reference!));
    expect(
      annotatedExternalReferences.map(([, reference]) => reference),
      `${relativePath}:external action annotations`,
    ).toEqual(externalSteps.map((step) => step.uses));
    for (const [, reference, release] of annotatedExternalReferences) {
      const action = reference!.split("@", 1)[0]!;
      expect(release, `${relativePath}:${reference}`).toBe(reviewedActionReleases[action]);
    }

    for (const step of steps.filter((candidate) => candidate.uses!.startsWith("./"))) {
      visit(localActionDocument(root, step.uses!));
    }
    visiting.delete(relativePath);
    visited.add(relativePath);
  };

  for (const entryPath of entryPaths) visit(entryPath);
  return visited;
}

function isMapping(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertProtectionReadyGate(workflow: Workflow): void {
  expect(isMapping(workflow.on), "workflow triggers must be a mapping").toBe(true);
  const triggers = workflow.on!;
  const pullRequest = triggers.pull_request;

  expect(workflow.name).toBe("gate / kaji");
  expect(triggers).not.toHaveProperty("pull_request_target");
  expect(triggers).toHaveProperty("pull_request");
  expect(
    pullRequest === null || isMapping(pullRequest),
    "pull_request must be null or an unfiltered mapping",
  ).toBe(true);
  if (isMapping(pullRequest)) {
    expect(Object.keys(pullRequest), "pull_request mapping must be unfiltered").toEqual([]);
  }
  expect(workflow.permissions).toEqual({ contents: "read" });

  const jobs = Object.entries(workflow.jobs ?? {});
  expect(jobs).toHaveLength(1);
  const [jobId, job] = jobs[0]!;
  expect(jobId).toBe("kaji-beta-pr-gate");
  expect(job.name).toBe("beta release gate");
  expect(job.strategy).toBeUndefined();
  expect(job.if).toBeUndefined();
  expect(job["continue-on-error"] ?? false).toBe(false);
  expect(job["timeout-minutes"]).toBeGreaterThan(0);
  expect(job.defaults?.run?.["working-directory"]).toBe(".");
  expect(effectivePermissions(workflow, job)).toEqual({ contents: "read" });

  const steps = job.steps ?? [];
  expect(steps).toHaveLength(5);
  for (const [index, step] of steps.entries()) {
    expect(step.if, `gate step ${index} must execute normally`).toBeUndefined();
    expect(step["continue-on-error"] ?? false, `gate step ${index} must fail closed`).toBe(false);
  }
  expect(steps.slice(0, 4).map((step) => step.uses)).toEqual([
    `actions/checkout@${reviewedActionPins["actions/checkout"]}`,
    `actions/setup-node@${reviewedActionPins["actions/setup-node"]}`,
    "./.github/actions/setup-python-uv",
    "./.github/actions/setup-bun-cache",
  ]);

  const checkout = steps[0];
  expect(checkout?.uses).toBe(`actions/checkout@${reviewedActionPins["actions/checkout"]}`);
  expect(steps.find((step) => step.uses?.startsWith("actions/setup-node@"))?.with).toEqual({
    "node-version": "24",
  });
  expect(
    steps.find((step) => step.uses === "./.github/actions/setup-python-uv")?.with,
  ).toMatchObject({ "working-directory": "kaji", "sync-args": "--frozen" });
  expect(
    steps.find((step) => step.uses === "./.github/actions/setup-bun-cache")?.with,
  ).toMatchObject({
    "working-directory": ".",
    "bun-version": "1.3.11",
    "install-args": "--frozen-lockfile",
  });
  expect(steps.flatMap((step) => (step.run ? [step.run.trim()] : []))).toEqual([
    requiredGateCommand,
  ]);
}

function assertNarrowPermissions(name: (typeof workflowFiles)[number], workflow: Workflow): void {
  expect(workflow.permissions, `${name}:workflow permissions`).toEqual(readOnlyPermissions);
  const declarations = expectedJobPermissionDeclarations[name] ?? {};
  for (const [jobId, job] of Object.entries(workflow.jobs ?? {})) {
    const expectedDeclaration = declarations[jobId];
    if (expectedDeclaration === undefined) {
      expect(job.permissions, `${name}:${jobId}:job permissions`).toBeUndefined();
    } else {
      expect(job.permissions, `${name}:${jobId}:job permissions`).toEqual(expectedDeclaration);
    }
    expect(effectivePermissions(workflow, job), `${name}:${jobId}:effective permissions`).toEqual(
      expectedDeclaration ?? readOnlyPermissions,
    );
  }
}

function writeFixture(root: string, relativePath: string, source: string): void {
  const path = resolve(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, source);
}

function withTemporaryRepository(run: (root: string) => void): void {
  const root = mkdtempSync(resolve(tmpdir(), "kaji-workflow-contract-"));
  try {
    run(root);
  } finally {
    rmSync(root, { force: true, recursive: true });
  }
}

function gateJob(workflow: Workflow): WorkflowJob {
  const job = workflow.jobs?.["kaji-beta-pr-gate"];
  if (!job) throw new Error("missing Kaji beta release gate job");
  return job;
}

function workflowStep(job: WorkflowJob, name: string): WorkflowStep {
  const step = (job.steps ?? []).find((candidate) => candidate.name === name);
  if (step === undefined) throw new Error(`missing workflow step: ${name}`);
  return step;
}

function literalPathLines(value: unknown): string[] {
  if (typeof value !== "string") throw new Error("workflow path input must be a string");
  return value
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

function assertTrustedHandoffWorkflow(workflow: Workflow, source: string): void {
  expect(workflow.name).toBe("handoff / kaji");
  expect(workflow.permissions).toEqual({ contents: "read" });
  expect(workflow.env).toBeUndefined();
  const call = workflow.on?.workflow_call as
    | {
        inputs?: Record<string, unknown>;
        secrets?: Record<string, unknown>;
      }
    | undefined;
  expect(call?.inputs).toEqual({
    mode: { required: true, type: "string" },
    tag_name: { required: false, type: "string", default: "" },
  });
  expect(call?.secrets).toEqual({ node_auth_token: { required: false } });
  expect(source).not.toContain("secrets: inherit");
  expect(source).not.toContain("secrets.github_token");
  expect(source).not.toContain("expected_sha");

  const jobs = workflow.jobs ?? {};
  expect(Object.keys(jobs).sort()).toEqual(["finalize", "node", "stage"]);
  const stage = jobs.stage!;
  const node = jobs.node!;
  const finalize = jobs.finalize!;
  expect(stage["timeout-minutes"]).toBe(90);
  expect(node["timeout-minutes"]).toBe(30);
  expect(finalize["timeout-minutes"]).toBe(30);
  expect(stage.permissions).toEqual({ contents: "read" });
  expect(node.permissions).toEqual({ contents: "read" });
  expect(finalize.permissions).toEqual({
    contents: "read",
    "id-token": "write",
    attestations: "write",
  });
  expect(stage.outputs).toEqual({
    "source-commit": "${{ steps.stage.outputs.source-commit }}",
    "artifact-filename": "${{ steps.stage.outputs.artifact-filename }}",
    "artifact-sha256": "${{ steps.stage.outputs.artifact-sha256 }}",
    "preflight-sha256": "${{ steps.stage.outputs.preflight-sha256 }}",
  });
  expect(node.needs).toBe("stage");
  expect(finalize.needs).toEqual(["stage", "node"]);
  expect(node.outputs).toBeUndefined();
  expect(node.strategy).toEqual({ "fail-fast": false, matrix: { node: [22, 24] } });
  const conditionalSteps: Array<{ jobId: string; name: string | undefined; condition: unknown }> =
    [];
  for (const [jobId, job] of Object.entries(jobs)) {
    expect(job["continue-on-error"], `${jobId}: job continue-on-error`).toBeUndefined();
    expect(job.if, `${jobId}: job condition`).toBeUndefined();
    for (const step of job.steps ?? []) {
      expect(
        [undefined, false],
        `${jobId}:${step.name ?? step.uses}: step continue-on-error`,
      ).toContain(step["continue-on-error"]);
      if (step.if !== undefined)
        conditionalSteps.push({ jobId, name: step.name, condition: step.if });
    }
  }
  expect(conditionalSteps).toEqual([
    {
      jobId: "stage",
      name: "Preflight internal-evaluation handoff",
      condition: "${{ inputs.mode == 'internal-evaluation' }}",
    },
    {
      jobId: "stage",
      name: "Preflight release handoff",
      condition: "${{ inputs.mode == 'release' }}",
    },
  ]);

  const expectedGuardEnvironment = {
    CALLED_WORKFLOW_REPOSITORY: "${{ job.workflow_repository }}",
    CALLED_WORKFLOW_FILE_PATH: "${{ job.workflow_file_path }}",
    CALLED_WORKFLOW_SHA: "${{ job.workflow_sha }}",
    CALLED_WORKFLOW_REF: "${{ job.workflow_ref }}",
    CALLER_REPOSITORY: "${{ github.repository }}",
    CANDIDATE_SHA: "${{ github.sha }}",
    CANDIDATE_REF: "${{ github.ref }}",
    HANDOFF_MODE: "${{ inputs.mode }}",
    HANDOFF_TAG_NAME: "${{ inputs.tag_name }}",
  };
  for (const job of [stage, node, finalize]) {
    const guard = job.steps?.[0];
    expect(guard?.name).toBe("Guard called workflow identity and candidate ref");
    expect(guard?.env).toEqual(expectedGuardEnvironment);
    expect(guard?.run).toContain('test "$CALLED_WORKFLOW_REPOSITORY" = "enkyuan/alloy"');
    expect(guard?.run).toContain(
      'test "$CALLED_WORKFLOW_FILE_PATH" = ".github/workflows/kaji.handoff.trusted.yml"',
    );
    expect(guard?.run).toContain('test "$CALLER_REPOSITORY" = "enkyuan/alloy"');
    expect(guard?.run).toContain("${#CALLED_WORKFLOW_SHA}");
    expect(guard?.run).toContain(
      "$CALLED_WORKFLOW_REPOSITORY/$CALLED_WORKFLOW_FILE_PATH@$CALLED_WORKFLOW_SHA",
    );
    expect(guard?.run).toContain('test "$CANDIDATE_REF" = "refs/heads/main"');
    expect(guard?.run).toContain('test "$CANDIDATE_REF" = "refs/tags/$HANDOFF_TAG_NAME"');
  }

  const checkoutPin = `actions/checkout@${reviewedActionPins["actions/checkout"]}`;
  const stageCheckouts = (stage.steps ?? []).filter((step) => step.uses === checkoutPin);
  expect(stageCheckouts.map((step) => step.with)).toEqual([
    {
      repository: "${{ job.workflow_repository }}",
      ref: "${{ job.workflow_sha }}",
      "fetch-depth": 0,
      "persist-credentials": false,
      path: "trusted",
    },
    {
      repository: "enkyuan/alloy",
      ref: "${{ github.sha }}",
      "fetch-depth": 0,
      "persist-credentials": false,
      path: "candidate",
    },
  ]);
  const nodeCheckouts = (node.steps ?? []).filter((step) => step.uses === checkoutPin);
  expect(nodeCheckouts).toHaveLength(1);
  expect(nodeCheckouts[0]?.with?.path).toBe("trusted");
  expect(JSON.stringify(node)).not.toContain('path":"candidate');
  const finalizeCheckouts = (finalize.steps ?? []).filter((step) => step.uses === checkoutPin);
  expect(finalizeCheckouts).toHaveLength(2);
  for (const checkout of [...stageCheckouts, ...nodeCheckouts, ...finalizeCheckouts]) {
    expect(checkout.with?.["fetch-depth"]).toBe(0);
    expect(checkout.with?.["persist-credentials"]).toBe(false);
  }
  expect(source).not.toMatch(/^\s*git\b[^\n]*\bfetch\b/gmu);
  for (const history of [
    workflowStep(stage, "Establish protected-main history and clean checkouts"),
    workflowStep(finalize, "Establish protected-main history and clean checkouts"),
  ]) {
    expect(history.run).not.toMatch(/^\s*git\b[^\n]*\bfetch\b/gmu);
    for (const fragment of [
      "for checkout in trusted candidate; do",
      `test "$(git -C "$checkout" rev-parse --is-shallow-repository)" = "false"`,
      `main_commit=$(git -C "$checkout" rev-parse --verify 'refs/remotes/origin/main^{commit}')`,
      'test "${#main_commit}" -eq 40',
      'case "$main_commit" in *[!0-9a-f]*) exit 1 ;; esac',
      `test "$(git -C "$checkout" cat-file -t "$main_commit")" = "commit"`,
      "status --porcelain --untracked-files=all",
    ]) {
      expect(history.run).toContain(fragment);
    }
  }

  const protectedBindings = Object.entries(jobs).flatMap(([jobId, job]) =>
    (job.steps ?? []).flatMap((step) => {
      const keys = Object.keys(step.env ?? {}).filter((key) =>
        ["GH_TOKEN", "GITHUB_TOKEN", "NODE_AUTH_TOKEN", "NPM_TOKEN"].includes(key),
      );
      return keys.length === 0 ? [] : [{ jobId, name: step.name, keys, env: step.env }];
    }),
  );
  expect(protectedBindings).toEqual([
    {
      jobId: "stage",
      name: "Verify candidate source and signatures with the trusted verifier",
      keys: ["GH_TOKEN"],
      env: expect.objectContaining({ GH_TOKEN: "${{ github.token }}" }),
    },
    {
      jobId: "stage",
      name: "Preflight release handoff",
      keys: ["NODE_AUTH_TOKEN"],
      env: expect.objectContaining({ NODE_AUTH_TOKEN: "${{ secrets.node_auth_token }}" }),
    },
  ]);
  const protectedTokenKeys = ["GH_TOKEN", "GITHUB_TOKEN", "NODE_AUTH_TOKEN", "NPM_TOKEN"];
  expect(workflow.env).toBeUndefined();
  for (const [jobId, job] of Object.entries(jobs)) {
    expect(
      protectedTokenKeys.filter((key) => Object.hasOwn(job.env ?? {}, key)),
      `${jobId}: job-scoped token environment`,
    ).toEqual([]);
  }
  const serializedWorkflow = JSON.stringify(workflow);
  expect(serializedWorkflow.match(/\$\{\{ github[.]token \}\}/gu)).toHaveLength(1);
  expect(serializedWorkflow.match(/\$\{\{ secrets[.]node_auth_token \}\}/gu)).toHaveLength(1);
  expect(workflowStep(stage, "Preflight internal-evaluation handoff").env).not.toHaveProperty(
    "NODE_AUTH_TOKEN",
  );
  expect(workflowStep(finalize, "Attest exact consumer handoff").with).not.toHaveProperty(
    "github-token",
  );

  const stageSteps = stage.steps ?? [];
  const stageIndex = stageSteps.findIndex((step) =>
    step.run?.includes("trusted/kaji/scripts/ts_handoff.py stage"),
  );
  const compositeIndex = stageSteps.findIndex((step) =>
    step.run?.includes("--for-handoff artifact-contract"),
  );
  expect(stageIndex).toBeGreaterThanOrEqual(0);
  expect(compositeIndex).toBe(stageIndex + 1);
  expect(stageSteps[stageIndex]?.run).not.toContain("npm pack");
  expect(stageSteps[compositeIndex]?.run).not.toContain("npm pack");
  expect(stageSteps[compositeIndex]?.run).not.toContain("bun run build");
  const stageRun = workflowStep(stage, "Stage the immutable package exactly once").run ?? "";
  for (const fragment of [
    `preflight_sha256=$(sha256sum "$preflight" | cut -d ' ' -f 1)`,
    'test "${#preflight_sha256}" -eq 64',
    'case "$preflight_sha256" in *[!0-9a-f]*) exit 1 ;; esac',
    'test "$stage_preflight_sha256" = "$preflight_sha256"',
    `printf 'preflight-sha256=%s\\n' "$preflight_sha256"`,
  ]) {
    expect(stageRun).toContain(fragment);
  }
  expect(stageRun).toMatch(
    /printf 'preflight-sha256=%s\\n' "\$preflight_sha256"\n\s*\} >>"\$GITHUB_OUTPUT"/u,
  );

  const uploadPin = `actions/upload-artifact@${reviewedActionPins["actions/upload-artifact"]}`;
  const allUploads = Object.values(jobs).flatMap((job) =>
    (job.steps ?? []).filter((step) => step.uses === uploadPin),
  );
  for (const upload of allUploads) {
    expect(upload.with?.["if-no-files-found"]).toBe("error");
    expect(upload.with?.["include-hidden-files"]).toBe(true);
    expect(upload.with).not.toHaveProperty("overwrite");
    expect(literalPathLines(upload.with?.path).every((path) => !path.includes("*"))).toBe(true);
  }
  const stageUpload = workflowStep(stage, "Upload exact stage transfer envelope");
  expect(stageUpload.with?.name).toBe("kaji-ts-handoff-stage-${{ env.KAJI_RELEASE_COMMIT }}");
  expect(literalPathLines(stageUpload.with?.path)).toEqual([
    ".artifacts/kaji-handoff-staging/",
    ".artifacts/kaji-handoff-inputs/source/",
    ".artifacts/kaji-handoff-inputs/preflight.json",
  ]);
  const compositeUpload = workflowStep(stage, "Upload artifact-contract receipt only");
  expect(literalPathLines(compositeUpload.with?.path)).toEqual([
    ".artifacts/kaji-handoff-inputs/receipts/artifact-contract.json",
  ]);
  const nodeUpload = workflowStep(node, "Upload one Node receipt only");
  expect(nodeUpload.with?.name).toBe(
    "kaji-ts-handoff-node-${{ matrix.node }}-${{ needs.stage.outputs.source-commit }}",
  );
  expect(literalPathLines(nodeUpload.with?.path)).toEqual([
    ".artifacts/kaji-handoff-inputs/receipts/node-${{ matrix.node }}.json",
  ]);

  const downloadPin = `actions/download-artifact@${reviewedActionPins["actions/download-artifact"]}`;
  const nodeDownloads = (node.steps ?? []).filter((step) => step.uses === downloadPin);
  expect(nodeDownloads.map((step) => step.with?.name)).toEqual([
    "kaji-ts-handoff-stage-${{ needs.stage.outputs.source-commit }}",
  ]);
  const finalDownloads = (finalize.steps ?? []).filter((step) => step.uses === downloadPin);
  expect(finalDownloads.map((step) => step.with?.name)).toEqual([
    "kaji-ts-handoff-stage-${{ needs.stage.outputs.source-commit }}",
    "kaji-ts-handoff-artifact-contract-${{ needs.stage.outputs.source-commit }}",
    "kaji-ts-handoff-node-22-${{ needs.stage.outputs.source-commit }}",
    "kaji-ts-handoff-node-24-${{ needs.stage.outputs.source-commit }}",
  ]);
  for (const download of [...nodeDownloads, ...finalDownloads]) {
    expect(download.with).not.toHaveProperty("pattern");
    expect(download.with).not.toHaveProperty("merge-multiple");
    expect(String(download.with?.name)).not.toContain("*");
  }
  expect(workflowStep(node, "Revalidate staged tarball and resolve Node binary").run).toContain(
    "sha256sum",
  );
  expect(
    workflowStep(finalize, "Revalidate transfer and select the recorded toolchain").run,
  ).toContain("sha256sum");
  const finalizeSteps = finalize.steps ?? [];
  const authenticateIndex = finalizeSteps.findIndex(
    (step) => step.name === "Authenticate exact preflight transfer",
  );
  const toolchainIndex = finalizeSteps.findIndex(
    (step) => step.name === "Revalidate transfer and select the recorded toolchain",
  );
  expect(authenticateIndex).toBeGreaterThanOrEqual(0);
  expect(authenticateIndex).toBeLessThan(toolchainIndex);
  const authenticate = workflowStep(finalize, "Authenticate exact preflight transfer");
  expect(authenticate.env).toEqual({
    EXPECTED_PREFLIGHT_SHA256: "${{ needs.stage.outputs.preflight-sha256 }}",
  });
  for (const fragment of [
    'test "${#EXPECTED_PREFLIGHT_SHA256}" -eq 64',
    'case "$EXPECTED_PREFLIGHT_SHA256" in *[!0-9a-f]*) exit 1 ;; esac',
    `test "$(sha256sum "$preflight" | cut -d ' ' -f 1)" = "$EXPECTED_PREFLIGHT_SHA256"`,
    `stage_preflight_sha256=$(jq -er '.preflightSha256 | select(test("^[0-9a-f]{64}$"))' "$stage")`,
    'test "$stage_preflight_sha256" = "$EXPECTED_PREFLIGHT_SHA256"',
  ]) {
    expect(authenticate.run).toContain(fragment);
  }
  for (const setupName of [
    "Set up finalizer Python",
    "Set up recorded uv",
    "Set up recorded Node",
    "Set up recorded Bun",
  ]) {
    const setupIndex = finalizeSteps.findIndex((step) => step.name === setupName);
    expect(setupIndex, setupName).toBeGreaterThan(authenticateIndex);
  }
  expect(workflowStep(finalize, "Guard exact stage transfer download").run).toContain(
    "expected_stage",
  );
  expect(workflowStep(finalize, "Guard artifact-contract download before merge").run).toContain(
    "artifact-contract.json",
  );
  expect(workflowStep(finalize, "Guard Node 22 download before merge").run).toContain(
    "node-22.json",
  );
  expect(workflowStep(finalize, "Guard Node 24 download before finalization").run).toContain(
    "node-24.json",
  );

  const consumerUpload = workflowStep(finalize, "Upload exact consumer handoff");
  const provenance = workflowStep(finalize, "Attest exact consumer handoff");
  const expectedSubjects = [
    ".artifacts/kaji-handoff/${{ env.KAJI_HANDOFF_TARBALL }}",
    ".artifacts/kaji-handoff/kaji-sdk.manifest.json",
    ".artifacts/kaji-handoff/kaji-ts-consumer-handoff-v1.schema.json",
  ];
  expect(literalPathLines(consumerUpload.with?.path)).toEqual(expectedSubjects);
  expect(literalPathLines(provenance.with?.["subject-path"])).toEqual(expectedSubjects);
  const retain = workflowStep(finalize, "Retain closed transport and provenance evidence");
  expect(retain.env).toMatchObject({
    KAJI_HANDOFF_ARTIFACT_ID: "${{ steps.handoff-upload.outputs.artifact-id }}",
    KAJI_HANDOFF_ACTION_DIGEST: "${{ steps.handoff-upload.outputs.artifact-digest }}",
    KAJI_ATTESTATION_ID: "${{ steps.handoff-provenance.outputs.attestation-id }}",
    KAJI_ATTESTATION_URL: "${{ steps.handoff-provenance.outputs.attestation-url }}",
    KAJI_ATTESTATION_BUNDLE: "${{ steps.handoff-provenance.outputs.bundle-path }}",
  });
  for (const fragment of [
    'case "$bundle_real" in "$runner_temp_real"/*)',
    "select(length == 1)",
    "(.subject | sort_by(.name)) == ([",
    'apiDigest: ("sha256:" + $actionDigest)',
    'attestations/" + $attestationId',
    "expected_evidence",
    "expected_receipt_set",
    "authorization[[:space:]]*:",
  ]) {
    expect(retain.run).toContain(fragment);
  }
  const evidenceUpload = workflowStep(finalize, "Upload separate operational handoff evidence");
  expect(evidenceUpload.with?.name).toBe(
    "kaji-ts-consumer-handoff-evidence-${{ env.KAJI_RELEASE_COMMIT }}",
  );
  expect(evidenceUpload.with?.name).not.toBe(consumerUpload.with?.name);
  expect(literalPathLines(evidenceUpload.with?.path)).not.toEqual(expectedSubjects);
  expect(source).not.toContain('acceptedHandoff":true');
}

function runTrustedHandoffGuard(
  guard: WorkflowStep,
  overrides: Record<string, string> = {},
): ReturnType<typeof spawnSync> {
  const calledSha = "a".repeat(40);
  return spawnSync("/bin/bash", ["-c", guard.run!], {
    encoding: "utf8",
    env: {
      ...process.env,
      CALLED_WORKFLOW_REPOSITORY: "enkyuan/alloy",
      CALLED_WORKFLOW_FILE_PATH: ".github/workflows/kaji.handoff.trusted.yml",
      CALLED_WORKFLOW_SHA: calledSha,
      CALLED_WORKFLOW_REF: `enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@${calledSha}`,
      CALLER_REPOSITORY: "enkyuan/alloy",
      CANDIDATE_SHA: "b".repeat(40),
      CANDIDATE_REF: "refs/heads/main",
      HANDOFF_MODE: "internal-evaluation",
      HANDOFF_TAG_NAME: "",
      ...overrides,
    },
  });
}

async function runCandidateArtifactBinding(runAttempt: string | undefined) {
  const step = readWorkflow("kaji.performance.yml").workflow.jobs?.[
    "candidate-artifact"
  ]?.steps?.find((candidate) => candidate.name === "Bind immutable candidate artifact metadata");
  if (typeof step?.with?.script !== "string") {
    throw new Error("candidate artifact binding script is missing");
  }

  const commit = "a".repeat(40);
  const artifactId = 123;
  const artifactDigest = "b".repeat(64);
  const getArtifact = vi.fn().mockResolvedValue({
    data: {
      id: artifactId,
      name: "kaji-beta-artifacts",
      expired: false,
      digest: `sha256:${artifactDigest}`,
      workflow_run: { id: 30117911132, head_sha: commit },
    },
  });
  const env: Record<string, string> = {
    CANDIDATE_ARTIFACT_ID: String(artifactId),
    CANDIDATE_ARTIFACT_DIGEST: artifactDigest,
    KAJI_RELEASE_COMMIT: commit,
    RUN_PAIRED: "true",
    RUN_SOAK: "true",
  };
  if (runAttempt !== undefined) env.RUN_ATTEMPT = runAttempt;

  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor as new (
    ...arguments_: string[]
  ) => (...values: unknown[]) => Promise<void>;
  const run = new AsyncFunction(
    "github",
    "context",
    "process",
    `"use strict";\n${step.with.script}`,
  );
  await run(
    { rest: { actions: { getArtifact } } },
    { repo: { owner: "enkyuan", repo: "alloy" }, runId: 30117911132 },
    { env },
  );
  return getArtifact;
}

function signedBetaFixture() {
  const tagName = "kaji-v0.2.0-beta.10";
  const tagObject = "a".repeat(40);
  const commit = "b".repeat(40);
  const taggerEmail = "release@example.com";
  const taggerName = "Kaji Release";
  const epoch = 1_786_000_000;
  const runId = 123_456;
  const candidateArtifactId = 234_567;
  const evidenceArtifactId = 345_678;
  const candidateArtifactDigest = `sha256:${"c".repeat(64)}`;
  const evidenceArtifactDigest = `sha256:${"d".repeat(64)}`;
  const releaseManifestSha256 = "e".repeat(64);
  const npmTarballSha256 = "f".repeat(64);
  const authorization = {
    candidateArtifact: {
      digest: candidateArtifactDigest,
      id: candidateArtifactId,
      name: "kaji-beta-artifacts",
    },
    commit,
    evidenceArtifact: {
      digest: evidenceArtifactDigest,
      id: evidenceArtifactId,
      name: "kaji-release-candidate-evidence",
    },
    npmTarball: {
      name: "kaji-sdk-0.2.0-beta.10.tgz",
      sha256: npmTarballSha256,
    },
    rehearsal: {
      runAttempt: 1,
      runId,
      workflowPath: ".github/workflows/kaji.rehearsal.yml",
      workflowSha: commit,
    },
    releaseManifestSha256,
    schemaVersion: "1.0.0",
  };
  const body = `${JSON.stringify(authorization)}\n`;
  const payload = [
    `object ${commit}`,
    "type commit",
    `tag ${tagName}`,
    `tagger ${taggerName} <${taggerEmail}> ${epoch} +0000`,
    "",
    body,
  ].join("\n");
  const artifact = (id: number, name: string, digest: string): Record<string, unknown> => ({
    id,
    name,
    digest,
    expired: false,
    size_in_bytes: 4096,
    url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${id}`,
    archive_download_url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${id}/zip`,
    workflow_run: {
      id: runId,
      head_branch: "main",
      head_sha: commit,
    },
  });
  return {
    expected: {
      tagName,
      tagObject,
      commit,
      taggerEmail,
      authorizationSha256: createHash("sha256").update(body, "ascii").digest("hex"),
      runId,
      candidateArtifactId,
      candidateArtifactDigest,
      evidenceArtifactId,
      evidenceArtifactDigest,
      releaseManifestSha256,
      npmTarballSha256,
    },
    ref: {
      ref: `refs/tags/${tagName}`,
      url: `https://api.github.com/repos/enkyuan/alloy/git/refs/tags/${tagName}`,
      object: { type: "tag", sha: tagObject },
    },
    tag: {
      sha: tagObject,
      url: `https://api.github.com/repos/enkyuan/alloy/git/tags/${tagObject}`,
      tag: tagName,
      object: { type: "commit", sha: commit },
      tagger: {
        name: taggerName,
        email: taggerEmail,
        date: new Date(epoch * 1000).toISOString(),
      },
      verification: {
        verified: true,
        reason: "valid",
        signature: "verified-signature",
        payload,
      },
    },
    run: {
      id: runId,
      run_attempt: 1,
      event: "workflow_dispatch",
      path: ".github/workflows/kaji.rehearsal.yml",
      head_branch: "main",
      head_sha: commit,
      status: "completed",
      conclusion: "success",
    },
    candidate: artifact(candidateArtifactId, "kaji-beta-artifacts", candidateArtifactDigest),
    evidence: artifact(
      evidenceArtifactId,
      "kaji-release-candidate-evidence",
      evidenceArtifactDigest,
    ),
    comparison: { merge_base_commit: { sha: commit } },
  };
}

type SignedBetaFixture = ReturnType<typeof signedBetaFixture>;

async function runSignedTagParser(
  mutate?: (fixture: SignedBetaFixture) => void,
  runAttempt: string | null = "1",
): Promise<Record<string, string>> {
  const fixture = signedBetaFixture();
  mutate?.(fixture);
  const processEnvironment: Record<string, string> = {
    EXPECTED_TAGGER_EMAIL: fixture.expected.taggerEmail,
  };
  if (runAttempt !== null) processEnvironment.RUN_ATTEMPT = runAttempt;
  const step = workflowStep(
    readWorkflow("kaji.publish.yml").workflow.jobs?.["verify-tag"]!,
    "Verify exact signed annotated beta tag",
  );
  const outputs: Record<string, string> = {};
  const summary = {
    addHeading: vi.fn(),
    addList: vi.fn(),
    write: vi.fn().mockResolvedValue(undefined),
  };
  summary.addHeading.mockReturnValue(summary);
  summary.addList.mockReturnValue(summary);
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor as new (
    ...arguments_: string[]
  ) => (...values: unknown[]) => Promise<void>;
  const run = new AsyncFunction(
    "github",
    "context",
    "core",
    "process",
    "createHash",
    `"use strict";\n${String(step.with?.script).replace(
      'const { createHash } = await import("node:crypto");',
      "",
    )}`,
  );
  await run(
    {
      rest: {
        git: {
          getRef: vi.fn().mockResolvedValue({ data: fixture.ref }),
          getTag: vi.fn().mockResolvedValue({ data: fixture.tag }),
        },
        actions: {
          getWorkflowRun: vi.fn().mockResolvedValue({ data: fixture.run }),
          getArtifact: vi.fn().mockImplementation(({ artifact_id }: { artifact_id: number }) =>
            Promise.resolve({
              data:
                artifact_id === fixture.expected.candidateArtifactId
                  ? fixture.candidate
                  : fixture.evidence,
            }),
          ),
        },
        repos: {
          compareCommits: vi.fn().mockResolvedValue({ data: fixture.comparison }),
        },
      },
    },
    {
      repo: { owner: "enkyuan", repo: "alloy" },
      eventName: "push",
      ref: "refs/tags/kaji-v0.2.0-beta.10",
      payload: {
        repository: {
          private: false,
          default_branch: "main",
        },
      },
    },
    {
      setOutput: (name: string, value: string) => {
        outputs[name] = String(value);
      },
      summary,
    },
    { env: processEnvironment },
    createHash,
  );
  return outputs;
}

function runCompositeTagReverification(
  mutate?: (fixture: SignedBetaFixture) => void,
): ReturnType<typeof spawnSync> & { endpoints: string[] } {
  const fixture = signedBetaFixture();
  mutate?.(fixture);
  const action = readYaml(".github/actions/verify-kaji-beta-tag/action.yml").value;
  const step = (action.runs as { steps: WorkflowStep[] }).steps[0]!;
  const root = mkdtempSync(join(tmpdir(), "kaji-signed-tag-action-"));
  const bin = join(root, "bin");
  const endpointLog = join(root, "endpoints.log");
  mkdirSync(bin);
  writeFileSync(endpointLog, "");
  for (const [name, value] of [
    ["ref.json", fixture.ref],
    ["tag.json", fixture.tag],
    ["run.json", fixture.run],
    ["candidate.json", fixture.candidate],
    ["evidence.json", fixture.evidence],
  ] as const) {
    writeFileSync(join(root, name), JSON.stringify(value));
  }
  const gh = join(bin, "gh");
  writeFileSync(
    gh,
    `#!/bin/bash
set -euo pipefail
for endpoint in "$@"; do :; done
printf '%s\n' "$endpoint" >>"$KAJI_ENDPOINT_LOG"
case "$endpoint" in
  */git/ref/tags/*) file=ref.json ;;
  */git/tags/*) file=tag.json ;;
  */actions/runs/*) file=run.json ;;
  */actions/artifacts/${fixture.expected.candidateArtifactId}) file=candidate.json ;;
  */actions/artifacts/${fixture.expected.evidenceArtifactId}) file=evidence.json ;;
  *) exit 64 ;;
esac
cat "$KAJI_FIXTURE_ROOT/$file"
`,
  );
  chmodSync(gh, 0o700);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        KAJI_ENDPOINT_LOG: endpointLog,
        KAJI_FIXTURE_ROOT: root,
        GITHUB_REPOSITORY: "enkyuan/alloy",
        EXPECTED_TAG: fixture.expected.tagName,
        EXPECTED_TAG_OBJECT: fixture.expected.tagObject,
        EXPECTED_COMMIT: fixture.expected.commit,
        EXPECTED_TAGGER_EMAIL: fixture.expected.taggerEmail,
        EXPECTED_AUTHORIZATION_SHA256: fixture.expected.authorizationSha256,
        EXPECTED_REHEARSAL_RUN_ID: String(fixture.expected.runId),
        EXPECTED_REHEARSAL_RUN_ATTEMPT: "1",
        EXPECTED_REHEARSAL_WORKFLOW_PATH: ".github/workflows/kaji.rehearsal.yml",
        EXPECTED_REHEARSAL_WORKFLOW_SHA: fixture.expected.commit,
        EXPECTED_CANDIDATE_ARTIFACT_ID: String(fixture.expected.candidateArtifactId),
        EXPECTED_CANDIDATE_ARTIFACT_NAME: "kaji-beta-artifacts",
        EXPECTED_CANDIDATE_ARTIFACT_DIGEST: fixture.expected.candidateArtifactDigest,
        EXPECTED_EVIDENCE_ARTIFACT_ID: String(fixture.expected.evidenceArtifactId),
        EXPECTED_EVIDENCE_ARTIFACT_NAME: "kaji-release-candidate-evidence",
        EXPECTED_EVIDENCE_ARTIFACT_DIGEST: fixture.expected.evidenceArtifactDigest,
        EXPECTED_RELEASE_MANIFEST_SHA256: fixture.expected.releaseManifestSha256,
        EXPECTED_NPM_TARBALL_NAME: "kaji-sdk-0.2.0-beta.10.tgz",
        EXPECTED_NPM_TARBALL_SHA256: fixture.expected.npmTarballSha256,
      },
    });
    const endpoints = readFileSync(endpointLog, "utf8").split("\n").filter(Boolean);
    return Object.assign(completed, { endpoints });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

const onboardingArtifactKeys = ["producer", "onboarding", "node22", "node24"] as const;
type OnboardingArtifactKey = (typeof onboardingArtifactKeys)[number];
type OnboardingConsumerWorkflow = "kaji.rehearsal.yml" | "kaji.publish.yml";

function onboardingBindingFixture(workflowName: OnboardingConsumerWorkflow) {
  const publish = workflowName === "kaji.publish.yml";
  const runId = publish ? 701_002 : 701_001;
  const commit = publish ? "6".repeat(40) : "5".repeat(40);
  const headBranch = publish ? "kaji-v0.2.0-beta.10" : "main";
  const expected = {
    producer: {
      id: 702_001,
      name: "kaji-beta-artifacts",
      digest: `sha256:${"a".repeat(64)}`,
    },
    onboarding: {
      id: 702_002,
      name: "kaji-typescript-onboarding-evidence",
      digest: `sha256:${"b".repeat(64)}`,
    },
    node22: {
      id: 702_003,
      name: "kaji-node-compat-22",
      digest: `sha256:${"c".repeat(64)}`,
    },
    node24: {
      id: 702_004,
      name: "kaji-node-compat-24",
      digest: `sha256:${"d".repeat(64)}`,
    },
  };
  const artifacts = Object.fromEntries(
    onboardingArtifactKeys.map((key) => {
      const binding = expected[key];
      return [
        key,
        {
          id: binding.id,
          name: binding.name,
          digest: binding.digest,
          expired: false,
          size_in_bytes: 4096,
          url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${binding.id}`,
          archive_download_url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${binding.id}/zip`,
          workflow_run: {
            id: runId,
            head_branch: headBranch,
            head_sha: commit,
          },
        } as Record<string, unknown>,
      ];
    }),
  ) as Record<OnboardingArtifactKey, Record<string, unknown>>;
  return {
    runId,
    commit,
    headBranch,
    event: publish ? "push" : "workflow_dispatch",
    workflowPath: `.github/workflows/${workflowName}`,
    expected,
    artifacts,
    run: {
      id: runId,
      run_attempt: 1,
      event: publish ? "push" : "workflow_dispatch",
      path: `.github/workflows/${workflowName}`,
      head_branch: headBranch,
      head_sha: commit,
    } as Record<string, unknown>,
    env: {
      PRODUCER_ID: String(expected.producer.id),
      PRODUCER_DIGEST: expected.producer.digest,
      ONBOARDING_ID: String(expected.onboarding.id),
      ONBOARDING_DIGEST: expected.onboarding.digest,
      NODE22_ID: String(expected.node22.id),
      NODE22_DIGEST: expected.node22.digest,
      NODE24_ID: String(expected.node24.id),
      NODE24_DIGEST: expected.node24.digest,
    } as Record<string, string>,
  };
}

type OnboardingBindingFixture = ReturnType<typeof onboardingBindingFixture>;

function runOnboardingBindingAuthentication(
  workflowName: OnboardingConsumerWorkflow,
  mutate?: (fixture: OnboardingBindingFixture) => void,
): ReturnType<typeof spawnSync> & { endpoints: string[] } {
  const fixture = onboardingBindingFixture(workflowName);
  mutate?.(fixture);
  const jobId = workflowName === "kaji.publish.yml" ? "supply-chain" : "candidate-evidence";
  const job = readWorkflow(workflowName).workflow.jobs?.[jobId];
  const step = workflowStep(
    job!,
    "Authenticate exact onboarding artifact bindings before downloads",
  );
  const root = mkdtempSync(join(tmpdir(), "kaji-onboarding-bindings-"));
  const bin = join(root, "bin");
  const endpointLog = join(root, "endpoints.log");
  mkdirSync(bin);
  writeFileSync(endpointLog, "");
  writeFileSync(join(root, "run.json"), JSON.stringify(fixture.run));
  for (const key of onboardingArtifactKeys) {
    writeFileSync(join(root, `${key}.json`), JSON.stringify(fixture.artifacts[key]));
  }
  const gh = join(bin, "gh");
  writeFileSync(
    gh,
    `#!/bin/bash
set -euo pipefail
for endpoint in "$@"; do :; done
printf '%s\n' "$endpoint" >>"$KAJI_ENDPOINT_LOG"
case "$endpoint" in
  */actions/runs/${fixture.runId}) file=run.json ;;
  */actions/artifacts/${fixture.expected.producer.id}) file=producer.json ;;
  */actions/artifacts/${fixture.expected.onboarding.id}) file=onboarding.json ;;
  */actions/artifacts/${fixture.expected.node22.id}) file=node22.json ;;
  */actions/artifacts/${fixture.expected.node24.id}) file=node24.json ;;
  *) exit 64 ;;
esac
cat "$KAJI_FIXTURE_ROOT/$file"
`,
  );
  chmodSync(gh, 0o700);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        ...fixture.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        GH_TOKEN: "read-only-test-token",
        GITHUB_REPOSITORY: "enkyuan/alloy",
        GITHUB_RUN_ID: String(fixture.runId),
        GITHUB_RUN_ATTEMPT: "1",
        KAJI_ENDPOINT_LOG: endpointLog,
        KAJI_FIXTURE_ROOT: root,
        RUNNER_TEMP: root,
        EXPECTED_COMMIT: fixture.commit,
        EXPECTED_EVENT: fixture.event,
        EXPECTED_HEAD_BRANCH: fixture.headBranch,
        EXPECTED_WORKFLOW_PATH: fixture.workflowPath,
      },
    });
    const endpoints = readFileSync(endpointLog, "utf8").split("\n").filter(Boolean);
    return Object.assign(completed, { endpoints });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function publisherIdentityArtifactFixture() {
  const runId = 812_345;
  const artifactId = 812_346;
  const commit = "7".repeat(40);
  const digest = "8".repeat(64);
  const tag = "kaji-v0.2.0-beta.10";
  const name = `kaji-publisher-identity-${runId}-1`;
  return {
    runId,
    artifactId,
    commit,
    digest,
    tag,
    name,
    run: {
      id: runId,
      run_attempt: 1,
      event: "push",
      path: ".github/workflows/kaji.publish.yml",
      head_branch: tag,
      head_sha: commit,
    } as Record<string, unknown>,
    artifact: {
      id: artifactId,
      name,
      digest: `sha256:${digest}`,
      expired: false,
      size_in_bytes: 4096,
      url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${artifactId}`,
      archive_download_url: `https://api.github.com/repos/enkyuan/alloy/actions/artifacts/${artifactId}/zip`,
      workflow_run: {
        id: runId,
        head_branch: tag,
        head_sha: commit,
      },
    } as Record<string, unknown>,
    env: {
      PUBLISHER_ARTIFACT_ID: String(artifactId),
      PUBLISHER_ARTIFACT_NAME: name,
      PUBLISHER_ARTIFACT_DIGEST: digest,
      EXPECTED_COMMIT: commit,
      EXPECTED_TAG: tag,
      EXPECTED_WORKFLOW_PATH: ".github/workflows/kaji.publish.yml",
    } as Record<string, string>,
  };
}

type PublisherIdentityArtifactFixture = ReturnType<typeof publisherIdentityArtifactFixture>;

function runPublisherReceiptOutputBinding(
  overrides: Record<string, string> = {},
): ReturnType<typeof spawnSync> & { outputs: Record<string, string>; endpoints: string[] } {
  const step = workflowStep(
    readWorkflow("kaji.publish.yml").workflow.jobs?.["publication-status"]!,
    "Classify publisher identity receipt outputs before setup",
  );
  const root = mkdtempSync(join(tmpdir(), "kaji-publisher-output-binding-"));
  const bin = join(root, "bin");
  const output = join(root, "github-output");
  const endpointLog = join(root, "endpoints.log");
  mkdirSync(bin);
  writeFileSync(output, "");
  writeFileSync(endpointLog, "");
  const gh = join(bin, "gh");
  writeFileSync(
    gh,
    `#!/bin/bash
printf '%s\n' "$*" >>"$KAJI_ENDPOINT_LOG"
exit 70
`,
  );
  chmodSync(gh, 0o700);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        GITHUB_OUTPUT: output,
        GITHUB_RUN_ATTEMPT: "1",
        GITHUB_RUN_ID: "812345",
        KAJI_ENDPOINT_LOG: endpointLog,
        PUBLISH_RESULT: "skipped",
        PUBLISHER_ARTIFACT_ID: "",
        PUBLISHER_ARTIFACT_NAME: "",
        PUBLISHER_ARTIFACT_DIGEST: "",
        PUBLISHER_OUTPUT: "",
        ...overrides,
      },
    });
    const outputs = Object.fromEntries(
      readFileSync(output, "utf8")
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          const separator = line.indexOf("=");
          return [line.slice(0, separator), line.slice(separator + 1)];
        }),
    );
    const endpoints = readFileSync(endpointLog, "utf8").split("\n").filter(Boolean);
    return Object.assign(completed, { outputs, endpoints });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function runInitialPublicationStatus(
  publishResult: string,
): ReturnType<typeof spawnSync> & { payload: Record<string, unknown> } {
  const step = workflowStep(
    readWorkflow("kaji.publish.yml").workflow.jobs?.["publication-status"]!,
    "Initialize fail-closed publication status before setup",
  );
  const root = mkdtempSync(join(tmpdir(), "kaji-initial-publication-status-"));
  const output = join(root, "github-output");
  writeFileSync(output, "");
  const commit = "7".repeat(40);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        GITHUB_OUTPUT: output,
        GITHUB_REPOSITORY: "enkyuan/alloy",
        GITHUB_RUN_ATTEMPT: "1",
        GITHUB_RUN_ID: "812345",
        GITHUB_SERVER_URL: "https://github.com",
        NPM_PUBLISH_RESULT: publishResult,
        PUBLISHER_OUTPUT: "",
        RELEASE_COMMIT: commit,
        RELEASE_TAG: "kaji-v0.2.0-beta.10",
        RUNNER_TEMP: root,
        WORKFLOW_SHA: commit,
      },
    });
    const payload = JSON.parse(
      readFileSync(
        join(root, ".artifacts/kaji-publication-status/publication-status.json"),
        "utf8",
      ),
    ) as Record<string, unknown>;
    return Object.assign(completed, { payload });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

type ExactVersionRegistryFixture = {
  pypiHttp: string;
  controlHttp: string;
  controlBody: string;
  controlContentType: string;
  controlEffectiveUrl: string;
  controlRedirects: string;
  controlTransportStatus: string;
  packumentHttp: string;
  packumentBody: string;
  packumentContentType: string;
  packumentEffectiveUrl: string;
  packumentRedirects: string;
  packumentTransportStatus: string;
  targetHttp: string;
  targetBody: string;
  targetContentType: string;
  targetEffectiveUrl: string;
  targetRedirects: string;
  targetTransportStatus: string;
};

function runExactVersionRegistryAbsence(
  jobId: "registry-preflight" | "publish-npm",
  stepName:
    | "Require PyPI beta absence and exact npm beta absence"
    | "Recheck exact registry absence immediately before npm publication",
  overrides: Partial<ExactVersionRegistryFixture> = {},
): ReturnType<typeof spawnSync> {
  const step = workflowStep(readWorkflow("kaji.publish.yml").workflow.jobs?.[jobId]!, stepName);
  const fixture: ExactVersionRegistryFixture = {
    pypiHttp: "404",
    controlHttp: "200",
    controlBody: '{"name":"tiny-tarball","version":"1.0.0"}',
    controlContentType: "application/json",
    controlEffectiveUrl: "https://registry.npmjs.org/tiny-tarball/1.0.0",
    controlRedirects: "0",
    controlTransportStatus: "0",
    packumentHttp: "404",
    packumentBody: '{"error":"Not found"}',
    packumentContentType: "application/json",
    packumentEffectiveUrl: "https://registry.npmjs.org/kaji-sdk",
    packumentRedirects: "0",
    packumentTransportStatus: "0",
    targetHttp: "404",
    targetBody: '"Not Found"',
    targetContentType: "application/json",
    targetEffectiveUrl: "https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10",
    targetRedirects: "0",
    targetTransportStatus: "0",
    ...overrides,
  };
  const root = mkdtempSync(join(tmpdir(), "kaji-registry-preflight-"));
  const bin = join(root, "bin");
  mkdirSync(bin);
  for (const [name, body] of [
    ["control", fixture.controlBody],
    ["packument", fixture.packumentBody],
    ["target", fixture.targetBody],
  ] as const) {
    writeFileSync(join(root, `${name}.json`), body);
  }
  const curl = join(bin, "curl");
  writeFileSync(
    curl,
    `#!/bin/bash
set -euo pipefail
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output="$2"
      shift 2
      ;;
    --write-out|--header|--max-time|--connect-timeout|--proto|--max-filesize)
      shift 2
      ;;
    --silent|--show-error|--tlsv1.2)
      shift
      ;;
    https://*)
      url="$1"
      shift
      ;;
    *)
      exit 64
      ;;
  esac
done
case "$url" in
  https://pypi.org/pypi/kaji-sdk/0.2.0b1/json)
    printf '%s' "$KAJI_PYPI_HTTP"
    ;;
  https://registry.npmjs.org/tiny-tarball/1.0.0)
    key=CONTROL
    body_file="$KAJI_FIXTURE_ROOT/control.json"
    ;;
  https://registry.npmjs.org/kaji-sdk)
    key=PACKUMENT
    body_file="$KAJI_FIXTURE_ROOT/packument.json"
    ;;
  https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10)
    key=TARGET
    body_file="$KAJI_FIXTURE_ROOT/target.json"
    ;;
  *)
    exit 65
    ;;
esac
if [ -n "\${key:-}" ]; then
  eval "transport_status=\\\$KAJI_\${key}_TRANSPORT_STATUS"
  [ "$transport_status" -eq 0 ] || exit "$transport_status"
  eval "http_status=\\\$KAJI_\${key}_HTTP"
  eval "content_type=\\\$KAJI_\${key}_CONTENT_TYPE"
  eval "effective_url=\\\$KAJI_\${key}_EFFECTIVE_URL"
  eval "redirects=\\\$KAJI_\${key}_REDIRECTS"
  cp "$body_file" "$output"
  size="$(wc -c <"$output" | tr -d '[:space:]')"
  printf '%s\\t%s\\t%s\\t%s\\t%s\\n' \
    "$http_status" "$content_type" "$effective_url" "$redirects" "$size"
fi
`,
  );
  chmodSync(curl, 0o700);
  try {
    return spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        KAJI_FIXTURE_ROOT: root,
        KAJI_PYPI_HTTP: fixture.pypiHttp,
        KAJI_CONTROL_HTTP: fixture.controlHttp,
        KAJI_CONTROL_CONTENT_TYPE: fixture.controlContentType,
        KAJI_CONTROL_EFFECTIVE_URL: fixture.controlEffectiveUrl,
        KAJI_CONTROL_REDIRECTS: fixture.controlRedirects,
        KAJI_CONTROL_TRANSPORT_STATUS: fixture.controlTransportStatus,
        KAJI_PACKUMENT_HTTP: fixture.packumentHttp,
        KAJI_PACKUMENT_CONTENT_TYPE: fixture.packumentContentType,
        KAJI_PACKUMENT_EFFECTIVE_URL: fixture.packumentEffectiveUrl,
        KAJI_PACKUMENT_REDIRECTS: fixture.packumentRedirects,
        KAJI_PACKUMENT_TRANSPORT_STATUS: fixture.packumentTransportStatus,
        KAJI_TARGET_HTTP: fixture.targetHttp,
        KAJI_TARGET_CONTENT_TYPE: fixture.targetContentType,
        KAJI_TARGET_EFFECTIVE_URL: fixture.targetEffectiveUrl,
        KAJI_TARGET_REDIRECTS: fixture.targetRedirects,
        KAJI_TARGET_TRANSPORT_STATUS: fixture.targetTransportStatus,
        RUNNER_TEMP: root,
      },
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function runPublicationClassifierFallback(
  overrides: Record<string, string>,
): ReturnType<typeof spawnSync> & { payload: Record<string, unknown> } {
  const step = workflowStep(
    readWorkflow("kaji.publish.yml").workflow.jobs?.["publication-status"]!,
    "Reduce monotonic publication state",
  );
  const root = mkdtempSync(join(tmpdir(), "kaji-publication-fallback-"));
  const bin = join(root, "bin");
  const output = join(root, "github-output");
  const summary = join(root, "github-summary");
  mkdirSync(bin);
  writeFileSync(output, "");
  writeFileSync(summary, "");
  writeFileSync(join(root, "control.json"), '{"name":"tiny-tarball","version":"1.0.0"}');
  writeFileSync(join(root, "target.json"), '"Not Found"');
  const curl = join(bin, "curl");
  writeFileSync(
    curl,
    `#!/bin/bash
set -euo pipefail
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --write-out|--header|--max-time|--connect-timeout|--proto|--max-filesize)
      shift 2
      ;;
    --silent|--show-error|--tlsv1.2) shift ;;
    https://*) url="$1"; shift ;;
    *) exit 64 ;;
  esac
done
case "$url" in
  https://pypi.org/pypi/kaji-sdk/0.2.0b1/json)
    printf '404'
    exit 0
    ;;
  https://registry.npmjs.org/tiny-tarball/1.0.0)
    body="$KAJI_FIXTURE_ROOT/control.json"
    http=200
    ;;
  https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10)
    body="$KAJI_FIXTURE_ROOT/target.json"
    http=404
    ;;
  *) exit 65 ;;
esac
cp "$body" "$output"
size="$(wc -c <"$output" | tr -d '[:space:]')"
printf '%s\\tapplication/json\\t%s\\t0\\t%s\\n' "$http" "$url" "$size"
`,
  );
  chmodSync(curl, 0o700);
  const commit = "7".repeat(40);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        GITHUB_OUTPUT: output,
        GITHUB_REPOSITORY: "enkyuan/alloy",
        GITHUB_RUN_ATTEMPT: "1",
        GITHUB_RUN_ID: "812345",
        GITHUB_SERVER_URL: "https://github.com",
        GITHUB_STEP_SUMMARY: summary,
        KAJI_FIXTURE_ROOT: root,
        NPM_PUBLISH_RESULT: "failure",
        PUBLISHER_ARTIFACT_DIGEST: "8".repeat(64),
        PUBLISHER_ARTIFACT_ID: "812346",
        PUBLISHER_ARTIFACT_NAME: "kaji-publisher-identity-812345-1",
        PUBLISHER_BINDING_MODE: "receipt",
        PUBLISHER_BINDING_REASON: "",
        PUBLISHER_DOWNLOAD_OUTCOME: "success",
        PUBLISHER_INVENTORY_OUTCOME: "success",
        PUBLISHER_METADATA_OUTCOME: "success",
        PUBLISHER_OUTPUT: "approved-publisher",
        RELEASE_COMMIT: commit,
        RELEASE_TAG: "kaji-v0.2.0-beta.10",
        RUNNER_TEMP: root,
        WORKFLOW_SHA: commit,
        ...overrides,
      },
    });
    const payload = JSON.parse(
      readFileSync(
        join(root, ".artifacts/kaji-publication-status/publication-status.json"),
        "utf8",
      ),
    ) as Record<string, unknown>;
    return Object.assign(completed, { payload });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function runPublisherIdentityArtifactAuthentication(
  mutate?: (fixture: PublisherIdentityArtifactFixture) => void,
): ReturnType<typeof spawnSync> & { endpoints: string[] } {
  const fixture = publisherIdentityArtifactFixture();
  mutate?.(fixture);
  const step = workflowStep(
    readWorkflow("kaji.publish.yml").workflow.jobs?.["publication-status"]!,
    "Authenticate exact publisher identity artifact before download",
  );
  const root = mkdtempSync(join(tmpdir(), "kaji-publisher-identity-binding-"));
  const bin = join(root, "bin");
  const endpointLog = join(root, "endpoints.log");
  mkdirSync(bin);
  writeFileSync(endpointLog, "");
  writeFileSync(join(root, "run.json"), JSON.stringify(fixture.run));
  writeFileSync(join(root, "artifact.json"), JSON.stringify(fixture.artifact));
  const gh = join(bin, "gh");
  writeFileSync(
    gh,
    `#!/bin/bash
set -euo pipefail
for endpoint in "$@"; do :; done
printf '%s\n' "$endpoint" >>"$KAJI_ENDPOINT_LOG"
case "$endpoint" in
  */actions/runs/${fixture.runId}) file=run.json ;;
  */actions/artifacts/${fixture.artifactId}) file=artifact.json ;;
  *) exit 64 ;;
esac
cat "$KAJI_FIXTURE_ROOT/$file"
`,
  );
  chmodSync(gh, 0o700);
  try {
    const completed = spawnSync("/bin/bash", ["-c", step.run!], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        ...fixture.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        GH_TOKEN: "read-only-test-token",
        GITHUB_REPOSITORY: "enkyuan/alloy",
        GITHUB_RUN_ID: String(fixture.runId),
        GITHUB_RUN_ATTEMPT: "1",
        GITHUB_REF_NAME: fixture.tag,
        KAJI_ENDPOINT_LOG: endpointLog,
        KAJI_FIXTURE_ROOT: root,
        RUNNER_TEMP: root,
      },
    });
    const endpoints = readFileSync(endpointLog, "utf8").split("\n").filter(Boolean);
    return Object.assign(completed, { endpoints });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

describe("Kaji workflow contracts", () => {
  it("uses functional display names for every Kaji workflow and job", () => {
    for (const workflowFile of Object.keys(expectedKajiWorkflowNames) as KajiWorkflowFile[]) {
      const { workflow } = readWorkflow(workflowFile);
      const jobs = workflow.jobs ?? {};
      const expectedJobs = expectedKajiJobNames[workflowFile];

      expect(workflow.name, workflowFile).toBe(expectedKajiWorkflowNames[workflowFile]);
      expect(Object.keys(jobs).sort(), workflowFile).toEqual(Object.keys(expectedJobs).sort());
      for (const [jobId, expectedName] of Object.entries(expectedJobs)) {
        expect(jobs[jobId]?.name, `${workflowFile}:${jobId}`).toBe(expectedName);
      }
    }
  });

  it("defines the closed diagnostic-only trusted handoff workflow", () => {
    const { source, workflow } = readWorkflow("kaji.handoff.trusted.yml");
    assertTrustedHandoffWorkflow(workflow, source);
  });

  it("accepts bootstrap identity where caller and called revisions differ", () => {
    const calledSha = "a".repeat(40);
    const callerSha = "b".repeat(40);
    const bootstrapCall: WorkflowJob = {
      uses: `enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@${calledSha}`,
      with: { mode: "internal-evaluation", tag_name: "" },
      permissions: { contents: "read", "id-token": "write", attestations: "write" },
    };
    expect(isTrustedHandoffCall(bootstrapCall.uses!)).toBe(true);
    expect(callerSha).not.toBe(calledSha);
    const guard = readWorkflow("kaji.handoff.trusted.yml").workflow.jobs?.stage?.steps?.[0];
    expect(guard).toBeDefined();
    const execution = runTrustedHandoffGuard(guard!, { CANDIDATE_SHA: callerSha });
    expect(execution.status, String(execution.stderr)).toBe(0);
  });

  it.each([
    ["python.test.yml", ["kaji/**", "kaji/serve/**"]],
    ["ts.test.yml", ["kaji/ts/**", "ryo/auth/**", "packages/ui/**"]],
  ] as const)("routes shared beta inputs through %s", (name, packagePaths) => {
    const { source, workflow } = readWorkflow(name);

    for (const event of ["push", "pull_request"] as const) {
      const trigger = workflow.on?.[event] as { paths?: string[] } | undefined;
      expect(trigger?.paths, `${name}:${event}`).toEqual(
        expect.arrayContaining([...packagePaths, ...sharedBetaPaths]),
      );
    }
    for (const line of source.split("\n").filter((candidate) => candidate.includes("**"))) {
      expect(line, `${name}:${line.trim()}`).toMatch(/^\s+-\s+"[^"]*\*\*[^"]*"\s*$/);
    }
  });

  it("defines one always-on, protection-ready PR gate", () => {
    const { workflow } = readWorkflow("kaji.gate.yml");
    assertProtectionReadyGate(workflow);
  });

  it("pins and annotates every external action used by Kaji CI", () => {
    const closure = assertReviewedActionDocuments(
      workflowFiles.map((name) => `.github/workflows/${name}`),
    );

    expect(closure).toContain(".github/actions/setup-python-uv/action.yml");
    expect(closure).toContain(".github/actions/setup-bun-cache/action.yml");
    expect(closure).toContain(".github/actions/verify-kaji-beta-tag/action.yml");
  });

  it("parses every Kaji shell step with Bash", () => {
    const documents = assertReviewedActionDocuments(
      (Object.keys(expectedKajiWorkflowNames) as KajiWorkflowFile[]).map(
        (name) => `.github/workflows/${name}`,
      ),
    );

    for (const relativePath of documents) {
      const { value } = readYaml(relativePath);
      for (const [index, step] of workflowSteps(value).entries()) {
        if (step.run === undefined) continue;
        const syntax = spawnSync("/bin/bash", ["-n"], {
          encoding: "utf8",
          input: step.run,
        });
        expect(syntax.status, `${relativePath}:run step ${index}: ${syntax.stderr}`).toBe(0);
      }
    }
  }, 20_000);

  it("parses every Kaji github-script program with Node", () => {
    for (const name of Object.keys(expectedKajiWorkflowNames) as KajiWorkflowFile[]) {
      const { value } = readYaml(`.github/workflows/${name}`);
      for (const [index, step] of workflowSteps(value).entries()) {
        if (!step.uses?.startsWith("actions/github-script@")) continue;
        expect(typeof step.with?.script).toBe("string");
        const syntax = spawnSync(process.execPath, ["--check", "-"], {
          encoding: "utf8",
          input: `async function githubScript() {\n${String(step.with?.script)}\n}\n`,
        });
        expect(
          syntax.status,
          `.github/workflows/${name}:github-script ${index}: ${syntax.stderr}`,
        ).toBe(0);
      }
    }
  });

  it("binds candidate artifacts on a fresh workflow attempt without action-context fields", async () => {
    const step = readWorkflow("kaji.performance.yml").workflow.jobs?.[
      "candidate-artifact"
    ]?.steps?.find((candidate) => candidate.name === "Bind immutable candidate artifact metadata");

    expect(step?.env?.RUN_ATTEMPT).toBe("${{ github.run_attempt }}");
    expect(step?.env).not.toHaveProperty("GITHUB_RUN_ATTEMPT");
    expect(step?.with?.script).toContain("process.env.RUN_ATTEMPT");
    expect(step?.with?.script).not.toContain("context.runAttempt");
    const getArtifact = await runCandidateArtifactBinding("1");
    expect(getArtifact).toHaveBeenCalledOnce();
  });

  it.each(["2", "invalid", undefined])(
    "rejects candidate artifact binding for non-fresh attempt %s",
    async (runAttempt) => {
      await expect(runCandidateArtifactBinding(runAttempt)).rejects.toThrow(
        "protected performance evidence cannot be rerun; dispatch a new workflow run",
      );
    },
  );

  it("flattens exact candidate artifacts and initializes workspace evidence after checkout", () => {
    const jobs = readWorkflow("kaji.performance.yml").workflow.jobs ?? {};

    for (const jobId of ["paired-replica", "paired-aggregate", "soak"]) {
      const job = jobs[jobId];
      if (job?.steps === undefined) throw new Error(`missing ${jobId} steps`);
      const checkoutIndex = job.steps.findIndex((step) =>
        step.uses?.startsWith("actions/checkout@"),
      );
      const rerunRejectionIndex = job.steps.findIndex(
        (step) => step.name === "Reject protected rerun attempt",
      );
      const initializationIndex = job.steps.findIndex((step) =>
        step.name?.startsWith("Initialize"),
      );
      expect(rerunRejectionIndex, jobId).toBeGreaterThanOrEqual(0);
      expect(checkoutIndex, jobId).toBeGreaterThanOrEqual(0);
      expect(checkoutIndex, jobId).toBeGreaterThan(rerunRejectionIndex);
      expect(initializationIndex, jobId).toBeGreaterThan(checkoutIndex);
      expect(job.steps[initializationIndex]?.if, jobId).toBe(
        "${{ always() && github.run_attempt == 1 }}",
      );
    }

    for (const jobId of ["paired-replica", "soak"]) {
      const job = jobs[jobId];
      if (job === undefined) throw new Error(`missing ${jobId} job`);
      expect(workflowStep(job, "Download immutable candidate artifact").with).toMatchObject({
        "artifact-ids": "${{ inputs.candidate-artifact-id }}",
        path: ".artifacts/kaji-candidate",
        "merge-multiple": true,
      });
    }
  });

  it("bounds every Kaji job and keeps effective permissions narrow", () => {
    for (const name of workflowFiles) {
      const { workflow } = readWorkflow(name);
      for (const [jobId, job] of Object.entries(workflow.jobs ?? {})) {
        if (job.uses === undefined) {
          expect(job["timeout-minutes"], `${name}:${jobId}`).toBeGreaterThan(0);
        } else {
          expect(job["timeout-minutes"], `${name}:${jobId}:call job timeout`).toBeUndefined();
        }
        if (job["timeout-minutes"] === 75) {
          expect(`${name}:${jobId}`).toBe("kaji.publish.yml:performance");
        }
      }
      assertNarrowPermissions(name, workflow);
    }
  });

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "accepts only the installed-artifact Echo failure phase in %s",
    (workflowName) => {
      const { source } = readWorkflow(workflowName);
      const smokePhaseMatch = source.match(
        /def smoke_phase:\s*type == "string" and\s*test\("([^"]+)"\);/u,
      );

      expect(smokePhaseMatch, workflowName).not.toBeNull();
      expect(source, workflowName).toContain("installed-artifact-echo-run");
      expect(source, workflowName).not.toContain("docs-installed-artifact-echo-run");
      expect(source, workflowName).not.toContain("docs-tthw-echo-run");
      expect(source, workflowName).not.toContain("docs-(tthw-echo|installed-artifact-echo)-run");

      const smokePhase = new RegExp(smokePhaseMatch![1]!, "u");
      for (const manager of ["npm", "bun"] as const) {
        const producerReceipt = ordinaryFailureReceipt(
          new SmokeCommandError(`${manager}:installed-artifact-echo-run`, "exit"),
          { expectedCommit: "a".repeat(40) },
          {
            commit: "a".repeat(40),
            manifestSha256: "b".repeat(64),
            artifactSha256: {},
          },
          "v22.0.0",
        );
        const producerPhase = producerReceipt["failedPhase"];
        expect(producerPhase).toBe(`${manager}:installed-artifact-echo-run`);
        expect(
          typeof producerPhase === "string" && smokePhase.test(producerPhase),
          `${workflowName}:${manager}:installed-artifact`,
        ).toBe(true);
        expect(
          smokePhase.test(`${manager}:docs-tthw-echo-run`),
          `${workflowName}:${manager}:obsolete-tthw`,
        ).toBe(false);
      }
    },
  );

  it("freezes the npm-only calibration and protected onboarding workflow boundary", () => {
    const rehearsal = readWorkflow("kaji.rehearsal.yml");
    const publish = readWorkflow("kaji.publish.yml");
    const cases = [
      {
        name: "kaji.rehearsal.yml",
        document: rehearsal,
        jobCount: 8,
        calibrationNeeds: ["offline-release", "node-compat"],
        onboardingNeeds: [
          "offline-release",
          "python-compat",
          "node-compat",
          "typescript-onboarding-archive-calibration",
        ],
        workflowRef: "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main",
      },
      {
        name: "kaji.publish.yml",
        document: publish,
        jobCount: 14,
        calibrationNeeds: ["verify-tag", "offline-gates", "node-compat"],
        onboardingNeeds: [
          "verify-tag",
          "offline-gates",
          "performance",
          "python-compat",
          "node-compat",
          "typescript-onboarding-archive-calibration",
        ],
        workflowRef:
          "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.10",
      },
    ] as const;

    for (const {
      name,
      document: { source, workflow },
      jobCount,
      calibrationNeeds,
      onboardingNeeds,
      workflowRef,
    } of cases) {
      const jobs = workflow.jobs ?? {};
      expect(Object.keys(jobs), name).toHaveLength(jobCount);
      expect(jobs).not.toHaveProperty("tthw-evidence");
      expect(jobs).not.toHaveProperty("publisher-preflight");
      expect(source).not.toContain("KAJI_TTHW_EVIDENCE_JSON");
      expect(source).not.toContain("validate_tthw_evidence.py");
      expect(source).not.toContain("--tthw-status");
      expect(source).not.toContain("--tthw-evidence");

      const calibration = jobs["typescript-onboarding-archive-calibration"];
      const onboarding = jobs["typescript-onboarding-evidence"];
      expect(calibration?.name).toBe("TypeScript onboarding archive calibration");
      expect(onboarding?.name).toBe("TypeScript onboarding evidence");
      expect(calibration?.["runs-on"]).toBe("ubuntu-24.04");
      expect(onboarding?.["runs-on"]).toBe("ubuntu-24.04");
      expect(calibration?.needs).toEqual(calibrationNeeds);
      expect(onboarding?.needs).toEqual(onboardingNeeds);
      expect(calibration?.permissions).toEqual({ actions: "read", contents: "read" });
      expect(onboarding?.permissions).toEqual({ actions: "read", contents: "read" });
      expect(calibration?.environment).toBeUndefined();
      expect(onboarding?.environment).toBe("kaji-beta-onboarding");
      expect(calibration?.outputs).toBeUndefined();
      expect(Object.keys(onboarding?.outputs ?? {}).sort()).toEqual(
        [
          "aggregate-sha256",
          "node22-source-artifact-digest",
          "node22-source-artifact-id",
          "node24-source-artifact-digest",
          "node24-source-artifact-id",
          "onboarding-artifact-digest",
          "onboarding-artifact-id",
          "producer-artifact-digest",
          "producer-artifact-id",
          "release-manifest-sha256",
        ].sort(),
      );
      for (const [jobId, job, directNeeds] of [
        ["typescript-onboarding-archive-calibration", calibration, calibrationNeeds],
        ["typescript-onboarding-evidence", onboarding, onboardingNeeds],
      ] as const) {
        expect(job?.if, `${name}:${jobId}`).toContain("github.run_attempt == 1");
        expect(job?.if, `${name}:${jobId}`).toContain("!cancelled()");
        expect(job?.if, `${name}:${jobId}`).not.toContain("always()");
        for (const dependency of directNeeds) {
          expect(job?.if, `${name}:${jobId}:${dependency}`).toContain(
            `needs.${dependency}.result == 'success'`,
          );
        }
        expect(JSON.stringify(job), `${name}:${jobId}:secret-free`).not.toMatch(
          /NPM_TOKEN|KAJI_NPM_PUBLISHER|OPENAI_API_KEY|KAJI_TTHW_EVIDENCE_JSON|secrets\./u,
        );
        const checkout = (job?.steps ?? []).find((step) =>
          step.uses?.startsWith("actions/checkout@"),
        );
        expect(checkout?.with?.["persist-credentials"]).toBe(false);
        expect(job?.env?.EXPECTED_WORKFLOW_REF, `${name}:${jobId}:workflow ref`).toBe(workflowRef);
        const combinedRuns = (job?.steps ?? []).map((step) => step.run ?? "").join("\n");
        for (const fragment of [
          "X-GitHub-Api-Version: 2026-03-10",
          "actions/runs/$GITHUB_RUN_ID/artifacts?per_page=100",
          "actions/artifacts/$artifact_id",
          "actions/artifacts/$artifact_id/zip",
          "sha256:",
          "load_authenticated_archive",
          "validate_document",
          "recompute_and_compare",
          "validate_typescript_onboarding_evidence.py",
        ]) {
          expect(combinedRuns, `${name}:${jobId}:${fragment}`).toContain(fragment);
        }
        expect(combinedRuns, `${name}:${jobId}: stable collection binding`).toContain(
          ".artifacts as $artifacts",
        );
        expect(combinedRuns, `${name}:${jobId}: no streaming collection alias`).not.toContain(
          "inputs.artifacts",
        );
      }

      const calibrationUploads = (calibration?.steps ?? []).filter((step) =>
        step.uses?.startsWith("actions/upload-artifact@"),
      );
      expect(calibrationUploads.map((step) => step.with?.name)).toEqual([
        "kaji-typescript-onboarding-archive-calibration-initial",
        "kaji-typescript-onboarding-archive-calibration",
      ]);
      expect(calibrationUploads.every((step) => step.with?.["if-no-files-found"] === "error")).toBe(
        true,
      );
      const onboardingUploads = (onboarding?.steps ?? []).filter((step) =>
        step.uses?.startsWith("actions/upload-artifact@"),
      );
      expect(onboardingUploads.map((step) => step.with?.name)).toEqual([
        "kaji-typescript-onboarding-evidence-initial",
        "kaji-typescript-onboarding-evidence",
      ]);
      expect(String(onboardingUploads[1]?.with?.path)).toContain(
        "typescript-onboarding-evidence.json",
      );
      expect(source.match(/environment:\s+kaji-beta-onboarding/g)).toHaveLength(1);
      expect(source.match(/environment:\s+kaji-beta(?:\s|$)/g)).toHaveLength(1);
    }

    const dispatch = rehearsal.workflow.on?.workflow_dispatch as
      | { inputs?: Record<string, Record<string, unknown>> }
      | undefined;
    expect(dispatch?.inputs?.["expected-commit"]).toEqual({
      description: "Exact reviewed main commit",
      required: true,
      type: "string",
    });
    const firstRehearsalStep = rehearsal.workflow.jobs?.["offline-release"]?.steps?.[0];
    expect(firstRehearsalStep?.name).toBe("Bind exact reviewed main commit before execution");
    expect(firstRehearsalStep?.env?.EXPECTED_COMMIT).toBe("${{ inputs.expected-commit }}");
    expect(firstRehearsalStep?.run).toContain('test "$GITHUB_REF" = refs/heads/main');
    expect(firstRehearsalStep?.run).toContain('test "$EXPECTED_COMMIT" = "$GITHUB_SHA"');
    expect(firstRehearsalStep?.run).toContain('test "$GITHUB_RUN_ATTEMPT" = 1');
    for (const [name, workflow] of [
      ["kaji.rehearsal.yml", rehearsal.workflow],
      ["kaji.publish.yml", publish.workflow],
    ] as const) {
      for (const [jobId, job] of Object.entries(workflow.jobs ?? {})) {
        for (const checkout of (job.steps ?? []).filter((step) =>
          step.uses?.startsWith("actions/checkout@"),
        )) {
          expect(
            checkout.with?.["persist-credentials"],
            `${name}:${jobId}: checkout credentials`,
          ).toBe(false);
        }
      }
    }
  });

  it("requires signature-bound authorization at every npm release mutation boundary", () => {
    const { source, workflow } = readWorkflow("kaji.publish.yml");
    const verifyTag = workflow.jobs?.["verify-tag"];
    const expectedOutputs = [
      "authorization-sha256",
      "candidate-artifact-digest",
      "candidate-artifact-id",
      "candidate-artifact-name",
      "commit",
      "evidence-artifact-digest",
      "evidence-artifact-id",
      "evidence-artifact-name",
      "npm-tarball-name",
      "npm-tarball-sha256",
      "rehearsal-run-attempt",
      "rehearsal-run-id",
      "rehearsal-workflow-path",
      "rehearsal-workflow-sha",
      "release-manifest-sha256",
      "tag-name",
      "tag-object",
    ];
    expect(Object.keys(verifyTag?.outputs ?? {}).sort()).toEqual(expectedOutputs.sort());
    expect(verifyTag?.permissions).toEqual({ actions: "read", contents: "read" });
    const parser = workflowStep(verifyTag!, "Verify exact signed annotated beta tag");
    const parserSource = String(parser.with?.script ?? "");
    expect(parserSource).toContain("verification.payload");
    expect(parserSource).not.toContain("tag.data.message");
    expect(parserSource).toContain('verification.reason !== "valid"');
    expect(parserSource).toContain("canonicalize");
    expect(parserSource).toContain("authorization-sha256");
    expect(parserSource).toContain(".github/workflows/kaji.rehearsal.yml");
    expect(parserSource).toContain("getWorkflowRun");
    expect(parserSource.match(/getArtifact/g)?.length).toBeGreaterThanOrEqual(2);

    const action = readYaml(".github/actions/verify-kaji-beta-tag/action.yml");
    const requiredInputs = [
      "authorization_sha256",
      "candidate_artifact_digest",
      "candidate_artifact_id",
      "candidate_artifact_name",
      "commit",
      "evidence_artifact_digest",
      "evidence_artifact_id",
      "evidence_artifact_name",
      "npm_tarball_name",
      "npm_tarball_sha256",
      "rehearsal_run_attempt",
      "rehearsal_run_id",
      "rehearsal_workflow_path",
      "rehearsal_workflow_sha",
      "release_manifest_sha256",
      "tag",
      "tag_object",
      "tagger_email",
      "token",
    ];
    expect(Object.keys((action.value.inputs as Record<string, unknown>) ?? {}).sort()).toEqual(
      requiredInputs.sort(),
    );
    expect(action.source).toContain("verification.payload");
    expect(action.source).not.toContain(".message");
    expect(action.source).toContain("X-GitHub-Api-Version: 2026-03-10");
    expect(action.source).toContain("actions/runs/$EXPECTED_REHEARSAL_RUN_ID");
    expect(action.source).toContain("actions/artifacts/$EXPECTED_CANDIDATE_ARTIFACT_ID");
    expect(action.source).toContain("actions/artifacts/$EXPECTED_EVIDENCE_ARTIFACT_ID");

    expect(workflow.jobs).not.toHaveProperty("publisher-preflight");
    expect(source.match(/environment:\s+kaji-beta-publish/g)).toHaveLength(1);
    expect(source).not.toContain("inputs.artifacts");
    const offlineSteps = workflow.jobs?.["offline-gates"]?.steps ?? [];
    const signedSourceIndex = offlineSteps.findIndex(
      (step) => step.name === "Resolve and authenticate signed rehearsal source artifacts",
    );
    const checkoutIndex = offlineSteps.findIndex((step) =>
      step.uses?.startsWith("actions/checkout@"),
    );
    const restoreIndex = offlineSteps.findIndex(
      (step) => step.name === "Restore authenticated signed source after the exact clean checkout",
    );
    expect(signedSourceIndex).toBeGreaterThanOrEqual(0);
    expect(checkoutIndex).toBeGreaterThan(signedSourceIndex);
    expect(restoreIndex).toBe(checkoutIndex + 1);
    expect(offlineSteps[signedSourceIndex]?.run).toContain(
      'signed_root="$RUNNER_TEMP/kaji-authenticated-signed-source"',
    );
    expect(offlineSteps[signedSourceIndex]?.run).not.toContain(
      ".artifacts/kaji-authorized-rehearsal",
    );
    expect(offlineSteps[checkoutIndex]?.with?.["persist-credentials"]).toBe(false);
    expect(offlineSteps[restoreIndex]?.run).toContain('[ ! -e "$destination_path" ]');
    const publish = workflow.jobs?.["publish-npm"];
    expect(publish?.needs).toEqual(["verify-tag", "supply-chain", "registry-preflight"]);
    expect(publish?.permissions).toEqual({
      actions: "read",
      contents: "read",
      "id-token": "write",
    });
    const releaseEvidence = workflow.jobs?.["release-evidence"];
    expect(releaseEvidence?.permissions).toEqual({ actions: "read", contents: "write" });
    for (const job of [publish, releaseEvidence]) {
      const reverify = (job?.steps ?? []).filter(
        (step) => step.uses === "./.github/actions/verify-kaji-beta-tag",
      );
      expect(reverify).toHaveLength(1);
      expect(Object.keys(reverify[0]?.with ?? {}).sort()).toEqual(requiredInputs.sort());
    }
    const credentialedSteps = Object.values(workflow.jobs ?? {}).flatMap((job) =>
      (job.steps ?? []).filter((step) => JSON.stringify(step).includes("secrets.NPM_TOKEN")),
    );
    expect(credentialedSteps.map((step) => step.name)).toEqual([
      "Verify exact npm publisher identity",
      "Publish exact npm beta with provenance",
    ]);
  });

  it("executes the exact signed-tag parser and composite reverifier on valid authorization", async () => {
    const fixture = signedBetaFixture();
    await expect(runSignedTagParser()).resolves.toMatchObject({
      "tag-name": fixture.expected.tagName,
      "tag-object": fixture.expected.tagObject,
      commit: fixture.expected.commit,
      "authorization-sha256": fixture.expected.authorizationSha256,
      "rehearsal-run-id": String(fixture.expected.runId),
      "candidate-artifact-id": String(fixture.expected.candidateArtifactId),
      "candidate-artifact-digest": fixture.expected.candidateArtifactDigest,
      "evidence-artifact-id": String(fixture.expected.evidenceArtifactId),
      "evidence-artifact-digest": fixture.expected.evidenceArtifactDigest,
      "release-manifest-sha256": fixture.expected.releaseManifestSha256,
      "npm-tarball-sha256": fixture.expected.npmTarballSha256,
    });
    const composite = runCompositeTagReverification();
    expect(composite.status, String(composite.stderr)).toBe(0);
    expect(composite.endpoints).toEqual([
      `repos/enkyuan/alloy/git/ref/tags/${fixture.expected.tagName}`,
      `repos/enkyuan/alloy/git/tags/${fixture.expected.tagObject}`,
      `repos/enkyuan/alloy/actions/runs/${fixture.expected.runId}`,
      `repos/enkyuan/alloy/actions/artifacts/${fixture.expected.candidateArtifactId}`,
      `repos/enkyuan/alloy/actions/artifacts/${fixture.expected.evidenceArtifactId}`,
    ]);
  });

  it.each(["2", "invalid", null])(
    "rejects signed-tag verification for non-fresh attempt %s",
    async (runAttempt) => {
      await expect(runSignedTagParser(undefined, runAttempt)).rejects.toThrow(
        "publish workflow identity differs from the exact beta.10 boundary",
      );
    },
  );

  it.each([
    [
      "unverified signature before invalid JSON",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.verified = false;
        fixture.tag.verification.payload = "not-json";
      },
    ],
    [
      "extra signed authorization field",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.payload = fixture.tag.verification.payload.replace(
          ',"schemaVersion":"1.0.0"}\n',
          ',"schemaVersion":"1.0.0","unexpected":true}\n',
        );
      },
    ],
    [
      "retargeted annotated tag ref",
      (fixture: SignedBetaFixture) => {
        fixture.ref.object.sha = "0".repeat(40);
      },
    ],
    [
      "rerun rehearsal",
      (fixture: SignedBetaFixture) => {
        fixture.run.run_attempt = 2;
      },
    ],
    [
      "mutated candidate REST digest",
      (fixture: SignedBetaFixture) => {
        fixture.candidate.digest = `sha256:${"0".repeat(64)}`;
      },
    ],
    [
      "commit absent from default branch",
      (fixture: SignedBetaFixture) => {
        fixture.comparison.merge_base_commit.sha = "0".repeat(40);
      },
    ],
  ] as const)("rejects hostile initial signed-tag mutation: %s", async (_label, mutate) => {
    await expect(runSignedTagParser(mutate)).rejects.toThrow();
  });

  it.each([
    [
      "signature",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.reason = "unknown_key";
      },
    ],
    [
      "signed body",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.payload = fixture.tag.verification.payload.replace(
          '"runAttempt":1',
          '"runAttempt":2',
        );
      },
    ],
    [
      "rehearsal terminal state",
      (fixture: SignedBetaFixture) => {
        fixture.run.conclusion = "failure";
      },
    ],
    [
      "candidate expiry",
      (fixture: SignedBetaFixture) => {
        fixture.candidate.expired = true;
      },
    ],
    [
      "evidence artifact run",
      (fixture: SignedBetaFixture) => {
        const workflowRun = fixture.evidence.workflow_run as Record<string, unknown>;
        workflowRun.id = fixture.expected.runId + 1;
      },
    ],
  ] as const)("rejects hostile composite signed-tag mutation: %s", (_label, mutate) => {
    const completed = runCompositeTagReverification(mutate);
    expect(completed.status).not.toBe(0);
  });

  it.each([
    [
      "invalid signature",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.reason = "unknown_key";
      },
    ],
    [
      "missing signature",
      (fixture: SignedBetaFixture) => {
        delete (fixture.tag.verification as unknown as Record<string, unknown>).signature;
      },
    ],
    [
      "invalid payload",
      (fixture: SignedBetaFixture) => {
        fixture.tag.verification.payload = "not-json";
      },
    ],
    [
      "missing payload",
      (fixture: SignedBetaFixture) => {
        delete (fixture.tag.verification as unknown as Record<string, unknown>).payload;
      },
    ],
  ] as const)(
    "makes zero run or artifact queries when signed tag authorization has %s",
    (_label, mutate) => {
      const completed = runCompositeTagReverification(mutate);
      expect(completed.status).not.toBe(0);
      expect(completed.endpoints).toEqual([
        `repos/enkyuan/alloy/git/ref/tags/kaji-v0.2.0-beta.10`,
        `repos/enkyuan/alloy/git/tags/${"a".repeat(40)}`,
      ]);
      expect(completed.endpoints.some((endpoint) => endpoint.includes("/actions/"))).toBe(false);
    },
  );

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "%s authenticates all onboarding output artifacts before any download",
    (workflowName) => {
      const fixture = onboardingBindingFixture(workflowName);
      const completed = runOnboardingBindingAuthentication(workflowName);
      expect(completed.status, String(completed.stderr)).toBe(0);
      expect(completed.endpoints).toEqual([
        `repos/enkyuan/alloy/actions/runs/${fixture.runId}`,
        ...onboardingArtifactKeys.map(
          (key) => `repos/enkyuan/alloy/actions/artifacts/${fixture.expected[key].id}`,
        ),
      ]);
      expect(completed.endpoints.some((endpoint) => endpoint.endsWith("/zip"))).toBe(false);

      const jobId = workflowName === "kaji.publish.yml" ? "supply-chain" : "candidate-evidence";
      const steps = readWorkflow(workflowName).workflow.jobs?.[jobId]?.steps ?? [];
      const authenticationIndex = steps.findIndex(
        (step) => step.name === "Authenticate exact onboarding artifact bindings before downloads",
      );
      const exactArtifactIds = onboardingArtifactKeys.map(
        (key) =>
          `\${{ needs.typescript-onboarding-evidence.outputs.${
            key === "producer" ? "producer" : key === "onboarding" ? "onboarding" : `${key}-source`
          }-artifact-id }}`,
      );
      const downloadIndexes = exactArtifactIds.map((artifactId) =>
        steps.findIndex(
          (step) =>
            step.uses?.startsWith("actions/download-artifact@") &&
            step.with?.["artifact-ids"] === artifactId,
        ),
      );
      expect(authenticationIndex).toBeGreaterThan(0);
      for (const [index, downloadIndex] of downloadIndexes.entries()) {
        expect(
          downloadIndex,
          `${workflowName}:${onboardingArtifactKeys[index]} download`,
        ).toBeGreaterThan(authenticationIndex + 1);
      }
      const rawStepName =
        workflowName === "kaji.publish.yml"
          ? "Download and authenticate current validator raw source archives"
          : "Download and authenticate validator raw source archives by exact ID";
      const rawIndex = steps.findIndex((step) => step.name === rawStepName);
      expect(rawIndex).toBe(authenticationIndex + 1);
      const rawRun = steps[rawIndex]?.run ?? "";
      for (const key of onboardingArtifactKeys) {
        expect(rawRun, `${workflowName}:${key} raw archive`).toContain(
          `${key}|$${key === "node22" ? "NODE22" : key === "node24" ? "NODE24" : key.toUpperCase()}_ID`,
        );
      }
      expect(rawRun).toContain('[ "$observed" = "$digest" ]');
    },
    30_000,
  );

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "%s rejects every hostile onboarding artifact metadata field before a ZIP download",
    (workflowName) => {
      const artifactMutations = [
        ["id", (artifact: Record<string, unknown>) => (artifact.id = 999_999)],
        ["name", (artifact: Record<string, unknown>) => (artifact.name = "wrong-name")],
        [
          "digest",
          (artifact: Record<string, unknown>) => (artifact.digest = `sha256:${"0".repeat(64)}`),
        ],
        ["expired", (artifact: Record<string, unknown>) => (artifact.expired = true)],
        ["size", (artifact: Record<string, unknown>) => (artifact.size_in_bytes = 0)],
        ["url", (artifact: Record<string, unknown>) => (artifact.url = "https://example.invalid")],
        [
          "archive-url",
          (artifact: Record<string, unknown>) =>
            (artifact.archive_download_url = "https://example.invalid/archive"),
        ],
        [
          "run-id",
          (artifact: Record<string, unknown>) => {
            (artifact.workflow_run as Record<string, unknown>).id = 999_999;
          },
        ],
        [
          "head-branch",
          (artifact: Record<string, unknown>) => {
            (artifact.workflow_run as Record<string, unknown>).head_branch = "wrong-ref";
          },
        ],
        [
          "head-sha",
          (artifact: Record<string, unknown>) => {
            (artifact.workflow_run as Record<string, unknown>).head_sha = "0".repeat(40);
          },
        ],
      ] as const;
      for (const key of onboardingArtifactKeys) {
        for (const [field, mutate] of artifactMutations) {
          const completed = runOnboardingBindingAuthentication(workflowName, (fixture) => {
            mutate(fixture.artifacts[key]);
          });
          expect(completed.status, `${workflowName}:${key}:${field}`).not.toBe(0);
          expect(
            completed.endpoints.some((endpoint) => endpoint.endsWith("/zip")),
            `${workflowName}:${key}:${field}`,
          ).toBe(false);
        }
      }
    },
    30_000,
  );

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "%s rejects invalid onboarding output bindings before any API download",
    (workflowName) => {
      for (const key of onboardingArtifactKeys) {
        const prefix =
          key === "node22" ? "NODE22" : key === "node24" ? "NODE24" : key.toUpperCase();
        for (const [field, value] of [
          [`${prefix}_ID`, "0"],
          [`${prefix}_ID`, "9007199254740992"],
          [`${prefix}_DIGEST`, `sha256:${"A".repeat(64)}`],
        ] as const) {
          const completed = runOnboardingBindingAuthentication(workflowName, (fixture) => {
            fixture.env[field] = value;
          });
          expect(completed.status, `${workflowName}:${key}:${field}:${value}`).not.toBe(0);
          expect(completed.endpoints, `${workflowName}:${key}:${field}:${value}`).toEqual([]);
        }
      }
    },
  );

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "%s rejects hostile current-run identity before artifact metadata or downloads",
    (workflowName) => {
      const runMutations = [
        ["id", (fixture: OnboardingBindingFixture) => (fixture.run.id = 999_999)],
        ["attempt", (fixture: OnboardingBindingFixture) => (fixture.run.run_attempt = 2)],
        ["event", (fixture: OnboardingBindingFixture) => (fixture.run.event = "schedule")],
        ["path", (fixture: OnboardingBindingFixture) => (fixture.run.path = "wrong.yml")],
        ["head-branch", (fixture: OnboardingBindingFixture) => (fixture.run.head_branch = "wrong")],
        [
          "head-sha",
          (fixture: OnboardingBindingFixture) => (fixture.run.head_sha = "0".repeat(40)),
        ],
      ] as const;
      const expectedRunEndpoint = `repos/enkyuan/alloy/actions/runs/${onboardingBindingFixture(workflowName).runId}`;
      for (const [field, mutate] of runMutations) {
        const completed = runOnboardingBindingAuthentication(workflowName, mutate);
        expect(completed.status, `${workflowName}:run:${field}`).not.toBe(0);
        expect(completed.endpoints, `${workflowName}:run:${field}`).toEqual([expectedRunEndpoint]);
      }
    },
  );

  it("authenticates raw signed rehearsal evidence before extraction and carrier fanout", () => {
    const offline = readWorkflow("kaji.publish.yml").workflow.jobs?.["offline-gates"];
    expect(offline).toBeDefined();
    const steps = offline?.steps ?? [];
    const offlineIndex = steps.findIndex((step) => step.id === "offline");
    const signedEvidenceIndex = steps.findIndex((step) => step.id === "signed-evidence");
    const signedCandidateIndex = steps.findIndex((step) => step.id === "signed-candidate");
    const carrierIndex = steps.findIndex((step) => step.id === "carrier");
    expect(signedEvidenceIndex).toBe(offlineIndex + 1);
    expect(signedCandidateIndex).toBe(signedEvidenceIndex + 1);
    expect(carrierIndex).toBe(signedCandidateIndex + 1);
    const signedEvidence = steps[signedEvidenceIndex]!;
    expect(signedEvidence.name).toBe(
      "Revalidate exact signed rehearsal evidence before carrier fanout",
    );
    expect(signedEvidence.if).toBe("${{ steps.offline.outcome == 'success' }}");
    expect(steps[carrierIndex]?.if).toBe(
      "${{ steps.offline.outcome == 'success' && steps.signed-evidence.outcome == 'success' && steps.signed-candidate.outcome == 'success' }}",
    );
    for (const fragment of [
      "kaji/scripts/validate_release_evidence.py",
      "--mode rehearsal",
      "--artifacts-dir .artifacts/kaji-release",
      "--producer-archive .artifacts/kaji-authorized-rehearsal-raw/candidate.zip",
      "--node22-source-archive .artifacts/kaji-authorized-rehearsal-node-22/source.zip",
      "--node24-source-archive .artifacts/kaji-authorized-rehearsal-node-24/source.zip",
      '--expected-commit "$RELEASE_COMMIT"',
      '--workflow-run "https://github.com/enkyuan/alloy/actions/runs/$REHEARSAL_RUN_ID"',
      '--workflow-run-attempt "$REHEARSAL_RUN_ATTEMPT"',
      '--release-artifact-id "$SIGNED_CANDIDATE_ID"',
      '--release-artifact-digest "$SIGNED_CANDIDATE_DIGEST"',
      '--node22-source-artifact-id "$SIGNED_NODE22_ID"',
      '--node22-source-artifact-digest "$SIGNED_NODE22_DIGEST"',
      '--node24-source-artifact-id "$SIGNED_NODE24_ID"',
      '--node24-source-artifact-digest "$SIGNED_NODE24_DIGEST"',
      "--signed-evidence-archive .artifacts/kaji-authorized-rehearsal-evidence/source.zip",
      '--signed-evidence-artifact-id "$SIGNED_EVIDENCE_ID"',
      '--signed-evidence-artifact-digest "$SIGNED_EVIDENCE_DIGEST"',
      '--workspace "$GITHUB_WORKSPACE"',
      "--output .artifacts/kaji-offline-evidence/signed-rehearsal-revalidation.json",
    ]) {
      expect(signedEvidence.run, fragment).toContain(fragment);
    }
    for (const forbidden of [
      "--onboarding-status",
      "--onboarding-evidence",
      "--python-compat-311",
      "--python-compat-314",
      "--node-compat-22",
      "--node-compat-24",
      "--performance-status",
      "--benchmark-results",
      "--soak-results",
      "--performance-image-data",
      "--provider-evidence",
      "--signed-node22-source-artifact-id",
      "--signed-node22-source-artifact-digest",
      "--signed-node24-source-artifact-id",
      "--signed-node24-source-artifact-digest",
      "unzip",
      "cmp --silent",
    ]) {
      expect(signedEvidence.run, forbidden).not.toContain(forbidden);
    }
    for (const step of steps.slice(0, signedCandidateIndex)) {
      expect(step.run ?? "", step.name).not.toContain("unzip");
      expect(step.run ?? "", step.name).not.toContain("zipfile.ZipFile");
    }

    const signedCandidate = steps[signedCandidateIndex]!;
    expect(signedCandidate.name).toBe(
      "Extract authenticated signed candidate only after rehearsal revalidation",
    );
    expect(signedCandidate.if).toBe("${{ steps.signed-evidence.outcome == 'success' }}");
    for (const fragment of [
      '[ "sha256:$(sha256sum "$archive" | cut -d\' \' -f1)" = "$SIGNED_CANDIDATE_DIGEST" ]',
      "zipfile.ZipFile",
      '"SHA256SUMS"',
      '"kaji-sdk-0.2.0-beta.10.tgz"',
      '"kaji_sdk-0.2.0b1-py3-none-any.whl"',
      '"kaji_sdk-0.2.0b1.tar.gz"',
      '"manifest.json"',
      "len(members) != len(expected)",
      "len(names) != len(set(names))",
      "stat.S_ISLNK(mode)",
    ]) {
      expect(signedCandidate.run, fragment).toContain(fragment);
    }

    const carrierRun = steps[carrierIndex]?.run ?? "";
    expect(carrierRun.indexOf('--artifacts-dir "$signed"')).toBeLessThan(
      carrierRun.indexOf("cp .artifacts/kaji-authorized-rehearsal-raw/candidate.zip"),
    );
  });

  it("gates rehearsal and publication on deterministic protected TypeScript onboarding", () => {
    const rehearsal = readWorkflow("kaji.rehearsal.yml");
    const publish = readWorkflow("kaji.publish.yml");

    for (const [workflowName, { source, workflow }, terminalJobs] of [
      ["kaji.rehearsal.yml", rehearsal, ["keyed-proof", "candidate-evidence"]],
      [
        "kaji.publish.yml",
        publish,
        [
          "keyed-proof",
          "supply-chain",
          "registry-preflight",
          "publish-npm",
          "publication-status",
          "publication-incident",
          "release-evidence",
        ],
      ],
    ] as const) {
      const jobs = workflow.jobs ?? {};
      expect(jobs, workflowName).not.toHaveProperty("tthw-evidence");
      expect(source, workflowName).not.toContain("KAJI_TTHW_EVIDENCE_JSON");
      expect(source, workflowName).not.toContain("validate_tthw_evidence.py");
      expect(jobs["typescript-onboarding-archive-calibration"]?.environment).toBeUndefined();
      expect(jobs["typescript-onboarding-evidence"]?.environment).toBe("kaji-beta-onboarding");
      expect(jobs["keyed-proof"]?.environment).toBe("kaji-beta");
      for (const jobId of terminalJobs) {
        expect(
          dependencyClosure(workflow, jobId),
          `${workflowName}:${jobId}: onboarding closure`,
        ).toContain("typescript-onboarding-evidence");
      }
    }

    const classifier = publish.workflow.jobs?.["publication-status"]?.steps?.find(
      (step) => step.name === "Reduce monotonic publication state",
    );
    expect(classifier?.run).toContain('[ "$PYPI_STATE" = absent ]');
    expect(classifier?.run).toContain('[ "$NPM_STATE" = absent ]');
    expect(classifier?.run).toContain('[ "$REGISTRY_VERIFICATION" = not_run ]');
    expect(classifier?.run).toContain('[ "$NPM_PUBLISH_RESULT" = skipped ]');
    expect(classifier?.run).toContain("--target npm");
    expect(classifier?.run).toContain("npm_byte_verified");
  });

  it("documents the protected npm-only onboarding approval and fresh-token stop", () => {
    const runbookSource = readFileSync(resolve(repositoryRoot, "docs/kaji/releasing.md"), "utf8");
    const runbook = runbookSource.replace(/\s+/gu, " ");
    const orderedSteps = [
      "Immutable beta.9 run `30726249929` failed closed before `npm publish`",
      "Dispatch the rehearsal at ref `main`; never dispatch a raw SHA",
      "The calibration must be terminal success before `typescript-onboarding-evidence`",
      "Query the complete current-run artifact collection",
      "Run the approved helper first without `--approve`",
      "Only after that command succeeds, rerun the identical command with `--approve` appended",
      "Do not approve onboarding manually in the Actions UI",
      "Require the protected onboarding aggregate",
      "Approve the later, distinct `kaji-beta` deployment separately",
      "Stop here until the operator explicitly confirms a fresh `NPM_TOKEN`",
    ];
    const positions = orderedSteps.map((step) => runbook.indexOf(step));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((left, right) => left - right));

    for (const authority of [
      "`kaji-beta-onboarding` protects only the deterministic TypeScript onboarding aggregate",
      "`kaji-beta` protects mandatory keyed OpenAI proof",
      "`kaji-beta-publish` protects the sole final npm write",
      "It must not contain a provider key",
      "Do not inspect, copy, or test the secret locally",
      "Do not inspect or test the secret",
      "as its first credentialed action and fails closed before publication",
    ]) {
      expect(runbook).toContain(authority);
    }
    for (const binding of [
      "actions/runs/$REHEARSAL_RUN_ID/artifacts?per_page=100",
      "actions/artifacts/$PRODUCER_ARTIFACT_ID/zip",
      "actions/artifacts/$NODE22_ARTIFACT_ID/zip",
      "actions/artifacts/$NODE24_ARTIFACT_ID/zip",
      "kaji/scripts/approve_typescript_onboarding_gate.py gate",
      "--mode rehearsal",
      '--run-id "$REHEARSAL_RUN_ID"',
      '--expected-commit "$REVIEWED_COMMIT"',
      '--producer-artifact-id "$PRODUCER_ARTIFACT_ID"',
      '--producer-artifact-digest "$PRODUCER_ARTIFACT_DIGEST"',
      '--node22-artifact-id "$NODE22_ARTIFACT_ID"',
      '--node22-artifact-digest "$NODE22_ARTIFACT_DIGEST"',
      '--node24-artifact-id "$NODE24_ARTIFACT_ID"',
      '--node24-artifact-digest "$NODE24_ARTIFACT_DIGEST"',
    ]) {
      expect(runbookSource).toContain(binding);
    }
    expect(runbookSource).not.toContain("gh secret set");
    expect(runbook).toContain(
      "It does not claim five human participants, macOS or arm64 onboarding",
    );
    expect(runbook).toContain(
      "The separate paired benchmark and soak receipts retain their own reviewed runner claims",
    );
  });

  it("binds the current TypeScript candidate to beta.10 and preserves prior incident history", () => {
    const packageManifest = JSON.parse(readFileSync(resolve("package.json"), "utf8")) as {
      name: string;
      version: string;
      main: string;
      module: string;
      types: string;
      exports: { ".": { require: { types: string } } };
    };
    const sourceVersion = readFileSync(resolve("src/index.ts"), "utf8").match(
      /export const VERSION = "([^"]+)"/,
    );
    const packageSmokeVersion = readFileSync(resolve("scripts/smoke_package.mts"), "utf8").match(
      /const PACKAGE_VERSION = "([^"]+)"/,
    );
    const tarball = npmPackBasenameV1(
      handoffSchema(),
      packageManifest.name,
      packageManifest.version,
    );

    expect(packageManifest.name).toBe("kaji-sdk");
    expect(packageManifest.version).toBe("0.2.0-beta.10");
    expect(packageManifest.version).not.toBe("0.2.0-beta.2");
    expect(packageManifest.version).not.toBe("0.2.0-beta.4");
    expect(sourceVersion?.[1]).toBe(packageManifest.version);
    expect(packageSmokeVersion?.[1]).toBe(packageManifest.version);
    expect(tarball).toBe(`kaji-sdk-${packageManifest.version}.tgz`);
    expect(tarball).toBe("kaji-sdk-0.2.0-beta.10.tgz");
    if (existsSync(resolve("dist"))) {
      const exportedIdentityPaths = new Set([
        packageManifest.main,
        packageManifest.module,
        packageManifest.types,
        packageManifest.exports["."].require.types,
      ]);
      expect(exportedIdentityPaths.size).toBe(4);
      for (const relativePath of exportedIdentityPaths) {
        const outputPath = resolve(relativePath);
        expect(existsSync(outputPath), relativePath).toBe(true);
        const output = readFileSync(outputPath, "utf8");
        expect(output, relativePath).toMatch(/(?:var|declare const) VERSION = "0\.2\.0-beta\.10"/);
        expect(output, relativePath).not.toContain("0.2.0-beta.8");
      }
    }
    for (const name of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const { source } = readWorkflow(name);
      expect(source).toContain(tarball);
      expect(source).not.toContain("0.2.0-beta.2");
      expect(source).not.toContain("0.2.0-beta.4");
      expect(source).not.toContain("0.2.0-beta.5");
      expect(source).not.toContain("0.2.0-beta.6");
      expect(source).not.toContain("0.2.0-beta.7");
      expect(source).not.toContain("0.2.0-beta.8");
    }

    const changelog = readFileSync(resolve("CHANGELOG.md"), "utf8");
    expect(changelog).toContain("## [0.2.0-beta.10] - 2026-08-01");
    const beta9History = changelog
      .split("## [0.2.0-beta.9] - 2026-07-27", 2)[1]!
      .split("## [0.2.0-beta.8]", 1)[0]!
      .replace(/\s+/g, " ");
    for (const evidence of [
      "Signed tag `kaji-v0.2.0-beta.9` triggered protected run `30726249929`",
      "`9215c8c28b359c94ae8d85f0786fe4b4e7407123`",
      "`npm_whoami_output_invalid`",
      "npm and PyPI remained absent",
      "cannot be reused for beta.10",
    ]) {
      expect(beta9History).toContain(evidence);
    }
    const beta8History = changelog
      .split("## [0.2.0-beta.8] - 2026-07-27", 2)[1]!
      .split("## [0.2.0-beta.7]", 1)[0]!
      .replace(/\s+/g, " ");
    for (const evidence of [
      "Signed tag `kaji-v0.2.0-beta.8` triggered protected run `30296132900`",
      "`4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e`",
      "`KAJI_TTHW_EVIDENCE_JSON` was empty",
      "Provider proof, registry and publisher preflight, and npm publication were skipped",
      "npm and PyPI remained absent",
      "cannot be reused for beta.9",
      "rehearsal `30291287818` is terminal cancelled",
      "cannot be reused as beta.9 evidence",
    ]) {
      expect(beta8History).toContain(evidence);
    }
    expect(changelog).toMatch(
      /## \[0\.2\.0-beta\.7\][\s\S]*protected run `30265105639`[\s\S]*inconclusive[\s\S]*npm and PyPI remained absent/i,
    );
    expect(changelog).toMatch(
      /## \[0\.2\.0-beta\.6\][\s\S]*protected run `30230234051`[\s\S]*inconclusive[\s\S]*registry remained untouched/i,
    );
    const runbook = readFileSync(resolve(repositoryRoot, "docs/kaji/releasing.md"), "utf8");
    expect(runbook).toContain("run `30230234051`");
    expect(runbook).toContain("`1.2059658457`, `1.0034830060`, and `1.0137219363`");
    expect(runbook.replace(/\s+/g, " ")).toContain(
      "TTHW, provider proof, publisher preflight, and npm publication were skipped",
    );
    expect(runbook).toContain("run `30265105639`");
    expect(runbook).toContain("`0.9805314383`, `0.9756823917`,");
    expect(runbook).toContain("and `1.2290586651`");
    expect(runbook.replace(/\s+/g, " ")).toContain("recovery requires the new beta.8 attempt");
    expect(runbook).toContain("run `30296132900`");
    expect(runbook).toContain("`KAJI_TTHW_EVIDENCE_JSON` was empty");
    expect(runbook).toContain("five-user TTHW validation did not start");
    expect(runbook.replace(/\s+/g, " ")).toContain("recovery requires the new beta.9 attempt");
    expect(runbook).toContain("rehearsal `30291287818` is");
    expect(runbook).toContain("terminal cancelled and cannot be reused as beta.9 evidence");
  });

  it("smokes compatibility matrices only from verified producer artifacts", () => {
    const rehearsal = readWorkflow("kaji.rehearsal.yml").workflow;
    const publish = readWorkflow("kaji.publish.yml").workflow;

    for (const [workflow, producer] of [
      [rehearsal, "offline-release"],
      [publish, "offline-gates"],
    ] as const) {
      for (const [jobId, smokeScript] of [
        ["python-compat", "kaji/scripts/release_smoke.py"],
        ["node-compat", "kaji/ts/scripts/smoke_package.mts"],
      ] as const) {
        const job = workflow.jobs?.[jobId];
        expect(job, jobId).toBeDefined();
        expect(dependencyClosure(workflow, jobId)).toContain(producer);
        const steps = job?.steps ?? [];
        const checkout = steps.findIndex((step) => step.uses?.startsWith("actions/checkout@"));
        const initialize = steps.findIndex(
          (step) => step.name === "Initialize compatibility receipt before setup",
        );
        const initialUpload = steps.findIndex(
          (step) => step.name === "Retain initial not-run compatibility receipt",
        );
        const download = steps.findIndex((step) =>
          step.uses?.startsWith("actions/download-artifact@"),
        );
        const verify = steps.findIndex((step) => step.run?.includes("verify_release_artifacts.py"));
        const smoke = steps.findIndex((step) => step.run?.includes(smokeScript));
        const normalizerName =
          jobId === "node-compat"
            ? "Finalize closed protected Node receipt"
            : "Normalize compatibility receipt";
        const normalize = steps.findIndex((step) => step.name === normalizerName);
        const finalUpload = steps.findIndex(
          (step) => step.name === "Retain final compatibility receipt",
        );
        expect(initialize, `${jobId}: initialize`).toBeGreaterThanOrEqual(0);
        expect(initialize, `${jobId}: initialize before initial upload`).toBeLessThan(
          initialUpload,
        );
        expect(initialUpload, `${jobId}: initial upload before checkout`).toBeLessThan(checkout);
        expect(download, `${jobId}: download`).toBeGreaterThan(checkout);
        expect(verify, `${jobId}: verify`).toBeGreaterThan(download);
        expect(smoke, `${jobId}: smoke`).toBeGreaterThan(verify);
        expect(normalize, `${jobId}: normalize`).toBeGreaterThan(smoke);
        expect(finalUpload, `${jobId}: final upload`).toBeGreaterThan(normalize);
        expect(JSON.stringify(job?.env ?? {})).not.toContain("${{ runner.");
        if (jobId === "node-compat") {
          expect(steps[download]?.with).toEqual({
            "artifact-ids": `\${{ needs.${producer}.outputs.artifact-id }}`,
            path: ".artifacts/kaji-release",
            "merge-multiple": true,
            "github-token": "${{ github.token }}",
          });
        } else {
          expect(steps[download]?.with).toMatchObject({
            name: "kaji-beta-artifacts",
            path: ".artifacts/kaji-release",
          });
        }
        expect(steps[verify]?.run).toContain("--expected-commit");
        expect(steps[smoke]?.run).toContain("--output");
        if (jobId === "python-compat") {
          expect(steps[smoke]?.run).toContain("--artifacts-dir .artifacts/kaji-release");
        } else {
          expect(steps[smoke]?.run).toContain(
            "--release-manifest .artifacts/kaji-release/manifest.json",
          );
          expect(steps[smoke]?.run).toContain("--expected-commit");
        }
        expect(steps[normalize]?.if).toBe("${{ always() }}");
        if (jobId === "python-compat") {
          expect(steps[normalize]?.run).toContain('conclusion == "passed"');
          expect(steps[normalize]?.run).toContain('conclusion == "failed"');
          expect(steps[normalize]?.run).toContain("compatibility_receipt_not_terminal");
          expect(steps[normalize]?.run).toContain(".timings");
          expect(steps[normalize]?.run).toContain('keys == ["sdist", "wheel"]');
          expect(steps[normalize]?.run).toContain('keys == ["bun", "npm"]');
          expect(steps[normalize]?.run).toContain("9007199254740991");
        } else {
          expect(steps[normalize]?.run).toContain("assertClosedOrdinaryReceipt");
          expect(steps[normalize]?.run).toContain("assertProtectedOrdinaryReceiptForWorkflow");
          expect(steps[normalize]?.run).toContain('document.conclusion !== "passed"');
          expect(steps[normalize]?.run).toContain("failure_code=artifact_identity_failed");
          expect(steps[normalize]?.run).toContain("failure_code=node_smoke_failed");
        }
        const source = steps.map((step) => step.run ?? "").join("\n");
        expect(source).not.toContain("uv build");
        expect(source).not.toContain("npm pack");
        expect(source).not.toContain("bun run package:smoke");
        const uploads = steps.filter((step) => step.uses?.startsWith("actions/upload-artifact@"));
        const runtime = jobId === "python-compat" ? "python" : "node";
        const version = jobId === "python-compat" ? "python-version" : "node-version";
        const matrixExpression = `\${{ matrix.${version} }}`;
        const artifactName = `kaji-${runtime}-compat-${matrixExpression}`;
        const receiptPath = `\${{ runner.temp }}/kaji-${runtime}-compat-${matrixExpression}`;
        expect(uploads).toHaveLength(2);
        expect(uploads.map((step) => step.with?.name)).toEqual([
          `${artifactName}-initial`,
          artifactName,
        ]);
        expect(uploads[0]?.if).toBeUndefined();
        expect(uploads[1]?.if).toBe("${{ always() }}");
        expect(uploads.map((step) => step.with?.path)).toEqual([receiptPath, receiptPath]);
        expect(steps[initialize]?.env?.KAJI_COMPAT_RECEIPT_DIR).toBe(receiptPath);
        expect(steps[smoke]?.env?.KAJI_COMPAT_RECEIPT_DIR).toBe(receiptPath);
        expect(steps[normalize]?.env?.KAJI_COMPAT_RECEIPT_DIR).toBe(receiptPath);
      }
    }
  });

  it("pins protected Node onboarding to exact hosted runner/runtime cells", () => {
    for (const workflowName of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const workflow = readWorkflow(workflowName).workflow;
      const job = workflow.jobs?.["node-compat"];

      expect(job?.["runs-on"]).toBe("${{ matrix.runner }}");
      expect(job?.permissions).toEqual({ actions: "read", contents: "read" });
      expect(job?.strategy?.matrix).toEqual({
        include: [
          { "node-version": "22", runner: "ubuntu-22.04" },
          { "node-version": "24", runner: "ubuntu-24.04" },
        ],
      });
    }
  });

  it("resolves Node producer artifacts by authenticated API identity before ID download", () => {
    for (const [workflowName, producer] of [
      ["kaji.rehearsal.yml", "offline-release"],
      ["kaji.publish.yml", "offline-gates"],
    ] as const) {
      const workflow = readWorkflow(workflowName).workflow;
      const assertProtectedNodeJob = (job: WorkflowJob) => {
        expect(job.if).toBe("${{ github.run_attempt == 1 }}");
        expect(job["runs-on"]).toBe("${{ matrix.runner }}");
        expect(job.permissions).toEqual({ actions: "read", contents: "read" });
        expect(job.strategy?.matrix).toEqual({
          include: [
            { "node-version": "22", runner: "ubuntu-22.04" },
            { "node-version": "24", runner: "ubuntu-24.04" },
          ],
        });
        expect(JSON.stringify(job.env ?? {})).not.toContain("github.token");
        const steps = job.steps ?? [];
        const checkout = steps.findIndex((step) => step.uses?.startsWith("actions/checkout@"));
        const lookup = steps.findIndex((step) => step.uses?.startsWith("actions/github-script@"));
        const download = steps.findIndex((step) =>
          step.uses?.startsWith("actions/download-artifact@"),
        );
        const verify = steps.findIndex((step) => step.run?.includes("verify_release_artifacts.py"));
        const smoke = steps.findIndex((step) =>
          step.run?.includes("kaji/ts/scripts/smoke_package.mts"),
        );
        const finalizer = steps.findIndex(
          (step) => step.name === "Finalize closed protected Node receipt",
        );
        const upload = steps.findIndex(
          (step) =>
            step.uses?.startsWith("actions/upload-artifact@") &&
            step.with?.name === "kaji-node-compat-${{ matrix.node-version }}",
        );
        expect(lookup, workflowName).toBeGreaterThanOrEqual(0);
        expect(download, workflowName).toBeGreaterThan(lookup);
        expect(verify, workflowName).toBeGreaterThan(download);
        expect(smoke, workflowName).toBeGreaterThan(verify);
        expect(finalizer, workflowName).toBeGreaterThan(smoke);
        expect(upload, workflowName).toBeGreaterThan(finalizer);
        expect(steps[checkout]?.with?.["persist-credentials"]).toBe(false);
        expect(steps[lookup]?.with?.["github-token"]).toBe("${{ github.token }}");
        expect(steps[lookup]?.env).toMatchObject({
          RUN_ATTEMPT: "${{ github.run_attempt }}",
        });
        const lookupScript = String(steps[lookup]?.with?.script ?? "");
        for (const required of [
          "getArtifact",
          "getWorkflowRunAttempt",
          'artifact.name !== "kaji-beta-artifacts"',
          "artifact.id !== artifactId",
          "artifact.digest !== `sha256:${expectedDigest}`",
          "artifact.expired !== false",
          "artifact.workflow_run?.id !== context.runId",
          "artifact.workflow_run?.head_sha !== expectedCommit",
          "const runAttempt = Number(process.env.RUN_ATTEMPT)",
          "!Number.isSafeInteger(runAttempt)",
          "runAttempt !== 1",
          "attempt_number: 1",
          "producerRun.run_attempt !== 1",
          "producerRun.head_sha !== expectedCommit",
        ]) {
          expect(lookupScript, `${workflowName}:${required}`).toContain(required);
        }
        expect(steps[download]?.with).toEqual({
          "artifact-ids": `\${{ needs.${producer}.outputs.artifact-id }}`,
          path: ".artifacts/kaji-release",
          "merge-multiple": true,
          "github-token": "${{ github.token }}",
        });
        expect(steps[download]?.with).not.toHaveProperty("name");
        expect(steps[download]?.with).not.toHaveProperty("pattern");
        const smokeRun = steps[smoke]?.run ?? "";
        for (const required of [
          "--protected",
          "--expected-node-major",
          "--configured-runner-label",
          "--producer-artifact-id",
          "--producer-artifact-digest",
          "--release-manifest",
          "--expected-commit",
        ]) {
          expect(smokeRun).toContain(required);
        }
        const finalizerRun = steps[finalizer]?.run ?? "";
        expect(steps[finalizer]?.env).toMatchObject({
          KAJI_COMPAT_CANDIDATE_TARBALL: ".artifacts/kaji-release/kaji-sdk-0.2.0-beta.10.tgz",
          KAJI_COMPAT_RUNNER_LABEL: "${{ matrix.runner }}",
          KAJI_COMPAT_PRODUCER_ARTIFACT_ID: `\${{ needs.${producer}.outputs.artifact-id }}`,
          KAJI_COMPAT_PRODUCER_ARTIFACT_DIGEST: `\${{ needs.${producer}.outputs.artifact-digest }}`,
        });
        expect(finalizerRun).toContain("assertProtectedOrdinaryReceiptForWorkflow");
        expect(finalizerRun).toContain("KAJI_COMPAT_CANDIDATE_TARBALL");
        expect(finalizerRun).toContain("KAJI_COMPAT_PRODUCER_ARTIFACT_ID");
        expect(finalizerRun).toContain("KAJI_COMPAT_PRODUCER_ARTIFACT_DIGEST");
        expect(finalizerRun).toContain("GITHUB_WORKFLOW_REF");
        expect(finalizerRun).toContain("GITHUB_WORKFLOW_SHA");
        expect(finalizerRun).toContain('schemaVersion: 2, executionMode: "protected"');
        expect(finalizerRun).toContain("githubPackageProofs: {}, onboardingProofs: {}");
        for (const [index, step] of steps.entries()) {
          if (index === lookup || index === download) continue;
          expect(JSON.stringify(step), `${workflowName}:token step ${index}`).not.toContain(
            "github.token",
          );
        }
      };

      const job = workflow.jobs?.["node-compat"];
      expect(job).toBeDefined();
      assertProtectedNodeJob(job!);

      const rejectMutation = (mutate: (job: WorkflowJob) => void) => {
        const candidate = structuredClone(job!);
        mutate(candidate);
        expect(() => assertProtectedNodeJob(candidate)).toThrow();
      };
      rejectMutation((candidate) => {
        candidate["runs-on"] = "ubuntu-latest";
      });
      rejectMutation((candidate) => {
        candidate.if = "${{ always() }}";
      });
      rejectMutation((candidate) => {
        const checkout = candidate.steps!.find((step) =>
          step.uses?.startsWith("actions/checkout@"),
        )!;
        checkout.with = { ...checkout.with, "persist-credentials": true };
      });
      rejectMutation((candidate) => {
        candidate.permissions = { contents: "read" };
      });
      rejectMutation((candidate) => {
        candidate.strategy = {
          failFast: false,
          matrix: { "node-version": ["22", "24"], runner: ["ubuntu-22.04", "ubuntu-24.04"] },
        };
      });
      rejectMutation((candidate) => {
        candidate.env = { ...candidate.env, GITHUB_TOKEN: "${{ github.token }}" };
      });
      rejectMutation((candidate) => {
        const lookup = candidate.steps!.find((step) =>
          step.uses?.startsWith("actions/github-script@"),
        )!;
        lookup.env = { ...lookup.env };
        delete lookup.env.RUN_ATTEMPT;
      });
      for (const fragment of [
        "getArtifact",
        "getWorkflowRunAttempt",
        'artifact.name !== "kaji-beta-artifacts"',
        "artifact.digest !== `sha256:${expectedDigest}`",
        "artifact.expired !== false",
        "artifact.workflow_run?.head_sha !== expectedCommit",
        "const runAttempt = Number(process.env.RUN_ATTEMPT)",
        "!Number.isSafeInteger(runAttempt)",
        "runAttempt !== 1",
        "attempt_number: 1",
        "producerRun.run_attempt !== 1",
      ]) {
        rejectMutation((candidate) => {
          const lookup = candidate.steps!.find((step) =>
            step.uses?.startsWith("actions/github-script@"),
          )!;
          lookup.with = {
            ...lookup.with,
            script: String(lookup.with?.script ?? "").replace(fragment, "weakened_check"),
          };
        });
      }
      rejectMutation((candidate) => {
        const download = candidate.steps!.find((step) =>
          step.uses?.startsWith("actions/download-artifact@"),
        )!;
        download.with = {
          name: "kaji-beta-artifacts",
          path: ".artifacts/kaji-release",
        };
      });
      rejectMutation((candidate) => {
        const steps = candidate.steps!;
        const lookup = steps.findIndex((step) => step.uses?.startsWith("actions/github-script@"));
        const download = steps.findIndex((step) =>
          step.uses?.startsWith("actions/download-artifact@"),
        );
        [steps[lookup], steps[download]] = [steps[download]!, steps[lookup]!];
      });
    }
  });

  it("writes executable closed v2 initial and fallback Node receipts", () => {
    const expectedCommit = "a".repeat(40);
    const failureCases = [
      {
        expectedFailureCode: "artifact_identity_failed",
        outcomes: {
          CHECKOUT_OUTCOME: "failure",
          RUNTIME_SETUP_OUTCOME: "skipped",
          DEPENDENCY_SETUP_OUTCOME: "skipped",
          LOOKUP_OUTCOME: "skipped",
          DOWNLOAD_OUTCOME: "skipped",
          VERIFICATION_OUTCOME: "skipped",
          SMOKE_OUTCOME: "skipped",
        },
      },
      {
        expectedFailureCode: "node_smoke_failed",
        outcomes: {
          CHECKOUT_OUTCOME: "success",
          RUNTIME_SETUP_OUTCOME: "success",
          DEPENDENCY_SETUP_OUTCOME: "success",
          LOOKUP_OUTCOME: "success",
          DOWNLOAD_OUTCOME: "success",
          VERIFICATION_OUTCOME: "success",
          SMOKE_OUTCOME: "failure",
        },
      },
    ] as const;

    for (const workflowName of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const job = readWorkflow(workflowName).workflow.jobs?.["node-compat"];
      expect(job).toBeDefined();
      const initialize = workflowStep(job!, "Initialize compatibility receipt before setup");
      const finalizer = workflowStep(job!, "Finalize closed protected Node receipt");
      const root = mkdtempSync(join(tmpdir(), "kaji-node-receipt-writer-"));
      try {
        const environment = {
          ...process.env,
          EXPECTED_COMMIT: expectedCommit,
          KAJI_COMPAT_RECEIPT_DIR: root,
          KAJI_COMPAT_RUNTIME_VERSION: "24",
        };
        const initialized = spawnSync("bash", ["-c", initialize.run!], {
          cwd: repositoryRoot,
          encoding: "utf8",
          env: environment,
        });
        expect(initialized.status, initialized.stderr).toBe(0);
        expect(() =>
          assertClosedOrdinaryReceipt(
            JSON.parse(readFileSync(join(root, "compatibility-receipt.json"), "utf8")),
            "protected",
          ),
        ).not.toThrow();

        for (const { expectedFailureCode, outcomes } of failureCases) {
          writeFileSync(
            join(root, "compatibility-receipt.json"),
            JSON.stringify({ conclusion: "untrusted" }),
          );
          const finalized = spawnSync("bash", ["-c", finalizer.run!], {
            cwd: repositoryRoot,
            encoding: "utf8",
            env: {
              ...environment,
              ...outcomes,
            },
          });
          expect(finalized.status, `${workflowName}:${expectedFailureCode}`).toBe(1);
          const fallback = JSON.parse(
            readFileSync(join(root, "compatibility-receipt.json"), "utf8"),
          );
          expect(fallback.failureCode).toBe(expectedFailureCode);
          expect(fallback.conclusion).toBe("failed");
          expect(() => assertClosedOrdinaryReceipt(fallback, "protected")).not.toThrow();
        }
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    }
  });

  it("keeps supplied-artifact handoff children token-free and nonpacking", () => {
    const smoke = readFileSync(
      resolve(repositoryRoot, "kaji/ts/scripts/smoke_package.mts"),
      "utf8",
    );
    const installedProof = readFileSync(
      resolve(repositoryRoot, "kaji/ts/scripts/installed-github-smoke.mts"),
      "utf8",
    );
    const handoff = smoke.slice(
      smoke.indexOf("async function runHandoffCommand("),
      smoke.indexOf("function readManifest("),
    );
    const dispatcher = smoke.slice(
      smoke.indexOf("async function runSuppliedTarballHandoff("),
      smoke.indexOf("function readManifest("),
    );

    for (const token of ["GH_TOKEN", "GITHUB_TOKEN", "NODE_AUTH_TOKEN", "NPM_TOKEN"]) {
      expect(smoke).toContain(`"${token}"`);
      expect(installedProof).toContain(`"${token}" in process.env`);
    }
    expect(handoff).toContain("const childEnvironment = tokenFreeHandoffEnvironment(environment)");
    expect(handoff).toContain("PROTECTED_HANDOFF_TOKENS.some");
    expect(handoff).toContain("childEnvironment, timeoutMs");
    expect(smoke).toContain("function safeHandoffDiagnostic(output: string): string");
    expect(smoke).toContain('"[redacted-token]"');
    expect(smoke).toContain('"$1$2[redacted]"');
    expect(handoff).toContain("npm_config_userconfig: userConfig");
    expect(handoff).toContain('npm_config_registry: "http://127.0.0.1:9"');
    expect(handoff).toContain('BUN_CONFIG_REGISTRY: "http://127.0.0.1:9"');
    expect(handoff).toContain(
      '["install", "--production", "--ignore-scripts", "--omit=dev", "--offline"]',
    );
    expect(smoke).not.toContain("https://registry.npmjs.org");
    expect(handoff).not.toContain('"npm", ["pack"');
    expect(handoff).not.toContain('"run", "build"');
    expect(dispatcher.indexOf("const digest = sha256(tarball)")).toBeGreaterThanOrEqual(0);
    expect(dispatcher.indexOf("const digest = sha256(tarball)")).toBeLessThan(
      dispatcher.indexOf("await runArtifactContractHandoff("),
    );
    expect(dispatcher.indexOf("const digest = sha256(tarball)")).toBeLessThan(
      dispatcher.indexOf("await runNodeHandoff("),
    );
  });

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "keeps runner contexts out of every job-level environment in %s",
    (workflowName) => {
      const jobs = readWorkflow(workflowName).workflow.jobs ?? {};
      for (const [jobId, job] of Object.entries(jobs)) {
        expect(JSON.stringify(job.env ?? {}), jobId).not.toContain("${{ runner.");
      }
    },
  );

  it("fails closed on interrupted compatibility receipts and preserves terminal evidence", () => {
    const job = readWorkflow("kaji.rehearsal.yml").workflow.jobs?.["python-compat"];
    const script = job?.steps?.find((step) => step.name === "Normalize compatibility receipt")?.run;
    expect(script).toBeDefined();
    const root = mkdtempSync(join(tmpdir(), "kaji-compat-normalize-"));
    const receipt = resolve(root, "compatibility-receipt.json");
    const commit = "a".repeat(40);
    const environment = {
      ...process.env,
      EXPECTED_COMMIT: commit,
      KAJI_COMPAT_RECEIPT_DIR: root,
      KAJI_COMPAT_RUNTIME_KIND: "python",
      KAJI_COMPAT_RUNTIME_VERSION: "3.11",
      CHECKOUT_OUTCOME: "success",
      RUNTIME_SETUP_OUTCOME: "success",
      DEPENDENCY_SETUP_OUTCOME: "success",
      DOWNLOAD_OUTCOME: "success",
      VERIFICATION_OUTCOME: "success",
      SMOKE_OUTCOME: "cancelled",
      GITHUB_SERVER_URL: "https://github.example",
      GITHUB_REPOSITORY: "example/alloy",
      GITHUB_RUN_ID: "1234",
      GITHUB_RUN_ATTEMPT: "1",
    };
    try {
      writeFileSync(
        receipt,
        `${JSON.stringify({
          schemaVersion: 1,
          commit,
          conclusion: "passed",
          failureCode: null,
        })}\n`,
      );
      const interrupted = spawnSync("/bin/bash", ["-c", script!], {
        encoding: "utf8",
        env: environment,
      });
      expect(interrupted.status, interrupted.stderr).not.toBe(0);
      expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
        conclusion: "not_run",
        failureCode: "compatibility_receipt_not_terminal",
      });

      environment.SMOKE_OUTCOME = "success";
      writeFileSync(
        receipt,
        `${JSON.stringify({
          schemaVersion: 1,
          commit,
          conclusion: "passed",
          failureCode: null,
        })}\n`,
      );
      const identityFree = spawnSync("/bin/bash", ["-c", script!], {
        encoding: "utf8",
        env: environment,
      });
      expect(identityFree.status).not.toBe(0);
      expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
        conclusion: "not_run",
        failureCode: "compatibility_receipt_not_terminal",
      });

      const githubProof = {
        schemaVersion: 1,
        evidenceClass: "offline_exact_artifact_smoke",
        integration: "github",
        runtime: "python",
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
      const terminal = `${JSON.stringify({
        schemaVersion: 1,
        commit,
        conclusion: "passed",
        failureCode: null,
        releaseManifestSha256: "b".repeat(64),
        artifactSha256: {
          "kaji_sdk-0.2.0b1-py3-none-any.whl": "c".repeat(64),
          "kaji_sdk-0.2.0b1.tar.gz": "d".repeat(64),
        },
        runtime: {
          implementation: "CPython",
          version: "3.11.9",
          executable: "/opt/python/bin/python",
        },
        artifacts: {
          wheel: "/artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl",
          sdist: "/artifacts/kaji_sdk-0.2.0b1.tar.gz",
        },
        githubPackageProofs: {
          wheel: githubProof,
          sdist: githubProof,
        },
        timings: {
          wheel: { coldSetupToOutputMs: 11, warmRunMs: 2 },
          sdist: { coldSetupToOutputMs: 13, warmRunMs: 3 },
        },
        toolchain: {
          python: "3.11.9",
          uv: "0.11.25",
          node: "not-used",
          npm: "not-used",
          bun: "not-used",
          typescript: "not-used",
        },
      })}\n`;
      writeFileSync(receipt, terminal);
      const preserved = spawnSync("/bin/bash", ["-c", script!], {
        encoding: "utf8",
        env: environment,
      });
      expect(preserved.status, preserved.stderr).toBe(0);
      expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
        ...JSON.parse(terminal),
        workflowRun: "https://github.example/example/alloy/actions/runs/1234",
        workflowRunAttempt: 1,
      });
      environment.SMOKE_OUTCOME = "cancelled";
      writeFileSync(receipt, terminal);
      const failed = spawnSync("/bin/bash", ["-c", script!], {
        encoding: "utf8",
        env: environment,
      });
      expect(failed.status).not.toBe(0);
      expect(JSON.parse(readFileSync(receipt, "utf8"))).not.toHaveProperty("timings");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it.each([
    [
      "unexpected flag",
      ["--output", "$RECEIPT", "--malformed"],
      true,
      "unexpected package smoke argument",
    ],
    ["output missing value", ["--output"], false, "--output requires a value"],
    ["output empty value", ["--output", ""], false, "--output requires a value"],
    ["output flag value", ["--output", "--malformed"], false, "--output requires a value"],
    [
      "manifest missing value",
      ["--output", "$RECEIPT", "--release-manifest"],
      true,
      "--release-manifest requires a value",
    ],
    [
      "manifest empty value",
      ["--output", "$RECEIPT", "--release-manifest", ""],
      true,
      "--release-manifest requires a value",
    ],
    [
      "manifest flag value",
      ["--output", "$RECEIPT", "--release-manifest", "--malformed"],
      true,
      "--release-manifest requires a value",
    ],
    [
      "commit missing value",
      ["--output", "$RECEIPT", "--expected-commit"],
      true,
      "--expected-commit requires a value",
    ],
    [
      "commit empty value",
      ["--output", "$RECEIPT", "--expected-commit", ""],
      true,
      "--expected-commit requires a value",
    ],
    [
      "commit flag value",
      ["--output", "$RECEIPT", "--expected-commit", "--malformed"],
      true,
      "--expected-commit requires a value",
    ],
  ] as const)(
    "rejects %s before package/network work and cleans temporary state",
    (_label, rawArguments, expectsReceipt, expectedError) => {
      const bunExecutable = bunExecutableFromParentPath();
      expect(existsSync(bunExecutable)).toBe(true);
      const bunVersion = spawnSync(bunExecutable, ["--version"], {
        encoding: "utf8",
        env: process.env,
      });
      expect(bunVersion.status, bunVersion.stderr).toBe(0);
      expect(bunVersion.stdout.trim()).toMatch(/^\d+\.\d+\.\d+/);
      const root = mkdtempSync(join(tmpdir(), "kaji-invalid-smoke-"));
      const temporary = resolve(root, "tmp");
      const receipt = resolve(root, "failed-receipt.json");
      mkdirSync(temporary);
      try {
        const completed = spawnSync(
          bunExecutable,
          [
            resolve(repositoryRoot, "kaji/ts/scripts/smoke_package.mts"),
            ...rawArguments.map((argument) => (argument === "$RECEIPT" ? receipt : argument)),
          ],
          {
            cwd: root,
            encoding: "utf8",
            env: { ...process.env, PATH: "/nonexistent", TMPDIR: temporary },
          },
        );
        expect(completed.status).not.toBe(0);
        expect(completed.stderr).toContain(expectedError);
        if (expectsReceipt) {
          expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
            conclusion: "failed",
            failureCode: "artifact_identity_failed",
          });
        } else {
          expect(existsSync(receipt)).toBe(false);
        }
        expect(readdirSync(temporary)).toEqual([]);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );

  it("creates, normalizes, and uploads the exact publisher identity receipt", () => {
    const { workflow } = readWorkflow("kaji.publish.yml");
    const publish = workflow.jobs?.["publish-npm"]!;
    const steps = publish.steps ?? [];
    expect(Object.keys(publish.outputs ?? {}).sort()).toEqual(
      [
        "expected-publisher",
        "publisher-artifact-digest",
        "publisher-artifact-id",
        "publisher-artifact-name",
      ].sort(),
    );
    expect(publish.outputs).toEqual({
      "expected-publisher": "${{ steps.publisher-identity-init.outputs.expected-publisher }}",
      "publisher-artifact-id": "${{ steps.publisher-identity-upload.outputs.artifact-id }}",
      "publisher-artifact-digest": "${{ steps.publisher-identity-upload.outputs.artifact-digest }}",
      "publisher-artifact-name": "${{ steps.publisher-identity-init.outputs.artifact-name }}",
    });

    const initial = workflowStep(publish, "Initialize fail-closed publisher identity receipt");
    expect(steps[0]).toBe(initial);
    expect(initial.id).toBe("publisher-identity-init");
    expect(JSON.stringify(initial)).not.toMatch(/NPM_TOKEN|NODE_AUTH_TOKEN|secrets\./u);
    for (const field of [
      "schemaVersion",
      "commit",
      "tag",
      "workflowRun",
      "workflowRunAttempt",
      "workflowPath",
      "workflowSha",
      "expectedPublisher",
      "actualPublisher",
      "conclusion",
      "exitCode",
      "failureCode",
    ]) {
      expect(initial.run, field).toContain(field);
    }
    expect(initial.run).toContain("identity_check_incomplete");
    expect(initial.run).toContain("expected_publisher_missing");
    expect(initial.run).toContain("expected_publisher_invalid");
    expect(initial.run).toContain("jq --sort-keys --indent 2");
    expect(initial.run).toContain("publisher-identity-receipt.json");
    expect(initial.run).toContain("kaji-publisher-identity-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT");
    expect(initial.run).toContain('mv -- "$temporary" "$receipt"');
    expect(initial.run).toContain("65536");

    const sanitizeNpmConfig = workflowStep(
      publish,
      "Remove deprecated setup-node npm always-auth setting",
    );
    const setupNodeIndex = steps.findIndex((step) => step.uses?.startsWith("actions/setup-node@"));
    expect(steps.indexOf(sanitizeNpmConfig)).toBe(setupNodeIndex + 1);
    expect(JSON.stringify(sanitizeNpmConfig)).not.toMatch(/NPM_TOKEN|NODE_AUTH_TOKEN|secrets\./u);
    expect(sanitizeNpmConfig.run).toContain("^always-auth=false$");
    expect(sanitizeNpmConfig.run).toContain("awk '$0 != \"always-auth=false\" { print }'");
    expect(sanitizeNpmConfig.run).not.toMatch(/\bcat\b|tee|set -x/u);

    const npmConfigRoot = mkdtempSync(join(tmpdir(), "kaji-npm-config-"));
    try {
      const npmConfig = join(npmConfigRoot, ".npmrc");
      writeFileSync(
        npmConfig,
        "registry=https://registry.npmjs.org/\nalways-auth=false\n" +
          "//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}\n",
      );
      const sanitized = spawnSync("bash", ["-c", sanitizeNpmConfig.run!], {
        cwd: repositoryRoot,
        encoding: "utf8",
        env: {
          ...process.env,
          NPM_CONFIG_USERCONFIG: npmConfig,
          RUNNER_TEMP: npmConfigRoot,
        },
      });
      expect(sanitized.status, sanitized.stderr).toBe(0);
      expect(sanitized.stdout).toBe("");
      expect(sanitized.stderr).toBe("");
      expect(readFileSync(npmConfig, "utf8")).toBe(
        "registry=https://registry.npmjs.org/\n" +
          "//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}\n",
      );
    } finally {
      rmSync(npmConfigRoot, { recursive: true, force: true });
    }

    const whoami = workflowStep(publish, "Verify exact npm publisher identity");
    expect(steps.indexOf(sanitizeNpmConfig)).toBeLessThan(steps.indexOf(whoami));
    expect(whoami.run).toContain("npm whoami --registry=https://registry.npmjs.org/");
    expect(whoami.run).toContain("ulimit -f");
    expect(whoami.run).toContain("timeout --signal=TERM");
    expect(whoami.run).toContain("npm_whoami_failed");
    expect(whoami.run).toContain("npm_whoami_output_invalid");
    expect(whoami.run).toContain("publisher_mismatch");
    expect(whoami.run).toContain("token_missing");
    expect(whoami.run).not.toMatch(/\bcat\b|tee|set -x/u);

    const upload = steps.find((step) => step.id === "publisher-identity-upload");
    expect(upload?.name).toBe("Upload exact publisher identity receipt");
    expect(upload?.if).toBe("${{ always() }}");
    expect(upload?.with).toEqual({
      name: "${{ steps.publisher-identity-init.outputs.artifact-name }}",
      path: "${{ runner.temp }}/kaji-publisher-identity/publisher-identity-receipt.json",
      "if-no-files-found": "error",
    });
    expect(steps.indexOf(upload!)).toBe(steps.indexOf(whoami) + 1);
    expect(steps[steps.indexOf(upload!) + 1]?.name).toBe(
      "Revalidate current carrier immediately before npm publication",
    );

    const credentialedSteps = Object.values(workflow.jobs ?? {}).flatMap((job) =>
      (job.steps ?? []).filter((step) => JSON.stringify(step).includes("secrets.NPM_TOKEN")),
    );
    expect(credentialedSteps.map((step) => step.name)).toEqual([
      "Verify exact npm publisher identity",
      "Publish exact npm beta with provenance",
    ]);
    expect(whoami.env).toEqual({
      NODE_AUTH_TOKEN: "${{ secrets.NPM_TOKEN }}",
      EXPECTED_NPM_PUBLISHER: "${{ vars.KAJI_NPM_PUBLISHER }}",
    });
    expect(
      JSON.stringify([workflow.jobs?.["publication-status"], workflow.jobs?.["release-evidence"]]),
    ).not.toMatch(/KAJI_NPM_PUBLISHER|secrets\.NPM_TOKEN|NODE_AUTH_TOKEN/u);
  });

  it("authenticates the all-or-none publisher receipt output tuple before exact-ID download", () => {
    const { workflow } = readWorkflow("kaji.publish.yml");
    const status = workflow.jobs?.["publication-status"]!;
    expect(status.permissions).toEqual({
      actions: "read",
      contents: "read",
      attestations: "read",
    });
    const steps = status.steps ?? [];
    const binding = workflowStep(
      status,
      "Classify publisher identity receipt outputs before setup",
    );
    const metadata = workflowStep(
      status,
      "Authenticate exact publisher identity artifact before download",
    );
    const checkoutIndex = steps.findIndex((step) => step.uses?.startsWith("actions/checkout@"));
    expect(steps.indexOf(binding)).toBeLessThan(checkoutIndex);
    expect(binding["continue-on-error"]).toBe(true);
    expect(binding.run).toContain("receipt_outputs_missing");
    expect(binding.run).toContain("receipt_artifact_metadata_mismatch");
    expect(binding.run).toContain("publish_job_not_started");
    expect(binding.run).not.toMatch(/\bgh\s+api\b|actions\/artifacts|actions\/runs/u);
    expect(metadata.if).toContain("steps.publisher-receipt-binding.outputs.mode == 'receipt'");
    for (const fragment of [
      "actions/runs/$GITHUB_RUN_ID",
      "actions/artifacts/$PUBLISHER_ARTIFACT_ID",
      ".run_attempt == 1",
      '.path == ".github/workflows/kaji.publish.yml"',
      '.head_branch == "kaji-v0.2.0-beta.10"',
      ".head_sha == $commit",
      ".id == $id",
      ".name == $name",
      ".digest == $digest",
      ".expired == false",
      ".size_in_bytes > 0",
    ]) {
      expect(metadata.run, fragment).toContain(fragment);
    }
    const download = steps.find(
      (step) =>
        step.uses?.startsWith("actions/download-artifact@") &&
        step.with?.["artifact-ids"] === "${{ needs.publish-npm.outputs.publisher-artifact-id }}",
    );
    expect(download?.if).toContain("steps.publisher-artifact-metadata.outcome == 'success'");
    expect(download?.with).toMatchObject({
      "artifact-ids": "${{ needs.publish-npm.outputs.publisher-artifact-id }}",
      path: "${{ runner.temp }}/kaji-publisher-identity-download",
      "merge-multiple": true,
      "github-token": "${{ github.token }}",
    });
    const inventory = workflowStep(status, "Validate exact publisher receipt inventory");
    expect(inventory.run).toContain("publisher-identity-receipt.json");
    expect(inventory.run).toContain("find");
    expect(inventory.run).toContain('[ "$observed_count" = 1 ]');
    expect(steps.indexOf(inventory)).toBe(steps.indexOf(download!) + 1);

    const valid = runPublisherIdentityArtifactAuthentication();
    expect(valid.status, String(valid.stderr)).toBe(0);
    expect(valid.endpoints).toEqual([
      `repos/enkyuan/alloy/actions/runs/${publisherIdentityArtifactFixture().runId}`,
      `repos/enkyuan/alloy/actions/artifacts/${publisherIdentityArtifactFixture().artifactId}`,
    ]);
  });

  it("distinguishes a skipped no-start publisher job from missing started-job receipts", () => {
    const skipped = runPublisherReceiptOutputBinding();
    expect(skipped.status, String(skipped.stderr)).toBe(0);
    expect(skipped.outputs).toMatchObject({
      mode: "no-receipt",
      reason: "publish_job_not_started",
    });
    expect(skipped.endpoints).toEqual([]);

    for (const publishResult of ["failure", "cancelled", "success"]) {
      const started = runPublisherReceiptOutputBinding({ PUBLISH_RESULT: publishResult });
      expect(started.status, publishResult).not.toBe(0);
      expect(started.outputs).toMatchObject({
        mode: "no-receipt",
        reason: "receipt_outputs_missing",
      });
      expect(started.endpoints, publishResult).toEqual([]);
    }

    const partial = runPublisherReceiptOutputBinding({
      PUBLISH_RESULT: "failure",
      PUBLISHER_ARTIFACT_ID: "812346",
    });
    expect(partial.status).not.toBe(0);
    expect(partial.outputs).toMatchObject({
      mode: "no-receipt",
      reason: "receipt_outputs_missing",
    });
    expect(partial.endpoints).toEqual([]);
  });

  it("keeps the retained initial publication writer honest about publisher job start", () => {
    for (const [publishResult, expectedReason] of [
      ["skipped", "publish_job_not_started"],
      ["failure", "receipt_outputs_missing"],
      ["cancelled", "receipt_outputs_missing"],
      ["success", "receipt_outputs_missing"],
    ] as const) {
      const completed = runInitialPublicationStatus(publishResult);
      expect(completed.status, `${publishResult}: ${completed.stderr}`).toBe(0);
      expect(completed.payload).toMatchObject({
        state: "unpublished",
        releaseReady: false,
        installRecommendation: false,
        incident: {
          code: "classification_pending",
          recovery: "fix_forward_next_beta",
        },
        publisherIdentity: {
          conclusion: "not_run",
          reason: expectedReason,
          artifact: null,
          receiptSha256: null,
          identity: null,
        },
      });
    }
  });

  it.each([
    [
      "missing outputs",
      {
        PUBLISHER_BINDING_MODE: "no-receipt",
        PUBLISHER_BINDING_REASON: "receipt_outputs_missing",
      },
      "receipt_outputs_missing",
    ],
    [
      "metadata mismatch",
      { PUBLISHER_METADATA_OUTCOME: "failure" },
      "receipt_artifact_metadata_mismatch",
    ],
    ["download failure", { PUBLISHER_DOWNLOAD_OUTCOME: "failure" }, "receipt_download_failed"],
    ["inventory failure", { PUBLISHER_INVENTORY_OUTCOME: "failure" }, "receipt_download_failed"],
    ["raw receipt validation failure", {}, "receipt_invalid"],
  ] as const)(
    "preserves %s in the executable emergency publication fallback",
    (_label, overrides, expectedReason) => {
      const completed = runPublicationClassifierFallback(overrides);
      expect(completed.status, String(completed.stderr)).toBe(0);
      expect(completed.payload).toMatchObject({
        state: "unpublished",
        releaseReady: false,
        installRecommendation: false,
        expectedPublisher: null,
        publisherIdentity: {
          conclusion: "not_run",
          reason: expectedReason,
          artifact: null,
          receiptSha256: null,
          identity: null,
        },
        incident: {
          code: "status_classifier_unavailable",
          recovery: "fix_forward_next_beta",
        },
      });
      expect(completed.payload.state).not.toBe("npm_byte_verified");
    },
  );

  it.each([
    [
      "id",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.artifact.id = 999_999;
      },
    ],
    [
      "name",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.artifact.name = "wrong-name";
      },
    ],
    [
      "digest",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.artifact.digest = `sha256:${"0".repeat(64)}`;
      },
    ],
    [
      "expired",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.artifact.expired = true;
      },
    ],
    [
      "size",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.artifact.size_in_bytes = 0;
      },
    ],
    [
      "run",
      (fixture: PublisherIdentityArtifactFixture) => {
        (fixture.artifact.workflow_run as Record<string, unknown>).id = 999_999;
      },
    ],
    [
      "attempt",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.run.run_attempt = 2;
      },
    ],
    [
      "ref",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.run.head_branch = "wrong-ref";
      },
    ],
    [
      "head SHA",
      (fixture: PublisherIdentityArtifactFixture) => {
        fixture.run.head_sha = "0".repeat(40);
      },
    ],
  ] as const)(
    "rejects hostile publisher receipt artifact %s metadata before download",
    (_label, mutate) => {
      const completed = runPublisherIdentityArtifactAuthentication(mutate);
      expect(completed.status).not.toBe(0);
      expect(completed.endpoints.some((endpoint) => endpoint.endsWith("/zip"))).toBe(false);
    },
  );

  it("projects publisher identity through every status writer and terminal gate", () => {
    const { workflow } = readWorkflow("kaji.publish.yml");
    const status = workflow.jobs?.["publication-status"]!;
    expect(status.outputs?.["expected-publisher"]).toBe(
      "${{ steps.classify.outputs.expected-publisher }}",
    );
    const initial = workflowStep(status, "Initialize fail-closed publication status before setup");
    for (const fragment of [
      "publisherIdentity",
      'conclusion: "not_run"',
      "publisher_reason=publish_job_not_started",
      "reason: $publisherReason",
      "receiptSha256: null",
      "identity: null",
      "expectedPublisher",
      "workflowRunAttempt",
      "workflowPath",
      "workflowSha",
    ]) {
      expect(initial.run, fragment).toContain(fragment);
    }

    const classifier = workflowStep(status, "Reduce monotonic publication state");
    for (const fragment of [
      "--publisher-receipt",
      "--publisher-artifact-name",
      "--publisher-artifact-id",
      "--publisher-artifact-digest",
      "--publisher-no-receipt-reason",
      "--expected-publisher",
      "--workflow-run-attempt",
      "--workflow-path",
      "--workflow-sha",
      "--tag",
      "publisherIdentity",
      "receiptSha256",
      "receipt_invalid",
      "identity_check_failed",
    ]) {
      expect(classifier.run, fragment).toContain(fragment);
    }
    const fallbackWriter = classifier.run
      ?.split('if [ "$CLASSIFY_STATUS" -ne 0 ]; then', 2)[1]
      ?.split("cat .artifacts/kaji-publication-status/publication-status.md", 1)[0];
    expect(fallbackWriter).toContain('[ "$PUBLISHER_REASON" = publish_job_not_started ]');
    expect(fallbackWriter).toContain('publisherIdentity: {conclusion: "not_run"');
    expect(fallbackWriter).toContain("receiptSha256: null, identity: null");
    expect(fallbackWriter).toContain("expectedPublisher: null");
    expect(fallbackWriter).not.toContain("FALLBACK_STATE=npm_byte_verified");
    const exactState = workflowStep(status, "Require exact npm byte-verified publication state");
    expect(exactState.run).toContain('.publisherIdentity.conclusion == "passed"');
    expect(exactState.run).toContain(
      ".publisherIdentity.identity.actualPublisher == .expectedPublisher",
    );
    expect(exactState.run).toContain(
      ".publisherIdentity.identity.expectedPublisher == .expectedPublisher",
    );
    expect(exactState.run).toContain(".publisherIdentity.receiptSha256");
    expect(exactState.run).toContain('test -n "$EXPECTED_PUBLISHER"');

    const release = workflow.jobs?.["release-evidence"]!;
    const releaseSteps = release.steps ?? [];
    const validate = workflowStep(
      release,
      "Validate terminal publication status before release attachment",
    );
    const attach = workflowStep(
      release,
      "Create or verify prerelease and attach only missing digest-matched assets",
    );
    expect(releaseSteps.indexOf(validate)).toBeLessThan(releaseSteps.indexOf(attach));
    for (const fragment of [
      "validate_release_evidence.py publication-status",
      "--publication-status .artifacts/kaji-publication-status/publication-status.json",
      "--expected-commit",
      "--workflow-run",
      "--workflow-run-attempt 1",
      "--expected-tag",
      "--expected-workflow-path .github/workflows/kaji.publish.yml",
      "--expected-workflow-sha",
      "--expected-publisher",
      '--output "$RUNNER_TEMP/kaji-publication-status-validation.json"',
    ]) {
      expect(validate.run, fragment).toContain(fragment);
    }
    expect(validate.env?.EXPECTED_PUBLISHER).toBe(
      "${{ needs.publication-status.outputs.expected-publisher }}",
    );
    expect(attach.run).not.toContain("publisher-identity-receipt");
    expect(attach.run).not.toContain("kaji-publication-status-validation");
  });

  it("uses exact-version HTTPS registry absence responses instead of E404 text matching", () => {
    const { source, workflow } = readWorkflow("kaji.publish.yml");
    expect(source).not.toContain("npm view kaji-sdk@0.2.0-beta.10");
    expect(source).not.toMatch(/\bE404\b/u);
    const preflight = workflowStep(
      workflow.jobs?.["registry-preflight"]!,
      "Require PyPI beta absence and exact npm beta absence",
    );
    const immediate = workflowStep(
      workflow.jobs?.["publish-npm"]!,
      "Recheck exact registry absence immediately before npm publication",
    );
    const classifier = workflowStep(
      workflow.jobs?.["publication-status"]!,
      "Reduce monotonic publication state",
    );
    for (const step of [preflight, immediate]) {
      for (const fragment of [
        "https://registry.npmjs.org/tiny-tarball/1.0.0",
        "https://registry.npmjs.org/kaji-sdk",
        "https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10",
        "--connect-timeout 10",
        "--proto '=https'",
        "--tlsv1.2",
        "--max-filesize",
        "%{content_type}",
        "%{url_effective}",
        "%{num_redirects}",
        "%{size_download}",
        '[ "$effective_url" = "$url" ]',
        '[ "$redirects" = 0 ]',
        "application/json",
        '.name == "tiny-tarball"',
        '.version == "1.0.0"',
        'keys == ["error"]',
        '.error == "Not found"',
        'type == "string" and . == "Not Found"',
        '[ "$PACKUMENT_HTTP/$TARGET_HTTP" = 404/404 ]',
      ]) {
        expect(step.run, fragment).toContain(fragment);
      }
    }
    expect(JSON.stringify(immediate)).not.toMatch(
      /NPM_TOKEN|NODE_AUTH_TOKEN|secrets\.|KAJI_NPM_PUBLISHER/u,
    );
    expect(classifier.run).toContain("https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10");
    expect(classifier.run).toContain('type == "string" and . == "Not Found"');
    for (const fragment of [
      "https://registry.npmjs.org/tiny-tarball/1.0.0",
      "fetch_classification_json",
      "--max-filesize",
      "%{content_type}",
      "%{url_effective}",
      "%{num_redirects}",
      "%{size_download}",
      '.name == "tiny-tarball"',
      '.version == "1.0.0"',
    ]) {
      expect(classifier.run, fragment).toContain(fragment);
    }
    for (const step of [preflight, immediate, classifier]) {
      expect(step.run).toContain("https://registry.npmjs.org/kaji-sdk/0.2.0-beta.10");
    }
    expect(classifier.run).toContain('.name == "kaji-sdk"');
    expect(classifier.run).toContain('.version == "0.2.0-beta.10"');

    for (const [jobId, stepName] of [
      ["registry-preflight", "Require PyPI beta absence and exact npm beta absence"],
      ["publish-npm", "Recheck exact registry absence immediately before npm publication"],
    ] as const) {
      const absent = runExactVersionRegistryAbsence(jobId, stepName);
      expect(absent.status, `${jobId}: ${absent.stderr}`).toBe(0);
      for (const [label, overrides] of [
        ["control transport", { controlTransportStatus: "6" }],
        ["control status", { controlHttp: "500" }],
        ["control identity", { controlBody: '{"name":"other","version":"1.0.0"}' }],
        ["control content type", { controlContentType: "text/plain" }],
        ["control redirect", { controlRedirects: "1" }],
        [
          "control effective URL",
          { controlEffectiveUrl: "https://registry.npmjs.org/tiny-tarball/1.0.1" },
        ],
        ["packument object", { packumentBody: '{"error":"Not Found"}' }],
        ["packument string", { packumentBody: '"Not Found"' }],
        ["packument status", { packumentHttp: "500" }],
        ["packument content type", { packumentContentType: "text/html" }],
        ["target package object", { targetBody: '{"error":"Not found"}' }],
        ["target incidental E404", { targetBody: '"E404 Not Found"' }],
        ["target wrong string case", { targetBody: '"Not found"' }],
        ["target mixed JSON", { targetBody: '["Not Found",{"error":"E404"}]' }],
        ["target ambiguous status", { targetHttp: "500" }],
        ["target content type", { targetContentType: "text/plain" }],
        ["target redirect", { targetRedirects: "1" }],
        [
          "target effective URL",
          { targetEffectiveUrl: "https://registry.npmjs.org/kaji-sdk/0.2.0-beta.11" },
        ],
        ["target oversized body", { targetBody: `"${"x".repeat(70_000)}"` }],
      ] as const) {
        const completed = runExactVersionRegistryAbsence(jobId, stepName, overrides);
        expect(
          completed.status,
          `${jobId}:${label}:stdout=${completed.stdout}:stderr=${completed.stderr}`,
        ).not.toBe(0);
      }
      const targetPresent = runExactVersionRegistryAbsence(jobId, stepName, {
        targetHttp: "200",
        targetBody: "not-json",
      });
      expect(targetPresent.status, jobId).not.toBe(0);
      expect(targetPresent.stderr, jobId).toContain("already exists");
      const packagePresent = runExactVersionRegistryAbsence(jobId, stepName, {
        packumentHttp: "200",
        packumentBody: "not-json",
      });
      expect(packagePresent.status, jobId).not.toBe(0);
      expect(packagePresent.stderr, jobId).toContain("already exists");
    }
  }, 30_000);

  it("publishes and byte-verifies npm only while requiring PyPI absence", () => {
    const { source, workflow } = readWorkflow("kaji.publish.yml");
    const jobs = workflow.jobs ?? {};

    expect(jobs).not.toHaveProperty("publish-python");
    expect(source).not.toContain("pypa/gh-action-pypi-publish");
    expect(source).not.toContain("pypi-attestations");

    const registryPreflight = jobs["registry-preflight"]?.steps?.find((step) =>
      step.run?.includes("https://pypi.org/pypi/kaji-sdk/0.2.0b1/json"),
    );
    expect(registryPreflight?.run).toContain("404)");
    expect(registryPreflight?.run).toContain("PyPI beta 0.2.0b1 must remain absent");

    const publisherJob = jobs["publish-npm"]!;
    const identity = workflowStep(publisherJob, "Verify exact npm publisher identity");
    const npmPublish = workflowStep(publisherJob, "Publish exact npm beta with provenance");
    const identityRun = identity.run ?? "";
    const npmPublishRun = npmPublish.run ?? "";
    expect(identityRun).toContain("npm whoami --registry=https://registry.npmjs.org/");
    expect(identityRun).not.toContain("npm publish");
    expect(npmPublishRun).toContain("npm publish");
    expect(npmPublishRun).not.toContain("npm whoami");
    expect(identityRun).toContain('"$identity" = "$EXPECTED_NPM_PUBLISHER"');
    expect(identity.env).toEqual({
      NODE_AUTH_TOKEN: "${{ secrets.NPM_TOKEN }}",
      EXPECTED_NPM_PUBLISHER: "${{ vars.KAJI_NPM_PUBLISHER }}",
    });
    expect(npmPublish.env).toEqual({
      NODE_AUTH_TOKEN: "${{ secrets.NPM_TOKEN }}",
    });
    expect(npmPublish.run).toContain("--provenance");
    expect(npmPublish.run).toContain("--access public");
    expect(npmPublish.run).toContain("--tag beta");
    const publisherSteps = publisherJob.steps ?? [];
    const reverifyIndex = publisherSteps.findIndex(
      (step) => step.uses === "./.github/actions/verify-kaji-beta-tag",
    );
    expect(publisherSteps[reverifyIndex - 1]?.name).toBe(
      "Revalidate current carrier immediately before npm publication",
    );
    expect(publisherSteps[reverifyIndex + 1]?.name).toBe(
      "Recheck exact registry absence immediately before npm publication",
    );
    expect(publisherSteps[reverifyIndex + 2]?.name).toBe("Publish exact npm beta with provenance");
    expect([...dependencyClosure(workflow, "publish-npm")].sort()).toEqual([
      "keyed-proof",
      "node-compat",
      "offline-gates",
      "performance",
      "python-compat",
      "registry-preflight",
      "supply-chain",
      "typescript-onboarding-archive-calibration",
      "typescript-onboarding-evidence",
      "verify-tag",
    ]);

    const publicationStatus = jobs["publication-status"]!;
    expect(publicationStatus.needs).toEqual([
      "verify-tag",
      "supply-chain",
      "registry-preflight",
      "publish-npm",
    ]);
    const registryVerifier = workflowStep(
      publicationStatus,
      "Poll bounded npm propagation and verify published bytes",
    );
    expect(registryVerifier.run).toContain("verify_published_packages.py");
    expect(registryVerifier.run).toContain("--target npm");
    const classifier = workflowStep(publicationStatus, "Reduce monotonic publication state");
    expect(classifier.run).toContain("verify_published_packages.py state");
    expect(classifier.run).toContain("--target npm");
    expect(classifier.run).toContain('--pypi "$PYPI_STATE"');
    expect(classifier.run).toContain("npm_byte_verified");
    expect(classifier.run).not.toMatch(/(^|[^_])byte_verified([^_]|$)/u);

    const exactState = workflowStep(
      publicationStatus,
      "Require exact npm byte-verified publication state",
    );
    expect(exactState.if).toBe("${{ always() }}");
    expect(exactState.run).toContain('.state == "npm_byte_verified"');
    expect(exactState.run).toContain('.publisherIdentity.conclusion == "passed"');
    expect(jobs["publication-incident"]?.if).toContain("npm_byte_verified");
    expect(jobs["release-evidence"]?.if).toContain("npm_byte_verified");

    const pythonEvidence = JSON.stringify(jobs["supply-chain"]);
    expect(pythonEvidence).toContain("kaji_sdk-0.2.0b1-py3-none-any.whl");
    expect(pythonEvidence).toContain("kaji_sdk-0.2.0b1.tar.gz");

    const releaseAttach = jobs["release-evidence"]?.steps?.find((step) =>
      step.run?.includes("kaji/scripts/attach_release_assets.py"),
    )?.run;
    expect(releaseAttach).toContain("kaji-sdk-0.2.0-beta.10.tgz");
    for (const forbidden of [
      "kaji_sdk-0.2.0b1-py3-none-any.whl",
      "kaji_sdk-0.2.0b1.tar.gz",
      "registry-kaji_sdk",
      "pypi-attestations",
    ]) {
      expect(releaseAttach).not.toContain(forbidden);
    }
  });

  it("uses Bun's supported cwd syntax when rebuilding clean-checkout packages", () => {
    const { source, workflow } = readWorkflow("kaji.publish.yml");

    for (const [jobId, stepName] of [
      ["supply-chain", "Rebuild and verify exact package contents against the clean checkout"],
      ["publish-npm", "Rebuild and verify npm archive contents against the clean checkout"],
    ] as const) {
      const job = workflow.jobs?.[jobId];
      expect(job, jobId).toBeDefined();
      expect(workflowStep(job!, stepName).run).toContain("bun run --cwd kaji/ts build");
    }
    expect(source).not.toContain("bun --cwd kaji/ts run build");
  });

  it("fans every release-byte consumer out from one same-run artifact producer", () => {
    const cases = [
      {
        name: "kaji.rehearsal.yml" as const,
        producer: "offline-release",
        consumers: [
          "performance",
          "python-compat",
          "node-compat",
          "typescript-onboarding-archive-calibration",
          "typescript-onboarding-evidence",
          "keyed-proof",
          "candidate-evidence",
        ],
      },
      {
        name: "kaji.publish.yml" as const,
        producer: "offline-gates",
        consumers: [
          "performance",
          "python-compat",
          "node-compat",
          "typescript-onboarding-archive-calibration",
          "typescript-onboarding-evidence",
          "keyed-proof",
          "supply-chain",
          "publish-npm",
          "publication-status",
          "release-evidence",
        ],
      },
      {
        name: "kaji.benchmark.yml" as const,
        producer: "release-artifacts",
        consumers: ["performance"],
      },
    ];

    for (const { name, producer, consumers } of cases) {
      const { workflow } = readWorkflow(name);
      const jobs = workflow.jobs ?? {};
      const producerJob = jobs[producer];
      expect(producerJob, `${name}:${producer}`).toBeDefined();
      const candidateUploads = Object.values(jobs)
        .flatMap((job) => job.steps ?? [])
        .filter(
          (step) =>
            step.uses?.startsWith("actions/upload-artifact@") &&
            step.with?.name === "kaji-beta-artifacts",
        );
      expect(candidateUploads, `${name}: one candidate producer`).toHaveLength(1);
      expect(candidateUploads[0]?.with).toMatchObject({
        name: "kaji-beta-artifacts",
        path: ".artifacts/kaji-release",
        "if-no-files-found": "error",
      });

      for (const jobId of consumers) {
        const job = jobs[jobId];
        expect(job, `${name}:${jobId}`).toBeDefined();
        expect(dependencyClosure(workflow, jobId), `${name}:${jobId}`).toContain(producer);
        if (job?.uses === "./.github/workflows/kaji.performance.yml") {
          expect(job.with).toMatchObject({
            "candidate-artifact-id": `\${{ needs.${producer}.outputs.artifact-id }}`,
            "candidate-artifact-digest": `\${{ needs.${producer}.outputs.artifact-digest }}`,
          });
          continue;
        }
        const steps = job?.steps ?? [];
        if (
          jobId === "typescript-onboarding-archive-calibration" ||
          jobId === "typescript-onboarding-evidence"
        ) {
          const commands = steps.map((step) => step.run ?? "").join("\n");
          expect(commands, `${name}:${jobId}: complete artifact collection`).toContain(
            "actions/runs/$GITHUB_RUN_ID/artifacts?per_page=100",
          );
          expect(commands, `${name}:${jobId}: exact producer ZIP`).toContain(
            "actions/artifacts/$artifact_id/zip",
          );
          expect(commands, `${name}:${jobId}: raw ZIP authentication`).toContain(
            "load_authenticated_archive",
          );
          continue;
        }
        if (jobId === "node-compat") {
          const downloads = steps.filter(
            (step) =>
              step.uses?.startsWith("actions/download-artifact@") &&
              step.with?.["artifact-ids"] === `\${{ needs.${producer}.outputs.artifact-id }}`,
          );
          expect(downloads, `${name}:${jobId}: exact candidate ID download`).toHaveLength(1);
          expect(downloads[0]?.with).toEqual({
            "artifact-ids": `\${{ needs.${producer}.outputs.artifact-id }}`,
            path: ".artifacts/kaji-release",
            "merge-multiple": true,
            "github-token": "${{ github.token }}",
          });
          const downloadIndex = steps.indexOf(downloads[0]!);
          const verifyIndex = steps.findIndex((step) =>
            step.run?.includes("kaji/scripts/verify_release_artifacts.py"),
          );
          expect(verifyIndex, `${name}:${jobId}: verifier`).toBeGreaterThan(downloadIndex);
          continue;
        }
        const exactIdExpression =
          jobId === "candidate-evidence" || jobId === "supply-chain"
            ? "${{ needs.typescript-onboarding-evidence.outputs.producer-artifact-id }}"
            : jobId === "publish-npm" ||
                jobId === "publication-status" ||
                jobId === "release-evidence"
              ? "${{ needs.supply-chain.outputs.carrier-artifact-id }}"
              : undefined;
        if (exactIdExpression !== undefined) {
          const downloads = steps.filter(
            (step) =>
              step.uses?.startsWith("actions/download-artifact@") &&
              step.with?.["artifact-ids"] === exactIdExpression,
          );
          expect(downloads, `${name}:${jobId}: exact candidate ID download`).toHaveLength(1);
          expect(downloads[0]?.with).toMatchObject({
            "artifact-ids": exactIdExpression,
            path: ".artifacts/kaji-release",
            "merge-multiple": true,
            "github-token": "${{ github.token }}",
          });
          const downloadIndex = steps.indexOf(downloads[0]!);
          const verifyIndex = steps.findIndex((step) =>
            step.run?.includes("kaji/scripts/verify_release_artifacts.py"),
          );
          expect(verifyIndex, `${name}:${jobId}: verifier`).toBeGreaterThan(downloadIndex);
          continue;
        }
        const downloads = steps.filter(
          (step) =>
            step.uses?.startsWith("actions/download-artifact@") &&
            step.with?.name === "kaji-beta-artifacts",
        );
        expect(downloads, `${name}:${jobId}: exact candidate download`).toHaveLength(1);
        expect(downloads[0]?.with).toEqual({
          name: "kaji-beta-artifacts",
          path: ".artifacts/kaji-release",
        });
        const downloadIndex = steps.indexOf(downloads[0]!);
        const verifyIndex = steps.findIndex((step) =>
          step.run?.includes("kaji/scripts/verify_release_artifacts.py"),
        );
        expect(verifyIndex, `${name}:${jobId}: verifier`).toBeGreaterThan(downloadIndex);
        expect(steps[verifyIndex]?.run, `${name}:${jobId}: expected commit`).toContain(
          "--expected-commit",
        );
      }
    }
  });

  it("runs protected benchmark and provider consumers only from installed candidate bytes", () => {
    const performance = readWorkflow("kaji.performance.yml").workflow;
    const paired = performance.jobs?.["paired-replica"]?.steps?.find((step) =>
      step.run?.includes("paired_benchmark.py"),
    )?.run;
    expect(paired).toContain("--protected");
    expect(paired).toContain("--reference-artifacts-dir .artifacts/kaji-reference");
    expect(paired).toContain("--candidate-artifacts-dir .artifacts/kaji-candidate");
    expect(paired).toContain('--runner-image-data "$HOME/imagedata.json"');
    const soak = performance.jobs?.soak?.steps?.find((step) =>
      step.run?.includes("run_beta_soak.py"),
    )?.run;
    expect(soak).toContain("--minutes 30 --protected");
    expect(soak).toContain("--artifacts-dir .artifacts/kaji-candidate");

    for (const workflowName of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const performanceCall = readWorkflow(workflowName).workflow.jobs?.performance;
      expect(performanceCall?.uses).toBe("./.github/workflows/kaji.performance.yml");

      const provider = readWorkflow(workflowName).workflow.jobs?.["keyed-proof"];
      const command = provider?.steps?.find((step) =>
        step.run?.includes("live_provider_proof.py"),
      )?.run;
      expect(command, workflowName).toContain("--protected");
      expect(command, workflowName).toContain("--artifacts-dir .artifacts/kaji-release");
      expect(command, workflowName).toContain("--expected-commit");
    }
  });

  it("centrally validates every current-run rehearsal receipt", () => {
    const { workflow } = readWorkflow("kaji.rehearsal.yml");
    const evidence = workflow.jobs?.["candidate-evidence"];
    expect(evidence?.needs).toEqual([
      "offline-release",
      "performance",
      "typescript-onboarding-evidence",
      "keyed-proof",
      "python-compat",
      "node-compat",
    ]);
    expect(evidence?.if).toBe(
      "${{ github.run_attempt == 1 && !cancelled() && needs.offline-release.result == 'success' && needs.performance.result == 'success' && needs.typescript-onboarding-evidence.result == 'success' && needs.keyed-proof.result == 'success' && needs.python-compat.result == 'success' && needs.node-compat.result == 'success' }}",
    );
    const steps = evidence?.steps ?? [];
    const downloads = steps.filter((step) => step.uses?.startsWith("actions/download-artifact@"));
    const requiredDownloads = downloads.filter((step) => !step["continue-on-error"]);
    expect(requiredDownloads.map((step) => step.with?.["artifact-ids"])).toEqual([
      "${{ needs.typescript-onboarding-evidence.outputs.producer-artifact-id }}",
      undefined,
      "${{ needs.typescript-onboarding-evidence.outputs.onboarding-artifact-id }}",
      "${{ needs.typescript-onboarding-evidence.outputs.node22-source-artifact-id }}",
      "${{ needs.typescript-onboarding-evidence.outputs.node24-source-artifact-id }}",
    ]);
    expect(
      requiredDownloads.filter((step) => step.with?.name).map((step) => step.with?.name),
    ).toEqual(["kaji-offline-evidence"]);
    expect(
      downloads.filter((step) => step["continue-on-error"]).map((step) => step.with?.name),
    ).toEqual([
      "kaji-provider-evidence",
      "kaji-performance-evidence",
      "kaji-python-compat-3.11",
      "kaji-python-compat-3.14",
    ]);
    const rawArchives = workflowStep(
      evidence!,
      "Download and authenticate validator raw source archives by exact ID",
    );
    for (const fragment of [
      "actions/artifacts/$artifact_id/zip",
      'observed="sha256:$(sha256sum "$archive"',
      '[ "$observed" = "$digest" ]',
    ]) {
      expect(rawArchives.run).toContain(fragment);
    }
    const verifyIndex = steps.findIndex((step) =>
      step.run?.includes("kaji/scripts/verify_release_artifacts.py"),
    );
    const validation = steps.find((step) =>
      step.run?.includes("kaji/scripts/validate_release_evidence.py"),
    );
    const validationIndex = steps.indexOf(validation!);
    expect(verifyIndex).toBeGreaterThan(steps.indexOf(requiredDownloads[0]!));
    expect(validationIndex).toBeGreaterThan(verifyIndex);
    expect(validation?.["continue-on-error"]).toBeUndefined();
    for (const flag of [
      "--release-artifact-id",
      "--release-artifact-digest",
      "--producer-archive",
      "--node22-source-archive",
      "--node24-source-archive",
      "--node22-source-artifact-id",
      "--node22-source-artifact-digest",
      "--node24-source-artifact-id",
      "--node24-source-artifact-digest",
      "--onboarding-status",
      "--onboarding-evidence",
      "--python-compat-311",
      "--python-compat-314",
      "--node-compat-22",
      "--node-compat-24",
      "--performance-status",
      "--benchmark-results",
      "--soak-results",
      "--performance-image-data",
      "--provider-evidence",
      "--mode rehearsal",
      "--output",
    ]) {
      expect(validation?.run, flag).toContain(flag);
    }
    const staging = workflowStep(evidence!, "Stage exact signed rehearsal evidence archive");
    expect(steps.indexOf(staging)).toBe(validationIndex + 1);
    const exactSignedEvidenceMembers = [
      "compat-node-22.json",
      "compat-node-24.json",
      "compat-python-3.11.json",
      "compat-python-3.14.json",
      "offline-gate-summary.json",
      "offline-gates.log",
      "paired-benchmark-results.json",
      "performance-imagedata.json",
      "performance-status.json",
      "provider-evidence.json",
      "raw/benchmarks/replica-1-imagedata.json",
      "raw/benchmarks/replica-1.json",
      "raw/benchmarks/replica-2-imagedata.json",
      "raw/benchmarks/replica-2.json",
      "raw/benchmarks/replica-3-imagedata.json",
      "raw/benchmarks/replica-3.json",
      "raw/soak/python.json",
      "raw/soak/results.json",
      "raw/soak/typescript.json",
      "release-evidence-validation.json",
      "soak-results.json",
      "typescript-onboarding/status.json",
      "typescript-onboarding/typescript-onboarding-evidence.json",
      "typescript-onboarding/validation.log",
    ];
    expect(exactSignedEvidenceMembers).toHaveLength(24);
    for (const member of exactSignedEvidenceMembers) {
      expect(staging.run, member).toContain(member);
    }
    for (const excludedDiagnostic of [
      "raw/benchmarks/replica-1-status.json",
      "raw/benchmarks/replica-2-status.json",
      "raw/benchmarks/replica-3-status.json",
      "raw/soak/imagedata.json",
      "raw/soak/installed-runtime.json",
    ]) {
      expect(staging.run, excludedDiagnostic).not.toContain(excludedDiagnostic);
    }
    expect(staging.run).toContain("destination=.artifacts/kaji-signed-evidence");
    expect(staging.run).toContain('[ "$observed_count" = 24 ]');
    const upload = steps.find(
      (step) =>
        step.uses?.startsWith("actions/upload-artifact@") &&
        step.with?.name === "kaji-release-candidate-evidence",
    );
    expect(steps.indexOf(upload!)).toBe(steps.indexOf(staging) + 1);
    expect(upload?.if).toBe("${{ always() }}");
    expect(upload?.with?.path).toBe(".artifacts/kaji-signed-evidence");
    expect(upload?.with?.["if-no-files-found"]).toBe("error");
  });

  it("terminal-normalizes calibration, onboarding, and provider evidence after failures", () => {
    for (const workflowName of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const workflow = readWorkflow(workflowName).workflow;
      for (const [jobId, normalizerName, uploadName] of [
        [
          "typescript-onboarding-archive-calibration",
          "Normalize terminal calibration diagnostic",
          "kaji-typescript-onboarding-archive-calibration",
        ],
        [
          "typescript-onboarding-evidence",
          "Normalize terminal onboarding evidence",
          "kaji-typescript-onboarding-evidence",
        ],
        ["keyed-proof", "Normalize terminal provider evidence", "kaji-provider-evidence"],
      ] as const) {
        const steps = workflow.jobs?.[jobId]?.steps ?? [];
        const normalizer = steps.find((step) => step.name === normalizerName);
        const finalUpload = steps.findIndex(
          (step) =>
            step.uses?.startsWith("actions/upload-artifact@") && step.with?.name === uploadName,
        );
        expect(normalizer, `${workflowName}:${jobId}`).toBeDefined();
        expect(normalizer?.if).toBe("${{ always() }}");
        expect(normalizer?.run).toContain('conclusion: "failed"');
        expect(normalizer?.run).toContain("workflowRunAttempt");
        expect(
          steps.indexOf(normalizer!),
          `${workflowName}:${jobId}: normalization order`,
        ).toBeLessThan(finalUpload);
        expect(steps[finalUpload]?.if).toBe("${{ always() }}");
      }
    }
  });

  it("centrally validates and attests every current-run publish receipt", () => {
    const { workflow } = readWorkflow("kaji.publish.yml");
    const supplyChain = workflow.jobs?.["supply-chain"];
    expect(supplyChain?.if).toBe(
      "${{ github.run_attempt == 1 && !cancelled() && needs.verify-tag.result == 'success' && needs.offline-gates.result == 'success' && needs.performance.result == 'success' && needs.typescript-onboarding-evidence.result == 'success' && needs.keyed-proof.result == 'success' && needs.python-compat.result == 'success' && needs.node-compat.result == 'success' }}",
    );
    const steps = supplyChain?.steps ?? [];
    const compatibilityDownloads = steps.filter((step) =>
      String(step.with?.name ?? "").match(/^kaji-(python|node)-compat-(3\.11|3\.14|22|24)$/),
    );
    expect(compatibilityDownloads.map((step) => step.with?.name)).toEqual([
      "kaji-python-compat-3.11",
      "kaji-python-compat-3.14",
    ]);
    expect(
      steps
        .filter((step) =>
          String(step.with?.["artifact-ids"] ?? "").includes(
            "typescript-onboarding-evidence.outputs.node",
          ),
        )
        .map((step) => step.with?.["artifact-ids"]),
    ).toEqual([
      "${{ needs.typescript-onboarding-evidence.outputs.node22-source-artifact-id }}",
      "${{ needs.typescript-onboarding-evidence.outputs.node24-source-artifact-id }}",
    ]);
    const rename = steps.find((step) => step.name === "Uniquely name final compatibility receipts");
    expect(rename?.run).toContain("compat-python-3.11.json");
    expect(rename?.run).toContain("compat-python-3.14.json");
    expect(rename?.run).toContain("compat-node-22.json");
    expect(rename?.run).toContain("compat-node-24.json");
    const sourceProofCheck = workflowStep(
      supplyChain!,
      "Revalidate current signed-source proof identity",
    );
    const sourceProofDownload = workflowStep(
      supplyChain!,
      "Download authenticated signed-source proof by exact ID",
    );
    expect(sourceProofCheck.env?.SOURCE_PROOF_ACTION_DIGEST).toBe(
      "${{ needs.offline-gates.outputs.source-proof-artifact-digest }}",
    );
    expect(sourceProofCheck.run).toContain('.name == "kaji-authorized-rehearsal-source"');
    expect(sourceProofCheck.run).toContain(".digest == $digest");
    expect(steps.indexOf(sourceProofCheck)).toBeLessThan(steps.indexOf(sourceProofDownload));

    const validateIndex = steps.findIndex((step) =>
      step.run?.includes("kaji/scripts/validate_release_evidence.py"),
    );
    const attestIndex = steps.findIndex((step) =>
      step.uses?.startsWith("actions/attest-build-provenance@"),
    );
    expect(validateIndex).toBeGreaterThan(0);
    expect(attestIndex).toBeGreaterThan(validateIndex);
    const validation = steps[validateIndex]?.run ?? "";
    for (const flag of [
      "--release-artifact-id",
      "--release-artifact-digest",
      "--mode publish",
      "--producer-archive",
      "--node22-source-archive",
      "--node24-source-archive",
      "--node22-source-artifact-id",
      "--node22-source-artifact-digest",
      "--node24-source-artifact-id",
      "--node24-source-artifact-digest",
      "--onboarding-status",
      "--onboarding-evidence",
      "--workflow-run",
      "--workflow-run-attempt",
      "--python-compat-311",
      "--python-compat-314",
      "--node-compat-22",
      "--node-compat-24",
      "--performance-status",
      "--benchmark-results",
      "--soak-results",
      "--performance-image-data",
      "--provider-evidence",
      "--authorization-sha256",
      "--rehearsal-run-id",
      "--rehearsal-run-attempt",
      "--rehearsal-workflow-path",
      "--rehearsal-workflow-sha",
      "--signed-candidate-archive",
      "--signed-candidate-artifact-id",
      "--signed-candidate-artifact-digest",
      "--signed-evidence-archive",
      "--signed-evidence-artifact-id",
      "--signed-evidence-artifact-digest",
      "--signed-node22-source-artifact-id",
      "--signed-node22-source-artifact-digest",
      "--signed-node24-source-artifact-id",
      "--signed-node24-source-artifact-digest",
      "--signed-release-manifest-sha256",
      "--signed-npm-tarball-name",
      "--signed-npm-tarball-sha256",
      "--signed-npm-tarball",
      "--rebuilt-npm-tarball",
      "--workspace",
      "--output",
    ]) {
      expect(validation).toContain(flag);
    }
    for (const binding of [
      '--signed-node22-source-artifact-id "${{ needs.offline-gates.outputs.signed-node22-artifact-id }}"',
      '--signed-node22-source-artifact-digest "${{ needs.offline-gates.outputs.signed-node22-artifact-digest }}"',
      '--signed-node24-source-artifact-id "${{ needs.offline-gates.outputs.signed-node24-artifact-id }}"',
      '--signed-node24-source-artifact-digest "${{ needs.offline-gates.outputs.signed-node24-artifact-digest }}"',
    ]) {
      expect(validation).toContain(binding);
    }
    const subjectPaths = String(steps[attestIndex]?.with?.["subject-path"] ?? "");
    for (const filename of [
      "compat-python-3.11.json",
      "compat-python-3.14.json",
      "compat-node-22.json",
      "compat-node-24.json",
      "performance-imagedata.json",
      "release-evidence-validation.json",
    ]) {
      expect(subjectPaths).toContain(filename);
    }

    const releaseEvidence = workflow.jobs?.["release-evidence"]?.steps ?? [];
    const attach = releaseEvidence.find((step) =>
      step.run?.includes("kaji/scripts/attach_release_assets.py"),
    );
    const attachedPaths = (attach?.run?.match(/\.artifacts\/[^\s]+/gu) ?? []).map((path) =>
      path.replace(/\s+$/u, ""),
    );
    expect(attachedPaths).toEqual([
      ".artifacts/kaji-release/kaji-sdk-0.2.0-beta.10.tgz",
      ".artifacts/kaji-release/manifest.json",
      ".artifacts/kaji-release/SHA256SUMS",
      ".artifacts/kaji-evidence/offline-gates.log",
      ".artifacts/kaji-evidence/offline-gate-summary.json",
      ".artifacts/kaji-evidence/provider-evidence.json",
      ".artifacts/kaji-evidence/typescript-onboarding/status.json",
      ".artifacts/kaji-evidence/typescript-onboarding/validation.log",
      ".artifacts/kaji-evidence/typescript-onboarding/typescript-onboarding-evidence.json",
      ".artifacts/kaji-evidence/paired-benchmark-results.json",
      ".artifacts/kaji-evidence/soak-results.json",
      ".artifacts/kaji-evidence/performance-status.json",
      ".artifacts/kaji-evidence/performance-imagedata.json",
      ".artifacts/kaji-evidence/compat-python-3.11.json",
      ".artifacts/kaji-evidence/compat-python-3.14.json",
      ".artifacts/kaji-evidence/compat-node-22.json",
      ".artifacts/kaji-evidence/compat-node-24.json",
      ".artifacts/kaji-evidence/release-evidence-validation.json",
      ".artifacts/kaji-evidence/sbom.spdx.json",
      ".artifacts/kaji-evidence/provenance.bundle.jsonl",
      ".artifacts/kaji-evidence/provenance.json",
      ".artifacts/kaji-publication-status/registry-verification.json",
      ".artifacts/kaji-publication-status/publication-status.json",
      ".artifacts/kaji-publication-status/publication-status.md",
      ".artifacts/kaji-publication-status/downloaded/registry-kaji-sdk-0.2.0-beta.10.tgz",
      ".artifacts/kaji-publication-status/downloaded/registry-kaji-sdk-0.2.0-beta.10.tgz.github-attestation.json",
      ".artifacts/kaji-publication-status/downloaded/npm-signature-audit.json",
    ]);
  });

  it("sets up frozen Python dependencies before central evidence validation", () => {
    const { source, workflow } = readWorkflow("kaji.publish.yml");
    const steps = workflow.jobs?.["supply-chain"]?.steps ?? [];
    const setupIndex = steps.findIndex((step) => step.uses === "./.github/actions/setup-python-uv");
    const validationSteps = steps.filter((step) =>
      step.run?.includes("kaji/scripts/validate_release_evidence.py"),
    );
    const validateIndex = steps.indexOf(validationSteps[0]!);

    expect(setupIndex).toBeGreaterThan(0);
    expect(steps[setupIndex]?.with).toMatchObject({
      "working-directory": "kaji",
      "python-version": "3.14",
      "sync-args": "--frozen",
    });
    expect(validationSteps).toHaveLength(1);
    expect(setupIndex).toBeLessThan(validateIndex);
    expect(validationSteps[0]?.run).toContain(
      "uv run --project kaji --no-sync python kaji/scripts/validate_release_evidence.py",
    );
    expect(source).not.toMatch(/^\s+python(?:3)?\s+kaji\/scripts\/validate_release_evidence\.py/m);
  });

  it.each(["kaji.rehearsal.yml", "kaji.publish.yml"] as const)(
    "binds %s performance evidence to the measured GitHub-hosted macOS image",
    (workflowName) => {
      const { workflow } = readWorkflow(workflowName);
      const call = workflow.jobs?.performance;
      expect(call?.uses).toBe("./.github/workflows/kaji.performance.yml");
      expect(call?.permissions).toEqual({ actions: "read", contents: "read" });

      const shared = readWorkflow("kaji.performance.yml").workflow;
      expect(shared.jobs?.["paired-replica"]?.["runs-on"]).toBe("macos-15");
      expect(shared.jobs?.soak?.["runs-on"]).toBe("macos-15");
      const paired = shared.jobs?.["paired-replica"];
      expect(paired?.strategy).toMatchObject({
        "fail-fast": false,
        matrix: { replica: [1, 2, 3] },
      });
      const measurement = paired?.steps?.find((step) =>
        step.run?.includes("paired_benchmark.py"),
      )?.run;
      expect(measurement).toContain('--runner-image-data "$HOME/imagedata.json"');
      const retainedImage = paired?.steps?.find((step) =>
        step.run?.includes("replica-${{ matrix.replica }}-imagedata.json"),
      )?.run;
      expect(retainedImage).toContain('cp "$HOME/imagedata.json"');
      const binder = shared.jobs?.["performance-evidence"]?.steps?.find((step) =>
        step.run?.includes("candidate.releaseManifestSha256"),
      )?.run;
      expect(binder).toContain("sha256sum");
      expect(binder).toContain("paired-benchmark-results.json");
      expect(JSON.stringify(shared)).not.toContain("baselineFingerprint");
    },
  );

  it("keeps paired performance on measured GitHub-hosted macOS images", () => {
    const benchmark = readWorkflow("kaji.benchmark.yml").workflow;
    expect(benchmark.jobs?.["release-artifacts"]?.["runs-on"]).toBe("ubuntu-latest");
    expect(benchmark.jobs?.performance?.uses).toBe("./.github/workflows/kaji.performance.yml");
    expect(JSON.stringify(benchmark)).not.toContain("calibrate");

    const shared = readWorkflow("kaji.performance.yml").workflow;
    for (const jobId of ["paired-replica", "soak"] as const) {
      const job = shared.jobs?.[jobId];
      expect(job, jobId).toBeDefined();
      expect(job?.["runs-on"], jobId).toBe("macos-15");
      const environment = effectiveEnvironment(shared, job!);
      expect(environment.KAJI_BENCHMARK_PINNED_RUNNER, jobId).toBeUndefined();
      expect(environment.KAJI_BENCHMARK_RUNNER_MANIFEST, jobId).toBeUndefined();
      expect(environment.KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256, jobId).toBeUndefined();
      expect(environment.KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST, jobId).toBeUndefined();
      expect(environment.KAJI_BENCHMARK_CALIBRATION, jobId).toBeUndefined();
    }

    const runtimeGuard = readFileSync(
      resolve(repositoryRoot, "kaji/scripts/benchmark_platform.py"),
      "utf8",
    );
    for (const guard of [
      'os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"',
      'os.environ.get("RUNNER_OS") != "macOS"',
      'os.environ.get("RUNNER_ARCH") != "ARM64"',
      'platform.system() != "Darwin"',
      'platform.machine().lower() != "arm64"',
      "imagedata.json",
      'getattr(os, "O_NOFOLLOW"',
      "os.fstat(descriptor)",
      "MAX_IMAGE_DATA_BYTES = 8 * 1024",
      "validate_retained_runner",
    ]) {
      expect(runtimeGuard).toContain(guard);
    }
    expect(runtimeGuard).not.toContain("imageDigest");
    expect(runtimeGuard).not.toContain("bootstrapManifestSha256");
  });
});

describe("Kaji workflow contract mutations", () => {
  it.each([
    ["called repository", { CALLED_WORKFLOW_REPOSITORY: "fork/alloy" }],
    ["called path", { CALLED_WORKFLOW_FILE_PATH: ".github/workflows/other.yml" }],
    ["called digest", { CALLED_WORKFLOW_SHA: "A".repeat(40) }],
    [
      "called canonical ref",
      { CALLED_WORKFLOW_REF: "enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@main" },
    ],
    ["caller repository", { CALLER_REPOSITORY: "fork/alloy" }],
    ["candidate digest", { CANDIDATE_SHA: "short" }],
    ["feature source ref", { CANDIDATE_REF: "refs/heads/feature" }],
    ["internal tag", { HANDOFF_TAG_NAME: "kaji-v1" }],
    ["open mode", { HANDOFF_MODE: "diagnostic" }],
  ] as const)("rejects mutated trusted handoff %s", (_label, environment) => {
    const guard = readWorkflow("kaji.handoff.trusted.yml").workflow.jobs?.stage?.steps?.[0];
    expect(guard).toBeDefined();
    expect(runTrustedHandoffGuard(guard!, environment).status).not.toBe(0);
  });

  it("accepts only the canonical release tag relation", () => {
    const guard = readWorkflow("kaji.handoff.trusted.yml").workflow.jobs?.stage?.steps?.[0];
    expect(guard).toBeDefined();
    const valid = runTrustedHandoffGuard(guard!, {
      HANDOFF_MODE: "release",
      HANDOFF_TAG_NAME: "kaji-beta.1",
      CANDIDATE_REF: "refs/tags/kaji-beta.1",
    });
    expect(valid.status, String(valid.stderr)).toBe(0);
    for (const tag of ["kaji-", "kaji-beta.lock", "kaji-beta/1", "Kaji-beta.1"]) {
      expect(
        runTrustedHandoffGuard(guard!, {
          HANDOFF_MODE: "release",
          HANDOFF_TAG_NAME: tag,
          CANDIDATE_REF: `refs/tags/${tag}`,
        }).status,
        tag,
      ).not.toBe(0);
    }
  });

  it.each([
    [
      "called identity binding",
      (workflow: Workflow): void => {
        workflow.jobs!.stage!.steps![0]!.env!.CALLED_WORKFLOW_REPOSITORY =
          "${{ github.repository }}";
      },
    ],
    [
      "top-level token environment",
      (workflow: Workflow): void => {
        workflow.env = { GH_TOKEN: "${{ github.token }}" };
      },
    ],
    [
      "job-scoped token environment",
      (workflow: Workflow): void => {
        workflow.jobs!.finalize!.env = { NODE_AUTH_TOKEN: "${{ secrets.node_auth_token }}" };
      },
    ],
    [
      "aliased token expression",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.finalize!, "Upload exact consumer handoff").with!.SAFE_ALIAS =
          "${{ github.token }}";
      },
    ],
    [
      "preflight stage output authority",
      (workflow: Workflow): void => {
        workflow.jobs!.stage!.outputs!["preflight-sha256"] =
          "${{ steps.stage.outputs.artifact-sha256 }}";
      },
    ],
    [
      "preflight finalizer binding",
      (workflow: Workflow): void => {
        workflowStep(
          workflow.jobs!.finalize!,
          "Authenticate exact preflight transfer",
        ).env!.EXPECTED_PREFLIGHT_SHA256 = "${{ needs.stage.outputs.artifact-sha256 }}";
      },
    ],
    [
      "preflight content hash",
      (workflow: Workflow): void => {
        const authenticate = workflowStep(
          workflow.jobs!.finalize!,
          "Authenticate exact preflight transfer",
        );
        authenticate.run = authenticate.run!.replace(
          `sha256sum "$preflight"`,
          `printf '%s' "$stage_preflight_sha256"`,
        );
      },
    ],
    [
      "preflight guard ordering",
      (workflow: Workflow): void => {
        const steps = workflow.jobs!.finalize!.steps!;
        const authenticate = steps.findIndex(
          (step) => step.name === "Authenticate exact preflight transfer",
        );
        const [guard] = steps.splice(authenticate, 1);
        const setup = steps.findIndex((step) => step.name === "Set up recorded Bun");
        steps.splice(setup + 1, 0, guard!);
      },
    ],
    [
      "independent validation continue-on-error",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.finalize!, "Independently validate exact consumer handoff")[
          "continue-on-error"
        ] = true;
      },
    ],
    [
      "independent validation condition",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.finalize!, "Independently validate exact consumer handoff").if =
          "${{ always() }}";
      },
    ],
    [
      "job-level condition",
      (workflow: Workflow): void => {
        workflow.jobs!.finalize!.if = "${{ always() }}";
      },
    ],
    [
      "preflight condition drift",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.stage!, "Preflight release handoff").if = "${{ always() }}";
      },
    ],
    [
      "post-checkout shell fetch",
      (workflow: Workflow): void => {
        const history = workflowStep(
          workflow.jobs!.stage!,
          "Establish protected-main history and clean checkouts",
        );
        history.run = `${history.run}\ngit -C "$checkout" fetch origin main`;
      },
    ],
    [
      "main tracking-ref drift",
      (workflow: Workflow): void => {
        const history = workflowStep(
          workflow.jobs!.finalize!,
          "Establish protected-main history and clean checkouts",
        );
        history.run = history.run!.replace(
          "refs/remotes/origin/main^{commit}",
          "refs/heads/main^{commit}",
        );
      },
    ],
    [
      "checkout fetch depth",
      (workflow: Workflow): void => {
        const checkout = workflow.jobs!.stage!.steps!.find((step) =>
          step.uses?.startsWith("actions/checkout@"),
        );
        checkout!.with!["fetch-depth"] = 1;
      },
    ],
    [
      "checkout credential persistence",
      (workflow: Workflow): void => {
        const checkout = workflow.jobs!.finalize!.steps!.find((step) =>
          step.uses?.startsWith("actions/checkout@"),
        );
        checkout!.with!["persist-credentials"] = true;
      },
    ],
    [
      "stage/composite adjacency",
      (workflow: Workflow): void => {
        const steps = workflow.jobs!.stage!.steps!;
        const stage = steps.findIndex(
          (step) => step.name === "Stage the immutable package exactly once",
        );
        steps.splice(stage + 1, 0, { name: "mutated gap", run: "true" });
      },
    ],
    [
      "composite token environment",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.stage!, "Prove the supplied artifact contract").env = {
          GH_TOKEN: "${{ github.token }}",
        };
      },
    ],
    [
      "wildcard stage transfer",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.stage!, "Upload exact stage transfer envelope").with!.path =
          ".artifacts/**";
      },
    ],
    [
      "hidden-file exclusion",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.stage!, "Upload artifact-contract receipt only").with![
          "include-hidden-files"
        ] = false;
      },
    ],
    [
      "matrix shared output",
      (workflow: Workflow): void => {
        workflow.jobs!.node!.outputs = { receipt: "${{ steps.smoke.outputs.receipt }}" };
      },
    ],
    [
      "wildcard receipt download",
      (workflow: Workflow): void => {
        const step = workflow.jobs!.finalize!.steps!.find((candidate) =>
          candidate.name?.includes("Download exact Node 22"),
        )!;
        step.with!.name = "kaji-ts-handoff-node-*";
      },
    ],
    [
      "attestation subject drift",
      (workflow: Workflow): void => {
        workflowStep(workflow.jobs!.finalize!, "Attest exact consumer handoff").with![
          "subject-path"
        ] = ".artifacts/kaji-handoff/*";
      },
    ],
  ] as const)("rejects trusted handoff structural mutation: %s", (_label, mutate) => {
    const current = readWorkflow("kaji.handoff.trusted.yml");
    const workflow = structuredClone(current.workflow);
    mutate(workflow);
    expect(() => assertTrustedHandoffWorkflow(workflow, current.source)).toThrow();
  });

  it.each([
    ["job continue-on-error", (job: WorkflowJob): void => void (job["continue-on-error"] = true)],
    ["job if false", (job: WorkflowJob): void => void (job.if = false)],
    [
      "setup continue-on-error",
      (job: WorkflowJob): void => void (job.steps![1]!["continue-on-error"] = true),
    ],
    ["setup if false", (job: WorkflowJob): void => void (job.steps![2]!.if = false)],
    [
      "command continue-on-error",
      (job: WorkflowJob): void => void (job.steps![4]!["continue-on-error"] = true),
    ],
    ["command if false", (job: WorkflowJob): void => void (job.steps![4]!.if = false)],
  ] as const)("rejects %s on the required PR gate path", (_label, mutate) => {
    const workflow = structuredClone(readWorkflow("kaji.gate.yml").workflow);
    mutate(gateJob(workflow));

    expect(() => assertProtectionReadyGate(workflow)).toThrow();
  });

  it.each([
    ["false", false],
    ["string", "all"],
    ["number", 1],
    ["array", []],
    ["filtered mapping", { paths: ["**"] }],
  ] as const)("rejects an invalid pull_request trigger: %s", (_label, trigger) => {
    const workflow = structuredClone(readWorkflow("kaji.gate.yml").workflow);
    workflow.on!.pull_request = trigger;

    expect(() => assertProtectionReadyGate(workflow)).toThrow();
  });

  it("accepts an empty unfiltered pull_request mapping", () => {
    const workflow = structuredClone(readWorkflow("kaji.gate.yml").workflow);
    workflow.on!.pull_request = {};

    expect(() => assertProtectionReadyGate(workflow)).not.toThrow();
  });

  it.each(["checks", "deployments", "security-events", "id-token"] as const)(
    "rejects unexpected %s write permission on the PR gate",
    (permission) => {
      const workflow = structuredClone(readWorkflow("kaji.gate.yml").workflow);
      gateJob(workflow).permissions = { contents: "read", [permission]: "write" };

      expect(() => assertNarrowPermissions("kaji.gate.yml", workflow)).toThrow();
    },
  );

  it("rejects permission drift on a privileged release job", () => {
    const workflow = structuredClone(readWorkflow("kaji.publish.yml").workflow);
    const supplyChain = workflow.jobs?.["supply-chain"];
    if (!supplyChain?.permissions) throw new Error("missing supply-chain permissions");
    supplyChain.permissions.checks = "write";

    expect(() => assertNarrowPermissions("kaji.publish.yml", workflow)).toThrow();
  });

  it("rejects a transitive floating action in a nested local composite", () => {
    withTemporaryRepository((root) => {
      writeFixture(
        root,
        ".github/workflows/test.yml",
        "jobs:\n  test:\n    steps:\n      - uses: ./.github/actions/outer\n",
      );
      writeFixture(
        root,
        ".github/actions/outer/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/nested\n",
      );
      writeFixture(
        root,
        ".github/actions/nested/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: actions/checkout@v4 # v4.3.1\n",
      );

      expect(() => assertReviewedActionDocuments([".github/workflows/test.yml"], root)).toThrow();
    });
  });

  it("rejects a missing local action", () => {
    withTemporaryRepository((root) => {
      writeFixture(
        root,
        ".github/workflows/test.yml",
        "jobs:\n  test:\n    steps:\n      - uses: ./.github/actions/missing\n",
      );

      expect(() => assertReviewedActionDocuments([".github/workflows/test.yml"], root)).toThrow();
    });
  });

  it("rejects a cycle in local composite actions", () => {
    withTemporaryRepository((root) => {
      writeFixture(
        root,
        ".github/workflows/test.yml",
        "jobs:\n  test:\n    steps:\n      - uses: ./.github/actions/outer\n",
      );
      writeFixture(
        root,
        ".github/actions/outer/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/nested\n",
      );
      writeFixture(
        root,
        ".github/actions/nested/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/outer\n",
      );

      expect(() => assertReviewedActionDocuments([".github/workflows/test.yml"], root)).toThrow();
    });
  });
});
