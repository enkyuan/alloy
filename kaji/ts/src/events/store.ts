import { EventIdConflictError, EventStoreCapacityError } from "@/events/errors";
import { structurallyEqualJson } from "@/events/json";
import { EventType } from "@/events/types";
import {
  type NewKajiEvent as NewKajiEventType,
  type StoredKajiEvent,
  snapshotNewEvent,
  snapshotStoredEventForAppend,
  validateStoredEvent,
} from "@/events/schemas";

export interface AppendResult {
  event: StoredKajiEvent;
  inserted: boolean;
}

export interface EventStore {
  /** Optional retained-session bound used to align runtime projection caches. */
  readonly maxSessions?: number;
  append(event: NewKajiEventType): Promise<AppendResult>;
  getEvents(
    sessionId: string,
    options?: { afterSequence?: number; limit?: number },
  ): Promise<StoredKajiEvent[]>;
  lastSequence(sessionId: string): Promise<number>;
}

export interface InMemoryEventStoreOptions {
  maxSessions?: number;
  maxEventsPerSession?: number;
}

interface SessionLog {
  events: StoredKajiEvent[];
  closed: boolean;
  lastAccess: number;
}

function draftOf(event: StoredKajiEvent): unknown {
  const { sequence: _, ...draft } = event;
  return draft;
}

function cloneStoredEvent(event: StoredKajiEvent): StoredKajiEvent {
  return validateStoredEvent(event);
}

export class InMemoryEventStore implements EventStore {
  private readonly sessions = new Map<string, SessionLog>();
  private readonly eventsById = new Map<string, StoredKajiEvent>();
  readonly maxSessions: number;
  private readonly maxEventsPerSession: number;
  private clock = 0;

  constructor(options: InMemoryEventStoreOptions = {}) {
    this.maxSessions = options.maxSessions ?? 1_000;
    this.maxEventsPerSession = options.maxEventsPerSession ?? 10_000;
    if (!Number.isInteger(this.maxSessions) || this.maxSessions <= 0) {
      throw new RangeError("maxSessions must be a positive integer");
    }
    if (!Number.isInteger(this.maxEventsPerSession) || this.maxEventsPerSession <= 0) {
      throw new RangeError("maxEventsPerSession must be a positive integer");
    }
  }

  async append(input: NewKajiEventType): Promise<AppendResult> {
    const event = snapshotNewEvent(input);
    const existing = this.eventsById.get(event.id);
    if (existing !== undefined) {
      if (!structurallyEqualJson(draftOf(existing), event)) {
        throw new EventIdConflictError(event.id);
      }
      return { event: cloneStoredEvent(existing), inserted: false };
    }

    let session = this.sessions.get(event.session_id);
    const isNewSession = session === undefined;
    if (session === undefined) {
      session = { events: [], closed: false, lastAccess: 0 };
    }
    if (session.events.length >= this.maxEventsPerSession) {
      throw new EventStoreCapacityError(
        event.session_id,
        `Session ${event.session_id} reached ${this.maxEventsPerSession} events`,
      );
    }

    const stored = snapshotStoredEventForAppend({
      ...event,
      sequence: session.events.length + 1,
    });
    if (isNewSession) {
      this.admitSession(event.session_id);
      this.sessions.set(event.session_id, session);
    }
    session.events.push(stored);
    session.closed = event.type === EventType.SESSION_CLOSED;
    session.lastAccess = ++this.clock;
    this.eventsById.set(stored.id, stored);
    return { event: cloneStoredEvent(stored), inserted: true };
  }

  async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<StoredKajiEvent[]> {
    const afterSequence = options.afterSequence ?? 0;
    const limit = options.limit;
    if (!Number.isInteger(afterSequence) || afterSequence < 0) {
      throw new RangeError("afterSequence must be a non-negative integer");
    }
    if (limit !== undefined && (!Number.isInteger(limit) || limit < 0)) {
      throw new RangeError("limit must be a non-negative integer");
    }
    const session = this.sessions.get(sessionId);
    if (session === undefined || limit === 0) return [];
    session.lastAccess = ++this.clock;
    const start = Math.min(afterSequence, session.events.length);
    return session.events
      .slice(start, limit === undefined ? undefined : start + limit)
      .map(cloneStoredEvent);
  }

  async lastSequence(sessionId: string): Promise<number> {
    const session = this.sessions.get(sessionId);
    if (session === undefined) return 0;
    session.lastAccess = ++this.clock;
    return session.events.length;
  }

  private admitSession(sessionId: string): void {
    if (this.sessions.size < this.maxSessions) return;
    let candidate: [string, SessionLog] | undefined;
    for (const entry of this.sessions) {
      if (
        entry[1].closed &&
        (candidate === undefined || entry[1].lastAccess < candidate[1].lastAccess)
      ) {
        candidate = entry;
      }
    }
    if (candidate === undefined) {
      throw new EventStoreCapacityError(
        sessionId,
        `Cannot admit session ${sessionId}; ${this.maxSessions} active sessions are retained`,
      );
    }
    this.sessions.delete(candidate[0]);
    for (const event of candidate[1].events) this.eventsById.delete(event.id);
  }
}
