import { describe, expect, it, vi } from "vitest";

import type { MetricMeasurement, MetricsSink, ToolExecutionContext, TraceSink } from "@kaji/sdk";

import { createGithubIntegration } from "@/integrations/github";
import { createPackageGitHubState } from "@/integrations/github-package-internal";

function context(signal = new AbortController().signal): ToolExecutionContext {
  return {
    principalId: "poison-principal",
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal,
    metadata: { poison: "private-metadata" },
  };
}

function capture() {
  const measurements: MetricMeasurement[] = [];
  const spans: Array<{
    name: string;
    attributes: Record<string, string>;
    errors: string[];
  }> = [];
  const metricsSink: MetricsSink = {
    record(measurement) {
      measurements.push(measurement);
    },
  };
  const traceSink: TraceSink = {
    startSpan(name, attributes = {}) {
      const span = { name, attributes: { ...attributes }, errors: [] as string[] };
      spans.push(span);
      return {
        setAttribute(key, value) {
          span.attributes[key] = value;
        },
        recordError(error) {
          span.errors.push(String(error));
        },
        end() {},
      };
    },
  };
  return { measurements, metricsSink, spans, traceSink };
}

function captureInstrumentedTokenFor(
  tokenFor: (executionContext: ToolExecutionContext) => Promise<string>,
  observed: ReturnType<typeof capture>,
) {
  let instrumented: ((executionContext: ToolExecutionContext) => Promise<string>) | undefined;
  const close = vi.fn();
  const state = createPackageGitHubState(
    {
      tokenFor,
      repositories: ["octo/widgets"],
      metricsSink: observed.metricsSink,
      traceSink: observed.traceSink,
    },
    {
      createRequester: () => ({ request: vi.fn(), close }) as never,
      createClient(options) {
        instrumented = options.tokenFor;
        return {} as never;
      },
    },
  );
  expect(instrumented).toBeDefined();
  return { close: state.close, tokenFor: instrumented! };
}

const CORRELATION_ATTRIBUTES = {
  "session.id": "session",
  "turn.id": "turn",
  "request.id": "request",
  "trace.id": "trace",
  "tool.call_id": "call",
} as const;

describe("packaged GitHub observability wiring", () => {
  it("emits through caller sinks from the public package factory without network I/O", async () => {
    const observed = capture();
    const integration = createGithubIntegration({
      tokenFor: async () => "private-token",
      repositories: ["octo/widgets"],
      metricsSink: observed.metricsSink,
      traceSink: observed.traceSink,
    });
    const pair = integration.tools().find(([spec]) => spec.name === "search_code");
    expect(pair).toBeDefined();
    let abortReads = 0;
    const signal = {
      get aborted() {
        abortReads += 1;
        return abortReads >= 3;
      },
      reason: new DOMException("cancelled", "AbortError"),
      addEventListener() {},
      removeEventListener() {},
    } as unknown as AbortSignal;
    await expect(
      pair![1]({ repository: "octo/widgets", query: "needle" }, context(signal)),
    ).rejects.toMatchObject({ name: "AbortError" });

    expect(observed.measurements).toHaveLength(2);
    expect(observed.measurements).toEqual([
      expect.objectContaining({
        name: "kaji.integration.auth_ms",
        labels: { integration: "github", operation: "token", outcome: "success" },
      }),
      expect.objectContaining({
        name: "kaji.integration.request_ms",
        labels: { integration: "github", operation: "read", outcome: "cancelled" },
      }),
    ]);
    expect(observed.spans).toMatchObject([
      {
        name: "kaji.integration.auth",
        attributes: {
          ...CORRELATION_ATTRIBUTES,
          "integration.name": "github",
          "integration.operation": "token",
          "http.status_family": "none",
        },
      },
      {
        name: "kaji.integration.request",
        attributes: {
          ...CORRELATION_ATTRIBUTES,
          "integration.name": "github",
          "integration.operation": "read",
          "http.status_family": "none",
        },
      },
    ]);
    expect(JSON.stringify(observed)).not.toMatch(
      /private-token|poison-principal|private-metadata|octo\/widgets|needle/,
    );
    integration.close();
  });

  it("returns the exact token from the instrumented callback", async () => {
    const observed = capture();
    const instrumented = captureInstrumentedTokenFor(async () => "private-token", observed);

    await expect(instrumented.tokenFor(context())).resolves.toBe("private-token");

    expect(observed.measurements).toEqual([
      expect.objectContaining({
        name: "kaji.integration.auth_ms",
        labels: { integration: "github", operation: "token", outcome: "success" },
      }),
    ]);
    expect(observed.spans).toMatchObject([
      {
        name: "kaji.integration.auth",
        attributes: {
          ...CORRELATION_ATTRIBUTES,
          "integration.name": "github",
          "integration.operation": "token",
          "http.status_family": "none",
        },
      },
    ]);
    expect(JSON.stringify(observed)).not.toMatch(/private-token|poison-principal|private-metadata/);
    instrumented.close();
  });

  it.each([
    ["error", new Error("private callback failure")],
    ["cancelled", new DOMException("private cancellation reason", "AbortError")],
  ] as const)(
    "classifies %s token lookup and preserves the callback error",
    async (outcome, error) => {
      const observed = capture();
      const tokenFor = vi.fn(async () => {
        throw error;
      });
      const instrumented = captureInstrumentedTokenFor(tokenFor, observed);

      const caught = await instrumented.tokenFor(context()).catch((failure: unknown) => failure);

      expect(caught).toBe(error);
      expect(tokenFor).toHaveBeenCalledOnce();
      expect(observed.measurements).toEqual([
        expect.objectContaining({
          name: "kaji.integration.auth_ms",
          labels: { integration: "github", operation: "token", outcome },
        }),
      ]);
      expect(observed.measurements[0]!.labels).toEqual({
        integration: "github",
        operation: "token",
        outcome,
      });
      expect(observed.spans).toMatchObject([
        {
          name: "kaji.integration.auth",
          attributes: {
            ...CORRELATION_ATTRIBUTES,
            "integration.name": "github",
            "integration.operation": "token",
            "http.status_family": "none",
          },
        },
      ]);
      expect(JSON.stringify(observed)).not.toMatch(
        /private callback failure|private cancellation reason|poison-principal|private-metadata/,
      );
      instrumented.close();
    },
  );
});
