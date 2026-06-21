export interface SessionRecord {
  sessionId: string;
  userId: string;
  createdAt: number;
  title: string;
}

export interface SessionStore {
  recordSession(record: SessionRecord): Promise<void>;
  listSessions(userId: string): Promise<SessionRecord[]>;
}

export class InMemorySessionStore implements SessionStore {
  private readonly records = new Map<string, Map<string, SessionRecord>>();

  async recordSession(record: SessionRecord): Promise<void> {
    let userMap = this.records.get(record.userId);
    if (userMap === undefined) {
      userMap = new Map();
      this.records.set(record.userId, userMap);
    }
    if (!userMap.has(record.sessionId)) {
      userMap.set(record.sessionId, record);
    }
  }

  async listSessions(userId: string): Promise<SessionRecord[]> {
    const userMap = this.records.get(userId);
    if (userMap === undefined) return [];
    return [...userMap.values()].sort((a, b) => b.createdAt - a.createdAt);
  }
}
