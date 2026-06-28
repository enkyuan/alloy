import { describe, expect, it } from "vitest";

import {
  KajiEvent,
  EventType,
  InMemoryEventStore,
  InMemorySessionStore,
  SessionManager,
} from "../src/index";

function makeEvent(input: Record<string, unknown>) {
  return KajiEvent.parse(input);
}

describe("SessionManager", () => {
  describe("getState", () => {
    it("returns empty SessionState for a session with no events (no throw)", async () => {
      const manager = new SessionManager(new InMemoryEventStore());
      const state = await manager.getState("nonexistent-session");
      expect(state).toEqual({
        sessionId: "nonexistent-session",
        isActive: false,
        messages: [],
        pendingApprovals: new Set<string>(),
        approvedToolCallIds: new Set<string>(),
        rejectedToolCallIds: new Set<string>(),
        totalTokens: { input: 0, output: 0 },
        totalCostUsd: 0,
      });
    });

    it("returns correct SessionState from replayed events", async () => {
      const eventStore = new InMemoryEventStore();
      await eventStore.append(
        makeEvent({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      );
      await eventStore.append(
        makeEvent({
          type: EventType.USER_MESSAGE,
          session_id: "s1",
          content: "hello",
          timestamp: 2,
        }),
      );
      await eventStore.append(
        makeEvent({
          type: EventType.AGENT_MESSAGE_COMPLETED,
          session_id: "s1",
          content: "hi there",
          timestamp: 3,
        }),
      );

      const manager = new SessionManager(eventStore);
      const state = await manager.getState("s1");

      expect(state.sessionId).toBe("s1");
      expect(state.isActive).toBe(true);
      expect(state.messages).toEqual([
        { role: "user", content: "hello" },
        { role: "assistant", content: "hi there" },
      ]);
    });
  });

  describe("recordSession", () => {
    it("no-ops gracefully without a session store", async () => {
      const manager = new SessionManager(new InMemoryEventStore());
      await expect(manager.recordSession("s1", "u1", "My Session")).resolves.toBeUndefined();
    });

    it("is idempotent: second call with same sessionId does not create a duplicate", async () => {
      const eventStore = new InMemoryEventStore();
      const sessionStore = new InMemorySessionStore();
      const manager = new SessionManager(eventStore, sessionStore);

      await manager.recordSession("s1", "u1", "First Title");
      await manager.recordSession("s1", "u1", "Second Title");

      const sessions = await sessionStore.listSessions("u1");
      expect(sessions).toHaveLength(1);
      expect(sessions.at(0)?.title).toBe("First Title");
    });
  });

  describe("listActive", () => {
    it("returns [] without a session store", async () => {
      const manager = new SessionManager(new InMemoryEventStore());
      await expect(manager.listActive("u1")).resolves.toEqual([]);
    });

    it("returns sessions sorted newest-first", async () => {
      const eventStore = new InMemoryEventStore();
      const sessionStore = new InMemorySessionStore();
      const manager = new SessionManager(eventStore, sessionStore);

      await sessionStore.recordSession({
        sessionId: "old",
        userId: "u1",
        createdAt: 1000,
        title: "Older",
      });
      await sessionStore.recordSession({
        sessionId: "new",
        userId: "u1",
        createdAt: 2000,
        title: "Newer",
      });

      const sessions = await manager.listActive("u1");
      expect(sessions.map((s) => s.sessionId)).toEqual(["new", "old"]);
    });
  });

  describe("full round-trip", () => {
    it("record + list + getState all return consistent data", async () => {
      const eventStore = new InMemoryEventStore();
      const sessionStore = new InMemorySessionStore();
      const manager = new SessionManager(eventStore, sessionStore);

      await eventStore.append(
        makeEvent({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      );
      await eventStore.append(
        makeEvent({
          type: EventType.USER_MESSAGE,
          session_id: "s1",
          content: "round-trip",
          timestamp: 2,
        }),
      );

      await manager.recordSession("s1", "u1", "Round Trip");

      const sessions = await manager.listActive("u1");
      expect(sessions).toHaveLength(1);
      expect(sessions.at(0)?.sessionId).toBe("s1");
      expect(sessions.at(0)?.userId).toBe("u1");
      expect(sessions.at(0)?.title).toBe("Round Trip");
      expect(typeof sessions.at(0)?.createdAt).toBe("number");

      const state = await manager.getState("s1");
      expect(state.sessionId).toBe("s1");
      expect(state.isActive).toBe(true);
      expect(state.messages).toHaveLength(1);
      expect(state.messages.at(0)?.content).toBe("round-trip");
    });
  });
});
