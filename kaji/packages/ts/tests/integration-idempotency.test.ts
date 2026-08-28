import { describe, expect, it, vi } from "vitest";

import {
  IntegrationExecutionError,
  IntegrationTransientReadError,
  IntegrationTransportError,
} from "@/integrations/errors";
import type { ToolExecutionContext } from "@/runtime/context";
import { ToolExecutionController } from "@/tools/execution";

function context(callId: string): ToolExecutionContext {
  return {
    principalId: "principal",
    sessionId: "integration-idempotency",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: callId,
    idempotencyKey: `integration-idempotency:${callId}`,
    signal: new AbortController().signal,
    metadata: {},
  };
}

async function runTwice(callId: string, execute: () => Promise<unknown>) {
  const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
  const request = {
    name: "integration",
    args: {},
    context: context(callId),
    exclusive: false,
    onStarted: async () => {},
    execute,
  } as const;
  return [await controller.execute(request), await controller.execute(request)];
}

describe("integration idempotency outcomes", () => {
  it("releases every certified failed claim regardless of retryability", async () => {
    for (const [callId, error] of [
      ["permanent", new IntegrationExecutionError("api_rejected")],
      ["transient", new IntegrationTransientReadError()],
    ] as const) {
      const execute = vi.fn(async () => {
        throw error;
      });
      const outcomes = await runTwice(callId, execute);
      expect(execute).toHaveBeenCalledTimes(2);
      expect(outcomes).toEqual([
        { status: "failed", error: expect.objectContaining({ outcome: "failed" }) },
        { status: "failed", error: expect.objectContaining({ outcome: "failed" }) },
      ]);
    }
  });

  it("retains unknown outcomes and completed results", async () => {
    const unknownExecute = vi.fn(async () => {
      throw new IntegrationTransportError("TOOL_EXECUTION_FAILED", "github_mutation_unknown");
    });
    const unknown = await runTwice("unknown", unknownExecute);
    expect(unknownExecute).toHaveBeenCalledTimes(1);
    expect(unknown[0]).toMatchObject({ status: "failed", error: { outcome: "unknown" } });
    expect(unknown[1]).toEqual(unknown[0]);

    const completedExecute = vi.fn().mockResolvedValue({ ok: true });
    const completed = await runTwice("completed", completedExecute);
    expect(completedExecute).toHaveBeenCalledTimes(1);
    expect(completed).toEqual([
      { status: "completed", result: { ok: true } },
      { status: "completed", result: { ok: true } },
    ]);
  });
});
