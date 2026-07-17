import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import { ToolExecutionError, type ToolExecutionContext } from "@kaji/sdk";
import {
  IntegrationAuthRequiredError,
  IntegrationPolicyError,
  snapshotIntegrationResult,
  type BoundedResponse,
  type FixedOriginRequester,
} from "@kaji/sdk/integrations";
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
    new URL("../../contracts/integrations/github-api-conformance-v1.json", import.meta.url),
    "utf8",
  ),
) as Fixture;

const TYPESCRIPT_REQUEST_IDENTITY = {
  "user-agent": "@kaji/sdk-github/0.2.0",
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
      "json" in response
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
