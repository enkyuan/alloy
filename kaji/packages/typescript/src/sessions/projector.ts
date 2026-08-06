import type { EventStore } from "@/events/store";
import { validateStoredEvent, type StoredKajiEvent } from "@/events/schemas";
import {
  applyEvent,
  cloneSessionState,
  createSessionState,
  type SessionState,
} from "@/sessions/replay";
import { NOOP_METRICS, recordMetric, type MetricsSink } from "@/observability";
import { ContextIndex, type ContextIndexStats } from "@/sessions/context-index";
import type { ContextBuildResult, ContextWindow } from "@/runtime/context";

/** Incremental projection that owns one session-local sequence cursor. */
export class SessionProjector {
  private readonly projectionState: SessionState;
  private readonly contextIndex: ContextIndex;
  lastSequence = 0;
  appliedEvents = 0;
  initialized = false;

  constructor(
    readonly sessionId: string,
    private readonly metrics: MetricsSink = NOOP_METRICS,
    contextWindow?: Readonly<ContextWindow>,
  ) {
    this.projectionState = createSessionState(sessionId);
    this.contextIndex = new ContextIndex(this.projectionState, contextWindow);
  }

  /** Return a deep snapshot; projection state remains privately owned. */
  get state(): SessionState {
    return cloneSessionState(this.projectionState);
  }

  apply(event: StoredKajiEvent): void {
    this.applyValidated(validateStoredEvent(event));
  }

  private applyValidated(event: StoredKajiEvent): void {
    if (event.session_id !== this.sessionId) {
      throw new Error("Cannot project events from mixed sessions");
    }
    const expected = this.lastSequence + 1;
    if (event.sequence !== expected) {
      throw new Error(`Cannot project sequence ${event.sequence}; expected sequence ${expected}`);
    }
    this.contextIndex.assertProjectionOwned();
    const messageIndex = applyEvent(this.projectionState, event);
    this.contextIndex.apply(messageIndex);
    this.lastSequence = event.sequence;
    this.appliedEvents++;
  }

  async sync(store: EventStore, onApplied?: (event: StoredKajiEvent) => void): Promise<number> {
    const events = (
      await store.getEvents(this.sessionId, {
        afterSequence: this.lastSequence,
      })
    ).map(validateStoredEvent);
    recordMetric(this.metrics, "kaji.replay.input_events", events.length, {});
    for (const event of events) {
      this.applyValidated(event);
      onApplied?.(event);
    }
    this.initialized = true;
    this.contextIndex.sealColdBuild();
    return events.length;
  }

  get contextIndexStats(): Readonly<ContextIndexStats> {
    return this.contextIndex.stats;
  }

  buildProjectedContext(systemPrompt?: string, window?: ContextWindow): ContextBuildResult {
    return this.contextIndex.suffix(systemPrompt, window, this.metrics);
  }

  latestUserContent(): string | undefined {
    return this.contextIndex.latestUserContent();
  }
}
