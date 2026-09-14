import { describe, expect, it } from "vitest";
import * as z from "zod";

import { InMemoryBackend } from "@/backends/in-memory";
import { EventType } from "@/events/types";
import {
  Kaji,
  MissingToolIdentityError,
  ToolExecutionError,
  ToolPolicy,
  capability,
  capabilityResult,
} from "@/index";
import { isCapabilityResult } from "@/capabilities/result";

describe("Kaji.execute", () => {
  it("round-trips a capabilityResult through executeBatch", async () => {
    const cap = capability({
      name: "kaji_test_round_trip",
      description: "Returns a pre-built CapabilityResult.",
      input: z.object({}),
      risk: "read",
      execute: async () => capabilityResult({ foo: "bar" }),
    });

    const result = await Kaji.execute({
      capability: cap,
      input: {},
      principal: "test-principal",
    });

    expect(isCapabilityResult(result)).toBe(true);
    expect(result).toEqual(result); // reference equality for pre-wrapped results
    expect(result.value).toEqual({ foo: "bar" });
  });

  it("dispatches through the planner and journals the request event", async () => {
    const backend = new InMemoryBackend();
    const sessionId = "kaji_test_planner_dispatch";
    const cap = capability({
      name: "kaji_test_planner_dispatch",
      description: "Confirms planner-mediated dispatch.",
      input: z.object({}),
      risk: "read",
      execute: async () => ({ ok: true }),
    });

    await Kaji.execute({
      capability: cap,
      input: {},
      principal: "test-principal",
      backend,
      sessionId,
    });

    const events = await backend.store.getEvents(sessionId);
    expect(events.map((event) => event.type)).toContain(EventType.TOOL_CALL_REQUESTED);
  });

  it("deduplicates identical retries by session and capability", async () => {
    const backend = new InMemoryBackend();
    const sessionId = "kaji_test_retry";
    let executions = 0;
    const cap = capability({
      name: "kaji_test_retry",
      description: "Counts executions for retry identity checks.",
      input: z.object({ value: z.string() }),
      risk: "read",
      execute: async (input) => {
        executions += 1;
        return { value: input.value, execution: executions };
      },
    });

    const first = await Kaji.execute({
      capability: cap,
      input: { value: "same" },
      principal: "test-principal",
      backend,
      sessionId,
    });
    const retry = await Kaji.execute({
      capability: cap,
      input: { value: "same" },
      principal: "test-principal",
      backend,
      sessionId,
    });

    expect(executions).toBe(1);
    expect(retry).toEqual(first);
    await expect(
      Kaji.execute({
        capability: cap,
        input: { value: "changed" },
        principal: "test-principal",
        backend,
        sessionId,
      }),
    ).rejects.toMatchObject({ error_code: "IDEMPOTENCY_CONFLICT" });

    const otherSession = await Kaji.execute({
      capability: cap,
      input: { value: "same" },
      principal: "test-principal",
      backend,
      sessionId: "kaji_test_retry_other",
    });
    expect(executions).toBe(2);
    expect(otherSession.value).toEqual({ value: "same", execution: 2 });
  });

  it("wraps a plain JSON result with capabilityResult", async () => {
    const cap = capability({
      name: "kaji_test_plain_wrap",
      description: "Returns plain JSON that Kaji.execute must wrap.",
      input: z.object({}),
      risk: "read",
      execute: async () => ({ foo: "bar" }),
    });

    const result = await Kaji.execute({
      capability: cap,
      input: {},
      principal: "test-principal",
    });

    expect(isCapabilityResult(result)).toBe(true);
    expect(result.value).toEqual({ foo: "bar" });
  });

  it("fails closed when principal is absent", async () => {
    const cap = capability({
      name: "kaji_test_no_principal",
      description: "Must never run.",
      input: z.object({}),
      risk: "read",
      execute: async () => ({}),
    });

    await expect(
      Kaji.execute({
        capability: cap,
        input: {},
        // principal deliberately omitted — normalizePrincipalId throws fail-closed
        principal: undefined as unknown as string,
      }),
    ).rejects.toThrow(MissingToolIdentityError);
  });

  it("rejects structured principal values at runtime", async () => {
    const cap = capability({
      name: "kaji_test_structured_principal_rejected",
      description: "Must never run with a structured principal.",
      input: z.object({}),
      risk: "read",
      execute: async () => ({ ok: true }),
    });

    await expect(
      Kaji.execute({
        capability: cap,
        input: {},
        principal: { id: "structured-user" } as unknown as string,
      }),
    ).rejects.toThrow(MissingToolIdentityError);
  });

  it("fails closed when approval is required but rejected", async () => {
    const cap = capability({
      name: "kaji_test_approval_rejected",
      description: "Destructive capability requiring approval.",
      input: z.object({}),
      risk: "destructive",
      execute: async () => ({ ok: true }),
    });

    await expect(
      Kaji.execute({
        capability: cap,
        input: {},
        principal: "test-principal",
        policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
        approvalHandler: {
          async request() {
            return { granted: false, code: "rejected", reason: "blocked" };
          },
        },
      }),
    ).rejects.toThrow(ToolExecutionError);

    // Verify the specific error code
    try {
      await Kaji.execute({
        capability: cap,
        input: {},
        principal: "test-principal",
        policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
        approvalHandler: {
          async request() {
            return { granted: false, code: "rejected", reason: "blocked" };
          },
        },
      });
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ToolExecutionError);
      expect((e as ToolExecutionError).error_code).toBe("APPROVAL_REJECTED");
    }
  });

  it("fails closed when policy denies the tool", async () => {
    const cap = capability({
      name: "kaji_test_denied",
      description: "Capability that policy will block.",
      input: z.object({}),
      risk: "read",
      execute: async () => ({ ok: true }),
    });

    await expect(
      Kaji.execute({
        capability: cap,
        input: {},
        principal: "test-principal",
        policy: new ToolPolicy({ allowed: new Set<string>() }), // deny-all allowlist
      }),
    ).rejects.toThrow(ToolExecutionError);

    // Verify the specific error code
    try {
      await Kaji.execute({
        capability: cap,
        input: {},
        principal: "test-principal",
        policy: new ToolPolicy({ allowed: new Set<string>() }),
      });
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ToolExecutionError);
      expect((e as ToolExecutionError).error_code).toBe("TOOL_NOT_ALLOWED");
    }
  });

  it("passes metadata through to the execution context", async () => {
    const cap = capability({
      name: "kaji_test_metadata",
      description: "Echoes received principal + metadata.",
      input: z.object({}),
      risk: "read",
      execute: async (_input, ctx) => ({
        principalId: ctx.principalId,
        metadata: ctx.metadata,
      }),
    });

    const result = await Kaji.execute({
      capability: cap,
      input: {},
      principal: "test-principal",
      metadata: { client: "kaji-test" },
    });

    expect(isCapabilityResult(result)).toBe(true);
    expect(result.value).toEqual({
      principalId: "test-principal",
      metadata: { client: "kaji-test" },
    });
  });
});
