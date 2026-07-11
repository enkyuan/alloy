import { describe, it, expect, vi } from "vitest";
import { ToolPlanner } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { EventType } from "@/events/types";
import { InMemoryEventStore } from "@/events/store";
import { KajiEvent } from "@/events/schemas";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import { InMemoryEventCommitter } from "@/events/committer";

describe("ToolPlanner", () => {
  it("emits lifecycle events on success", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });

    const planner = new ToolPlanner({ executor });
    await planner.executeScatterGather(
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

    const planner = new ToolPlanner({ executor });
    const results = await planner.executeScatterGather(
      "sess-1",
      [{ id: "call-2", name: "broken", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(results[0]).toHaveProperty("error", "Error: tool exploded");
    expect(emitted.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });

  it("rejects non-object arguments before executor", async () => {
    for (const badArgs of [[], "not-object", null]) {
      const emitted: any[] = [];
      const executor = vi.fn().mockResolvedValue({ ok: true });
      const planner = new ToolPlanner({ executor });

      const results = await planner.executeScatterGather(
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

  it("redacts provider parse-error details before recording validation failure", async () => {
    const emitted: any[] = [];
    const executor = vi.fn();
    const planner = new ToolPlanner({ executor });
    const secret = "sk-secret-value-that-must-not-appear";

    const results = await planner.executeScatterGather(
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
    const planner = new ToolPlanner({ executor: vi.fn().mockResolvedValue("ok") });
    await planner.executeScatterGather("sess-1", [{ name: "search", arguments: {} }], async (e) => {
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
        },
      ],
    ]);

    const planner = new ToolPlanner({ executor, specs });
    await planner.executeScatterGather(
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
    const approvalHandler = vi.fn().mockResolvedValue(true);

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);
    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });

    const results = await planner.executeScatterGather(
      "sess-approval",
      [{ id: "c1", name: "nuke", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REQUESTED);
    expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(results[0]).toHaveProperty("result", { ok: true });
  });

  it("isolates execution arguments from event and approval mutations", async () => {
    const original = { nested: { value: "validated" } };
    const executor = vi.fn(async (_name, args) => ({ value: (args.nested as any).value }));
    const approvalHandler = vi.fn(async (_name, args: Record<string, unknown>) => {
      (args.nested as any).value = "approval-mutated";
      return true;
    });
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
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
    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });

    const results = await planner.executeScatterGather(
      "sess-isolation",
      [{ id: "c-isolation", name: "nuke", arguments: original }],
      async (event) => {
        if (
          event.type === EventType.TOOL_CALL_REQUESTED ||
          event.type === EventType.TOOL_APPROVAL_REQUESTED
        ) {
          (event.tool_args.nested as any).value = "event-mutated";
        }
      },
    );

    expect(results[0]).toHaveProperty("result", { value: "validated" });
    expect(executor).toHaveBeenCalledWith("nuke", { nested: { value: "validated" } });
    expect(approvalHandler).toHaveBeenCalledOnce();
    expect(original).toEqual({ nested: { value: "validated" } });
  });

  it("emits exactly one approval request when EventApprovalHandler publishes request events", async () => {
    const store = new InMemoryEventStore();
    const sessionId = "sess-event-handler-approval";
    const turnId = "turn-event-handler-approval";
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const committer = new InMemoryEventCommitter(store);
    const approvalHandler = new EventApprovalHandler(committer, { timeoutMs: 250 });
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

    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });
    const results = await planner.executeScatterGather(
      sessionId,
      [{ id: "c-typed", name: "nuke", arguments: {} }],
      async (e) => {
        await committer.commit(e);
      },
      turnId,
    );
    await approveRequest;

    const events = await store.getEvents(sessionId);
    expect(events.filter((e) => e.type === EventType.TOOL_APPROVAL_REQUESTED)).toHaveLength(1);
    expect(events.map((e) => e.type)).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(events.every((event) => event.turn_id === turnId)).toBe(true);
    expect(results[0]).toHaveProperty("result", { ok: true });
  });

  it("fails closed before invoking an event approval handler without a turn id", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const approvalHandler = new EventApprovalHandler(committer, { timeoutMs: 250 });
    const request = vi.spyOn(approvalHandler, "request");
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);
    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });

    const results = await planner.executeScatterGather(
      "sess-missing-turn",
      [{ id: "c-missing-turn", name: "nuke", arguments: {} }],
      async (event) => {
        await committer.commit(event);
      },
    );

    expect(request).not.toHaveBeenCalled();
    expect(executor).not.toHaveBeenCalled();
    expect(results[0]).toMatchObject({
      error: expect.stringContaining("non-empty turn identity"),
    });
    const events = await store.getEvents("sess-missing-turn");
    expect(events.some((event) => event.type === EventType.TOOL_APPROVAL_REQUESTED)).toBe(false);
    expect(events.some((event) => event.type === EventType.TOOL_APPROVAL_REJECTED)).toBe(true);
    expect(events.some((event) => event.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });

  it("approval rejected skips execution", async () => {
    const emitted: any[] = [];
    const executor = vi.fn();
    const approvalHandler = vi.fn().mockResolvedValue(false);

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["financial"]) });
    const specs = new Map([
      [
        "charge",
        { name: "charge", description: "charge card", parameters: {}, risk: "financial" as const },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });

    const results = await planner.executeScatterGather(
      "sess-reject",
      [{ id: "c2", name: "charge", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
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
    const planner = new ToolPlanner({ executor, policy });

    const results = await planner.executeScatterGather(
      "sess-deny",
      [{ id: "c-deny", name: "blocked", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    const types = emitted.map((e) => e.type);
    expect(types).toEqual([EventType.TOOL_CALL_REQUESTED, EventType.TOOL_CALL_FAILED]);
    expect(results[0]).toHaveProperty("error", "Tool not permitted: blocked");
  });

  it("allow-list permits only listed tools", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const policy = new ToolPolicy({ allowed: new Set(["allowed_tool"]) });
    const planner = new ToolPlanner({ executor, policy });

    await planner.executeScatterGather(
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
        },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    await planner.executeScatterGather(
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
        },
      ],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    const results = await planner.executeScatterGather(
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
    expect(results[0]).toHaveProperty("error", "Tool not permitted: weather_getWeather");
  });

  it("unclassified risk skips approval gate", async () => {
    const emitted: any[] = [];
    const executor = vi.fn().mockResolvedValue({ ok: true });

    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["search", { name: "search", description: "search", parameters: {}, risk: "read" as const }],
    ]);
    const planner = new ToolPlanner({ executor, policy, specs });

    await planner.executeScatterGather(
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

    const results = await planner.executeScatterGather(
      "sess-no-handler",
      [{ id: "c4", name: "add_user", arguments: {} }],
      async (e) => {
        emitted.push(e);
      },
    );

    const types = emitted.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REJECTED);
    expect(types).not.toContain(EventType.TOOL_CALL_STARTED);
    expect(results[0]).toHaveProperty("error");
  });
});
