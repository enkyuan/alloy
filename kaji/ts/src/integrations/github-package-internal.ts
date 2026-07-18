import {
  NOOP_METRICS,
  NOOP_TRACE,
  recordMetric,
  startSpan,
  type MetricsSink,
  type ToolExecutionContext,
  type TraceSink,
} from "@kaji/sdk";
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
  const { metricsSink, traceSink, tokenFor, ...clientOptions } = options;
  const metrics = metricsSink ?? NOOP_METRICS;
  const trace = traceSink ?? NOOP_TRACE;
  const instrumentedTokenFor = async (context: ToolExecutionContext): Promise<string> => {
    const started = performance.now();
    const span = startSpan(trace, "kaji.integration.auth", {
      "session.id": context.sessionId,
      "turn.id": context.turnId,
      "request.id": context.requestId,
      "trace.id": context.traceId,
      "tool.call_id": context.toolCallId,
      "integration.name": "github",
      "integration.operation": "token",
      "http.status_family": "none",
    });
    let outcome: "success" | "error" | "cancelled" = "error";
    try {
      const token = await tokenFor(context);
      outcome = "success";
      return token;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") outcome = "cancelled";
      span.recordError(error);
      throw error;
    } finally {
      recordMetric(metrics, "kaji.integration.auth_ms", Math.max(0, performance.now() - started), {
        integration: "github",
        operation: "token",
        outcome,
      });
      span.end();
    }
  };
  const requester = runtime.createRequester({ metricsSink, traceSink });
  try {
    return {
      client: runtime.createClient({
        ...clientOptions,
        tokenFor: instrumentedTokenFor,
        http: requester,
      }),
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
