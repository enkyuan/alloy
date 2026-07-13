import { describe, expect, it, vi } from "vitest";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, relative, resolve } from "node:path";
import { inspect } from "node:util";

import { startSpan, type TraceSink } from "@/observability";
import { providerAPIErrorFromUnknown } from "@/providers/errors";
import { AgentBuilder } from "@/runtime/builder";
import { ToolExecutionController } from "@/tools/execution";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";

describe("release redaction boundaries", () => {
  it.each([
    "tests/integration/openai-tools.test.ts",
    "tests/integration/anthropic-live.test.ts",
  ])("keeps %s on the stable event committer path", (relativePath) => {
    const source = readFileSync(resolve(relativePath), "utf8");

    expect(source).not.toContain("import { EventBus }");
    expect(source).not.toMatch(/\.build\(\{[^}]*\bbus:/s);
    expect(source).toMatch(/\.build\(\{\s*store(?:\s*:|\s*\})/s);
  });

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
    expect(error.responseText).toBeUndefined();
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
  "ast-grep.yml",
  "kaji.benchmark.yml",
  "kaji.beta-pr.yml",
  "kaji.beta.yml",
  "kaji.beta-publish.yml",
] as const;
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
  "kaji/sdk/uv.lock",
  ...workflowFiles.map((name) => `.github/workflows/${name}`),
];
const reviewedActionPins: Record<string, string> = {
  "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
  "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
  "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
  "actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093",
  "actions/github-script": "f28e40c7f34bde8b3046d885e986cb6290c5673b",
  "actions/attest-build-provenance": "e8998f949152b193b063cb0ec769d69d929409be",
  "anchore/sbom-action": "fbfd9c6c189226748411491745178e0c2017392d",
  "pypa/gh-action-pypi-publish": "cef221092ed1bacb1cc03d23a2d87d1d172e277b",
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
  "pypa/gh-action-pypi-publish": "v1.14.0",
  "actions/setup-python": "v5.6.0",
  "astral-sh/setup-uv": "v3.2.4",
  "oven-sh/setup-bun": "v2.2.0",
  "actions/cache": "v4.3.0",
};
const readOnlyPermissions: PermissionMap = { contents: "read" };
const expectedJobPermissionDeclarations: Partial<
  Record<(typeof workflowFiles)[number], Record<string, PermissionMap>>
> = {
  "kaji.beta-publish.yml": {
    "supply-chain": {
      contents: "read",
      "id-token": "write",
      attestations: "write",
    },
    "publisher-preflight": { contents: "read" },
    "publish-python": { contents: "read", "id-token": "write" },
    "publish-npm": { contents: "read", "id-token": "write" },
    "publication-status": { contents: "read", attestations: "read" },
    "publication-incident": { contents: "write" },
    "release-evidence": { contents: "write" },
  },
};
const requiredGateCommands = [
  "uv run --project kaji/sdk python kaji/scripts/check_beta_contract.py",
  "uv run --project kaji/sdk python kaji/scripts/sync_beta_contracts.py --check",
  "uv run --project kaji/sdk python kaji/scripts/sync_integration_contracts.py --check",
  "uv run --project kaji/sdk python kaji/scripts/check_integration_abi.py --explain",
  "uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- uv run --project kaji/sdk --no-sync python kaji/scripts/check_sdk_parity.py",
  "bun run audit:ast-grep",
  "uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- uv run --project kaji/sdk --no-sync python kaji/scripts/run_beta_benchmarks.py --quick",
  "uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- uv run --project kaji/sdk --no-sync python kaji/scripts/integration_benchmark.py --mode quick",
  'uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- uv run --project kaji/sdk --no-sync pytest -m "not integration"',
  "uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- bun run --cwd kaji/ts build",
  "uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- bun run --cwd kaji/ts test",
];

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

function actionSteps(value: Record<string, unknown>): WorkflowStep[] {
  const workflow = value as Workflow;
  const jobSteps = Object.values(workflow.jobs ?? {}).flatMap((job) => [
    ...(job.uses ? [{ uses: job.uses }] : []),
    ...(job.steps ?? []),
  ]);
  const compositeSteps = (value.runs as { steps?: WorkflowStep[] } | undefined)?.steps ?? [];
  return [...jobSteps, ...compositeSteps].filter((step) => step.uses !== undefined);
}

function localActionDocument(root: string, reference: string): string {
  const directory = resolve(root, reference);
  const fromRoot = relative(root, directory);
  if (fromRoot === ".." || fromRoot.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`)) {
    throw new Error(`local action escapes the repository: ${reference}`);
  }
  const candidates = [resolve(directory, "action.yml"), resolve(directory, "action.yaml")].filter(
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
    const externalSteps = steps.filter((step) => !step.uses!.startsWith("./"));
    for (const step of externalSteps) {
      const [action, revision] = step.uses!.split("@");
      expect(revision, `${relativePath}:${step.uses}`).toMatch(/^[0-9a-f]{40}$/);
      expect(revision, `${relativePath}:${step.uses}`).toBe(reviewedActionPins[action!]);
    }
    const annotatedExternalReferences = [
      ...source.matchAll(/^\s*(?:-\s*)?uses:\s+([^\s#]+)(?:\s+#\s+([^\s]+))?\s*$/gm),
    ].filter(([, reference]) => !reference!.startsWith("./"));
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

  expect(workflow.name).toBe("Kaji beta PR gate");
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
  expect(job.name).toBe("Kaji beta PR gate");
  expect(job.strategy).toBeUndefined();
  expect(job.if).toBeUndefined();
  expect(job["continue-on-error"] ?? false).toBe(false);
  expect(job["timeout-minutes"]).toBeGreaterThan(0);
  expect(job.defaults?.run?.["working-directory"]).toBe(".");
  expect(effectivePermissions(workflow, job)).toEqual({ contents: "read" });

  const steps = job.steps ?? [];
  expect(steps).toHaveLength(14);
  for (const [index, step] of steps.entries()) {
    expect(step.if, `gate step ${index} must execute normally`).toBeUndefined();
    expect(step["continue-on-error"] ?? false, `gate step ${index} must fail closed`).toBe(false);
  }
  expect(steps.slice(0, 3).map((step) => step.uses)).toEqual([
    `actions/checkout@${reviewedActionPins["actions/checkout"]}`,
    "./.github/actions/setup-python-uv",
    "./.github/actions/setup-bun-cache",
  ]);

  const checkout = steps[0];
  expect(checkout?.uses).toBe(`actions/checkout@${reviewedActionPins["actions/checkout"]}`);
  expect(
    steps.find((step) => step.uses === "./.github/actions/setup-python-uv")?.with,
  ).toMatchObject({ "working-directory": "kaji/sdk", "sync-args": "--frozen" });
  expect(
    steps.find((step) => step.uses === "./.github/actions/setup-bun-cache")?.with,
  ).toMatchObject({
    "working-directory": ".",
    "bun-version": "1.3.11",
    "install-args": "--frozen-lockfile",
  });
  expect(steps.flatMap((step) => (step.run ? [step.run.trim()] : []))).toEqual(
    requiredGateCommands,
  );
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
  if (!job) throw new Error("missing Kaji beta PR gate job");
  return job;
}

describe("Kaji workflow contracts", () => {
  it.each([
    ["python.test.yml", ["kaji/sdk/**", "kaji/serve/**"]],
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
    const { workflow } = readWorkflow("kaji.beta-pr.yml");
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

  it("bounds every Kaji job and keeps effective permissions narrow", () => {
    for (const name of workflowFiles) {
      const { workflow } = readWorkflow(name);
      for (const [jobId, job] of Object.entries(workflow.jobs ?? {})) {
        expect(job["timeout-minutes"], `${name}:${jobId}`).toBeGreaterThan(0);
        if (job["timeout-minutes"] === 75) {
          expect(`${name}:${jobId}`).toBe("kaji.beta-publish.yml:performance");
        }
      }
      assertNarrowPermissions(name, workflow);
    }
  });

  it("gates rehearsal and publication on exact-commit protected TTHW evidence", () => {
    const rehearsal = readWorkflow("kaji.beta.yml");
    const publish = readWorkflow("kaji.beta-publish.yml");

    expect(Object.keys(rehearsal.workflow.jobs ?? {})).toHaveLength(5);
    expect(Object.keys(publish.workflow.jobs ?? {})).toHaveLength(15);
    for (const { source, workflow } of [rehearsal, publish]) {
      const job = workflow.jobs?.["tthw-evidence"];
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
      expect(secretSteps[0]?.run).toContain('if [ "$status" -eq 0 ]; then');

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
      "publish-python",
      "publish-npm",
      "publication-status",
      "publication-incident",
      "release-evidence",
    ]) {
      expect(dependencyClosure(publish.workflow, jobId), jobId).toContain("tthw-evidence");
    }
    expect(publish.workflow.jobs?.["tthw-evidence"]?.if).toContain("github.run_attempt == 1");

    const classifier = publish.workflow.jobs?.["publication-status"]?.steps?.find(
      (step) => step.name === "Reduce monotonic publication state",
    );
    expect(classifier?.run).toContain('[ "$PYPI_STATE" = absent ]');
    expect(classifier?.run).toContain('[ "$NPM_STATE" = absent ]');
    expect(classifier?.run).toContain('[ "$REGISTRY_VERIFICATION" = not_run ]');
    expect(classifier?.run).toContain('[ "$PYPI_PUBLISH_RESULT" = skipped ]');
    expect(classifier?.run).toContain('[ "$NPM_PUBLISH_RESULT" = skipped ]');
  });

  it("keeps calibration on the protected pinned runner", () => {
    const { workflow } = readWorkflow("kaji.benchmark.yml");
    const jobs = workflow.jobs ?? {};
    for (const [jobId, job] of Object.entries(jobs)) {
      expect(job["runs-on"], jobId).toEqual(["self-hosted", "linux", "x64", "kaji-benchmark"]);
      const environment = effectiveEnvironment(workflow, job);
      expect(environment.KAJI_BENCHMARK_PINNED_RUNNER, jobId).toBe("1");
      expect(environment.KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST, jobId).toBe(
        "${{ vars.KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST }}",
      );
      expect(environment.KAJI_BENCHMARK_CALIBRATION, jobId).toBe(
        jobId === "calibrate" ? "1" : undefined,
      );
    }
    expect(jobs.calibrate?.if).toBe(
      "github.event_name == 'workflow_dispatch' && inputs.job == 'calibrate'",
    );

    const runtimeGuard = readFileSync(
      resolve(repositoryRoot, "kaji/scripts/beta_benchmark_gate.py"),
      "utf8",
    );
    for (const guard of [
      'os.environ.get("KAJI_BENCHMARK_CALIBRATION") != "1"',
      'os.environ.get("KAJI_BENCHMARK_PINNED_RUNNER") != "1"',
      'current["runner"]["imageDigest"] == "local-unpinned"',
    ]) {
      expect(runtimeGuard).toContain(guard);
    }
  });
});

describe("Kaji workflow contract mutations", () => {
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
      (job: WorkflowJob): void => void (job.steps![3]!["continue-on-error"] = true),
    ],
    ["command if false", (job: WorkflowJob): void => void (job.steps![3]!.if = false)],
  ] as const)("rejects %s on the required PR gate path", (_label, mutate) => {
    const workflow = structuredClone(readWorkflow("kaji.beta-pr.yml").workflow);
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
    const workflow = structuredClone(readWorkflow("kaji.beta-pr.yml").workflow);
    workflow.on!.pull_request = trigger;

    expect(() => assertProtectionReadyGate(workflow)).toThrow();
  });

  it("accepts an empty unfiltered pull_request mapping", () => {
    const workflow = structuredClone(readWorkflow("kaji.beta-pr.yml").workflow);
    workflow.on!.pull_request = {};

    expect(() => assertProtectionReadyGate(workflow)).not.toThrow();
  });

  it.each(["checks", "deployments", "security-events", "id-token"] as const)(
    "rejects unexpected %s write permission on the PR gate",
    (permission) => {
      const workflow = structuredClone(readWorkflow("kaji.beta-pr.yml").workflow);
      gateJob(workflow).permissions = { contents: "read", [permission]: "write" };

      expect(() => assertNarrowPermissions("kaji.beta-pr.yml", workflow)).toThrow();
    },
  );

  it("rejects permission drift on a privileged release job", () => {
    const workflow = structuredClone(readWorkflow("kaji.beta-publish.yml").workflow);
    const supplyChain = workflow.jobs?.["supply-chain"];
    if (!supplyChain?.permissions) throw new Error("missing supply-chain permissions");
    supplyChain.permissions.checks = "write";

    expect(() => assertNarrowPermissions("kaji.beta-publish.yml", workflow)).toThrow();
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
