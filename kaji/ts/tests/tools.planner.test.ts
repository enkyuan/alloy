import { describe, it, expect, vi } from "vitest";
import { ToolPlanner } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { EventType } from "@/events/types";
import { InMemoryEventStore } from "@/events/store";
import { KajiEvent } from "@/events/schemas";
import { EventApprovalHandler } from "@/runtime/approval/event_handler";

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

  it("emits exactly one approval request when EventApprovalHandler publishes request events", async () => {
    const store = new InMemoryEventStore();
    const sessionId = "sess-event-handler-approval";
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const approvalHandler = new EventApprovalHandler(store, { timeoutMs: 250 });
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const specs = new Map([
      ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
    ]);

    store.subscribe(sessionId, (event) => {
      if (event.type === EventType.TOOL_APPROVAL_REQUESTED && event.tool_call_id === "c-typed") {
        void store.append(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: sessionId,
            tool_name: "nuke",
            tool_call_id: "c-typed",
          }),
        );
      }
    });

    const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });
    const results = await planner.executeScatterGather(
      sessionId,
      [{ id: "c-typed", name: "nuke", arguments: {} }],
      async (e) => {
        await store.append(e);
      },
    );

    const events = await store.getEvents(sessionId);
    expect(events.filter((e) => e.type === EventType.TOOL_APPROVAL_REQUESTED)).toHaveLength(1);
    expect(events.map((e) => e.type)).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(results[0]).toHaveProperty("result", { ok: true });
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
