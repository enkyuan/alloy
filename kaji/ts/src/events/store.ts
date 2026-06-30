/**
 * Event store interface and in-memory backend, mirroring
 * `kaji.infra.events.store`. The append-only log is the source of truth;
 * session state is a projection (see `replaySession`).
 */
import type { KajiEvent } from "@/events/schemas";

/** Interface every persistent backend implements. */
export interface EventStore {
  /** Append an event to the store. */
  append(event: KajiEvent): Promise<void>;
  /** Retrieve all events for a session, ordered by time. */
  getEvents(sessionId: string): Promise<KajiEvent[]>;
  /**
   * Subscribe to events for a session. The callback fires synchronously
   * after each `append` for the given `sessionId`. Returns an unsubscribe
   * function; call it to stop receiving events.
   */
  subscribe(sessionId: string, callback: (event: KajiEvent) => void): () => void;
}

/**
 * In-memory event store for tests and simple deployments. Events live in a
 * per-session map and are lost on process exit.
 */
export class InMemoryEventStore implements EventStore {
  private readonly events = new Map<string, KajiEvent[]>();
  private readonly listeners = new Map<string, Set<(event: KajiEvent) => void>>();

  async append(event: KajiEvent): Promise<void> {
    // Fast path: runtime-emitted events have monotonically increasing
    // timestamps, so the bucket stays sorted with a single `push`. Only
    // re-sort when a caller (test fixture, replay tooling) backdates the
    // timestamp.
    const bucket = this.events.get(event.session_id);
    if (bucket === undefined) {
      this.events.set(event.session_id, [event]);
    } else {
      bucket.push(event);
      if (
        bucket.length > 1 &&
        bucket[bucket.length - 1]!.timestamp < bucket[bucket.length - 2]!.timestamp
      ) {
        bucket.sort((a, b) => a.timestamp - b.timestamp);
      }
    }

    // Notify listeners after the event is stored.
    const subs = this.listeners.get(event.session_id);
    if (subs !== undefined) {
      for (const cb of subs) {
        cb(event);
      }
    }
  }

  async getEvents(sessionId: string): Promise<KajiEvent[]> {
    return [...(this.events.get(sessionId) ?? [])];
  }

  subscribe(sessionId: string, callback: (event: KajiEvent) => void): () => void {
    let subs = this.listeners.get(sessionId);
    if (subs === undefined) {
      subs = new Set();
      this.listeners.set(sessionId, subs);
    }
    subs.add(callback);
    return () => {
      subs!.delete(callback);
      if (subs!.size === 0) {
        this.listeners.delete(sessionId);
      }
    };
  }
}
