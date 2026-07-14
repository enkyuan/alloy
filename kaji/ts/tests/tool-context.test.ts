import { describe, expect, it, vi } from "vitest";

import { EventType } from "@/events/types";
import type { Integrable } from "@/runtime/builder";
import { AgentBuilder } from "@/runtime/builder";
import { CancellationToken } from "@/runtime/cancellation";
import {
  MissingToolIdentityError,
  deadlineAfter,
  type ToolExecutionContext,
  type TurnContext,
} from "@/runtime/context";
import { MockProvider } from "@/providers/mock";
import { ToolPolicy } from "@/tools/policy";
import {
  ToolRegistry,
  ToolSchemaValidationError,
  UnclassifiedToolRiskError,
  type ToolHandler,
  type ToolSpec,
} from "@/index";

class CaptureIntegration implements Integrable {
  constructor(private readonly seen: ToolExecutionContext[]) {}

  register(registry: ToolRegistry): void {
    const spec: ToolSpec = {
      name: "capture",
      description: "Capture execution context",
      parameters: { type: "object" },
      risk: "read",
    };
    const handler: ToolHandler = async (_args, context) => {
      this.seen.push(context);
      await Promise.resolve();
      return { captured: true };
    };
    registry.register(spec, handler);
  }
}

describe("tool execution context", () => {
  it("converts durations once and rejects legacy or invalid public deadlines", async () => {
    const clock = { nowWallSeconds: () => 1_700_000_000, nowMonotonic: () => 10 };
    expect(deadlineAfter(2_500, clock)).toBe(1_700_000_002_500);
    for (const invalid of [true, "1", Number.NaN, Number.POSITIVE_INFINITY, -1]) {
      expect(() => deadlineAfter(invalid as never, clock)).toThrow(/finite non-negative/);
    }

    const runtime = new AgentBuilder().provider(new MockProvider({ reply: "unused" })).build();
    for (const context of [
      { deadlineMs: undefined },
      { deadlineMs: 1, deadlineAtMs: 2 },
      { deadlineAtMs: true },
      { deadlineAtMs: "1" },
      { deadlineAtMs: Number.NaN },
      { deadlineAtMs: Number.POSITIVE_INFINITY },
      { deadlineAtMs: -1 },
    ]) {
      await expect(
        runtime.turn("invalid", {
          sessionId: "invalid-deadline",
          context: context as unknown as TurnContext,
        }),
      ).rejects.toThrow();
    }
    expect(await runtime.history("invalid-deadline")).toEqual([]);
  });

  it("propagates and isolates concurrent principals", async () => {
    const seen: ToolExecutionContext[] = [];
    const metadataA = { tenant: { id: "a" } };
    const dbA = {};
    const tokenA = new CancellationToken();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new CaptureIntegration(seen))
      .build();
    const contextA: TurnContext = {
      principalId: "principal-a",
      requestId: "request-a",
      traceId: "trace-a",
      deadlineAtMs: deadlineAfter(30_000),
      db: dbA,
      metadata: metadataA,
    };
    const contextB: TurnContext = {
      principalId: "principal-b",
      requestId: "request-b",
      traceId: "trace-b",
      metadata: { tenant: { id: "b" } },
    };
    const pendingA = runtime.turn("capture", {
      sessionId: "session-a",
      cancellationToken: tokenA,
      context: contextA,
    });
    const pendingB = runtime.turn("capture", { sessionId: "session-b", context: contextB });
    metadataA.tenant.id = "mutated";
    const [resultA, resultB] = await Promise.all([pendingA, pendingB]);

    const bySession = new Map(seen.map((context) => [context.sessionId, context]));
    const capturedA = bySession.get("session-a")!;
    const capturedB = bySession.get("session-b")!;
    expect(capturedA.principalId).toBe("principal-a");
    expect(capturedB.principalId).toBe("principal-b");
    expect(capturedA.turnId).toBe(resultA.turnId);
    expect(capturedB.turnId).toBe(resultB.turnId);
    expect(capturedA.requestId).toBe("request-a");
    expect(capturedA.traceId).toBe("trace-a");
    expect(capturedA.toolCallId).toBe("mock-call-1");
    expect(capturedA.idempotencyKey).toBe("session-a:mock-call-1");
    expect(capturedA.signal).toBeInstanceOf(AbortSignal);
    expect(capturedA.signal.aborted).toBe(false);
    expect(capturedA.deadlineMonotonicMs).toBeGreaterThan(globalThis.performance.now());
    expect(capturedA.db).toBe(dbA);
    expect(capturedA.metadata).toEqual({ tenant: { id: "a" } });
    expect(Object.isFrozen(capturedA.metadata)).toBe(true);
    expect(Object.isFrozen(capturedA.metadata.tenant)).toBe(true);
    expect(() => {
      (capturedA.metadata.tenant as { id: string }).id = "escaped";
    }).toThrow();
    expect(capturedA.metadata).toEqual({ tenant: { id: "a" } });
  });

  it("normalizes principal identity and rejects whitespace-only identities", async () => {
    const seen: ToolExecutionContext[] = [];
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new CaptureIntegration(seen))
      .build();

    await runtime.turn("capture", {
      sessionId: "trimmed-principal",
      context: { principalId: "  principal  " },
    });
    expect(seen.at(-1)?.principalId).toBe("principal");

    await expect(
      runtime.turn("capture", {
        sessionId: "blank-principal",
        context: { principalId: "   " },
      }),
    ).rejects.toMatchObject({ code: "MISSING_TOOL_IDENTITY" });
    expect(seen).toHaveLength(1);
    expect(
      (await runtime.history("blank-principal")).some(
        (event) => event.type === EventType.TOOL_CALL_REQUESTED,
      ),
    ).toBe(false);
  });

  it("requires identity before approval or execution without poisoning replay", async () => {
    const seen: ToolExecutionContext[] = [];
    const requestApproval = vi.fn(async () => ({
      granted: true as const,
      code: "approved" as const,
    }));
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new CaptureIntegration(seen))
      .policy(new ToolPolicy({ requireApprovalFor: new Set(["read"]) }))
      .approvalHandler({ request: requestApproval })
      .build();

    await expect(runtime.turn("capture", { sessionId: "missing-principal" })).rejects.toMatchObject(
      {
        code: "MISSING_TOOL_IDENTITY",
      },
    );
    expect(requestApproval).not.toHaveBeenCalled();
    expect(seen).toEqual([]);
    const failedEvents = await runtime.history("missing-principal");
    expect(failedEvents.some((event) => event.type === EventType.TOOL_CALL_REQUESTED)).toBe(false);

    await runtime.turn("capture", {
      sessionId: "missing-principal",
      context: { principalId: "recovered" },
    });
    expect(seen.at(-1)?.principalId).toBe("recovered");
  });

  it("allows a no-tool turn to omit context", async () => {
    const runtime = new AgentBuilder().provider(new MockProvider({ reply: "ok" })).build();
    await expect(runtime.turn("hello", { sessionId: "no-tools" })).resolves.toMatchObject({
      text: "ok",
    });
  });

  it("uses explicit builder defaults and refreshes generated IDs", async () => {
    const seen: ToolExecutionContext[] = [];
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new CaptureIntegration(seen))
      .defaultContext({ principalId: "single-tenant" })
      .build();

    await runtime.turn("capture", { sessionId: "default-a" });
    await runtime.turn("capture", { sessionId: "default-b" });

    expect(seen.map((context) => context.principalId)).toEqual(["single-tenant", "single-tenant"]);
    expect(seen[0]!.requestId).not.toBe(seen[1]!.requestId);
    expect(seen[0]!.traceId).not.toBe(seen[1]!.traceId);
  });

  it("requires a known risk for enabled tools", () => {
    expect(() =>
      new ToolRegistry().register(
        { name: "missing", description: "missing", parameters: {} } as ToolSpec,
        async () => ({}),
      ),
    ).toThrow(UnclassifiedToolRiskError);
    expect(() =>
      new ToolRegistry().register(
        {
          name: "unknown",
          description: "unknown",
          parameters: {},
          risk: "typo",
        } as unknown as ToolSpec,
        async () => ({}),
      ),
    ).toThrow(ToolSchemaValidationError);
  });

  it("exports the public context declarations", () => {
    const context: TurnContext = { principalId: "principal" };
    expect(context.principalId).toBe("principal");
    expect(MissingToolIdentityError.name).toBe("MissingToolIdentityError");
  });
});
