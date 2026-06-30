import { describe, expect, it } from "vitest";

import { EventBus } from "../src/events/bus";
import { KajiEvent } from "../src/events/schemas";
import { EventType } from "../src/events/types";
import { InMemoryEventStore } from "../src/events/store";
import { MockProvider } from "../src/providers/mock";
import { AgentRuntime } from "../src/runtime/runtime";
import { AgentBuilder, type Integrable } from "../src/runtime/builder";
import { ToolRegistry, type ToolSpec, type ToolHandler } from "../src/tools/registry";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeInfra() {
  return { bus: new EventBus(), store: new InMemoryEventStore() };
}

/** A minimal integration that registers a single "ping" tool. */
class PingIntegration implements Integrable {
  register(registry: ToolRegistry): void {
    const spec: ToolSpec = { name: "ping", description: "Ping", parameters: {} };
    const handler: ToolHandler = async (_ctx, _args) => ({ pong: true });
    registry.register(spec, handler);
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AgentBuilder", () => {
  it("throws when provider not set", () => {
    const { bus, store } = makeInfra();
    expect(() => new AgentBuilder().build({ bus, store })).toThrow(/provider/i);
  });

  it("builds runtime with no integrations", () => {
    const { bus, store } = makeInfra();
    const runtime = new AgentBuilder().provider(new MockProvider()).build({ bus, store });
    expect(runtime).toBeInstanceOf(AgentRuntime);
  });

  it("accepts typed approval handlers in the fluent builder", () => {
    const { bus, store } = makeInfra();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .approvalHandler({
        async request() {
          return { granted: true };
        },
      })
      .build({ bus, store });

    expect(runtime).toBeInstanceOf(AgentRuntime);
  });

  it("executes integration tools via scoped registry", async () => {
    const { bus, store } = makeInfra();
    const sessionId = "s-builder-ping";
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }));
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "ping",
      }),
    );

    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new PingIntegration())
      .build({ bus, store });

    await runtime.runTurn(sessionId);

    const events = await store.getEvents(sessionId);
    const types = events.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    const completed = events.find((e) => e.type === EventType.TOOL_CALL_COMPLETED);
    expect(completed && "result" in completed ? completed.result : null).toEqual({ pong: true });
  });

  it("registers integration tools into runtime", () => {
    const { bus, store } = makeInfra();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new PingIntegration())
      .build({ bus, store });
    expect(runtime).toBeInstanceOf(AgentRuntime);
    // Access the private fixedTools field via casting to verify the tool was registered.
    const tools = (runtime as unknown as { fixedTools: ToolSpec[] | undefined }).fixedTools;
    expect(tools).toBeDefined();
    expect(tools!.some((t) => t.name === "ping")).toBe(true);
  });

  it("applies system prompt", () => {
    const { bus, store } = makeInfra();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .systemPrompt("You are a payment assistant.")
      .build({ bus, store });
    // Access the private systemPrompt field to verify it was applied.
    const sp = (runtime as unknown as { systemPrompt: string | undefined }).systemPrompt;
    expect(sp).toBe("You are a payment assistant.");
  });
});
