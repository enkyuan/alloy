import { describe, expect, it, vi } from "vitest";
import { spawnSync } from "node:child_process";
import {
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
    "tthw-evidence": "time-to-hello-world evidence",
    "keyed-proof": "keyed provider proof",
    "candidate-evidence": "release candidate evidence",
  },
  "kaji.publish.yml": {
    "verify-tag": "verify release tag",
    "offline-gates": "offline release gates",
    performance: "performance evidence",
    "python-compat": "Python ${{ matrix.python-version }} compatibility",
    "node-compat": "Node ${{ matrix.node-version }} compatibility",
    "tthw-evidence": "time-to-hello-world evidence",
    "keyed-proof": "keyed provider proof",
    "supply-chain": "supply-chain evidence",
    "registry-preflight": "registry preflight",
    "publisher-preflight": "publisher preflight",
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
  },
  "kaji.publish.yml": {
    performance: { actions: "read", contents: "read" },
    "supply-chain": {
      contents: "read",
      "id-token": "write",
      attestations: "write",
    },
    "publisher-preflight": { contents: "read" },
    "publish-npm": { contents: "read", "id-token": "write" },
    "publication-status": { contents: "read", attestations: "read" },
    "publication-incident": { contents: "write" },
    "release-evidence": { contents: "write" },
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
  });

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

  it("gates rehearsal and publication on exact-commit protected TTHW evidence", () => {
    const rehearsal = readWorkflow("kaji.rehearsal.yml");
    const publish = readWorkflow("kaji.publish.yml");

    expect(Object.keys(rehearsal.workflow.jobs ?? {})).toHaveLength(7);
    expect(Object.keys(publish.workflow.jobs ?? {})).toHaveLength(14);
    for (const [workflowName, { source, workflow }] of [
      ["kaji.rehearsal.yml", rehearsal],
      ["kaji.publish.yml", publish],
    ] as const) {
      const job = workflow.jobs?.["tthw-evidence"];
      expect(job?.needs).toEqual(
        workflowName === "kaji.rehearsal.yml"
          ? ["offline-release", "python-compat", "node-compat"]
          : ["verify-tag", "offline-gates", "performance", "python-compat", "node-compat"],
      );
      expect(job?.environment).toBe("kaji-beta");
      expect(effectivePermissions(workflow, job!)).toEqual(readOnlyPermissions);
      expect(JSON.stringify(job?.env ?? {})).not.toContain("secrets.KAJI_TTHW_EVIDENCE_JSON");
      expect(source.match(/\$\{\{ secrets\.KAJI_TTHW_EVIDENCE_JSON \}\}/g)).toHaveLength(1);

      const secretSteps = (job?.steps ?? []).filter((step) =>
        JSON.stringify(step).includes("secrets.KAJI_TTHW_EVIDENCE_JSON"),
      );
      expect(secretSteps).toHaveLength(1);
      expect(secretSteps[0]?.name).toBe("Validate protected exact-commit five-user TTHW evidence");
      expect(secretSteps[0]?.run).toContain("validate_tthw_evidence.py");
      expect(secretSteps[0]?.run).toContain(
        "--release-manifest .artifacts/kaji-release/manifest.json",
      );
      expect(secretSteps[0]?.run).toContain("--artifacts-dir .artifacts/kaji-release");
      expect(secretSteps[0]?.run).toContain(
        "--python-compatibility-receipt .artifacts/kaji-tthw-compat/python-3.14/compatibility-receipt.json",
      );
      expect(secretSteps[0]?.run).toContain(
        "--node-compatibility-receipt .artifacts/kaji-tthw-compat/node-24/compatibility-receipt.json",
      );
      expect(secretSteps[0]?.run).toContain("--expected-workflow-run-attempt");
      expect(secretSteps[0]?.run).toContain('if [ "$status" -eq 0 ]; then');

      const compatibilityDownloads = (job?.steps ?? []).filter((step) =>
        ["kaji-python-compat-3.14", "kaji-node-compat-24"].includes(String(step.with?.name ?? "")),
      );
      expect(compatibilityDownloads.map((step) => step.with?.name)).toEqual([
        "kaji-python-compat-3.14",
        "kaji-node-compat-24",
      ]);
      expect(compatibilityDownloads.map((step) => step.with?.path)).toEqual([
        ".artifacts/kaji-tthw-compat/python-3.14",
        ".artifacts/kaji-tthw-compat/node-24",
      ]);
      expect(
        compatibilityDownloads.every((step) => !String(step.with?.name).endsWith("-initial")),
      ).toBe(true);

      const uploads = (job?.steps ?? []).filter((step) =>
        step.uses?.startsWith("actions/upload-artifact@"),
      );
      expect(uploads.map((step) => step.with?.name)).toEqual([
        "kaji-tthw-evidence-initial",
        "kaji-tthw-evidence",
      ]);
      expect(uploads[1]?.if).toBe("${{ always() }}");
    }

    expect(dependencyClosure(rehearsal.workflow, "keyed-proof")).toContain("tthw-evidence");
    for (const jobId of [
      "keyed-proof",
      "supply-chain",
      "registry-preflight",
      "publisher-preflight",
      "publish-npm",
      "publication-status",
      "publication-incident",
      "release-evidence",
    ]) {
      expect(dependencyClosure(publish.workflow, jobId), jobId).toContain("tthw-evidence");
    }
    expect(publish.workflow.jobs?.["tthw-evidence"]?.if).toContain("github.run_attempt == 1");
    expect(publish.workflow.jobs?.["tthw-evidence"]?.if).toContain(
      "needs.performance.result == 'success'",
    );
    expect(rehearsal.workflow.jobs?.["tthw-evidence"]?.if).not.toContain("github.run_attempt == 1");

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

  it("collects TTHW from current tag artifacts before environment approval", () => {
    const runbookSource = readFileSync(resolve(repositoryRoot, "docs/kaji/releasing.md"), "utf8");
    const runbook = runbookSource.replace(/\s+/gu, " ");
    const orderedSteps = [
      "Before creating the tag, configure the required `kaji-beta` reviewer",
      "Leave `KAJI_TTHW_EVIDENCE_JSON` unset",
      "Create and push the signed, annotated tag",
      "Wait for the exact tag-triggered workflow run",
      "Download `kaji-beta-artifacts` by the exact workflow run ID and artifact ID",
      "Generate five candidate-bound participant skeletons",
      "Set `KAJI_TTHW_EVIDENCE_JSON`",
      "Only then approve the waiting `tthw-evidence` job",
    ];
    const positions = orderedSteps.map((step) => runbook.indexOf(step));

    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((left, right) => left - right));
    expect(runbook).toContain("`kaji-beta` approval is the safe pause");
    expect(runbook).toContain("Do not remove the approval requirement");
    for (const exactBinding of [
      "set -euo pipefail",
      "umask 077",
      ': "${RUN_ID:?set RUN_ID to the numeric tag-triggered workflow run ID}"',
      "actions/runs/$RUN_ID/artifacts?per_page=100",
      'select(.name == "kaji-beta-artifacts" and .expired == false)',
      'case "$ARTIFACT_ID" in',
      "*[!0-9]*",
      'mktemp -d "$HOME/.kaji-release-${RUN_ID}.XXXXXX"',
      "actions/artifacts/$ARTIFACT_ID/zip",
      'unzip -q "$ARCHIVE" -d "$ARTIFACTS_DIR"',
    ]) {
      expect(runbook).toContain(exactBinding);
    }
    expect(runbook).not.toContain("RUN_ID=<tag-triggered-publish-run-id>");
    expect(runbook).not.toContain("/secure/");
    const artifactShell =
      "set -euo pipefail" + runbookSource.split("set -euo pipefail", 2)[1]!.split("```", 1)[0]!;
    const syntax = spawnSync("/bin/bash", ["-n"], {
      encoding: "utf8",
      input: artifactShell,
    });
    expect(syntax.status, syntax.stderr).toBe(0);
    expect(runbook).toContain(
      "Prior release, rehearsal, and performance artifacts are invalid substitutes.",
    );
    expect(runbook).toContain("`kaji-beta-publish` remains a separate");

    const guide = readFileSync(
      resolve(repositoryRoot, "docs/kaji/tthw-evidence.md"),
      "utf8",
    ).replace(/\s+/gu, " ");
    expect(guide).toContain("exact `kaji-beta-artifacts` upload from the current tag-triggered");
    expect(guide).toContain("workflow run ID and artifact ID");
    expect(guide).toContain(': "${EVIDENCE_ROOT:?follow the release runbook first}"');
    expect(guide).toContain(': "${ARTIFACTS_DIR:?follow the release runbook first}"');
    expect(guide).toContain('TTHW_DIR="$EVIDENCE_ROOT/tthw"');
    expect(guide).not.toContain("/secure/");
    expect(guide).toContain("never rerun only the TTHW job");
    expect(guide).toContain("Mixed-attempt receipts are intentionally rejected");
    expect(guide).toContain(
      "Prior release, rehearsal, and performance artifacts are invalid substitutes.",
    );
  });

  it("binds the current TypeScript candidate to beta.6 and preserves beta.5 as unpublished history", () => {
    const packageManifest = JSON.parse(readFileSync(resolve("package.json"), "utf8")) as {
      name: string;
      version: string;
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
    expect(packageManifest.version).toBe("0.2.0-beta.6");
    expect(packageManifest.version).not.toBe("0.2.0-beta.2");
    expect(packageManifest.version).not.toBe("0.2.0-beta.4");
    expect(sourceVersion?.[1]).toBe(packageManifest.version);
    expect(packageSmokeVersion?.[1]).toBe(packageManifest.version);
    expect(tarball).toBe(`kaji-sdk-${packageManifest.version}.tgz`);
    expect(tarball).toBe("kaji-sdk-0.2.0-beta.6.tgz");
    for (const name of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const { source } = readWorkflow(name);
      expect(source).toContain(tarball);
      expect(source).not.toContain("0.2.0-beta.2");
      expect(source).not.toContain("0.2.0-beta.4");
      expect(source).not.toContain("0.2.0-beta.5");
    }

    const changelog = readFileSync(resolve("CHANGELOG.md"), "utf8");
    expect(changelog).toContain("## [0.2.0-beta.6] - 2026-07-26");
    expect(changelog).toMatch(
      /## \[0\.2\.0-beta\.5\][\s\S]*signed,[\s\S]*unpublished[\s\S]*superseded before registry publication/i,
    );
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
        const normalize = steps.findIndex(
          (step) => step.name === "Normalize compatibility receipt",
        );
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
        expect(steps[download]?.with).toMatchObject({
          name: "kaji-beta-artifacts",
          path: ".artifacts/kaji-release",
        });
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
        expect(steps[normalize]?.run).toContain('conclusion == "passed"');
        expect(steps[normalize]?.run).toContain('conclusion == "failed"');
        expect(steps[normalize]?.run).toContain("compatibility_receipt_not_terminal");
        expect(steps[normalize]?.run).toContain(".timings");
        expect(steps[normalize]?.run).toContain('keys == ["sdist", "wheel"]');
        expect(steps[normalize]?.run).toContain('keys == ["bun", "npm"]');
        expect(steps[normalize]?.run).toContain("9007199254740991");
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

    const npmPublish = workflowStep(jobs["publish-npm"]!, "Publish exact npm beta with provenance");
    const npmPublishRun = npmPublish.run ?? "";
    expect(npmPublishRun).toContain("npm whoami --registry=https://registry.npmjs.org/");
    expect(npmPublishRun).toContain("npm publish");
    expect(npmPublishRun.indexOf("npm whoami")).toBeLessThan(npmPublishRun.indexOf("npm publish"));
    expect(npmPublishRun).toContain('"$IDENTITY" = "$EXPECTED_NPM_PUBLISHER"');
    expect(npmPublish.env).toMatchObject({
      NODE_AUTH_TOKEN: "${{ secrets.NPM_TOKEN }}",
      EXPECTED_NPM_PUBLISHER: "${{ vars.KAJI_NPM_PUBLISHER }}",
    });
    expect(npmPublish.run).toContain("--provenance");
    expect(npmPublish.run).toContain("--access public");
    expect(npmPublish.run).toContain("--tag beta");
    expect([...dependencyClosure(workflow, "publish-npm")].sort()).toEqual([
      "keyed-proof",
      "node-compat",
      "offline-gates",
      "performance",
      "publisher-preflight",
      "python-compat",
      "registry-preflight",
      "supply-chain",
      "tthw-evidence",
      "verify-tag",
    ]);

    const publicationStatus = jobs["publication-status"]!;
    expect(publicationStatus.needs).toEqual([
      "verify-tag",
      "supply-chain",
      "registry-preflight",
      "publisher-preflight",
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
    expect(exactState.if).toContain("npm_byte_verified");
    expect(jobs["publication-incident"]?.if).toContain("npm_byte_verified");
    expect(jobs["release-evidence"]?.if).toContain("npm_byte_verified");

    const pythonEvidence = JSON.stringify(jobs["supply-chain"]);
    expect(pythonEvidence).toContain("kaji_sdk-0.2.0b1-py3-none-any.whl");
    expect(pythonEvidence).toContain("kaji_sdk-0.2.0b1.tar.gz");

    const releaseAttach = jobs["release-evidence"]?.steps?.find((step) =>
      step.run?.includes("kaji/scripts/attach_release_assets.py"),
    )?.run;
    expect(releaseAttach).toContain("kaji-sdk-0.2.0-beta.6.tgz");
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
      expect(workflowStep(workflow.jobs?.[jobId]!, stepName).run).toContain(
        "bun run --cwd kaji/ts build",
      );
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
          "tthw-evidence",
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
          "tthw-evidence",
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
      "tthw-evidence",
      "keyed-proof",
      "python-compat",
      "node-compat",
    ]);
    expect(evidence?.if).toBe("${{ always() && needs.offline-release.result == 'success' }}");
    const steps = evidence?.steps ?? [];
    const downloads = steps.filter((step) => step.uses?.startsWith("actions/download-artifact@"));
    const requiredDownloads = downloads.filter((step) => !step["continue-on-error"]);
    expect(requiredDownloads.map((step) => step.with?.name)).toEqual([
      "kaji-beta-artifacts",
      "kaji-offline-evidence",
    ]);
    expect(
      downloads.filter((step) => step["continue-on-error"]).map((step) => step.with?.name),
    ).toEqual([
      "kaji-provider-evidence",
      "kaji-tthw-evidence",
      "kaji-performance-evidence",
      "kaji-python-compat-3.11",
      "kaji-python-compat-3.14",
      "kaji-node-compat-22",
      "kaji-node-compat-24",
    ]);
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
      "--python-compat-311",
      "--python-compat-314",
      "--node-compat-22",
      "--node-compat-24",
      "--performance-status",
      "--benchmark-results",
      "--soak-results",
      "--performance-image-data",
      "--provider-evidence",
      "--tthw-status",
      "--tthw-evidence",
      "--output",
    ]) {
      expect(validation?.run, flag).toContain(flag);
    }
    const upload = steps.find(
      (step) =>
        step.uses?.startsWith("actions/upload-artifact@") &&
        step.with?.name === "kaji-release-candidate-evidence",
    );
    expect(steps.indexOf(upload!)).toBeGreaterThan(validationIndex);
    expect(upload?.if).toBe("${{ always() }}");
    expect(upload?.with?.["if-no-files-found"]).toBe("error");
  });

  it("terminal-normalizes protected TTHW and provider receipts after every failure boundary", () => {
    for (const workflowName of ["kaji.rehearsal.yml", "kaji.publish.yml"] as const) {
      const workflow = readWorkflow(workflowName).workflow;
      for (const [jobId, normalizerName, uploadName] of [
        ["tthw-evidence", "Normalize terminal TTHW status", "kaji-tthw-evidence"],
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
      "${{ always() && needs.verify-tag.result == 'success' && needs.offline-gates.result == 'success' }}",
    );
    const steps = supplyChain?.steps ?? [];
    const compatibilityDownloads = steps.filter((step) =>
      String(step.with?.name ?? "").match(/^kaji-(python|node)-compat-(3\.11|3\.14|22|24)$/),
    );
    expect(compatibilityDownloads.map((step) => step.with?.name)).toEqual([
      "kaji-python-compat-3.11",
      "kaji-python-compat-3.14",
      "kaji-node-compat-22",
      "kaji-node-compat-24",
    ]);
    const rename = steps.find((step) => step.name === "Uniquely name final compatibility receipts");
    expect(rename?.run).toContain("compat-python-3.11.json");
    expect(rename?.run).toContain("compat-python-3.14.json");
    expect(rename?.run).toContain("compat-node-22.json");
    expect(rename?.run).toContain("compat-node-24.json");

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
      "--tthw-status",
      "--tthw-evidence",
      "--workspace",
      "--output",
    ]) {
      expect(validation).toContain(flag);
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
    for (const filename of [
      "compat-python-3.11.json",
      "compat-python-3.14.json",
      "compat-node-22.json",
      "compat-node-24.json",
      "performance-imagedata.json",
      "release-evidence-validation.json",
    ]) {
      expect(attach?.run).toContain(filename);
    }
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
      const job = shared.jobs?.[jobId]!;
      expect(job["runs-on"], jobId).toBe("macos-15");
      const environment = effectiveEnvironment(shared, job);
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
