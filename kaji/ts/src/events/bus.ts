/**
 * In-memory event bus, the infra-free analog of the Python Redis Stream bus
 * (`kaji.infra.events.bus.EventBus`). Events are fanned out per session to
 * any number of async-iterator subscribers. No infra required.
 *
 * The Redis-backed bus (durable, cross-process) is deferred until there is a
 * server runtime in TS; for an embedded SDK this in-memory fan-out is enough.
 */
import type { EventBusProtocol } from "./protocols";
import type { KajiEvent } from "./schemas";

/** A queue that bridges synchronous `publish` to an async iterator. */
class Subscription implements AsyncIterableIterator<KajiEvent> {
  private readonly buffered: KajiEvent[] = [];
  private pending: ((r: IteratorResult<KajiEvent>) => void) | null = null;
  private closed = false;

  constructor(private readonly onReturn: () => void) {}

  /** Deliver an event to the consumer (or buffer it until they ask). */
  push(event: KajiEvent): void {
    if (this.closed) return;
    if (this.pending) {
      const resolve = this.pending;
      this.pending = null;
      resolve({ value: event, done: false });
    } else {
      this.buffered.push(event);
    }
  }

  next(): Promise<IteratorResult<KajiEvent>> {
    const buffered = this.buffered.shift();
    if (buffered !== undefined) {
      return Promise.resolve({ value: buffered, done: false });
    }
    if (this.closed) {
      return Promise.resolve({ value: undefined, done: true });
    }
    return new Promise((resolve) => {
      this.pending = resolve;
    });
  }

  return(): Promise<IteratorResult<KajiEvent>> {
    this.close();
    this.onReturn();
    return Promise.resolve({ value: undefined, done: true });
  }

  /** Stop the iterator, resolving any awaiting `next()`. */
  close(): void {
    this.closed = true;
    if (this.pending) {
      const resolve = this.pending;
      this.pending = null;
      resolve({ value: undefined, done: true });
    }
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<KajiEvent> {
    return this;
  }
}

export class EventBus implements EventBusProtocol {
  private readonly subscribers = new Map<string, Set<Subscription>>();

  /**
   * Publish an event to every subscriber of its session.
   *
   * Intentionally `async` (returns a resolved Promise): the body is synchronous
   * fan-out via `Subscription.push`, but an async signature lets every caller
   * `await bus.publish(...)` uniformly, matching the Python runtime's
   * `await self.bus.publish(event)`. The agent runtime depends on this shape.
   */
  async publish(event: KajiEvent): Promise<void> {
    const subs = this.subscribers.get(event.session_id);
    if (!subs) return;
    for (const sub of subs) sub.push(event);
  }

  /**
   * Subscribe to a session's events. Iterate with `for await`; the
   * subscription is cleaned up when the loop breaks/returns or `close()` runs.
   */
  subscribe(sessionId: string): AsyncIterableIterator<KajiEvent> {
    let subs = this.subscribers.get(sessionId);
    if (!subs) {
      subs = new Set();
      this.subscribers.set(sessionId, subs);
    }
    const bucket = subs;
    const sub = new Subscription(() => {
      bucket.delete(sub);
      if (bucket.size === 0) this.subscribers.delete(sessionId);
    });
    bucket.add(sub);
    return sub;
  }

  /** Close every subscription (e.g. on shutdown). */
  close(): void {
    for (const subs of this.subscribers.values()) {
      for (const sub of subs) sub.close();
    }
    this.subscribers.clear();
  }
}
