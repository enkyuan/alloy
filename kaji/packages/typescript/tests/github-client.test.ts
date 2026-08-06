import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import { ToolExecutionError, type ToolExecutionContext } from "kaji-sdk";
import {
  IntegrationAuthRequiredError,
  IntegrationPolicyError,
  snapshotIntegrationResult,
  type BoundedResponse,
  type FixedOriginRequester,
} from "kaji-sdk/integrations";
import { recoveryForReason } from "@/contracts/integration-recovery";
import { GitHubClient } from "../registry/github/client";

interface FixtureCase {
  readonly name: string;
  readonly operation:
    | "search_code"
    | "get_file"
    | "list_issues"
    | "get_issue"
    | "create_issue"
    | "add_comment";
  readonly input: Readonly<Record<string, unknown>>;
  readonly responses: readonly Readonly<Record<string, unknown>>[];
  readonly expected_requests: readonly unknown[];
  readonly expected_sleeps?: readonly number[];
  readonly expected_token_calls?: number;
  readonly expected: Readonly<Record<string, unknown>>;
}

interface Fixture {
  readonly repository: string;
  readonly token: string;
  readonly cases: readonly FixtureCase[];
  readonly durable_result_boundaries: readonly {
    readonly name: string;
    readonly serialized_bytes: number;
    readonly accepted: boolean;
  }[];
}

const fixture = JSON.parse(
  readFileSync(
    new URL("../../../contracts/integrations/github-api-conformance-v1.json", import.meta.url),
    "utf8",
  ),
) as Fixture;

const packageAbi = JSON.parse(
  readFileSync(
    new URL("../../../contracts/integrations/github-tool-abi-typescript-v1.json", import.meta.url),
    "utf8",
  ),
) as { readonly catalog_version: string };

const TYPESCRIPT_REQUEST_IDENTITY = {
  "user-agent": "kaji-sdk-github/0.2.0",
  "x-github-api-version": "2026-03-10",
} as const;

function withoutTypeScriptRequestIdentity(request: unknown): unknown {
  const document = structuredClone(request) as {
    headers?: Record<string, string>;
  };
  if (document.headers !== undefined) {
    delete document.headers["user-agent"];
    delete document.headers["x-github-api-version"];
  }
  return document;
}

function context(overrides: Partial<ToolExecutionContext> = {}): ToolExecutionContext {
  return {
    principalId: "tester",
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal: new AbortController().signal,
    metadata: {},
    ...overrides,
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
    const response = this.responses.shift()!;
    if (response.transport_error === "response_limit") {
      throw new Error("private response limit detail");
    }
    if (response.transport_error === "cancelled") {
      throw new DOMException("private cancellation detail", "AbortError");
    }
    if (response.transport_error === "connection") {
      throw new Error("private connection detail");
    }
    const body =
      "bytes" in response
        ? Uint8Array.from(response.bytes as number[])
        : "json" in response
          ? new TextEncoder().encode(JSON.stringify(response.json))
          : new TextEncoder().encode((response.body as string | undefined) ?? "");
    return {
      status: response.status as number,
      headers: Object.freeze({
        ...(response.headers as Record<string, string> | undefined),
      }),
      bytes: body,
    };
  }
}

type ExtensionOperation =
  | "get_commit"
  | "get_pull_request"
  | "list_pull_request_files"
  | "list_check_runs"
  | "get_workflow_run"
  | "list_workflow_jobs"
  | "list_file_commits"
  | "get_release"
  | "list_deployments";

interface ExtensionCase {
  readonly operation: ExtensionOperation;
  readonly input: Readonly<Record<string, unknown>>;
  readonly path: string;
  readonly response: unknown;
  readonly expected: unknown;
}

const extensionCases: readonly ExtensionCase[] = [
  {
    operation: "get_commit",
    input: { repository: fixture.repository, ref: "feature/x" },
    path: `/repos/${fixture.repository}/commits/feature%2Fx?page=1&per_page=10`,
    response: {
      sha: "abc123",
      html_url: "https://github.com/octo/widgets/commit/abc123",
      commit: { author: { name: "Ada", date: "2026-07-17T00:00:00Z" }, message: "fix" },
      parents: [{ sha: "parent", html_url: "https://github.com/octo/widgets/commit/parent" }],
      stats: { additions: 2, deletions: 1, total: 3 },
      files: [{ filename: "src/a.ts", status: "modified", additions: 2, deletions: 1, changes: 3 }],
      secret_marker: "must-not-survive",
    },
    expected: {
      sha: "abc123",
      url: "https://github.com/octo/widgets/commit/abc123",
      author: { name: "Ada", date: "2026-07-17T00:00:00Z" },
      message: "fix",
      message_truncated: false,
      parents: [{ sha: "parent", url: "https://github.com/octo/widgets/commit/parent" }],
      parents_omitted_count: 0,
      stats: { additions: 2, deletions: 1, total: 3 },
      files: [{ filename: "src/a.ts", status: "modified", additions: 2, deletions: 1, changes: 3 }],
      files_omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
  {
    operation: "get_pull_request",
    input: { repository: fixture.repository, pullNumber: 7 },
    path: `/repos/${fixture.repository}/pulls/7`,
    response: {
      number: 7,
      state: "open",
      title: "Ship",
      body: null,
      base: { sha: "base" },
      head: { sha: "head" },
      merge_commit_sha: null,
      html_url: "https://github.com/octo/widgets/pull/7",
      private: "must-not-survive",
    },
    expected: {
      number: 7,
      state: "open",
      title: "Ship",
      title_truncated: false,
      body: null,
      body_truncated: false,
      base_sha: "base",
      head_sha: "head",
      merge_sha: null,
      url: "https://github.com/octo/widgets/pull/7",
    },
  },
  {
    operation: "list_pull_request_files",
    input: { repository: fixture.repository, pullNumber: 7 },
    path: `/repos/${fixture.repository}/pulls/7/files?page=1&per_page=10`,
    response: [
      { filename: "bin.dat", status: "modified", additions: 0, deletions: 0, changes: 0 },
      {
        filename: "src/a.ts",
        status: "added",
        additions: 1,
        deletions: 0,
        changes: 1,
        patch: null,
      },
    ],
    expected: {
      items: [
        {
          filename: "bin.dat",
          status: "modified",
          additions: 0,
          deletions: 0,
          changes: 0,
          patch: null,
          patch_truncated: false,
        },
        {
          filename: "src/a.ts",
          status: "added",
          additions: 1,
          deletions: 0,
          changes: 1,
          patch: null,
          patch_truncated: false,
        },
      ],
      omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
  {
    operation: "list_check_runs",
    input: { repository: fixture.repository, ref: "feature/x" },
    path: `/repos/${fixture.repository}/commits/feature%2Fx/check-runs?filter=latest&page=1&per_page=10`,
    response: {
      total_count: 1,
      check_runs: [
        {
          id: 9,
          name: "test",
          status: "future_status",
          conclusion: null,
          html_url: "https://github.com/octo/widgets/runs/9",
          output: { title: null, summary: null, text: null },
        },
      ],
    },
    expected: {
      total_count: 1,
      items: [
        {
          id: 9,
          name: "test",
          status: "future_status",
          conclusion: null,
          url: "https://github.com/octo/widgets/runs/9",
          output: {
            title: null,
            title_truncated: false,
            summary: null,
            summary_truncated: false,
            text: null,
            text_truncated: false,
          },
        },
      ],
      omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
  {
    operation: "get_workflow_run",
    input: { repository: fixture.repository, runId: 11 },
    path: `/repos/${fixture.repository}/actions/runs/11`,
    response: {
      id: 11,
      name: "CI",
      event: "push",
      status: "queued",
      conclusion: null,
      head_sha: "abc",
      run_attempt: 2,
      html_url: "https://github.com/octo/widgets/actions/runs/11",
    },
    expected: {
      id: 11,
      workflow: "CI",
      event: "push",
      status: "queued",
      conclusion: null,
      head_sha: "abc",
      attempt: 2,
      url: "https://github.com/octo/widgets/actions/runs/11",
    },
  },
  {
    operation: "list_workflow_jobs",
    input: { repository: fixture.repository, runId: 11 },
    path: `/repos/${fixture.repository}/actions/runs/11/jobs?filter=latest&page=1&per_page=10`,
    response: {
      total_count: 1,
      jobs: [
        {
          id: 12,
          name: "test",
          status: "queued",
          conclusion: null,
          started_at: null,
          completed_at: null,
          html_url: "https://github.com/octo/widgets/actions/runs/11/job/12",
          steps: null,
        },
      ],
    },
    expected: {
      total_count: 1,
      items: [
        {
          id: 12,
          name: "test",
          status: "queued",
          conclusion: null,
          started_at: null,
          completed_at: null,
          url: "https://github.com/octo/widgets/actions/runs/11/job/12",
          steps: [],
          steps_omitted_count: 0,
        },
      ],
      omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
  {
    operation: "list_file_commits",
    input: { repository: fixture.repository, path: "src/a b.ts", ref: "feature/x" },
    path: `/repos/${fixture.repository}/commits?page=1&path=src%2Fa%20b.ts&per_page=10&sha=feature%2Fx`,
    response: [
      {
        sha: "abc",
        commit: { message: "change", author: null },
        html_url: "https://github.com/octo/widgets/commit/abc",
      },
    ],
    expected: {
      items: [
        {
          sha: "abc",
          message: "change",
          message_truncated: false,
          author_date: null,
          url: "https://github.com/octo/widgets/commit/abc",
        },
      ],
      omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
  {
    operation: "get_release",
    input: { repository: fixture.repository, tag: "release/v1" },
    path: `/repos/${fixture.repository}/releases/tags/release%2Fv1`,
    response: {
      tag_name: "release/v1",
      target_commitish: "main",
      draft: false,
      prerelease: true,
      published_at: null,
      body: null,
      html_url: "https://github.com/octo/widgets/releases/tag/release/v1",
    },
    expected: {
      tag: "release/v1",
      target: "main",
      draft: false,
      prerelease: true,
      published_at: null,
      body: null,
      body_truncated: false,
      url: "https://github.com/octo/widgets/releases/tag/release/v1",
    },
  },
  {
    operation: "list_deployments",
    input: {
      repository: fixture.repository,
      ref: "main",
      sha: "aBc123",
      environment: "prod",
      task: "deploy",
    },
    path: `/repos/${fixture.repository}/deployments?environment=prod&page=1&per_page=10&ref=main&sha=aBc123&task=deploy`,
    response: [
      {
        id: 13,
        ref: "main",
        sha: "abc123",
        environment: "prod",
        task: "deploy",
        created_at: "2026-07-17T00:00:00Z",
        url: "https://api.github.com/repos/octo/widgets/deployments/13",
        html_url: "must-not-be-used",
      },
    ],
    expected: {
      items: [
        {
          id: 13,
          ref: "main",
          sha: "abc123",
          environment: "prod",
          task: "deploy",
          created_at: "2026-07-17T00:00:00Z",
          url: "https://api.github.com/repos/octo/widgets/deployments/13",
        },
      ],
      omitted_count: 0,
      page: 1,
      per_page: 10,
    },
  },
];

type ProviderUrlPath = readonly (string | number)[];

const providerUrlCases: ReadonlyArray<{
  readonly name: string;
  readonly testCase: ExtensionCase;
  readonly path: ProviderUrlPath;
}> = [
  { name: "commit", testCase: extensionCases[0]!, path: ["html_url"] },
  { name: "commit parent", testCase: extensionCases[0]!, path: ["parents", 0, "html_url"] },
  { name: "pull request", testCase: extensionCases[1]!, path: ["html_url"] },
  { name: "check run", testCase: extensionCases[3]!, path: ["check_runs", 0, "html_url"] },
  { name: "workflow run", testCase: extensionCases[4]!, path: ["html_url"] },
  { name: "workflow job", testCase: extensionCases[5]!, path: ["jobs", 0, "html_url"] },
  { name: "file commit", testCase: extensionCases[6]!, path: [0, "html_url"] },
  { name: "release", testCase: extensionCases[7]!, path: ["html_url"] },
  { name: "deployment", testCase: extensionCases[8]!, path: [0, "url"] },
];

function valueAtResponsePath(value: unknown, path: ProviderUrlPath): unknown {
  let current: any = value;
  for (const segment of path) current = current[segment];
  return current;
}

function responseWithProviderUrl(
  testCase: ExtensionCase,
  path: ProviderUrlPath,
  url: string,
): unknown {
  const response = structuredClone(testCase.response) as any;
  let target = response;
  for (const segment of path.slice(0, -1)) target = target[segment];
  target[path.at(-1)!] = url;
  return response;
}

function unsafeProviderUrls(validUrl: string): readonly string[] {
  const parsed = new URL(validUrl);
  const wrongRoute =
    parsed.hostname === "api.github.com"
      ? `https://api.github.com/repos/${fixture.repository}/issues/1`
      : `https://github.com/${fixture.repository}/issues/1`;
  return [
    "javascript:secret-marker",
    validUrl.replace("https://", "http://"),
    `https://example.invalid${parsed.pathname}`,
    validUrl.replace(parsed.host, parsed.host.toUpperCase()),
    validUrl.replace(parsed.host, `${parsed.host}:443`),
    validUrl.replace(parsed.host, `${parsed.host}.evil.invalid`),
    `https://user:secret-marker@${parsed.host}${parsed.pathname}`,
    `${validUrl}?token=secret-marker`,
    `${validUrl}?`,
    `${validUrl}#secret-marker`,
    `${validUrl}#`,
    `${validUrl}%0A`,
    `${validUrl}\nsecret-marker`,
    wrongRoute,
    "\ud800",
  ];
}

async function invokeExtension(
  client: GitHubClient,
  executionContext: ToolExecutionContext,
  operation: ExtensionOperation,
  input: Readonly<Record<string, any>>,
): Promise<unknown> {
  switch (operation) {
    case "get_commit":
      return client.getCommit(executionContext, input as never);
    case "get_pull_request":
      return client.getPullRequest(executionContext, input as never);
    case "list_pull_request_files":
      return client.listPullRequestFiles(executionContext, input as never);
    case "list_check_runs":
      return client.listCheckRuns(executionContext, input as never);
    case "get_workflow_run":
      return client.getWorkflowRun(executionContext, input as never);
    case "list_workflow_jobs":
      return client.listWorkflowJobs(executionContext, input as never);
    case "list_file_commits":
      return client.listFileCommits(executionContext, input as never);
    case "get_release":
      return client.getRelease(executionContext, input as never);
    case "list_deployments":
      return client.listDeployments(executionContext, input as never);
  }
}

async function invoke(
  client: GitHubClient,
  executionContext: ToolExecutionContext,
  testCase: FixtureCase,
): Promise<unknown> {
  const input = testCase.input as Record<string, any>;
  switch (testCase.operation) {
    case "search_code":
      return client.searchCode(executionContext, {
        repository: fixture.repository,
        query: input.query,
        page: input.page,
        perPage: input.per_page,
      });
    case "get_file":
      return client.getFile(executionContext, {
        repository: fixture.repository,
        path: input.path,
        ...(input.ref === undefined ? {} : { ref: input.ref }),
      });
    case "list_issues":
      return client.listIssues(executionContext, {
        repository: fixture.repository,
        state: input.state,
        page: input.page,
        perPage: input.per_page,
      });
    case "get_issue":
      return client.getIssue(executionContext, {
        repository: fixture.repository,
        issueNumber: input.issue_number,
      });
    case "create_issue":
      return client.createIssue(executionContext, {
        repository: fixture.repository,
        title: input.title,
        body: input.body,
      });
    case "add_comment":
      return client.addComment(executionContext, {
        repository: fixture.repository,
        issueNumber: input.issue_number,
        body: input.body,
      });
  }
}

describe("shared GitHub client conformance", () => {
  it.each(extensionCases)("normalizes and bounds $operation", async (testCase) => {
    const http = new ScriptedRequester([{ status: 200, headers: {}, json: testCase.response }]);
    const tokenFor = vi.fn(async () => fixture.token);
    const client = new GitHubClient({ tokenFor, repositories: [fixture.repository], http });

    const result = await invokeExtension(client, context(), testCase.operation, testCase.input);

    expect(result).toEqual(testCase.expected);
    expect(http.requests).toEqual([
      {
        method: "GET",
        path_and_query: testCase.path,
        headers: {
          accept: "application/vnd.github+json",
          authorization: `Bearer ${fixture.token}`,
          ...TYPESCRIPT_REQUEST_IDENTITY,
        },
        body: null,
      },
    ]);
    expect(JSON.stringify(result)).not.toContain("must-not-survive");
    expect(tokenFor).toHaveBeenCalledOnce();
  });

  it.each(extensionCases)(
    "rejects a disallowed repository before credentials for $operation",
    async (testCase) => {
      const http = new ScriptedRequester([]);
      const tokenFor = vi.fn(async () => fixture.token);
      const client = new GitHubClient({ tokenFor, repositories: [fixture.repository], http });

      await expect(
        invokeExtension(client, context(), testCase.operation, {
          ...testCase.input,
          repository: "other/private",
        }),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      expect(tokenFor).not.toHaveBeenCalled();
      expect(http.requests).toEqual([]);
    },
  );

  it.each(extensionCases)(
    "maps credential failure before HTTP for $operation",
    async (testCase) => {
      const http = new ScriptedRequester([]);
      const client = new GitHubClient({
        tokenFor: async () => {
          throw new Error("credential-secret");
        },
        repositories: [fixture.repository],
        http,
      });

      await expect(
        invokeExtension(client, context(), testCase.operation, testCase.input),
      ).rejects.toBeInstanceOf(IntegrationAuthRequiredError);
      expect(http.requests).toEqual([]);
    },
  );

  it.each(extensionCases)("redacts upstream failure details for $operation", async (testCase) => {
    const marker = `secret-${testCase.operation}`;
    const http = new ScriptedRequester([
      { status: 500, headers: { "x-secret": marker }, body: marker },
    ]);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http,
    });

    let seen: unknown;
    try {
      await invokeExtension(client, context(), testCase.operation, testCase.input);
    } catch (error) {
      seen = error;
    }
    expect(seen).toBeInstanceOf(ToolExecutionError);
    expect(JSON.stringify(seen)).not.toContain(marker);
    expect(String(seen)).not.toContain(marker);
  });

  it("adds stable GitHub request identity", async () => {
    const testCase = fixture.cases.find((candidate) => candidate.name === "get issue")!;
    const http = new ScriptedRequester(testCase.responses);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http,
    });

    await invoke(client, context(), testCase);

    expect(http.requests[0]).toMatchObject({
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${fixture.token}`,
        ...TYPESCRIPT_REQUEST_IDENTITY,
      },
    });
    expect(TYPESCRIPT_REQUEST_IDENTITY["user-agent"]).toBe(
      `kaji-sdk-github/${packageAbi.catalog_version}`,
    );
  });

  it.each([
    [
      "pull zero",
      (client: GitHubClient) =>
        client.getPullRequest(context(), { repository: fixture.repository, pullNumber: 0 }),
    ],
    [
      "pull negative",
      (client: GitHubClient) =>
        client.getPullRequest(context(), { repository: fixture.repository, pullNumber: -1 }),
    ],
    [
      "pull fractional",
      (client: GitHubClient) =>
        client.getPullRequest(context(), { repository: fixture.repository, pullNumber: 1.5 }),
    ],
    [
      "pull unsafe",
      (client: GitHubClient) =>
        client.getPullRequest(context(), {
          repository: fixture.repository,
          pullNumber: Number.MAX_SAFE_INTEGER + 1,
        }),
    ],
    [
      "run zero",
      (client: GitHubClient) =>
        client.getWorkflowRun(context(), { repository: fixture.repository, runId: 0 }),
    ],
    [
      "run unsafe",
      (client: GitHubClient) =>
        client.listWorkflowJobs(context(), {
          repository: fixture.repository,
          runId: Number.MAX_SAFE_INTEGER + 1,
        }),
    ],
    [
      "ref too long",
      (client: GitHubClient) =>
        client.getCommit(context(), { repository: fixture.repository, ref: "x".repeat(101) }),
    ],
    [
      "ref lone surrogate",
      (client: GitHubClient) =>
        client.listCheckRuns(context(), { repository: fixture.repository, ref: "\ud800" }),
    ],
    [
      "tag too long",
      (client: GitHubClient) =>
        client.getRelease(context(), { repository: fixture.repository, tag: "x".repeat(101) }),
    ],
    [
      "page zero",
      (client: GitHubClient) =>
        client.getCommit(context(), { repository: fixture.repository, ref: "main", page: 0 }),
    ],
    [
      "page too large",
      (client: GitHubClient) =>
        client.listPullRequestFiles(context(), {
          repository: fixture.repository,
          pullNumber: 1,
          page: 1001,
        }),
    ],
    [
      "per page zero",
      (client: GitHubClient) =>
        client.listFileCommits(context(), {
          repository: fixture.repository,
          path: "a",
          perPage: 0,
        }),
    ],
    [
      "per page too large",
      (client: GitHubClient) =>
        client.listDeployments(context(), { repository: fixture.repository, perPage: 21 }),
    ],
    [
      "check filter",
      (client: GitHubClient) =>
        client.listCheckRuns(context(), {
          repository: fixture.repository,
          ref: "main",
          filter: "old" as never,
        }),
    ],
    [
      "job filter",
      (client: GitHubClient) =>
        client.listWorkflowJobs(context(), {
          repository: fixture.repository,
          runId: 1,
          filter: "old" as never,
        }),
    ],
    ...["", "x".repeat(513), "src//a", ".", "..", "src/../a", "src\\a", "\ud800"].map(
      (path) =>
        [
          `path ${JSON.stringify(path)}`,
          (client: GitHubClient) =>
            client.listFileCommits(context(), { repository: fixture.repository, path }),
        ] as const,
    ),
    [
      "deployment sha empty",
      (client: GitHubClient) =>
        client.listDeployments(context(), { repository: fixture.repository, sha: "" }),
    ],
    [
      "deployment sha nonhex",
      (client: GitHubClient) =>
        client.listDeployments(context(), { repository: fixture.repository, sha: "xyz" }),
    ],
    [
      "deployment sha too long",
      (client: GitHubClient) =>
        client.listDeployments(context(), { repository: fixture.repository, sha: "a".repeat(65) }),
    ],
    [
      "deployment query surrogate",
      (client: GitHubClient) =>
        client.listDeployments(context(), {
          repository: fixture.repository,
          environment: "\ud800",
        }),
    ],
  ] as const)("rejects invalid extension input before token: %s", async (_name, call) => {
    const http = new ScriptedRequester([]);
    const tokenFor = vi.fn(async () => fixture.token);
    const client = new GitHubClient({ tokenFor, repositories: [fixture.repository], http });

    await expect(call(client)).rejects.toBeInstanceOf(IntegrationPolicyError);
    expect(tokenFor).not.toHaveBeenCalled();
    expect(http.requests).toEqual([]);
  });

  it.each(["./repo", "../repo", "owner/.", "owner/.."])(
    "rejects repository dot components at construction: %s",
    (repository) => {
      expect(
        () =>
          new GitHubClient({
            tokenFor: async () => fixture.token,
            repositories: [repository],
            http: new ScriptedRequester([]),
          }),
      ).toThrow(IntegrationPolicyError);
    },
  );

  it.each([
    `/repos/${fixture.repository}/commits/feature/x`,
    `/repos/${fixture.repository}/commits/feature%2fx`,
    `/repos/${fixture.repository}/commits/%`,
    `/repos/${fixture.repository}/commits/.`,
    `/repos/${fixture.repository}/commits/%2E`,
    `/repos/${fixture.repository}/commits/..`,
    `/repos/${fixture.repository}/commits/feature%5Cx`,
  ])("rejects a noncanonical direct route before token: %s", async (path) => {
    const http = new ScriptedRequester([]);
    const tokenFor = vi.fn(async () => fixture.token);
    const client = new GitHubClient({ tokenFor, repositories: [fixture.repository], http });

    await expect(
      client.requestJson(context(), {
        method: "GET",
        repository: fixture.repository,
        path,
        query: { page: 1, per_page: 10 },
      }),
    ).rejects.toBeInstanceOf(IntegrationPolicyError);
    expect(tokenFor).not.toHaveBeenCalled();
    expect(http.requests).toEqual([]);
  });

  it("encodes a literal percent once inside one ref segment", async () => {
    const response = extensionCases[0]!.response;
    const http = new ScriptedRequester([{ status: 200, headers: {}, json: response }]);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http,
    });

    await client.getCommit(context(), { repository: fixture.repository, ref: "feature%raw" });

    expect(http.requests[0]).toMatchObject({
      path_and_query: `/repos/${fixture.repository}/commits/feature%25raw?page=1&per_page=10`,
    });
  });

  it.each([403, 429])(
    "retries a bounded rate response once with one token and identical headers: %s",
    async (status) => {
      const http = new ScriptedRequester([
        { status, headers: { "retry-after": "0.001" }, body: "rate-secret" },
        { status: 200, headers: {}, json: extensionCases[0]!.response },
      ]);
      const tokenFor = vi.fn(async () => fixture.token);
      const sleeps: number[] = [];
      const client = new GitHubClient(
        { tokenFor, repositories: [fixture.repository], http },
        {
          sleep: async (delay) => {
            sleeps.push(delay);
          },
          monotonicNow: () => 0,
        },
      );

      await expect(
        client.getCommit(context({ deadlineMonotonicMs: 10_000 }), {
          repository: fixture.repository,
          ref: "main",
        }),
      ).resolves.toBeTruthy();
      expect(tokenFor).toHaveBeenCalledOnce();
      expect(http.requests).toHaveLength(2);
      expect((http.requests[0] as any).headers).toEqual((http.requests[1] as any).headers);
      expect(sleeps).toEqual([1]);
    },
  );

  it("does not retry past the execution deadline", async () => {
    const http = new ScriptedRequester([
      { status: 429, headers: { "retry-after": "2" }, body: "secret" },
    ]);
    const tokenFor = vi.fn(async () => fixture.token);
    const client = new GitHubClient(
      { tokenFor, repositories: [fixture.repository], http },
      { sleep: async () => undefined, monotonicNow: () => 0 },
    );

    await expect(
      client.getCommit(context({ deadlineMonotonicMs: 2_000 }), {
        repository: fixture.repository,
        ref: "main",
      }),
    ).rejects.toBeInstanceOf(ToolExecutionError);
    expect(tokenFor).toHaveBeenCalledOnce();
    expect(http.requests).toHaveLength(1);
  });

  it.each([
    ["wrong object shape", { status: 200, headers: {}, json: [] }],
    [
      "unsafe integer",
      {
        status: 200,
        headers: {},
        json: { ...(extensionCases[4]!.response as object), id: Number.MAX_SAFE_INTEGER + 1 },
      },
    ],
    [
      "overlong scalar",
      {
        status: 200,
        headers: {},
        json: { ...(extensionCases[4]!.response as object), name: "x".repeat(257) },
      },
    ],
    [
      "invalid unicode",
      {
        status: 200,
        headers: {},
        json: { ...(extensionCases[4]!.response as object), status: "\ud800" },
      },
    ],
    ["invalid json", { status: 200, headers: {}, body: "{" }],
    ["invalid utf8", { status: 200, headers: {}, bytes: [0xff] }],
    ["response limit", { transport_error: "response_limit" }],
  ] as const)("maps provider failure to a safe transient read: %s", async (_name, response) => {
    const http = new ScriptedRequester([response]);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http,
    });
    await expect(
      client.getWorkflowRun(context(), { repository: fixture.repository, runId: 11 }),
    ).rejects.toBeInstanceOf(ToolExecutionError);
  });

  it.each(providerUrlCases)(
    "accepts the exact canonical provider URL for $name",
    async ({ testCase, path }) => {
      const http = new ScriptedRequester([
        {
          status: 200,
          headers: {},
          json: responseWithProviderUrl(
            testCase,
            path,
            valueAtResponsePath(testCase.response, path) as string,
          ),
        },
      ]);
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http,
      });

      await expect(
        invokeExtension(client, context(), testCase.operation, testCase.input),
      ).resolves.toBeTruthy();
    },
  );

  it.each(providerUrlCases)(
    "rejects and redacts every unsafe provider URL shape for $name",
    async ({ testCase, path }) => {
      const validUrl = valueAtResponsePath(testCase.response, path) as string;
      for (const unsafeUrl of unsafeProviderUrls(validUrl)) {
        const http = new ScriptedRequester([
          {
            status: 200,
            headers: {},
            json: responseWithProviderUrl(testCase, path, unsafeUrl),
          },
        ]);
        const client = new GitHubClient({
          tokenFor: async () => fixture.token,
          repositories: [fixture.repository],
          http,
        });
        let seen: unknown;
        try {
          await invokeExtension(client, context(), testCase.operation, testCase.input);
        } catch (error) {
          seen = error;
        }
        expect(seen).toBeInstanceOf(ToolExecutionError);
        expect(String(seen)).not.toContain("secret-marker");
        expect(JSON.stringify(seen)).not.toContain("secret-marker");
      }
    },
  );

  it.each([
    [401, IntegrationAuthRequiredError],
    [403, ToolExecutionError],
    [404, ToolExecutionError],
    [422, ToolExecutionError],
    [503, ToolExecutionError],
  ] as const)(
    "preserves safe common status handling on a new read: %s",
    async (status, ErrorType) => {
      const http = new ScriptedRequester([{ status, headers: {}, body: "status-secret" }]);
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http,
      });
      await expect(
        client.getPullRequest(context(), { repository: fixture.repository, pullNumber: 7 }),
      ).rejects.toBeInstanceOf(ErrorType);
    },
  );

  it("truncates text at exact UTF-8 boundaries with truthful flags", async () => {
    const call = async (patch: string) => {
      const http = new ScriptedRequester([
        {
          status: 200,
          headers: {},
          json: [
            { filename: "a", status: "modified", additions: 1, deletions: 1, changes: 2, patch },
          ],
        },
      ]);
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http,
      });
      return client.listPullRequestFiles(context(), {
        repository: fixture.repository,
        pullNumber: 1,
      }) as Promise<any>;
    };

    await expect(call("x".repeat(8_192))).resolves.toMatchObject({
      items: [{ patch: "x".repeat(8_192), patch_truncated: false }],
    });
    await expect(call("x".repeat(8_193))).resolves.toMatchObject({
      items: [{ patch: "x".repeat(8_192), patch_truncated: true }],
    });
    await expect(call("é".repeat(4_097))).resolves.toMatchObject({
      items: [{ patch: "é".repeat(4_096), patch_truncated: true }],
    });
  });

  it.each([
    ["NUL", "\0".repeat(8_192), true],
    ["control", "\u001f".repeat(8_192), true],
    ["quote", '"'.repeat(8_192), false],
    ["backslash", "\\".repeat(8_192), false],
    ["ASCII", "x".repeat(8_192), false],
    ["multibyte", "é".repeat(4_096), false],
  ] as const)(
    "fits escape-heavy pull request single objects at the exact text boundary: %s",
    async (_name, text, aggregateShrinkExpected) => {
      const response = {
        ...(extensionCases[1]!.response as Record<string, unknown>),
        title: text,
        body: text,
      };
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
      });

      const result = (await client.getPullRequest(context(), {
        repository: fixture.repository,
        pullNumber: 7,
      })) as any;

      expect(new TextEncoder().encode(JSON.stringify(result)).byteLength).toBeLessThanOrEqual(
        61_440,
      );
      expect(result.title).toBe(text);
      expect(result.title_truncated).toBe(false);
      expect(result.body_truncated).toBe(aggregateShrinkExpected);
      expect(result.body === text).toBe(!aggregateShrinkExpected);
    },
  );

  it.each([
    ["NUL", "\0".repeat(8_192)],
    ["control", "\u001f".repeat(8_192)],
    ["quote", '"'.repeat(8_192)],
    ["backslash", "\\".repeat(8_192)],
    ["ASCII", "x".repeat(8_192)],
    ["multibyte", "é".repeat(4_096)],
  ] as const)(
    "fits release single-object text at the exact UTF-8 boundary: %s",
    async (_name, text) => {
      const response = {
        ...(extensionCases[7]!.response as Record<string, unknown>),
        body: text,
      };
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
      });

      const result = (await client.getRelease(context(), {
        repository: fixture.repository,
        tag: "v1",
      })) as any;

      expect(new TextEncoder().encode(JSON.stringify(result)).byteLength).toBeLessThanOrEqual(
        61_440,
      );
      expect(result.body).toBe(text);
      expect(result.body_truncated).toBe(false);
    },
  );

  it.each([
    ["NUL", "\0".repeat(8_192), true],
    ["control", "\u001f".repeat(8_192), true],
    ["quote", '"'.repeat(8_192), false],
    ["backslash", "\\".repeat(8_192), false],
    ["ASCII", "x".repeat(8_192), false],
    ["multibyte", "é".repeat(4_096), false],
  ] as const)(
    "shrinks commit text before omitting parent or file evidence: %s",
    async (_name, text, aggregateShrinkExpected) => {
      const response = {
        ...(extensionCases[0]!.response as Record<string, unknown>),
        commit: {
          ...((extensionCases[0]!.response as any).commit as Record<string, unknown>),
          message: text,
        },
        parents: Array.from({ length: 20 }, (_, index) => ({
          sha: `p${index}`,
          html_url: `https://github.com/${fixture.repository}/commit/p${index}`,
        })),
        files: Array.from({ length: 20 }, (_, index) => ({
          filename: `${index}-${'"'.repeat(256)}.ts`,
          status: "modified",
          additions: 1,
          deletions: 1,
          changes: 2,
        })),
      };
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
      });

      const result = (await client.getCommit(context(), {
        repository: fixture.repository,
        ref: "main",
        perPage: 20,
      })) as any;

      expect(new TextEncoder().encode(JSON.stringify(result)).byteLength).toBeLessThanOrEqual(
        61_440,
      );
      expect(result.parents).toHaveLength(20);
      expect(result.files).toHaveLength(20);
      expect(result.parents_omitted_count).toBe(0);
      expect(result.files_omitted_count).toBe(0);
      expect(result.message_truncated).toBe(aggregateShrinkExpected);
      expect(result.message === text).toBe(!aggregateShrinkExpected);
    },
  );

  it("budgets escape-heavy rows by serialized JSON bytes with exact local omissions", async () => {
    const patch = '"\\\n'.repeat(3_000);
    const response = Array.from({ length: 20 }, (_, index) => ({
      filename: `${index}.ts`,
      status: "modified",
      additions: 1,
      deletions: 1,
      changes: 2,
      patch,
    }));
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
    });

    const result = (await client.listPullRequestFiles(context(), {
      repository: fixture.repository,
      pullNumber: 1,
      perPage: 20,
    })) as any;
    const bytes = new TextEncoder().encode(JSON.stringify(result)).byteLength;
    expect(bytes).toBeLessThanOrEqual(61_440);
    expect(result.items.length + result.omitted_count).toBe(20);
    expect(result.omitted_count).toBeGreaterThan(0);
    expect(result.items.some((item: any) => item.patch_truncated)).toBe(true);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.items)).toBe(true);
  });

  it("keeps 20 commit parents and files with scoped zero omission counts", async () => {
    const response = {
      ...(extensionCases[0]!.response as object),
      parents: Array.from({ length: 20 }, (_, index) => ({
        sha: `p${index}`,
        html_url: `https://github.com/${fixture.repository}/commit/p${index}`,
      })),
      files: Array.from({ length: 20 }, (_, index) => ({
        filename: `${index}.ts`,
        status: "modified",
        additions: 1,
        deletions: 1,
        changes: 2,
      })),
    };
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
    });
    const result = (await client.getCommit(context(), {
      repository: fixture.repository,
      ref: "main",
      perPage: 20,
    })) as any;
    expect(result.parents).toHaveLength(20);
    expect(result.files).toHaveLength(20);
    expect(result.parents_omitted_count).toBe(0);
    expect(result.files_omitted_count).toBe(0);
  });

  it("budgets nested job steps with scoped omission counts", async () => {
    const steps = Array.from({ length: 20 }, (_, index) => ({
      number: index + 1,
      name: '"'.repeat(256),
      status: "completed",
      conclusion: "success",
      started_at: null,
      completed_at: null,
    }));
    const jobs = Array.from({ length: 20 }, (_, index) => ({
      id: index + 1,
      name: `job-${index}`,
      status: "completed",
      conclusion: "success",
      started_at: null,
      completed_at: null,
      html_url: `https://github.com/${fixture.repository}/actions/runs/1/job/${index + 1}`,
      steps,
    }));
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http: new ScriptedRequester([{ status: 200, headers: {}, json: { total_count: 20, jobs } }]),
    });
    const result = (await client.listWorkflowJobs(context(), {
      repository: fixture.repository,
      runId: 1,
      perPage: 20,
    })) as any;
    expect(new TextEncoder().encode(JSON.stringify(result)).byteLength).toBeLessThanOrEqual(61_440);
    expect(result.items.length + result.omitted_count).toBe(20);
    for (const item of result.items) expect(item.steps.length + item.steps_omitted_count).toBe(20);
  });

  it.each(fixture.cases)("matches $name", async (testCase) => {
    const http = new ScriptedRequester(testCase.responses);
    const tokenContexts: ToolExecutionContext[] = [];
    const sleeps: number[] = [];
    const tokenFor = vi.fn(async (executionContext: ToolExecutionContext) => {
      tokenContexts.push(executionContext);
      return fixture.token;
    });
    const client = new GitHubClient(
      { tokenFor, repositories: [fixture.repository], http },
      {
        sleep: async (delayMs) => {
          sleeps.push(delayMs / 1_000);
        },
        monotonicNow: () => 0,
      },
    );
    const executionContext = context();

    let actual: Record<string, unknown>;
    try {
      actual = { result: await invoke(client, executionContext, testCase) };
    } catch (error) {
      if (error instanceof ToolExecutionError) {
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
        expect(String(error).toLowerCase()).not.toContain("private");
        if (testCase.expected.exception === "unknown") {
          const recovery = recoveryForReason("github_mutation_unknown");
          expect(error).toMatchObject({
            error_code: recovery.errorCode,
            reason_code: "github_mutation_unknown",
            recovery_code: recovery.recoveryCode,
            doc_url: recovery.docUrl,
          });
        }
        actual = { exception: "unknown" };
      }
    }

    expect(actual).toEqual(testCase.expected);
    for (const request of http.requests) {
      expect(request).toMatchObject({ headers: TYPESCRIPT_REQUEST_IDENTITY });
    }
    expect(http.requests.map(withoutTypeScriptRequestIdentity)).toEqual(testCase.expected_requests);
    expect(sleeps).toEqual(testCase.expected_sleeps ?? []);
    expect(tokenFor).toHaveBeenCalledTimes(testCase.expected_token_calls ?? 1);
    expect(tokenContexts.every((seen) => seen === executionContext)).toBe(true);
    expect(http.contexts.every((seen) => seen === executionContext)).toBe(true);
    expect(http.responses).toEqual([]);
  });

  it.each(["", "   ", "a\r\nb", "x".repeat(4_097), 7])(
    "rejects invalid token %j before HTTP",
    async (value) => {
      const http = new ScriptedRequester([]);
      const client = new GitHubClient({
        tokenFor: async () => value as string,
        repositories: [fixture.repository],
        http,
      });
      await expect(
        client.getIssue(context(), { repository: fixture.repository, issueNumber: 1 }),
      ).rejects.toBeInstanceOf(IntegrationAuthRequiredError);
      expect(http.requests).toEqual([]);
    },
  );

  it("maps credential-provider failures before HTTP", async () => {
    const http = new ScriptedRequester([]);
    const client = new GitHubClient({
      tokenFor: async () => {
        throw new Error("private credential detail");
      },
      repositories: [fixture.repository],
      http,
    });

    await expect(
      client.getIssue(context(), { repository: fixture.repository, issueNumber: 1 }),
    ).rejects.toBeInstanceOf(IntegrationAuthRequiredError);
    expect(http.requests).toEqual([]);
  });

  it.each(["", ".", "..", "src//secret", "src/../secret"])(
    "rejects content path %j before token or HTTP",
    async (path) => {
      const http = new ScriptedRequester([]);
      const tokenFor = vi.fn(async () => fixture.token);
      const client = new GitHubClient({
        tokenFor,
        repositories: [fixture.repository],
        http,
      });
      await expect(
        client.getFile(context(), { repository: fixture.repository, path }),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      expect(tokenFor).not.toHaveBeenCalled();
      expect(http.requests).toEqual([]);
    },
  );

  it.each(["../secret", "%2E%2E/secret", "src/%2Fsecret"])(
    "does not let the request core bypass content policy with %j",
    async (path) => {
      const http = new ScriptedRequester([]);
      const tokenFor = vi.fn(async () => fixture.token);
      const client = new GitHubClient({
        tokenFor,
        repositories: [fixture.repository],
        http,
      });
      await expect(
        client.requestJson(context(), {
          method: "GET",
          repository: fixture.repository,
          path: `/repos/${fixture.repository}/contents/${path}`,
        }),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      expect(tokenFor).not.toHaveBeenCalled();
      expect(http.requests).toEqual([]);
    },
  );

  it("validates and snapshots the repository allowlist", async () => {
    const repositories = [fixture.repository];
    const http = new ScriptedRequester([]);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories,
      http,
    });
    repositories.push("other/private");
    await expect(
      client.getIssue(context(), { repository: "other/private", issueNumber: 1 }),
    ).rejects.toBeInstanceOf(IntegrationPolicyError);
    expect(http.requests).toEqual([]);

    expect(
      () =>
        new GitHubClient({
          tokenFor: async () => fixture.token,
          repositories: ["invalid"],
          http,
        }),
    ).toThrow(IntegrationPolicyError);
  });

  it("validates every search repository before applying the row cap", async () => {
    const items = Array.from({ length: 20 }, (_, index) => ({
      path: `src/${index}.ts`,
      sha: String(index),
      repository: { full_name: fixture.repository },
      text_matches: [],
    }));
    items.push({
      path: "private.txt",
      sha: "bad",
      repository: { full_name: "other/private" },
      text_matches: [],
    });
    const http = new ScriptedRequester([
      { status: 200, headers: {}, json: { total_count: 21, items } },
    ]);
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http,
    });
    await expect(
      client.searchCode(context(), { repository: fixture.repository, query: "needle" }),
    ).rejects.toBeInstanceOf(ToolExecutionError);
  });

  it.each([
    ["path", 512],
    ["title", 256],
  ] as const)("bounds provider %s by Unicode characters", async (field, maximum) => {
    const call = async (value: string): Promise<unknown> => {
      const response =
        field === "path"
          ? {
              total_count: 1,
              items: [
                {
                  path: value,
                  sha: "abc123",
                  repository: { full_name: fixture.repository },
                  text_matches: [],
                },
              ],
            }
          : {
              number: 1,
              state: "open",
              title: value,
              body: "",
              html_url: "https://github.com/octo/widgets/issues/1",
            };
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http: new ScriptedRequester([{ status: 200, headers: {}, json: response }]),
      });
      return field === "path"
        ? client.searchCode(context(), { repository: fixture.repository, query: "needle" })
        : client.getIssue(context(), { repository: fixture.repository, issueNumber: 1 });
    };

    const valid = "é".repeat(maximum);
    await expect(call(valid)).resolves.toHaveProperty(
      field === "path" ? "items.0.path" : "title",
      valid,
    );
    await expect(call("é".repeat(maximum + 1))).rejects.toBeInstanceOf(ToolExecutionError);
  });

  it("bounds fragment previews by UTF-8 bytes", async () => {
    const client = new GitHubClient({
      tokenFor: async () => fixture.token,
      repositories: [fixture.repository],
      http: new ScriptedRequester([
        {
          status: 200,
          headers: {},
          json: {
            total_count: 1,
            items: [
              {
                path: "src/lib.ts",
                sha: "abc123",
                repository: { full_name: fixture.repository },
                text_matches: [{ fragment: "é".repeat(513) }],
              },
            ],
          },
        },
      ]),
    });
    const result = (await client.searchCode(context(), {
      repository: fixture.repository,
      query: "needle",
    })) as { readonly items: readonly [{ readonly fragment: string }] };
    expect(result.items[0].fragment).toBe("é".repeat(512));
    expect(new TextEncoder().encode(result.items[0].fragment).byteLength).toBe(1_024);
  });

  it("bounds issue bodies by UTF-8 bytes", async () => {
    const call = (body: string): Promise<unknown> => {
      const client = new GitHubClient({
        tokenFor: async () => fixture.token,
        repositories: [fixture.repository],
        http: new ScriptedRequester([
          {
            status: 200,
            headers: {},
            json: {
              number: 1,
              state: "open",
              title: "Title",
              body,
              html_url: "https://github.com/octo/widgets/issues/1",
            },
          },
        ]),
      });
      return client.getIssue(context(), { repository: fixture.repository, issueNumber: 1 });
    };

    await expect(call("é".repeat(8_192))).resolves.toHaveProperty("body", "é".repeat(8_192));
    await expect(call("é".repeat(8_193))).rejects.toBeInstanceOf(ToolExecutionError);
  });

  it.each(fixture.durable_result_boundaries)("enforces $name", (boundary) => {
    const emptySize = new TextEncoder().encode(JSON.stringify({ padding: "" })).byteLength;
    const value = { padding: "x".repeat(boundary.serialized_bytes - emptySize) };
    expect(new TextEncoder().encode(JSON.stringify(value)).byteLength).toBe(
      boundary.serialized_bytes,
    );
    if (boundary.accepted) {
      const result = snapshotIntegrationResult(value) as { readonly padding: string };
      expect(result).toEqual(value);
      expect(Object.isFrozen(result)).toBe(true);
    } else {
      expect(() => snapshotIntegrationResult(value)).toThrow();
    }
  });
});
