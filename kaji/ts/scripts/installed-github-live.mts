#!/usr/bin/env bun
/** Execute one narrow GitHub read/comment cell from an installed npm tarball. */

import { realpathSync } from "node:fs";
import { dirname, join, sep } from "node:path";
import { fileURLToPath } from "node:url";

import {
  InMemoryEventCommitter,
  InMemoryEventStore,
  ToolPlanner,
  ToolPolicy,
  ToolRegistry,
} from "kaji-sdk";
import { createGithubIntegration } from "kaji-sdk/integrations/github";

const MAX_INPUT_BYTES = 64 * 1024;
const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
const EXPECTED_TOOLS = new Set([
  "github_add_comment",
  "github_create_issue",
  "github_get_file",
  "github_get_issue",
  "github_list_issues",
  "github_search_code",
  "github_get_commit",
  "github_get_pull_request",
  "github_list_pull_request_files",
  "github_list_check_runs",
  "github_get_workflow_run",
  "github_list_workflow_jobs",
  "github_list_file_commits",
  "github_get_release",
  "github_list_deployments",
]);
const COMPONENT = /^[A-Za-z0-9_.-]{1,100}$/;

type Input = Readonly<{
  runtime: "typescript";
  owner: string;
  repository: string;
  issueNumber: number;
  marker: string;
}>;

function fail(): never {
  throw new Error("installed_github_live_failed");
}

function contained(path: string, root: string): string {
  const boundary = realpathSync(root);
  const candidate = realpathSync(path);
  if (candidate !== boundary && !candidate.startsWith(`${boundary}${sep}`)) fail();
  return candidate;
}

function inputDocument(encoded: string | undefined): Input {
  if (encoded === undefined || Buffer.byteLength(encoded, "utf8") > MAX_INPUT_BYTES) fail();
  // The owner orchestrator validates and atomically snapshots the private input
  // before passing this bounded value through the child's closed environment.
  const parsed: unknown = JSON.parse(encoded);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) fail();
  const value = parsed as Record<string, unknown>;
  if (
    Object.keys(value).sort().join(",") !== "issueNumber,marker,owner,repository,runtime" ||
    value.runtime !== "typescript" ||
    typeof value.owner !== "string" ||
    !COMPONENT.test(value.owner) ||
    value.owner === "." ||
    value.owner === ".." ||
    typeof value.repository !== "string" ||
    !COMPONENT.test(value.repository) ||
    value.repository === "." ||
    value.repository === ".." ||
    !Number.isSafeInteger(value.issueNumber) ||
    (value.issueNumber as number) < 1 ||
    (value.issueNumber as number) > MAX_SAFE_INTEGER ||
    typeof value.marker !== "string" ||
    value.marker.length < 1 ||
    value.marker.length > 256 ||
    /[\r\n]/.test(value.marker)
  ) {
    fail();
  }
  return value as Input;
}

function argumentsFrom(argv: string[]) {
  const allowed = new Set(["--sandbox-root", "--package-root"]);
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (name === undefined || value === undefined || !allowed.has(name) || values.has(name)) {
      fail();
    }
    values.set(name, value);
  }
  if (values.size !== allowed.size) fail();
  return {
    sandboxRoot: values.get("--sandbox-root")!,
    packageRoot: values.get("--package-root")!,
  };
}

async function execute(input: Input, token: string): Promise<Record<string, unknown>> {
  const repository = `${input.owner}/${input.repository}`;
  const integration = createGithubIntegration({
    tokenFor: async () => token,
    repositories: [repository],
    toolExposure: "all",
  });
  const registry = new ToolRegistry();
  integration.register(registry);
  const specs = new Map(registry.listSpecs().map((spec) => [spec.name, spec]));
  if (
    specs.size !== EXPECTED_TOOLS.size ||
    [...specs].some(([name]) => !EXPECTED_TOOLS.has(name))
  ) {
    fail();
  }
  const store = new InMemoryEventStore();
  const committer = new InMemoryEventCommitter(store);
  let approvals = 0;
  const commentArguments = {
    repository,
    issue_number: input.issueNumber,
    body: input.marker,
  };
  const planner = new ToolPlanner({
    specs,
    executor: (name, args, context) => registry.execute(name, { ...args }, context),
    policy: new ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
    approvalCommitter: committer,
    approvalHandler: {
      async request(call) {
        approvals += 1;
        if (
          approvals !== 1 ||
          call.name !== "github_add_comment" ||
          JSON.stringify(call.arguments) !== JSON.stringify(commentArguments)
        ) {
          fail();
        }
        return { granted: true as const, code: "approved" as const };
      },
    },
  });
  try {
    const read = await planner.executeBatch(
      "github-proof-read",
      [
        {
          id: "read",
          name: "github_get_issue",
          arguments: {
            repository,
            issue_number: input.issueNumber,
          },
        },
      ],
      ToolPlanner.committerEmitter(committer),
      "github-proof-read",
      {
        principalId: "github-proof",
        requestId: "github-proof-read",
        traceId: "github-proof-read",
      },
    );
    const readResult = "result" in read[0]! ? read[0].result : undefined;
    if (
      readResult === null ||
      typeof readResult !== "object" ||
      Array.isArray(readResult) ||
      (readResult as Record<string, unknown>).number !== input.issueNumber
    ) {
      fail();
    }
    const mutation = await planner.executeBatch(
      "github-proof-comment",
      [
        {
          id: "comment",
          name: "github_add_comment",
          arguments: commentArguments,
        },
      ],
      ToolPlanner.committerEmitter(committer),
      "github-proof-comment",
      {
        principalId: "github-proof",
        requestId: "github-proof-comment",
        traceId: "github-proof-comment",
      },
    );
    const result = "result" in mutation[0]! ? mutation[0].result : undefined;
    const commentId =
      result !== null && typeof result === "object" && !Array.isArray(result)
        ? (result as Record<string, unknown>).id
        : undefined;
    if (!Number.isSafeInteger(commentId) || (commentId as number) < 1 || approvals !== 1) fail();
    return {
      runtime: "typescript",
      readPassed: true,
      approvedCommentPassed: true,
      commentId,
    };
  } finally {
    integration.close();
  }
}

async function main(): Promise<void> {
  if (
    "GITHUB_TOKEN" in process.env ||
    "GH_TOKEN" in process.env ||
    "NODE_AUTH_TOKEN" in process.env ||
    "NPM_TOKEN" in process.env ||
    "NODE_PATH" in process.env
  ) {
    fail();
  }
  const token = process.env.KAJI_GITHUB_PROOF_TOKEN;
  if (
    token === undefined ||
    token.length < 1 ||
    token.length > 4_096 ||
    token.includes("\r") ||
    token.includes("\n") ||
    token.includes("\u0000")
  ) {
    fail();
  }
  const args = argumentsFrom(process.argv.slice(2));
  const sandbox = realpathSync(args.sandboxRoot);
  const packageRoot = contained(args.packageRoot, sandbox);
  contained(fileURLToPath(import.meta.url), sandbox);
  const entry = fileURLToPath(import.meta.resolve("kaji-sdk"));
  if (realpathSync(join(dirname(entry), "..")) !== packageRoot) fail();
  const input = inputDocument(process.env.KAJI_GITHUB_PROOF_INPUT);
  delete process.env.KAJI_GITHUB_PROOF_INPUT;
  const result = await execute(input, token);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

try {
  await main();
} catch {
  process.stderr.write("installed GitHub proof failed\n");
  process.exitCode = 1;
}
