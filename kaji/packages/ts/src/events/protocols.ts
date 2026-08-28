import type { KajiEvent, NewKajiEvent, StoredKajiEvent } from "@/events/schemas";
import type { EventStore } from "@/events/store";

export interface EventBusSubscribeOptions {
  afterSequence?: number;
}

export interface EventBusProtocol<TEvent extends { readonly session_id: string } = KajiEvent> {
  publish(event: TEvent): Promise<void | string>;
  /**
   * Return an iterator that cannot miss events published after `afterSequence`.
   * Implementations must either attach synchronously before returning or retain
   * cursor-addressable history that a lazy iterator reads when iteration starts.
   */
  subscribe(sessionId: string, options?: EventBusSubscribeOptions): AsyncIterableIterator<TEvent>;
  close(): void | Promise<void>;
}

export interface EventCommitter {
  readonly store: EventStore;
  commit(event: NewKajiEvent): Promise<StoredKajiEvent>;
  subscribe(
    sessionId: string,
    options?: { afterSequence?: number },
  ): AsyncIterableIterator<StoredKajiEvent>;
}
