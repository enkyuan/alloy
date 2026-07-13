import { describe, expect, it, vi } from "vitest";

import { GoogleOAuthClient, type OAuthCredentialRecord } from "@/auth/oauth";
import { fixedOriginForTest, type FixedOriginTestTransport } from "@/integrations/fixed-origin";
import {
  recordMetric,
  startSpan,
  type MetricMeasurement,
  type MetricsSink,
  type TraceSink,
} from "@/observability";
import type { ToolExecutionContext } from "@/runtime/context";
import { MockProvider } from "@/providers/mock";
import { AgentBuilder } from "@/runtime/builder";
import { ToolExecutionController } from "@/tools/execution";

function context(principalId = "poison-principal-secret"): ToolExecutionContext {
  return {
    principalId,
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal: new AbortController().signal,
    metadata: {},
  };
}

function capture() {
  const measurements: MetricMeasurement[] = [];
  const spans: Array<{ name: string; attributes: Record<string, string> }> = [];
  const metrics: MetricsSink = {
    record(measurement) {
      measurements.push(measurement);
    },
  };
  const trace: TraceSink = {
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
  return { measurements, metrics, spans, trace };
}

describe("integration observability", () => {
  it("emits only bounded fixed-origin labels and attributes", async () => {
    const observed = capture();
    let tick = 1;
    const transport: FixedOriginTestTransport = {
      request: vi.fn(async () => ({
        status: 200,
        headers: [],
        body: (async function* () {
          yield new TextEncoder().encode("ok");
        })(),
        close() {},
      })),
    };
    const requester = fixedOriginForTest(
      "https://api.github.com",
      transport,
      { integration: "github" },
      {
        metricsSink: observed.metrics,
        traceSink: observed.trace,
        monotonicNow: () => tick++,
      },
    );

    await requester.request(
      "/repos/private-owner/private-repo",
      { method: "GET", headers: { authorization: "Bearer private-token" } },
      context(),
    );

    expect(observed.measurements).toEqual([
      {
        name: "kaji.integration.request_ms",
        value: 1,
        unit: "ms",
        labels: { integration: "github", operation: "read", outcome: "success" },
      },
    ]);
    expect(observed.spans).toEqual([
      {
        name: "kaji.integration.request",
        attributes: {
          "integration.name": "github",
          "integration.operation": "read",
          "http.status_family": "2xx",
        },
      },
    ]);
    expect(JSON.stringify(observed)).not.toMatch(
      /private-owner|private-repo|private-token|poison-principal-secret/,
    );
  });

  it("emits bounded OAuth auth telemetry without the principal or token", async () => {
    const observed = capture();
    const record: OAuthCredentialRecord = {
      schemaVersion: 1,
      state: "active",
      tokens: {
        accessToken: "private-access-token",
        refreshToken: "private-refresh-token",
        expiresAtEpochMs: Date.now() + 3_600_000,
        grantedScopes: ["scope"],
        tokenType: "Bearer",
      },
    };
    const oauth = new GoogleOAuthClient({
      clientId: "client",
      scopes: ["scope"],
      storage: {
        async load() {
          return record;
        },
        async save() {},
        async delete() {},
      },
      metricsSink: observed.metrics,
      traceSink: observed.trace,
    });

    expect(await oauth.accessToken(context())).toBe("private-access-token");
    expect(observed.measurements[0]).toMatchObject({
      name: "kaji.integration.auth_ms",
      labels: { integration: "gmail", operation: "token", outcome: "success" },
    });
    expect(observed.spans[0]).toEqual({
      name: "kaji.integration.auth",
      attributes: {
        "integration.name": "gmail",
        "integration.operation": "token",
        "http.status_family": "none",
      },
    });
    expect(JSON.stringify(observed)).not.toMatch(
      /private-access-token|private-refresh-token|poison-principal-secret/,
    );
  });

  it("fails closed for unknown metric labels and span attribute values", () => {
    const observed = capture();
    recordMetric(observed.metrics, "kaji.integration.request_ms", 1, {
      integration: "private" as "github",
      operation: "read",
      outcome: "success",
    });
    startSpan(observed.trace, "kaji.integration.request", {
      "integration.name": "private",
      "integration.operation": "read",
      "http.status_family": "2xx",
    }).end();
    startSpan(observed.trace, "kaji.turn", { "principal.id": "secret" } as never).end();

    expect(observed.measurements).toEqual([]);
    expect(observed.spans).toEqual([]);
  });

  it("never emits the principal on turn or tool spans", async () => {
    const observed = capture();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "ok" }))
      .traceSink(observed.trace)
      .build();
    await runtime.turn("prompt", {
      context: { principalId: "poison-principal-secret" },
    });

    const controller = new ToolExecutionController({ traceSink: observed.trace });
    await controller.execute({
      name: "echo",
      args: {},
      context: context(),
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({ ok: true }),
    });

    expect(observed.spans.map((span) => span.name)).toContain("kaji.turn");
    expect(observed.spans.map((span) => span.name)).toContain("kaji.tool");
    expect(JSON.stringify(observed.spans)).not.toContain("poison-principal-secret");
  });
});
