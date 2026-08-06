import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { Integration, listToolSpecs, ToolRegistry } from "kaji-sdk";
import type { FixedOriginRequester } from "kaji-sdk/integrations";
import { EventType } from "@/events/types";
import { InMemoryEventCommitter } from "@/events/committer";
import { InMemoryEventStore } from "@/events/store";
import { ToolPlanner, bindEmitterToCommitter } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { GitHubClient } from "../registry/github/client";
import { GitHubIntegration, inspectIntegration } from "../registry/github/index";
import { createPackageGitHubToolBindings } from "../registry/github/package-tools";
import {
  createGithubIntegration as createPackageGithubIntegration,
  GitHubIntegration as PackageGitHubIntegration,
  inspectIntegration as inspectPackageIntegration,
} from "@/integrations/github";
import { createPackageGitHubState } from "@/integrations/github-package-internal";

const kajiRoot = resolve(import.meta.dirname, "../../..");
const abi = JSON.parse(
  readFileSync(resolve(kajiRoot, "contracts/integrations/github-tool-abi-v1.json"), "utf8"),
) as { namespace: string; tools: Array<Record<string, unknown>> };
const packageAbi = JSON.parse(
  readFileSync(
    resolve(kajiRoot, "contracts/integrations/github-tool-abi-typescript-v1.json"),
    "utf8",
  ),
) as {
  schema_version: string;
  catalog_version: string;
  namespace: string;
  tools: Array<Record<string, unknown>>;
};

const PACKAGE_TOOLS = [
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

const PACKAGE_READ_TOOLS = PACKAGE_TOOLS.filter(
  (name) => name !== "add_comment" && name !== "create_issue",
);

describe("GitHub registry bundle", () => {
  it("closes its production-owned requester exactly once", () => {
    const close = vi.fn();
    const integration = new GitHubIntegration({} as never, close);

    integration.close();
    integration.close();

    expect(close).toHaveBeenCalledOnce();
  });

  it("allows teardown to be retried after an owned requester close failure", () => {
    const close = vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("close failed");
      })
      .mockImplementationOnce(() => undefined);
    const integration = new GitHubIntegration({} as never, close);

    expect(() => integration.close()).toThrow("close failed");
    integration.close();
    integration.close();

    expect(close).toHaveBeenCalledTimes(2);
  });

  it("matches the exact canonical ABI without global registration", () => {
    const before = listToolSpecs();
    const integration = inspectIntegration();
    const tools = integration.tools().map(([spec]) => ({
      name: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      risk: spec.risk,
      parallel_safe: spec.parallel_safe,
      timeout_ms: spec.timeout_ms,
    }));

    expect({ namespace: integration.namespace, tools }).toEqual({
      namespace: abi.namespace,
      tools: abi.tools,
    });
    expect(listToolSpecs()).toEqual(before);
  });

  it("exposes the exact 15-tool package catalog while the copied catalog stays shared-six", () => {
    const integration = inspectPackageIntegration();
    const tools = integration.tools().map(([spec]) => ({
      name: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      risk: spec.risk,
      parallel_safe: spec.parallel_safe,
      timeout_ms: spec.timeout_ms,
    }));

    expect(integration).toBeInstanceOf(PackageGitHubIntegration);
    expect({ namespace: integration.namespace, tools }).toEqual({
      namespace: packageAbi.namespace,
      tools: packageAbi.tools,
    });
    expect(tools.map((tool) => tool.name)).toEqual(PACKAGE_TOOLS);
    expect(tools.filter((tool) => tool.risk === "read").map((tool) => tool.name)).toEqual(
      PACKAGE_READ_TOOLS,
    );
    expect(
      inspectIntegration()
        .tools()
        .map(([spec]) => spec.name),
    ).toEqual(abi.tools.map((tool) => tool.name));
    integration.close();
  });

  it("exposes only canonical read tools when configured read-only", () => {
    const integration = createPackageGithubIntegration({
      tokenFor: async () => "token",
      repositories: ["owner/repo"],
      toolExposure: "read-only",
    });
    const tools = integration.tools().map(([spec]) => ({
      name: spec.name,
      risk: spec.risk,
    }));
    const registry = new ToolRegistry();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    integration.register(registry);

    expect(tools).toEqual(PACKAGE_READ_TOOLS.map((name) => ({ name, risk: "read" })));
    expect(registry.listSpecs().map(({ name, catalogName }) => ({ name, catalogName }))).toEqual(
      PACKAGE_READ_TOOLS.map((name) => ({
        name: `github_${name}`,
        catalogName: `github.${name}`,
      })),
    );
    expect(registry.listSpecs().map(({ name }) => name)).not.toContain("github_add_comment");
    expect(registry.listSpecs().map(({ name }) => name)).not.toContain("github_create_issue");
    expect(warn).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      '[kaji] 13 integration tool names sanitized for provider compatibility; first: "github.get_file" -> "github_get_file"',
    );
    warn.mockRestore();
    integration.close();
  });

  it("rejects invalid tool exposure before constructing package state", () => {
    expect(
      () =>
        new PackageGitHubIntegration({
          tokenFor: async () => "token",
          repositories: [],
          toolExposure: null,
        } as never),
    ).toThrow('GitHub toolExposure must be "all" or "read-only"');
  });

  it("keeps package ABI version domains distinct from npm and the shared manifest", () => {
    const packageManifest = JSON.parse(
      readFileSync(resolve(kajiRoot, "packages/typescript/package.json"), "utf8"),
    );
    const copiedManifest = JSON.parse(
      readFileSync(resolve(kajiRoot, "packages/typescript/registry/github/manifest.json"), "utf8"),
    );
    expect(packageAbi.schema_version).toBe("1.0.0");
    expect(packageAbi.catalog_version).toBe("0.2.0");
    expect(copiedManifest.version).toBe("0.1.0");
    expect(packageManifest.version).not.toBe(packageAbi.catalog_version);
  });

  it("keeps package factory lifecycle idempotent and introspectable", () => {
    const integration = createPackageGithubIntegration({
      tokenFor: async () => "token",
      repositories: [],
    });

    expect(integration.tools()).toHaveLength(PACKAGE_TOOLS.length);
    integration.close();
    integration.close();
    expect(integration.tools()).toHaveLength(PACKAGE_TOOLS.length);
  });

  it("rejects post-close package calls before reading credentials", async () => {
    const tokenFor = vi.fn(async () => "token");
    const integration = createPackageGithubIntegration({
      tokenFor,
      repositories: ["owner/repo"],
    });
    const getIssue = integration.tools().find(([spec]) => spec.name === "get_issue")?.[1];

    integration.close();

    await expect(
      getIssue?.({ repository: "owner/repo", issue_number: 1 }, {
        signal: new AbortController().signal,
      } as never),
    ).rejects.toMatchObject({ name: "IntegrationPolicyError" });
    expect(tokenFor).not.toHaveBeenCalled();
  });

  it("closes its requester when package client construction fails", () => {
    const close = vi.fn();
    const failure = new Error("client construction failed");

    expect(() =>
      createPackageGitHubState(
        { tokenFor: async () => "token", repositories: ["owner/repo"] },
        {
          createRequester: () => ({ request: vi.fn(), close }) as never,
          createClient: () => {
            throw failure;
          },
        },
      ),
    ).toThrow(failure);
    expect(close).toHaveBeenCalledOnce();
  });

  it("registers provider aliases with their logical catalog identities", () => {
    const integration = inspectPackageIntegration();
    const registry = new ToolRegistry();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    integration.register(registry);

    expect(registry.listSpecs().map(({ name, catalogName }) => ({ name, catalogName }))).toEqual(
      PACKAGE_TOOLS.map((name) => ({
        name: `github_${name}`,
        catalogName: `github.${name}`,
      })),
    );
    expect(warn).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      '[kaji] 15 integration tool names sanitized for provider compatibility; first: "github.add_comment" -> "github_add_comment"',
    );
    warn.mockRestore();
  });

  it("rejects colliding provider aliases before a turn", () => {
    class CollidingIntegration extends Integration {
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

    const registry = new ToolRegistry();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    inspectPackageIntegration().register(registry);

    expect(() => new CollidingIntegration().register(registry)).toThrow(
      "Tool already registered: github_get_file",
    );
    warn.mockRestore();
  });

  it("delegates snake_case tool arguments to the matching client method", async () => {
    const client = {
      addComment: vi.fn(async () => ({ operation: "add_comment" })),
      createIssue: vi.fn(async () => ({ operation: "create_issue" })),
      getFile: vi.fn(async () => ({ operation: "get_file" })),
      getIssue: vi.fn(async () => ({ operation: "get_issue" })),
      listIssues: vi.fn(async () => ({ operation: "list_issues" })),
      searchCode: vi.fn(async () => ({ operation: "search_code" })),
    };
    const integration = new GitHubIntegration(client);
    const context = { signal: new AbortController().signal } as never;
    const argumentsByName: Record<string, Record<string, unknown>> = {
      add_comment: { repository: "owner/repo", issue_number: 1, body: "comment" },
      create_issue: { repository: "owner/repo", title: "title", body: "body" },
      get_file: { repository: "owner/repo", path: "README.md" },
      get_issue: { repository: "owner/repo", issue_number: 1 },
      list_issues: { repository: "owner/repo" },
      search_code: { repository: "owner/repo", query: "needle" },
    };

    for (const [spec, handler] of integration.tools()) {
      await expect(handler(argumentsByName[spec.name]!, context)).resolves.toEqual({
        operation: spec.name,
      });
    }
    expect(client.addComment).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      issueNumber: 1,
      body: "comment",
    });
    expect(client.searchCode).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      query: "needle",
    });
  });

  it("delegates every package-only snake_case argument explicitly", async () => {
    const client = {
      getCommit: vi.fn(async () => ({ operation: "get_commit" })),
      getPullRequest: vi.fn(async () => ({ operation: "get_pull_request" })),
      listPullRequestFiles: vi.fn(async () => ({ operation: "list_pull_request_files" })),
      listCheckRuns: vi.fn(async () => ({ operation: "list_check_runs" })),
      getWorkflowRun: vi.fn(async () => ({ operation: "get_workflow_run" })),
      listWorkflowJobs: vi.fn(async () => ({ operation: "list_workflow_jobs" })),
      listFileCommits: vi.fn(async () => ({ operation: "list_file_commits" })),
      getRelease: vi.fn(async () => ({ operation: "get_release" })),
      listDeployments: vi.fn(async () => ({ operation: "list_deployments" })),
    };
    const bindings = createPackageGitHubToolBindings(client as never);
    const context = { signal: new AbortController().signal } as never;
    const argumentsByName: Record<string, Record<string, unknown>> = {
      get_commit: { repository: "owner/repo", ref: "main", page: 2, per_page: 20 },
      get_pull_request: { repository: "owner/repo", pull_number: 7 },
      list_pull_request_files: { repository: "owner/repo", pull_number: 7, page: 2, per_page: 20 },
      list_check_runs: {
        repository: "owner/repo",
        ref: "main",
        filter: "all",
        page: 2,
        per_page: 20,
      },
      get_workflow_run: { repository: "owner/repo", run_id: 11 },
      list_workflow_jobs: {
        repository: "owner/repo",
        run_id: 11,
        filter: "all",
        page: 2,
        per_page: 20,
      },
      list_file_commits: {
        repository: "owner/repo",
        path: "src/a.ts",
        ref: "main",
        page: 2,
        per_page: 20,
      },
      get_release: { repository: "owner/repo", tag: "v1" },
      list_deployments: {
        repository: "owner/repo",
        ref: "main",
        sha: "abc",
        environment: "prod",
        task: "deploy",
        page: 2,
        per_page: 20,
      },
    };

    for (const [spec, handler] of bindings) {
      await expect(handler(argumentsByName[spec.name]!, context)).resolves.toEqual({
        operation: spec.name,
      });
    }
    expect(client.getCommit).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      ref: "main",
      page: 2,
      perPage: 20,
    });
    expect(client.listCheckRuns).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      ref: "main",
      filter: "all",
      page: 2,
      perPage: 20,
    });
    expect(client.listFileCommits).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      path: "src/a.ts",
      ref: "main",
      page: 2,
      perPage: 20,
    });
    expect(client.listDeployments).toHaveBeenCalledWith(context, {
      repository: "owner/repo",
      ref: "main",
      sha: "abc",
      environment: "prod",
      task: "deploy",
      page: 2,
      perPage: 20,
    });
  });

  it("declares the exact native owner asset set", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(kajiRoot, "packages/typescript/registry/github/manifest.json"), "utf8"),
    );
    expect(manifest.files).toEqual([
      "index.ts",
      "client.ts",
      "tests/github.test.ts",
      "owner-fixtures.json",
      "LICENSE",
    ]);
    expect(manifest.tools).toEqual(abi.tools);
  });

  it.each([
    ["github_create_issue", { repository: "owner/repo", title: "title", body: "body" }],
    ["github_add_comment", { repository: "owner/repo", issue_number: 1, body: "body" }],
  ])("rejects approval for %s before token or HTTP", async (name, args) => {
    const tokenFor = vi.fn(async () => {
      throw new Error("token must not be read");
    });
    const request = vi.fn(async () => {
      throw new Error("HTTP must not run");
    });
    const integration = new GitHubIntegration(
      new GitHubClient({
        tokenFor,
        repositories: ["owner/repo"],
        http: { request } as FixedOriginRequester,
      }),
    );
    const registry = new ToolRegistry();
    integration.register(registry);
    const specs = new Map(registry.listSpecs().map((spec) => [spec.name, spec]));
    const events: Array<{ type: string }> = [];
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const planner = new ToolPlanner({
      specs,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
      approvalHandler: {
        async request() {
          return {
            granted: false as const,
            code: "rejected" as const,
            reason: "Rejected by test policy",
          };
        },
      },
      approvalCommitter,
      executor: async (toolName, toolArgs, toolContext) =>
        registry.execute(toolName, { ...toolArgs }, toolContext),
    });
    const results = await planner.executeBatch(
      "session",
      [{ id: "call", name, arguments: args }],
      bindEmitterToCommitter(async (event) => {
        events.push(event);
        return approvalCommitter.commit(event);
      }, approvalCommitter),
      "turn",
      { principalId: "principal", requestId: "request", traceId: "trace" },
    );

    expect(results[0]).toMatchObject({ error_code: "APPROVAL_REJECTED" });
    expect(events.map((event) => event.type)).not.toContain(EventType.TOOL_CALL_STARTED);
    expect(tokenFor).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });
});
