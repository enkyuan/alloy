import type { EventStore } from "../events/store";
import { replaySession } from "./replay";
import type { SessionState } from "./replay";
import type { SessionStore } from "./store";

export class SessionManager {
  private readonly _store: EventStore;
  private readonly _sessionStore?: SessionStore;

  constructor(store: EventStore, sessionStore?: SessionStore) {
    this._store = store;
    this._sessionStore = sessionStore;
  }

  async getState(sessionId: string): Promise<SessionState> {
    const events = await this._store.getEvents(sessionId);
    if (events.length === 0) {
      return {
        sessionId,
        isActive: false,
        messages: [],
        pendingApprovals: new Set<string>(),
        approvedToolCallIds: new Set<string>(),
        rejectedToolCallIds: new Set<string>(),
      };
    }
    return replaySession(events);
  }

  async recordSession(sessionId: string, userId: string, title?: string): Promise<void> {
    if (this._sessionStore === undefined) return;
    await this._sessionStore.recordSession({
      sessionId,
      userId,
      createdAt: Date.now(),
      title: title ?? "",
    });
  }

  async listActive(
    userId: string,
  ): Promise<Array<{ sessionId: string; userId: string; createdAt: number; title: string }>> {
    if (this._sessionStore === undefined) return [];
    const records = await this._sessionStore.listSessions(userId);
    return records.map((r) => ({
      sessionId: r.sessionId,
      userId: r.userId,
      createdAt: r.createdAt,
      title: r.title,
    }));
  }
}
