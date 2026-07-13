// This is YOUR GitHub integration. Edit it.

import {
  Integration,
  type MetricsSink,
  type ToolExecutionContext,
  type ToolHandler,
  type ToolSpec,
  type TraceSink,
} from "@kaji/sdk";
import { createGitHubRequester } from "@kaji/sdk/integrations";

import { GitHubClient } from "./client";

type Client = Pick<
  GitHubClient,
  "addComment" | "createIssue" | "getFile" | "getIssue" | "listIssues" | "searchCode"
>;

const repository = {
  type: "string",
  pattern: "^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$",
} as const;
const issueNumber = { type: "integer", minimum: 1, maximum: Number.MAX_SAFE_INTEGER } as const;

function parameters(
  properties: Readonly<Record<string, unknown>>,
  required: readonly string[],
): Record<string, unknown> {
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    properties,
    required: [...required],
    additionalProperties: false,
  };
}

function specs(): readonly ToolSpec[] {
  return [
    {
      name: "add_comment",
      description: "Add a comment to a GitHub issue.",
      parameters: parameters(
        {
          repository,
          issue_number: issueNumber,
          body: { type: "string", minLength: 1, maxLength: 16_384 },
        },
        ["repository", "issue_number", "body"],
      ),
      risk: "external_effect",
      parallel_safe: false,
      timeout_ms: 15_000,
    },
    {
      name: "create_issue",
      description: "Create a GitHub issue.",
      parameters: parameters(
        {
          repository,
          title: { type: "string", minLength: 1, maxLength: 256 },
          body: { type: "string", minLength: 0, maxLength: 16_384 },
        },
        ["repository", "title", "body"],
      ),
      risk: "external_effect",
      parallel_safe: false,
      timeout_ms: 15_000,
    },
    {
      name: "get_file",
      description: "Get a file from a GitHub repository.",
      parameters: parameters(
        {
          repository,
          path: { type: "string", minLength: 1, maxLength: 512 },
          ref: { type: "string", minLength: 1, maxLength: 100 },
        },
        ["repository", "path"],
      ),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "get_issue",
      description: "Get a GitHub issue.",
      parameters: parameters({ repository, issue_number: issueNumber }, [
        "repository",
        "issue_number",
      ]),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "list_issues",
      description: "List GitHub issues.",
      parameters: parameters(
        {
          repository,
          state: { type: "string", enum: ["open", "closed", "all"], default: "open" },
          page: { type: "integer", minimum: 1, maximum: 1_000, default: 1 },
          per_page: { type: "integer", minimum: 1, maximum: 20, default: 10 },
        },
        ["repository"],
      ),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "search_code",
      description: "Search code in a GitHub repository.",
      parameters: parameters(
        {
          repository,
          query: { type: "string", minLength: 1, maxLength: 256 },
          page: { type: "integer", minimum: 1, maximum: 50, default: 1 },
          per_page: { type: "integer", minimum: 1, maximum: 20, default: 10 },
        },
        ["repository", "query"],
      ),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
  ];
}

function objectResult(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("GitHub client returned an invalid tool result");
  }
  return value as Record<string, unknown>;
}

export class GitHubIntegration extends Integration {
  readonly namespace = "github";

  constructor(private readonly client: Client) {
    super();
  }

  override tools(): [ToolSpec, ToolHandler][] {
    return specs().map((spec) => [spec, this.handler(spec.name)]);
  }

  private handler(name: string): ToolHandler {
    return async (args, context) => {
      switch (name) {
        case "add_comment":
          return objectResult(
            await this.client.addComment(context, {
              repository: args.repository as string,
              issueNumber: args.issue_number as number,
              body: args.body as string,
            }),
          );
        case "create_issue":
          return objectResult(
            await this.client.createIssue(context, {
              repository: args.repository as string,
              title: args.title as string,
              body: args.body as string,
            }),
          );
        case "get_file":
          return objectResult(
            await this.client.getFile(context, {
              repository: args.repository as string,
              path: args.path as string,
              ...(args.ref === undefined ? {} : { ref: args.ref as string }),
            }),
          );
        case "get_issue":
          return objectResult(
            await this.client.getIssue(context, {
              repository: args.repository as string,
              issueNumber: args.issue_number as number,
            }),
          );
        case "list_issues":
          return objectResult(
            await this.client.listIssues(context, {
              repository: args.repository as string,
              ...(args.state === undefined
                ? {}
                : { state: args.state as "open" | "closed" | "all" }),
              ...(args.page === undefined ? {} : { page: args.page as number }),
              ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
            }),
          );
        case "search_code":
          return objectResult(
            await this.client.searchCode(context, {
              repository: args.repository as string,
              query: args.query as string,
              ...(args.page === undefined ? {} : { page: args.page as number }),
              ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
            }),
          );
        default:
          throw new Error("Unknown GitHub tool");
      }
    };
  }
}

export interface CreateGitHubIntegrationOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

export function createGithubIntegration(
  options: CreateGitHubIntegrationOptions,
): GitHubIntegration {
  const { metricsSink, traceSink, ...clientOptions } = options;
  return createGithubIntegrationForTest(
    new GitHubClient({
      ...clientOptions,
      http: createGitHubRequester({ metricsSink, traceSink }),
    }),
  );
}

function createGithubIntegrationForTest(client: Client): GitHubIntegration {
  return new GitHubIntegration(client);
}

const inspectionClient = new Proxy(
  {},
  {
    get: () => async () => {
      throw new Error("inspection dependencies must not execute");
    },
  },
) as Client;

export function inspectIntegration(): GitHubIntegration {
  return createGithubIntegrationForTest(inspectionClient);
}
