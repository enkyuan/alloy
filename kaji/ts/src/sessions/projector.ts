import type { EventStore } from "@/events/store";
import type { StoredKajiEvent } from "@/events/schemas";
import { applyEvent, createSessionState, type SessionState } from "@/sessions/replay";

/** Incremental projection that owns one session-local sequence cursor. */
export class SessionProjector {
  readonly state: SessionState;
  lastSequence = 0;
  appliedEvents = 0;
  initialized = false;

  constructor(readonly sessionId: string) {
    this.state = createSessionState(sessionId);
  }

  apply(event: StoredKajiEvent): void {
    if (event.session_id !== this.sessionId) {
      throw new Error("Cannot project events from mixed sessions");
    }
    const expected = this.lastSequence + 1;
    if (event.sequence !== expected) {
      throw new Error(`Cannot project sequence ${event.sequence}; expected sequence ${expected}`);
    }
    applyEvent(this.state, event);
    this.lastSequence = event.sequence;
    this.appliedEvents++;
  }

  async sync(store: EventStore): Promise<number> {
    const events = await store.getEvents(this.sessionId, {
      afterSequence: this.lastSequence,
    });
    for (const event of events) this.apply(event);
    this.initialized = true;
    return events.length;
  }
}
