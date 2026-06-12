import { describe, expect, it } from "vitest";

import { AgentKitEvent } from "../src/events/schemas";
import { InMemoryEventStore } from "../src/events/store";
import { EventType } from "../src/events/types";
import { SessionManager } from "../src/sessions/manager";
import { InMemorySessionStore } from "../src/sessions/store";

describe("SessionManager.getState", () => {
  it("returns empty SessionState for a session with no events (no throw)", async () => {
    const store = new InMemoryEventStore();
    const manager = new SessionManager(store);

    const state = await manager.getState("nonexistent-session");

    expect(state).toEqual({
      sessionId: "nonexistent-session",
      isActive: false,
      messages: [],
    });
  });

  it("projects a session that has events", async () => {
    const store = new InMemoryEventStore();
    const manager = new SessionManager(store);
    const sid = "test-session";

    await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: sid }));
    await store.append(
      AgentKitEvent.parse({ type: EventType.USER_MESSAGE, session_id: sid, content: "hi" }),
    );

    const state = await manager.getState(sid);

    expect(state.sessionId).toBe(sid);
    expect(state.isActive).toBe(true);
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toEqual({ role: "user", content: "hi" });
  });
});

describe("SessionManager.recordSession and listActive", () => {
  it("listActive returns empty array when no sessionStore is provided", async () => {
    const store = new InMemoryEventStore();
    const manager = new SessionManager(store);
    const result = await manager.listActive("user-1");
    expect(result).toEqual([]);
  });

  it("records and lists sessions", async () => {
    const store = new InMemoryEventStore();
    const sessionStore = new InMemorySessionStore();
    const manager = new SessionManager(store, sessionStore);

    await manager.recordSession("sess-1", "user-1", "My session");
    const result = await manager.listActive("user-1");

    expect(result).toHaveLength(1);
    expect(result[0]?.sessionId).toBe("sess-1");
    expect(result[0]?.userId).toBe("user-1");
    expect(result[0]?.title).toBe("My session");
  });
});
