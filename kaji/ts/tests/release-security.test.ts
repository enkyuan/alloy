import { describe, expect, it, vi } from "vitest";
import { inspect } from "node:util";

import { startSpan, type TraceSink } from "@/observability";
import { providerAPIErrorFromUnknown } from "@/providers/errors";
import { AgentBuilder } from "@/runtime/builder";
import { ToolExecutionController } from "@/tools/execution";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";

describe("release redaction boundaries", () => {
  it("redacts provider details from public exception strings", () => {
    const secret = "sk-provider-key-secret";
    const error = providerAPIErrorFromUnknown(
      "openai",
      new Error(`request failed with ${secret}`),
      "request",
    );

    expect(String(error)).toBe("ProviderAPIError: openai request failed");
    expect(String(error)).not.toContain(secret);
    expect(error.cause).toBeUndefined();
    expect(error.responseText).toBeUndefined();
    expect(inspect(error, { depth: 5 })).not.toContain(secret);
    expect(JSON.stringify(error)).not.toContain(secret);
  });

  it("redacts error details before handing them to trace sinks", () => {
    const recorded: unknown[] = [];
    const sink: TraceSink = {
      startSpan: () => ({
        setAttribute() {},
        recordError(error) {
          recorded.push(error);
        },
        end() {},
      }),
    };
    const secret = "sk-trace-secret";

    startSpan(sink, "kaji.turn").recordError(new Error(secret));

    expect(recorded).toHaveLength(1);
    expect(String(recorded[0])).toBe("Error: Error: details redacted");
    expect(String(recorded[0])).not.toContain(secret);
  });

  it("redacts provider, tool, and start-callback failures at the trace boundary", async () => {
    const recorded: unknown[] = [];
    const sink: TraceSink = {
      startSpan: () => ({
        setAttribute() {},
        recordError(error) {
          recorded.push(error);
        },
        end() {},
      }),
    };
    const providerFailure = new Error("sk-provider-runtime-secret");
    class FailingProvider {
      readonly providerFamily = "custom" as const;

      async generate(): Promise<never> {
        throw providerFailure;
      }

      // oxlint-disable-next-line require-yield -- the failure occurs when the stream is consumed.
      async *generateStream(): AsyncGenerator<never> {
        throw providerFailure;
      }
    }

    const runtime = new AgentBuilder().provider(new FailingProvider()).traceSink(sink).build();
    await expect(runtime.turn("hello")).rejects.toBe(providerFailure);

    const context = (toolCallId: string) => ({
      principalId: "principal",
      sessionId: `session-${toolCallId}`,
      turnId: "turn",
      requestId: "request",
      traceId: "trace",
      toolCallId,
      idempotencyKey: `session-${toolCallId}:${toolCallId}`,
      signal: new AbortController().signal,
      metadata: {},
    });
    const toolFailure = new Error("sk-tool-runtime-secret");
    const controller = new ToolExecutionController({ traceSink: sink });
    const failed = await controller.execute({
      name: "failing-tool",
      args: {},
      context: context("tool-failure"),
      exclusive: false,
      onStarted: async () => {},
      execute: async () => {
        throw toolFailure;
      },
    });
    expect(failed).toMatchObject({ status: "failed", error: { outcome: "unknown" } });
    if (failed.status !== "failed") throw new Error("expected a failed tool outcome");
    expect(failed.error.cause).toBeUndefined();
    expect(inspect(failed, { depth: 5 })).not.toContain(toolFailure.message);

    const startFailure = new Error("sk-start-callback-secret");
    await expect(
      controller.execute({
        name: "start-failure",
        args: {},
        context: context("start-failure"),
        exclusive: false,
        onStarted: async () => {
          throw startFailure;
        },
        execute: async () => ({ ok: true }),
      }),
    ).rejects.toBe(startFailure);

    const rendered = recorded.map(String).join(" ");
    expect(rendered).not.toContain(providerFailure.message);
    expect(rendered).not.toContain(toolFailure.message);
    expect(rendered).not.toContain(startFailure.message);
    expect(rendered).toContain("details redacted");
  });

  it("redacts late durable-claim cleanup failures", async () => {
    const secret = "sk-late-cleanup-secret";
    const backing = new InMemoryToolIdempotencyLedger();
    let releaseClaim!: () => void;
    const gate = new Promise<void>((resolve) => {
      releaseClaim = resolve;
    });
    let entered!: () => void;
    const claimEntered = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let attempted!: () => void;
    const cleanupAttempted = new Promise<void>((resolve) => {
      attempted = resolve;
    });
    const ledger: ToolIdempotencyLedger = {
      async claim(...args) {
        entered();
        await gate;
        return backing.claim(...args);
      },
      complete: (...args) => backing.complete(...args),
      async retryableFailure() {
        attempted();
        throw new Error(secret);
      },
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
    };
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const controller = new ToolExecutionController({ ledger, limits: { timeoutMs: 1 } });
    const abort = new AbortController();
    const pending = controller.execute({
      name: "late-claim",
      args: {},
      context: {
        principalId: "principal",
        sessionId: "session",
        turnId: "turn",
        requestId: "request",
        traceId: "trace",
        toolCallId: "call",
        idempotencyKey: "session:call",
        signal: abort.signal,
        metadata: {},
      },
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({}),
    });

    await claimEntered;
    await expect(pending).resolves.toMatchObject({ status: "failed" });
    releaseClaim();
    await cleanupAttempted;
    await Promise.resolve();

    expect(JSON.stringify(logged.mock.calls)).not.toContain(secret);
    expect(logged).toHaveBeenCalledWith(
      "[kaji] late claim cleanup failed (Error; details redacted)",
    );
    logged.mockRestore();
  });
});
