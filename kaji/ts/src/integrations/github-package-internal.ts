import type { MetricsSink, ToolExecutionContext, TraceSink } from "@kaji/sdk";
import { createGitHubRequester, type FixedOriginRequester } from "@kaji/sdk/integrations";

import { GitHubClient, type GitHubClientOptions } from "../../registry/github/client";
import type { PackageGitHubClient } from "../../registry/github/package-tools";

type OwnedGitHubRequester = FixedOriginRequester & { close(): void };

interface PackageGitHubOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

export interface PackageGitHubRuntime {
  readonly createRequester: (observability: {
    readonly metricsSink?: MetricsSink;
    readonly traceSink?: TraceSink;
  }) => OwnedGitHubRequester;
  readonly createClient: (options: GitHubClientOptions) => PackageGitHubClient;
}

const productionRuntime: PackageGitHubRuntime = {
  createRequester: (observability) => createGitHubRequester(observability),
  createClient: (options) => new GitHubClient(options),
};

export function createPackageGitHubState(
  options: PackageGitHubOptions,
  runtime: PackageGitHubRuntime = productionRuntime,
): Readonly<{ client: PackageGitHubClient; close: () => void }> {
  const { metricsSink, traceSink, ...clientOptions } = options;
  const requester = runtime.createRequester({ metricsSink, traceSink });
  try {
    return {
      client: runtime.createClient({ ...clientOptions, http: requester }),
      close: () => requester.close(),
    };
  } catch (error) {
    try {
      requester.close();
    } catch {
      // Preserve the client construction failure that prevented ownership transfer.
    }
    throw error;
  }
}
