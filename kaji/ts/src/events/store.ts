import { EventIdConflictError, EventStoreCapacityError } from "@/events/errors";
import { structurallyEqualJson } from "@/events/json";
import {
  type NewKajiEvent as NewKajiEventType,
  type StoredKajiEvent,
  snapshotNewEvent,
  snapshotStoredEventForAppend,
  validateStoredEvent,
} from "@/events/schemas";
import { EventType } from "@/events/types";
import { KeyedSerialExecutor } from "@/internal/keyed-serial";

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

export interface PurgeableEventStore extends EventStore {
  purgeSession(sessionId: string): Promise<boolean>;
}

export function supportsSessionPurge(store: EventStore): store is PurgeableEventStore {
  return typeof (store as Partial<PurgeableEventStore>).purgeSession === "function";
}

export type SessionEventListener = (event: StoredKajiEvent) => boolean;

export interface EventStoreSession {
  appendLocked(event: NewKajiEventType): Promise<AppendResult>;
  getEventsLocked(options?: { afterSequence?: number; limit?: number }): StoredKajiEvent[];
  lastSequenceLocked(): number;
  attachListenerLocked(listener: SessionEventListener): void;
  detachListenerLocked(listener: SessionEventListener): void;
}

export interface SessionTransactionalEventStore extends EventStore {
  readonly sessionTransactionsEnabled: boolean;
  sessionTransaction<T>(
    sessionId: string,
    operation: (transaction: EventStoreSession) => Promise<T>,
  ): Promise<T>;
}

export function supportsSessionTransactions(
  store: EventStore,
): store is SessionTransactionalEventStore {
  const candidate = store as Partial<SessionTransactionalEventStore>;
  return (
    candidate.sessionTransactionsEnabled === true &&
    typeof candidate.sessionTransaction === "function"
  );
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

interface ReservationOutcome {
  result?: AppendResult;
  error?: unknown;
}

interface IdReservation {
  draft: NewKajiEventType;
  done: Promise<ReservationOutcome>;
  settle(outcome: ReservationOutcome): void;
}

type IdClaim =
  | { kind: "existing"; result: AppendResult }
  | { kind: "owner"; reservation: IdReservation }
  | { kind: "follower"; reservation: IdReservation };

function draftOf(event: StoredKajiEvent): unknown {
  const { sequence: _, ...draft } = event;
  return draft;
}

function cloneStoredEvent(event: StoredKajiEvent): StoredKajiEvent {
  return validateStoredEvent(event);
}

export class InMemoryEventStore implements PurgeableEventStore {
  private readonly sessions = new Map<string, SessionLog>();
  private readonly eventsById = new Map<string, StoredKajiEvent>();
  private readonly idReservations = new Map<string, IdReservation>();
  private readonly listeners = new Map<string, Set<SessionEventListener>>();
  private readonly lanes = new KeyedSerialExecutor();
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

  get sessionTransactionsEnabled(): boolean {
    const prototype = InMemoryEventStore.prototype;
    return (
      this.append === prototype.append &&
      this.getEvents === prototype.getEvents &&
      this.lastSequence === prototype.lastSequence
    );
  }

  /** @internal Diagnostics for deterministic leak tests. */
  get activeSessionLaneCount(): number {
    return this.lanes.activeKeyCount;
  }

  /** @internal Diagnostics for deterministic leak tests. */
  get activeIdReservationCount(): number {
    return this.idReservations.size;
  }

  /** @internal Diagnostics for deterministic leak tests. */
  get activeListenerCount(): number {
    let count = 0;
    for (const listeners of this.listeners.values()) count += listeners.size;
    return count;
  }

  sessionTransaction<T>(
    sessionId: string,
    operation: (transaction: EventStoreSession) => Promise<T>,
  ): Promise<T> {
    const deliveries: Array<{
      event: StoredKajiEvent;
      listeners: readonly SessionEventListener[];
    }> = [];
    return this.lanes.run(
      sessionId,
      () =>
        operation({
          appendLocked: async (event) => {
            const result = await this.appendTransaction(sessionId, event);
            if (result.inserted) {
              const listeners = [...(this.listeners.get(sessionId) ?? [])];
              if (listeners.length > 0) deliveries.push({ event: result.event, listeners });
            }
            return result;
          },
          getEventsLocked: (options = {}) => this.getEventsLocked(sessionId, options),
          lastSequenceLocked: () => this.lastSequenceLocked(sessionId),
          attachListenerLocked: (listener) => this.attachListenerLocked(sessionId, listener),
          detachListenerLocked: (listener) => this.detachListenerLocked(sessionId, listener),
        }),
      () => {
        for (const delivery of deliveries) {
          this.fanoutSnapshot(delivery.event, delivery.listeners);
        }
      },
    );
  }

  async append(input: NewKajiEventType): Promise<AppendResult> {
    const event = snapshotNewEvent(input);
    return this.sessionTransaction(event.session_id, (transaction) =>
      transaction.appendLocked(event),
    );
  }

  private claimId(event: NewKajiEventType): IdClaim {
    const existing = this.eventsById.get(event.id);
    if (existing !== undefined) {
      if (!structurallyEqualJson(draftOf(existing), event)) {
        throw new EventIdConflictError(event.id);
      }
      return {
        kind: "existing",
        result: { event: cloneStoredEvent(existing), inserted: false },
      };
    }

    const pending = this.idReservations.get(event.id);
    if (pending !== undefined) {
      if (!structurallyEqualJson(pending.draft, event)) {
        throw new EventIdConflictError(event.id);
      }
      return { kind: "follower", reservation: pending };
    }

    let settle!: (outcome: ReservationOutcome) => void;
    const done = new Promise<ReservationOutcome>((resolve) => {
      settle = resolve;
    });
    const reservation = { draft: event, done, settle };
    this.idReservations.set(event.id, reservation);
    return { kind: "owner", reservation };
  }

  private finishReservation(
    eventId: string,
    reservation: IdReservation,
    outcome: ReservationOutcome,
  ): void {
    if (this.idReservations.get(eventId) === reservation) this.idReservations.delete(eventId);
    reservation.settle(outcome);
  }

  private async appendTransaction(
    sessionId: string,
    input: NewKajiEventType,
  ): Promise<AppendResult> {
    const event = snapshotNewEvent(input);
    if (event.session_id !== sessionId) {
      throw new RangeError("event session_id does not match the held transaction");
    }

    const claim = this.claimId(event);
    if (claim.kind === "existing") return claim.result;
    if (claim.kind === "follower") {
      const outcome = await claim.reservation.done;
      if (outcome.error !== undefined) throw outcome.error;
      if (outcome.result === undefined)
        throw new Error("event reservation settled without a result");
      return { event: cloneStoredEvent(outcome.result.event), inserted: false };
    }

    try {
      const result = await this.insertReserved(event);
      this.finishReservation(event.id, claim.reservation, { result });
      return result;
    } catch (error) {
      this.finishReservation(event.id, claim.reservation, { error });
      throw error;
    }
  }

  protected insertReserved(event: NewKajiEventType): Promise<AppendResult> {
    let session = this.sessions.get(event.session_id);
    const isNewSession = session === undefined;
    if (session === undefined) session = { events: [], closed: false, lastAccess: 0 };
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
    return Promise.resolve({ event: cloneStoredEvent(stored), inserted: true });
  }

  private fanoutSnapshot(event: StoredKajiEvent, listeners: readonly SessionEventListener[]): void {
    const active = this.listeners.get(event.session_id);
    for (const listener of listeners) {
      if (!listener(event)) active?.delete(listener);
    }
    if (active?.size === 0) this.listeners.delete(event.session_id);
  }

  private attachListenerLocked(sessionId: string, listener: SessionEventListener): void {
    let listeners = this.listeners.get(sessionId);
    if (listeners === undefined) {
      listeners = new Set();
      this.listeners.set(sessionId, listeners);
    }
    listeners.add(listener);
  }

  private detachListenerLocked(sessionId: string, listener: SessionEventListener): void {
    const listeners = this.listeners.get(sessionId);
    if (listeners === undefined) return;
    listeners.delete(listener);
    if (listeners.size === 0) this.listeners.delete(sessionId);
  }

  async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<StoredKajiEvent[]> {
    return this.sessionTransaction(sessionId, async (transaction) =>
      transaction.getEventsLocked(options),
    );
  }

  private getEventsLocked(
    sessionId: string,
    options: { afterSequence?: number; limit?: number },
  ): StoredKajiEvent[] {
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
    return this.sessionTransaction(sessionId, async (transaction) =>
      transaction.lastSequenceLocked(),
    );
  }

  async purgeSession(sessionId: string): Promise<boolean> {
    if (typeof sessionId !== "string" || sessionId.trim().length === 0) {
      throw new TypeError("sessionId must be a non-empty string");
    }
    return this.lanes.run(sessionId, async () => {
      const session = this.sessions.get(sessionId);
      const existed = session !== undefined || this.listeners.has(sessionId);
      if (session !== undefined) {
        this.sessions.delete(sessionId);
        for (const event of session.events) this.eventsById.delete(event.id);
      }
      this.listeners.delete(sessionId);
      return existed;
    });
  }

  private lastSequenceLocked(sessionId: string): number {
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
        !this.lanes.has(entry[0]) &&
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
