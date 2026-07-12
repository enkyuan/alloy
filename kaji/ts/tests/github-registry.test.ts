import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { listToolSpecs, ToolRegistry } from "@kaji/sdk";
import type { FixedOriginRequester } from "@kaji/sdk/integrations";
import { EventType } from "@/events/types";
import { StoredKajiEvent } from "@/events/schemas";
import { ToolPlanner } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { GitHubClient } from "../registry/github/client";
import { GitHubIntegration, inspectIntegration } from "../registry/github/index";

const kajiRoot = resolve(import.meta.dirname, "../..");
const abi = JSON.parse(
  readFileSync(resolve(kajiRoot, "contracts/integrations/github-tool-abi-v1.json"), "utf8"),
) as { namespace: string; tools: Array<Record<string, unknown>> };

describe("GitHub registry bundle", () => {
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

  it("declares the exact native owner asset set", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(kajiRoot, "ts/registry/github/manifest.json"), "utf8"),
    );
    expect(manifest.files).toEqual([
      "index.ts",
      "client.ts",
      "github_vitest.ts",
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
    const planner = new ToolPlanner({
      specs,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
      approvalHandler: async () => false,
      executor: async (invocation) =>
        registry.execute(invocation.name, { ...invocation.arguments }, invocation.context),
    });
    const results = await planner.executeBatch(
      "session",
      [{ id: "call", name, arguments: args }],
      async (event) => {
        events.push(event);
        return StoredKajiEvent.parse({ ...event, sequence: events.length });
      },
      "turn",
      { principalId: "principal", requestId: "request", traceId: "trace" },
    );

    expect(results[0]).toMatchObject({ error_code: "APPROVAL_REJECTED" });
    expect(events.map((event) => event.type)).not.toContain(EventType.TOOL_CALL_STARTED);
    expect(tokenFor).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });
});
