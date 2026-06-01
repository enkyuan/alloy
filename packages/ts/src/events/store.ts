/**
 * Event store interface and in-memory backend, mirroring
 * `agentkit.infra.events.store`. The append-only log is the source of truth;
 * session state is a projection (see `replaySession`).
 */
import type { AgentKitEvent } from "./schemas";

/** Interface every persistent backend implements. */
export interface EventStore {
  /** Append an event to the store. */
  append(event: AgentKitEvent): Promise<void>;
  /** Retrieve all events for a session, ordered by time. */
  getEvents(sessionId: string): Promise<AgentKitEvent[]>;
}

/**
 * In-memory event store for tests and simple deployments. Events live in a
 * per-session map and are lost on process exit.
 */
export class InMemoryEventStore implements EventStore {
  private readonly events = new Map<string, AgentKitEvent[]>();

  async append(event: AgentKitEvent): Promise<void> {
    const bucket = this.events.get(event.session_id) ?? [];
    bucket.push(event);
    bucket.sort((a, b) => a.timestamp - b.timestamp);
    this.events.set(event.session_id, bucket);
  }

  async getEvents(sessionId: string): Promise<AgentKitEvent[]> {
    return [...(this.events.get(sessionId) ?? [])];
  }
}
