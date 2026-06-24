/**
 * Structural contract for an event bus. The shipped in-memory `EventBus`
 * implements this; users may pass a Redis-, Kafka-, or test-backed bus that
 * satisfies the same shape without inheriting from the concrete class.
 *
 * Mirrors `agentkit.infra.events.protocols.EventBusProtocol` from the Python
 * SDK. The TS variant adds `close()` because the in-memory implementation
 * owns subscriber state that must be released on shutdown.
 *
 * Async/sync flexibility is deliberate: `publish` may return either `void`
 * or an opaque message id (Redis XADD returns one), and `close` may be
 * either sync (in-memory) or async (durable bus needing connection
 * teardown).
 */
import type { AgentKitEvent } from "./schemas";

export interface EventBusProtocol {
  /**
   * Fan an event out to subscribers of its session. May return an opaque
   * message/position id (mirrors Python's `Redis XADD` id) or nothing.
   */
  publish(event: AgentKitEvent): Promise<void | string>;
  /**
   * Subscribe to a session's events. Iterate with `for await`. Implementers
   * MUST implement `.return()` on the returned iterator so consumers can
   * signal early exit and release subscriber resources; the shipped
   * `EventBus.Subscription` does this for in-memory cleanup.
   */
  subscribe(sessionId: string): AsyncIterableIterator<AgentKitEvent>;
  /**
   * Release subscriber state. Idempotent. May be sync (in-memory) or async
   * (durable bus flushing in-flight writes / closing a connection).
   */
  close(): void | Promise<void>;
}
