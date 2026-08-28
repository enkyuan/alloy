import { describe, it, expect, vi } from "vitest";
import { ToolPlanner, bindEmitterToCommitter } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { EventType } from "@/events/types";
import { InMemoryEventStore } from "@/events/store";
import { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import type { ApprovalRequestContext } from "@/runtime/approval/types";
import type { ToolCall } from "@/providers/base";
import { InMemoryEventCommitter } from "@/events/committer";
import { UnclassifiedToolRiskError, UnknownToolError, type ToolSpec } from "@/tools/registry";

class MalformedPlannerReadStore extends InMemoryEventStore {
  constructor(private readonly missingField: string) {
    super();
  }

  override async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<Array<ReturnType<typeof StoredKajiEvent.parse>>> {
    const events = await super.getEvents(sessionId, options);
    return events.map((event) => {
      const row = structuredClone(event) as Record<string, unknown>;
      delete row[this.missingField];
      return row as ReturnType<typeof StoredKajiEvent.parse>;
    });
  }
}

const TURN_CONTEXT = {
  principalId: "test",
  requestId: "request",
  traceId: "trace",
};

function specsFor(...names: string[]): Map<string, ToolSpec> {
  return new Map(
    names.map((name) => [name, { name, description: name, parameters: {}, risk: "read" }]),
  );
}

function executePlanner(
  planner: ToolPlanner,
  sessionId: Parameters<ToolPlanner["executeBatch"]>[0],
  calls: Parameters<ToolPlanner["executeBatch"]>[1],
  emit: Parameters<ToolPlanner["executeBatch"]>[2],
  turnId = "test-turn",
) {
  return planner.executeBatch(sessionId, calls, emit, turnId, TURN_CONTEXT);
}

function sequencedEmitter(
  onEvent: (
    event: Parameters<ToolPlanner["executeBatch"]>[2] extends (event: infer T) => unknown
      ? T
      : never,
  ) => void,
) {
  let sequence = 0;
  return async (event: Parameters<typeof onEvent>[0]) => {
    onEvent(event);
    return StoredKajiEvent.parse({ ...event, sequence: ++sequence });
  };
}

describe("ToolPlanner", () => {
  it("exposes batch terminology only", () => {
    const planner = new ToolPlanner({ executor: vi.fn(), specs: specsFor("search") });
    expect(typeof planner.executeBatch).toBe("function");
    expect("executeScatterGather" in planner).toBe(false);
  });

  it("emits lifecycle events on success", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });

    const planner = new ToolPlanner({ executor, specs: specsFor("search") });
    await executePlanner(
      planner,
      "sess-1",
      [{ id: "call-1", name: "search", arguments: { q: "test" } }],
      async (e) => {
        emitted.push(e);
      },
    );

    const types = emitted.map((e) => e.type);
    expect(types).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_STARTED,
      EventType.TOOL_CALL_COMPLETED,
    ]);
  });

  it("emits TOOL_CALL_FAILED on executor error", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockRejectedValue(new Error("tool exploded"));

    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const planner = new ToolPlanner({ executor, specs: specsFor("broken") });
    const results = await executePlanner(
      planner,
      "sess-1",
      [{ id: "call-2", name: "broken", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(results[0]).toMatchObject({
      error: "Tool execution failed with an unknown outcome",
      error_code: "TOOL_EXECUTION_FAILED",
      retryable: false,
      outcome: "unknown",
    });
    expect(emitted.find((e) => e.type === EventType.TOOL_CALL_FAILED)).toMatchObject({
      error: "Tool execution failed with an unknown outcome",
      error_code: "TOOL_EXECUTION_FAILED",
      retryable: false,
      outcome: "unknown",
    });
    expect(JSON.stringify({ emitted, results })).not.toContain("tool exploded");
    expect(JSON.stringify(logged.mock.calls)).not.toContain("tool exploded");
    expect(logged).toHaveBeenCalledWith("[kaji] internal error (Error; details redacted)");
    logged.mockRestore();
  });

  it("rejects non-object arguments before executor", async () => {
    for (const badArgs of [[], "not-object", null]) {
      const emitted: any[] = [];
      const executor = vi.fn().mockResolvedValue({ ok: true });
      const planner = new ToolPlanner({ executor, specs: specsFor("search") });

      const results = await executePlanner(
        planner,
        "sess-bad-args",
        [{ id: "bad-args", name: "search", arguments: badArgs as any }],
        async (e) => {
          emitted.push(e);
        },
      );

      expect(executor).not.toHaveBeenCalled();
      expect(emitted.map((e) => e.type)).toEqual([
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
      ]);
      expect(results[0]).toHaveProperty("error");
      expect((results[0] as { error: string }).error).toContain("Invalid tool arguments");
      expect((results[0] as { error: string }).error).toContain("arguments must be an object");
      expect(results[0]).toMatchObject({
        error_code: "INVALID_TOOL_ARGUMENTS",
        error_path: "/",
        retryable: false,
        outcome: "not_started",
      });
    }
  });

  it("normalizes oversize arguments before persistence", async () => {
    const secret = "sk-oversize-provider-argument";
    const emitted: any[] = [];
    const executor = vi.fn();
    const planner = new ToolPlanner({ executor, specs: specsFor("search") });

    const results = await executePlanner(
      planner,
      "oversize",
      [{ id: "oversize", name: "search", arguments: { value: secret + "x".repeat(64 * 1024) } }],
      async (event) => {
        emitted.push(event);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    expect(emitted.map(({ type }) => type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(emitted[0].tool_args).toEqual({ __parse_error: "payload too large" });
    expect(results).toEqual([
      {
        id: "oversize",
        name: "search",
        error: "Invalid tool arguments: serialized arguments exceed 65536 bytes",
        error_code: "INVALID_TOOL_ARGUMENTS",
        error_path: "/",
        retryable: false,
        outcome: "not_started",
      },
    ]);
    expect(JSON.stringify({ emitted, results })).not.toContain(secret);
  });

  it("redacts provider parse-error details before recording validation failure", async () => {
    const emitted: any[] = [];
    const executor = vi.fn();
    const planner = new ToolPlanner({ executor, specs: specsFor("search") });
    const secret = "sk-secret-value-that-must-not-appear";

    const results = await executePlanner(
      planner,
      "sess-parse-error",
      [
        {
          id: "parse-error",
          name: "search",
          arguments: { __parse_error: `invalid JSON near ${secret}` },
        },
      ],
      async (event) => {
        emitted.push(event);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    expect(emitted.map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(emitted[0].tool_args).toEqual({ __parse_error: "invalid JSON" });
    expect(results[0]).toMatchObject({
      error: "Invalid tool arguments: arguments were not valid JSON",
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/",
      retryable: false,
      outcome: "not_started",
    });
    expect(JSON.stringify({ emitted, results })).not.toContain(secret);
  });

  it("generates a call ID when none is provided", async () => {
    const emitted: any[] = [];
    const planner = new ToolPlanner({
      executor: vi.fn().mockResolvedValue("ok"),
      specs: specsFor("search"),
    });
    await executePlanner(planner, "sess-1", [{ name: "search", arguments: {} }], async (e) => {
      emitted.push(e);
    });
    const started = emitted.find((e) => e.type === EventType.TOOL_CALL_STARTED);
    expect(started?.tool_call_id).toBeTruthy();
  });

  it("includes catalog name metadata when available", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const specs = new Map([
      [
        "weather_getWeather",
        {
          name: "weather_getWeather",
          catalogName: "weather.getWeather",
          description: "weather",
          parameters: {},
          risk: "read" as const,
        },
      ],
    ]);

    const planner = new ToolPlanner({ executor, specs });
    await executePlanner(
      planner,
      "sess-catalog",
      [{ id: "cat-1", name: "weather_getWeather", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(emitted.every((e) => e.metadata.catalog_name === "weather.getWeather")).toBe(true);
  });

  it("approval approved proceeds to execution", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const requestApproval = vi.fn().mockResolvedValue({
      granted: true as const,
      code: "approved" as const,
    });
    const approvalHandler = { request: requestApproval };

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);
    const planner = new ToolPlanner({
      executor,
      policy,
      approvalHandler,
      approvalCommitter,
      specs,
    });

    const results = await executePlanner(
      planner,
      "sess-approval",
      [{ id: "c1", name: "nuke", arguments: {} }],
      bindEmitterToCommitter(async (event) => {
        emitted.push(event);
        return approvalCommitter.commit(event);
      }, approvalCommitter),
    );

    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REQUESTED);
    expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(results[0]).toHaveProperty("result", { ok: true });
  });

  it("isolates execution arguments from approval mutations", async () => {
    const original = { nested: { value: "validated" } };
    const executor = vi.fn(async (_name, args) => ({ value: (args.nested as any).value }));
    const requestApproval = vi.fn(async (_call: ToolCall, context: ApprovalRequestContext) => {
      (context.arguments.nested as any).value = "approval-mutated";
      return { granted: true as const, code: "approved" as const };
    });
    const approvalHandler = { request: requestApproval };
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const specs = new Map([
      [
        "nuke",
        {
          name: "nuke",
          description: "nuke",
          risk: "destructive" as const,
          parameters: {
            type: "object",
            required: ["nested"],
            properties: {
              nested: {
                type: "object",
                required: ["value"],
                properties: { value: { const: "validated" } },
              },
            },
          },
        },
      ],
    ]);
    const planner = new ToolPlanner({
      executor,
      policy,
      approvalHandler,
      approvalCommitter,
      specs,
    });

    const results = await executePlanner(
      planner,
      "sess-isolation",
      [{ id: "c-isolation", name: "nuke", arguments: original }],
      bindEmitterToCommitter((event) => approvalCommitter.commit(event), approvalCommitter),
    );

    expect(results[0]).toHaveProperty("result", { value: "validated" });
    expect(executor).toHaveBeenCalledWith(
      "nuke",
      { nested: { value: "validated" } },
      expect.objectContaining({ principalId: "test" }),
    );
    expect(requestApproval).toHaveBeenCalledOnce();
    expect(original).toEqual({ nested: { value: "validated" } });
  });

  it("emits exactly one approval request when EventApprovalHandler publishes request events", async () => {
    const store = new InMemoryEventStore();
    const sessionId = "sess-event-handler-approval";
    const turnId = "turn-event-handler-approval";
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const committer = new InMemoryEventCommitter(store);
    const approvalHandler = new EventApprovalHandler();
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);

    const observed = committer.subscribe(sessionId);
    const approveRequest = (async () => {
      for await (const event of observed) {
        if (event.type === EventType.TOOL_APPROVAL_REQUESTED && event.tool_call_id === "c-typed") {
          await committer.commit(
            KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_APPROVED,
              session_id: sessionId,
              turn_id: turnId,
              tool_name: "nuke",
              tool_call_id: "c-typed",
            }),
          );
          return;
        }
      }
    })();

    const planner = new ToolPlanner({
      executor,
      policy,
      approvalHandler,
      approvalCommitter: committer,
      specs,
    });
    const results = await executePlanner(
      planner,
      sessionId,
      [{ id: "c-typed", name: "nuke", arguments: {} }],
      bindEmitterToCommitter((event) => committer.commit(event), committer),
      turnId,
    );
    await approveRequest;

    const events = await store.getEvents(sessionId);
    expect(events.filter((e) => e.type === EventType.TOOL_APPROVAL_REQUESTED)).toHaveLength(1);
    expect(events.map((e) => e.type)).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(events.every((event) => event.turn_id === turnId)).toBe(true);
    expect(results[0]).toHaveProperty("result", { ok: true });
  });

  it.each(["id", "version", "timestamp"])(
    "canonically validates authoritative approval rows missing %s",
    async (missingField) => {
      const store = new MalformedPlannerReadStore(missingField);
      const committer = new InMemoryEventCommitter(store);
      const executor = vi.fn().mockResolvedValue({ ok: true });
      const planner = new ToolPlanner({
        executor,
        policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
        approvalHandler: {
          request: vi.fn(async () => ({ granted: true as const, code: "approved" as const })),
        },
        approvalCommitter: committer,
        specs: new Map([
          [
            "ship",
            {
              name: "ship",
              description: "ship",
              parameters: {},
              risk: "destructive" as const,
            },
          ],
        ]),
      });

      let rejected: unknown;
      try {
        await executePlanner(
          planner,
          "malformed-approval",
          [{ id: "call", name: "ship", arguments: {} }],
          bindEmitterToCommitter((event) => committer.commit(event), committer),
        );
      } catch (error) {
        rejected = error;
      }

      expect(rejected).toBeInstanceOf(AggregateError);
      expect((rejected as AggregateError).errors[0]).toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${missingField}`,
      });
      expect(executor).not.toHaveBeenCalled();
    },
  );

  it("fails closed before invoking an event approval handler without the runtime committer", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const approvalHandler = new EventApprovalHandler();
    const request = vi.spyOn(approvalHandler, "request");
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);
    const planner = new ToolPlanner({
      executor,
      policy,
      approvalHandler,
      specs,
    });

    const results = await planner.executeBatch(
      "sess-missing-turn",
      [{ id: "c-missing-turn", name: "nuke", arguments: {} }],
      async (event) => {
        return committer.commit(event);
      },
      "turn-missing-committer",
      TURN_CONTEXT,
    );

    expect(request).not.toHaveBeenCalled();
    expect(executor).not.toHaveBeenCalled();
    expect(results[0]).toMatchObject({
      error: "Tool approval unavailable",
      error_code: "APPROVAL_UNAVAILABLE",
      outcome: "not_started",
    });
    const events = await store.getEvents("sess-missing-turn");
    expect(events.some((event) => event.type === EventType.TOOL_APPROVAL_REQUESTED)).toBe(true);
    expect(events.some((event) => event.type === EventType.TOOL_APPROVAL_REJECTED)).toBe(true);
    expect(events.some((event) => event.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });

  it("approval rejected skips execution", async () => {
    const emitted: any[] = [];
    const executor = vi.fn();
    const approvalHandler = {
      request: vi.fn().mockResolvedValue({
        granted: false as const,
        code: "rejected" as const,
        reason: "Rejected by test policy",
      }),
    };

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const specs = new Map([
      [
        "charge",
        {
          name: "charge",
          description: "charge card",
          parameters: {},
          risk: "destructive" as const,
        },
      ],
    ]);
    const planner = new ToolPlanner({
      executor,
      policy,
      approvalHandler,
      approvalCommitter,
      specs,
    });

    const results = await executePlanner(
      planner,
      "sess-reject",
      [{ id: "c2", name: "charge", arguments: {} }],
      bindEmitterToCommitter(async (event) => {
        emitted.push(event);
        return approvalCommitter.commit(event);
      }, approvalCommitter),
    );

    expect(executor).not.toHaveBeenCalled();
    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REQUESTED);
    expect(types).toContain(EventType.TOOL_APPROVAL_REJECTED);
    expect(types).not.toContain(EventType.TOOL_CALL_STARTED);
    expect(results[0]).toHaveProperty("error");
  });

  it("deny-list blocks execution before TOOL_CALL_STARTED", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const policy = new ToolPolicy({ denied: new Set(["blocked"]) });
    const planner = new ToolPlanner({ executor, policy, specs: specsFor("blocked") });

    const results = await executePlanner(
      planner,
      "sess-deny",
      [{ id: "c-deny", name: "blocked", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    const types = emitted.map((e) => e.type);
    expect(types).toEqual([EventType.TOOL_CALL_REQUESTED, EventType.TOOL_CALL_FAILED]);
    expect(results[0]).toMatchObject({
      error: "Tool not permitted",
      error_code: "TOOL_NOT_ALLOWED",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("allow-list permits only listed tools", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const policy = new ToolPolicy({ allowed: new Set(["allowed_tool"]) });
    const specs = new Map([
      [
        "allowed_tool",
        { name: "allowed_tool", description: "allowed", parameters: {}, risk: "read" as const },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    await executePlanner(
      planner,
      "sess-allow",
      [{ id: "c-allow", name: "allowed_tool", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(executor).toHaveBeenCalledOnce();
    expect(emitted.map((e) => e.type)).toContain(EventType.TOOL_CALL_COMPLETED);
  });

  it("allow-list accepts catalog name aliases", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const policy = new ToolPolicy({ allowed: new Set(["weather.getWeather"]) });
    const specs = new Map([
      [
        "weather_getWeather",
        {
          name: "weather_getWeather",
          catalogName: "weather.getWeather",
          description: "weather",
          parameters: {},
          risk: "read" as const,
        },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    await executePlanner(
      planner,
      "sess-allow-catalog",
      [{ id: "catalog-allow", name: "weather_getWeather", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(executor).toHaveBeenCalledOnce();
    expect(emitted.map((e) => e.type)).toContain(EventType.TOOL_CALL_COMPLETED);
  });

  it("deny-list blocks catalog name aliases", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const policy = new ToolPolicy({ denied: new Set(["weather.getWeather"]) });
    const specs = new Map([
      [
        "weather_getWeather",
        {
          name: "weather_getWeather",
          catalogName: "weather.getWeather",
          description: "weather",
          parameters: {},
          risk: "read" as const,
        },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    const results = await executePlanner(
      planner,
      "sess-deny-catalog",
      [{ id: "catalog-deny", name: "weather_getWeather", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    expect(emitted.map((e) => e.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(results[0]).toMatchObject({
      error: "Tool not permitted",
      error_code: "TOOL_NOT_ALLOWED",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("read risk skips a destructive approval gate", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["search", { name: "search", description: "search", parameters: {}, risk: "read" as const }],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    await executePlanner(
      planner,
      "sess-no-approval",
      [{ id: "c3", name: "search", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    const types = emitted.map((e) => e.type);
    expect(types).not.toContain(EventType.TOOL_APPROVAL_REQUESTED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
  });

  it("a broken emit for one call does not drop a sibling call's result", async () => {
    // A request-event failure for one prepared call must be aggregated only
    // after the remaining calls are processed, preserving completed outcomes.
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ done: true });

    const planner = new ToolPlanner({ executor, specs: specsFor("search") });
    const emit = vi.fn(async (e: any) => {
      if (e.tool_call_id === "broken" && e.type === EventType.TOOL_CALL_REQUESTED) {
        throw new Error("store.append failed");
      }
      emitted.push(e);
    });

    await expect(
      executePlanner(
        planner,
        "sess-partial-failure",
        [
          { id: "ok", name: "search", arguments: {} },
          { id: "broken", name: "search", arguments: {} },
        ],
        emit,
      ),
    ).rejects.toThrow(/1 of 2 tool call\(s\) failed/);

    // "ok" ran to completion and was recorded even though "broken" failed
    // to even announce itself.
    expect(executor).toHaveBeenCalledTimes(1);
    expect(executor).toHaveBeenCalledWith(
      "search",
      {},
      expect.objectContaining({ principalId: "test" }),
    );
    expect(
      emitted.some((e) => e.tool_call_id === "ok" && e.type === EventType.TOOL_CALL_COMPLETED),
    ).toBe(true);
  });

  it("rejects empty and duplicate call ids for the whole batch before emission", async () => {
    for (const calls of [
      [
        { id: "ok", name: "search", arguments: {} },
        { id: "   ", name: "search", arguments: {} },
      ],
      [
        { id: "duplicate", name: "search", arguments: {} },
        { id: "duplicate", name: "search", arguments: {} },
      ],
    ]) {
      const emit = vi.fn(async () => {});
      const executor = vi.fn();
      const planner = new ToolPlanner({ executor, specs: specsFor("search") });

      await expect(executePlanner(planner, "session", calls, emit)).rejects.toThrow();
      expect(emit).not.toHaveBeenCalled();
      expect(executor).not.toHaveBeenCalled();
    }
  });

  it("rejects duplicate generated ids before emission", async () => {
    const emit = vi.fn(async () => {});
    const planner = new ToolPlanner({
      executor: vi.fn(),
      specs: specsFor("search"),
      idFactory: { next: () => "duplicate" },
    });

    await expect(
      executePlanner(
        planner,
        "session",
        [
          { name: "search", arguments: {} },
          { name: "search", arguments: {} },
        ],
        emit,
      ),
    ).rejects.toThrow();
    expect(emit).not.toHaveBeenCalled();
  });

  it("requires every direct-planner call to have a classified spec before emission", async () => {
    const emit = vi.fn(async () => {});
    const executor = vi.fn();
    const missing = new ToolPlanner({ executor, specs: specsFor("known") });

    await expect(
      executePlanner(
        missing,
        "session",
        [
          { id: "known", name: "known", arguments: {} },
          { id: "missing", name: "missing", arguments: {} },
        ],
        emit,
      ),
    ).rejects.toBeInstanceOf(UnknownToolError);
    expect(emit).not.toHaveBeenCalled();
    expect(executor).not.toHaveBeenCalled();

    const unclassifiedSpec = {
      name: "disabled",
      description: "disabled",
      parameters: {},
      enabled: false,
    } as ToolSpec;
    const unclassified = new ToolPlanner({
      executor,
      specs: new Map([[unclassifiedSpec.name, unclassifiedSpec]]),
    });
    await expect(
      executePlanner(
        unclassified,
        "session",
        [{ id: "disabled", name: "disabled", arguments: {} }],
        emit,
      ),
    ).rejects.toBeInstanceOf(UnclassifiedToolRiskError);
    expect(emit).not.toHaveBeenCalled();
  });

  it("rejects classified disabled specs before lifecycle emission", async () => {
    const emit = vi.fn(async () => {});
    const executor = vi.fn();
    const spec: ToolSpec = {
      name: "disabled",
      description: "disabled",
      parameters: {},
      risk: "read",
      enabled: false,
    };
    const planner = new ToolPlanner({ executor, specs: new Map([[spec.name, spec]]) });

    await expect(
      executePlanner(
        planner,
        "session",
        [{ id: "disabled", name: "disabled", arguments: {} }],
        emit,
      ),
    ).rejects.toThrow();
    expect(emit).not.toHaveBeenCalled();
    expect(executor).not.toHaveBeenCalled();
  });

  it("closes approval-handler exceptions without leaking their cause", async () => {
    const emitted: any[] = [];
    const executor = vi.fn();
    const secret = "sk-approval-secret";
    const approvalHandler = { request: vi.fn().mockRejectedValue(new Error(secret)) };
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const planner = new ToolPlanner({
      executor,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["read"]) }),
      approvalHandler,
      approvalCommitter,
      specs: specsFor("search"),
    });
    const log = vi.spyOn(console, "error").mockImplementation(() => {});

    const results = await executePlanner(
      planner,
      "session",
      [{ id: "call", name: "search", arguments: {} }],
      bindEmitterToCommitter(async (event) => {
        emitted.push(event);
        return approvalCommitter.commit(event);
      }, approvalCommitter),
    );

    expect(executor).not.toHaveBeenCalled();
    expect(emitted.map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_REJECTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(results[0]).toMatchObject({
      error: "Tool approval unavailable",
      error_code: "APPROVAL_UNAVAILABLE",
      retryable: false,
      outcome: "not_started",
    });
    expect(JSON.stringify({ emitted, results })).not.toContain(secret);
    expect(log).toHaveBeenCalled();
    log.mockRestore();
  });

  it("validates planner execution context before lifecycle emission", async () => {
    const planner = new ToolPlanner({ executor: vi.fn(), specs: specsFor("search") });
    const call = [{ id: "call", name: "search", arguments: {} }];
    const invalidInvocations: Array<(emit: (event: any) => Promise<void>) => Promise<unknown>> = [
      (emit) => planner.executeBatch(" ", call, emit, "turn", TURN_CONTEXT),
      (emit) => planner.executeBatch("session", call, emit, " ", TURN_CONTEXT),
      (emit) =>
        planner.executeBatch("session", call, emit, "turn", {
          ...TURN_CONTEXT,
          principalId: " ",
        }),
      (emit) =>
        planner.executeBatch("session", call, emit, "turn", {
          ...TURN_CONTEXT,
          requestId: " ",
        }),
      (emit) =>
        planner.executeBatch("session", call, emit, "turn", {
          ...TURN_CONTEXT,
          traceId: " ",
        }),
      (emit) =>
        planner.executeBatch("session", call, emit, "turn", {
          ...TURN_CONTEXT,
          deadlineMonotonicMs: Number.POSITIVE_INFINITY,
        }),
      (emit) =>
        planner.executeBatch("session", call, emit, "turn", TURN_CONTEXT, {
          aborted: false,
        } as AbortSignal),
    ];

    for (const invoke of invalidInvocations) {
      const emit = vi.fn(async () => {});
      await expect(invoke(emit)).rejects.toThrow();
      expect(emit).not.toHaveBeenCalled();
    }
  });

  it("no approval handler rejects by default (fail-safe)", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["admin"]) });
    const specs = new Map([
      [
        "add_user",
        { name: "add_user", description: "add user", parameters: {}, risk: "admin" as const },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    const results = await executePlanner(
      planner,
      "sess-no-handler",
      [{ id: "c4", name: "add_user", arguments: {} }],
      sequencedEmitter((e) => {
        emitted.push(e);
      }),
    );

    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REJECTED);
    expect(types).not.toContain(EventType.TOOL_CALL_STARTED);
    expect(results[0]).toHaveProperty("error");
  });
});
