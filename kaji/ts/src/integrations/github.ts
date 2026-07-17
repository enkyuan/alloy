import {
  Integration,
  type MetricsSink,
  type ToolExecutionContext,
  type ToolHandler,
  type ToolSpec,
  type TraceSink,
} from "@kaji/sdk";
import { IntegrationPolicyError } from "@kaji/sdk/integrations";

import {
  createSharedGitHubToolBindings,
  type SharedGitHubClient,
} from "../../registry/github/index";
import { createPackageGitHubState } from "./github-package-internal";

export interface CreateGitHubIntegrationOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

export class GitHubIntegration extends Integration {
  readonly namespace = "github";
  #client: SharedGitHubClient;
  #closeOwnedRequester: (() => void) | undefined;
  #closed = false;

  constructor(options: CreateGitHubIntegrationOptions) {
    super();
    const state = createPackageGitHubState(options);
    this.#client = state.client;
    this.#closeOwnedRequester = state.close;
  }

  override tools(): [ToolSpec, ToolHandler][] {
    return createSharedGitHubToolBindings(this.#client).map(([spec, handler]) => [
      spec,
      async (args, context) => {
        if (this.#closed) throw new IntegrationPolicyError();
        return handler(args, context);
      },
    ]);
  }

  close(): void {
    const close = this.#closeOwnedRequester;
    if (close === undefined) return;
    close();
    this.#closeOwnedRequester = undefined;
    this.#closed = true;
  }
}

export function createGithubIntegration(
  options: CreateGitHubIntegrationOptions,
): GitHubIntegration {
  return new GitHubIntegration(options);
}

export function inspectIntegration(): GitHubIntegration {
  const integration = createGithubIntegration({
    tokenFor: async () => {
      throw new Error("inspection dependencies must not execute");
    },
    repositories: [],
  });
  integration.close();
  return integration;
}
