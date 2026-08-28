import type { ToolHandler, ToolSpec } from "kaji";

import packageAbi from "../../contracts/integrations/github-tool-abi-typescript-v1.json";
import type { GitHubClient } from "./client";
import type { SharedGitHubClient } from "./index";

export type PackageGitHubClient = SharedGitHubClient &
  Pick<
    GitHubClient,
    | "getCommit"
    | "getPullRequest"
    | "listPullRequestFiles"
    | "listCheckRuns"
    | "getWorkflowRun"
    | "listWorkflowJobs"
    | "listFileCommits"
    | "getRelease"
    | "listDeployments"
  >;

function objectResult(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("GitHub client returned an invalid tool result");
  }
  return value as Record<string, unknown>;
}

function extensionSpecs(): readonly ToolSpec[] {
  return packageAbi.tools.slice(6).map((tool) => ({
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    risk: "read",
    parallel_safe: true,
    timeout_ms: 10_000,
  }));
}

function extensionHandler(client: PackageGitHubClient, name: string): ToolHandler {
  return async (args, context) => {
    switch (name) {
      case "get_commit":
        return objectResult(
          await client.getCommit(context, {
            repository: args.repository as string,
            ref: args.ref as string,
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      case "get_pull_request":
        return objectResult(
          await client.getPullRequest(context, {
            repository: args.repository as string,
            pullNumber: args.pull_number as number,
          }),
        );
      case "list_pull_request_files":
        return objectResult(
          await client.listPullRequestFiles(context, {
            repository: args.repository as string,
            pullNumber: args.pull_number as number,
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      case "list_check_runs":
        return objectResult(
          await client.listCheckRuns(context, {
            repository: args.repository as string,
            ref: args.ref as string,
            ...(args.filter === undefined ? {} : { filter: args.filter as "latest" | "all" }),
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      case "get_workflow_run":
        return objectResult(
          await client.getWorkflowRun(context, {
            repository: args.repository as string,
            runId: args.run_id as number,
          }),
        );
      case "list_workflow_jobs":
        return objectResult(
          await client.listWorkflowJobs(context, {
            repository: args.repository as string,
            runId: args.run_id as number,
            ...(args.filter === undefined ? {} : { filter: args.filter as "latest" | "all" }),
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      case "list_file_commits":
        return objectResult(
          await client.listFileCommits(context, {
            repository: args.repository as string,
            path: args.path as string,
            ...(args.ref === undefined ? {} : { ref: args.ref as string }),
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      case "get_release":
        return objectResult(
          await client.getRelease(context, {
            repository: args.repository as string,
            tag: args.tag as string,
          }),
        );
      case "list_deployments":
        return objectResult(
          await client.listDeployments(context, {
            repository: args.repository as string,
            ...(args.ref === undefined ? {} : { ref: args.ref as string }),
            ...(args.sha === undefined ? {} : { sha: args.sha as string }),
            ...(args.environment === undefined ? {} : { environment: args.environment as string }),
            ...(args.task === undefined ? {} : { task: args.task as string }),
            ...(args.page === undefined ? {} : { page: args.page as number }),
            ...(args.per_page === undefined ? {} : { perPage: args.per_page as number }),
          }),
        );
      default:
        throw new Error("Unknown GitHub package tool");
    }
  };
}

export function createPackageGitHubToolBindings(
  client: PackageGitHubClient,
): [ToolSpec, ToolHandler][] {
  return extensionSpecs().map((spec) => [spec, extensionHandler(client, spec.name)]);
}
