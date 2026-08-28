import {
  Integration,
  type MetricsSink,
  type ToolExecutionContext,
  type ToolHandler,
  type ToolSpec,
  type TraceSink,
} from "kaji";
import { IntegrationPolicyError } from "kaji/integrations";

import { createSharedGitHubToolBindings } from "../../registry/github/index";
import {
  createPackageGitHubToolBindings,
  type PackageGitHubClient,
} from "../../registry/github/package-tools";
import { createPackageGitHubState } from "./github-package-internal";

export interface CreateGitHubIntegrationOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  /** Tools registered with the agent. Defaults to the complete 15-tool catalog. */
  readonly toolExposure?: "read-only" | "all";
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

export class GitHubIntegration extends Integration {
  readonly namespace = "github";
  #client: PackageGitHubClient;
  #closeOwnedRequester: (() => void) | undefined;
  #toolExposure: "read-only" | "all";
  #closed = false;

  constructor(options: CreateGitHubIntegrationOptions) {
    super();
    if (
      options.toolExposure !== undefined &&
      options.toolExposure !== "read-only" &&
      options.toolExposure !== "all"
    ) {
      throw new TypeError('GitHub toolExposure must be "all" or "read-only"');
    }
    this.#toolExposure = options.toolExposure ?? "all";
    const state = createPackageGitHubState(options);
    this.#client = state.client;
    this.#closeOwnedRequester = state.close;
  }

  override tools(): [ToolSpec, ToolHandler][] {
    const bindings: [ToolSpec, ToolHandler][] = [
      ...createSharedGitHubToolBindings(this.#client),
      ...createPackageGitHubToolBindings(this.#client),
    ];
    const exposed =
      this.#toolExposure === "read-only"
        ? bindings.filter(([spec]) => spec.risk === "read")
        : bindings;
    return exposed.map(([spec, handler]) => [
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
