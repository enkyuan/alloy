import { describe, expect, it } from "vitest";

import type { MetricMeasurement, MetricsSink, ToolExecutionContext, TraceSink } from "@kaji/sdk";

import { createGithubIntegration } from "../registry/github/index";

describe("GitHub observability wiring", () => {
  it("emits through caller sinks from the production factory without network I/O", async () => {
    const measurements: MetricMeasurement[] = [];
    const spans: Array<{ name: string; attributes: Record<string, string> }> = [];
    const metricsSink: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const traceSink: TraceSink = {
      startSpan(name, attributes = {}) {
        const span = { name, attributes: { ...attributes } };
        spans.push(span);
        return {
          setAttribute(key, value) {
            span.attributes[key] = value;
          },
          recordError() {},
          end() {},
        };
      },
    };
    const integration = createGithubIntegration({
      tokenFor: async () => "private-token",
      repositories: ["octo/widgets"],
      metricsSink,
      traceSink,
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
    const context: ToolExecutionContext = {
      principalId: "poison-principal",
      sessionId: "session",
      turnId: "turn",
      requestId: "request",
      traceId: "trace",
      toolCallId: "call",
      idempotencyKey: "session:call",
      signal,
      metadata: {},
    };

    await expect(
      pair![1]({ repository: "octo/widgets", query: "needle" }, context),
    ).rejects.toMatchObject({ name: "AbortError" });

    expect(measurements).toHaveLength(1);
    expect(measurements[0]).toMatchObject({
      name: "kaji.integration.request_ms",
      labels: { integration: "github", operation: "read", outcome: "cancelled" },
    });
    expect(spans[0]).toMatchObject({
      name: "kaji.integration.request",
      attributes: { "integration.name": "github", "integration.operation": "read" },
    });
    expect(JSON.stringify({ measurements, spans })).not.toMatch(
      /private-token|poison-principal|octo\/widgets|needle/,
    );
    integration.close();
  });
});
