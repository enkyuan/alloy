import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import {
  AgentBuilder,
  artifact,
  capability,
  capabilityResult,
  EventType,
  InMemoryEventStore,
  ToolPlanner,
  ToolPolicy,
  ToolRegistry,
  type ToolExecutionContext,
} from "@/index";
import { MockProvider } from "@/testing";

function context(): ToolExecutionContext {
  return {
    principalId: "principal",
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

describe("capability", () => {
  it("compiles into one ToolSpec and registers without a second execution path", async () => {
    const execute = vi.fn(async (input: { paymentId: string }, received: ToolExecutionContext) => ({
      paymentId: input.paymentId,
      principalId: received.principalId,
    }));
    const refund = capability({
      name: "payments.refund",
      description: "Refund a payment.",
      input: z.object({ paymentId: z.string() }),
      risk: "destructive",
      timeout_ms: 100,
      parallel_safe: true,
      metadata: { owner: "payments" },
      execute,
    });
    const registry = new ToolRegistry();
    refund.register(registry);

    expect(registry.listSpecs({ enabledOnly: false })).toEqual([
      expect.objectContaining({
        name: "payments.refund",
        risk: "destructive",
        timeout_ms: 100,
        parallel_safe: true,
      }),
    ]);
    expect(refund.metadata).toEqual({ owner: "payments" });
    await expect(registry.execute("payments.refund", {}, context())).rejects.toMatchObject({
      code: "INVALID_TOOL_ARGUMENTS",
    });
    await expect(
      registry.execute("payments.refund", { paymentId: "pay-1" }, context()),
    ).resolves.toEqual({
      paymentId: "pay-1",
      principalId: "principal",
    });
    expect(execute).toHaveBeenCalledOnce();
  });

  it("fails closed for an unknown risk when the shared registry validates its ToolSpec", () => {
    const invalid = capability({
      name: "bad.risk",
      description: "Bad risk.",
      input: z.object({}),
      risk: "unknown" as never,
      execute: async () => ({}),
    });
    expect(() => invalid.register(new ToolRegistry())).toThrow(
      expect.objectContaining({ code: "INVALID_TOOL_SCHEMA" }),
    );
  });

  it("preserves execution context and policy/approval semantics through AgentBuilder", async () => {
    const observed: ToolExecutionContext[] = [];
    const charge = capability({
      name: "payments.charge",
      description: "Charge a payment.",
      input: z.object({ amount: z.number().positive() }),
      risk: "destructive",
      execute: async (_input, received) => {
        observed.push(received);
        return capabilityResult({ charged: true }, [
          artifact("refund-1", "stripe/refund", "stripe://refunds/refund-1"),
        ]);
      },
    });
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ toolCall: { name: "payments.charge", args: { amount: 1 } } }))
      .capability(charge)
      .policy(new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }))
      .approvalHandler({
        async request() {
          return { granted: true, code: "approved" as const };
        },
      })
      .defaultContext({
        principalId: "principal-1",
        deadlineAtMs: Date.now() + 10_000,
        metadata: { requestSource: "capability-test" },
      })
      .build({ store });

    await runtime.send("capability-session", "charge");

    expect(observed).toHaveLength(1);
    expect(observed[0]).toMatchObject({
      principalId: "principal-1",
      sessionId: "capability-session",
      toolCallId: "mock-call-1",
      idempotencyKey: "capability-session:mock-call-1",
      metadata: { requestSource: "capability-test" },
    });
    expect(observed[0]!.turnId).not.toBe("");
    expect(observed[0]!.deadlineMonotonicMs).toEqual(expect.any(Number));
    expect(observed[0]!.signal).toBeInstanceOf(AbortSignal);
    const eventTypes = (await store.getEvents("capability-session")).map((event) => event.type);
    expect(eventTypes).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(eventTypes).toContain(EventType.ARTIFACT_EMITTED);
    expect(eventTypes).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(eventTypes.indexOf(EventType.ARTIFACT_EMITTED)).toBeLessThan(
      eventTypes.indexOf(EventType.TOOL_CALL_COMPLETED),
    );
  });

  it("preserves timeout, idempotency, and parallel-safe ToolSpec behavior", async () => {
    const timeout = capability({
      name: "timed.capability",
      description: "Times out.",
      input: z.object({}),
      risk: "read",
      timeout_ms: 1,
      execute: async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
        return { ok: true };
      },
    });
    const timeoutRegistry = new ToolRegistry();
    timeout.register(timeoutRegistry);
    const timeoutPlanner = new ToolPlanner({
      executor: (name, args, received) => timeoutRegistry.execute(name, args, received),
      specs: new Map(timeoutRegistry.listSpecs().map((spec) => [spec.name, spec])),
    });
    const timed = await timeoutPlanner.executeBatch(
      "timeout-session",
      [{ id: "timeout-call", name: "timed.capability", arguments: {} }],
      async () => {},
      "turn",
      { principalId: "principal" },
    );
    expect(timed[0]).toMatchObject({ error_code: "TOOL_TIMEOUT" });

    let calls = 0;
    const once = capability({
      name: "once.capability",
      description: "Runs once.",
      input: z.object({}),
      risk: "read",
      parallel_safe: true,
      execute: async () => ({ calls: ++calls }),
    });
    const registry = new ToolRegistry();
    once.register(registry);
    const planner = new ToolPlanner({
      executor: (name, args, received) => registry.execute(name, args, received),
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });
    const call = [{ id: "same-call", name: "once.capability", arguments: {} }];
    await planner.executeBatch("once-session", call, async () => {}, "turn-1", {
      principalId: "principal",
    });
    await planner.executeBatch("once-session", call, async () => {}, "turn-2", {
      principalId: "principal",
    });
    expect(calls).toBe(1);
  });

  it("uses the capability name for ToolPolicy decisions", async () => {
    const execute = vi.fn(async () => ({ ok: true }));
    const read = capability({
      name: "products.read",
      description: "Read products.",
      input: z.object({}),
      risk: "read",
      execute,
    });
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ toolCall: { name: "products.read", args: {} } }))
      .capability(read)
      .policy(new ToolPolicy({ denied: new Set(["products.read"]) }))
      .defaultContext({ principalId: "principal" })
      .build();

    await runtime.send("denied-capability", "read");

    expect(execute).not.toHaveBeenCalled();
  });
});
