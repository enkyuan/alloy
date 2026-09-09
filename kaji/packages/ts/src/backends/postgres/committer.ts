import type { EventCommitter } from "@/events/protocols";
import type { NewKajiEvent, StoredKajiEvent } from "@/events/schemas";

import { PostgresEventStore } from "./store";

export interface PostgresEventCommitterOptions {
  pollIntervalMs?: number;
  pageSize?: number;
}

export class PostgresEventCommitter implements EventCommitter {
  private readonly pollIntervalMs: number;
  private readonly pageSize: number;

  constructor(
    readonly store: PostgresEventStore,
    options: PostgresEventCommitterOptions = {},
  ) {
    this.pollIntervalMs = options.pollIntervalMs ?? 50;
    this.pageSize = options.pageSize ?? 100;
    if (this.pollIntervalMs <= 0 || this.pageSize < 1) {
      throw new RangeError("pollIntervalMs must be positive and pageSize must be at least one");
    }
  }

  async commit(event: NewKajiEvent): Promise<StoredKajiEvent> {
    return (await this.store.append(event)).event;
  }

  async *subscribe(
    sessionId: string,
    options: { afterSequence?: number } = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    let cursor = options.afterSequence ?? 0;
    if (!Number.isInteger(cursor) || cursor < 0) {
      throw new RangeError("afterSequence must be a non-negative integer");
    }
    while (true) {
      const events = await this.store.getEvents(sessionId, {
        afterSequence: cursor,
        limit: this.pageSize,
      });
      if (events.length === 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, this.pollIntervalMs));
        continue;
      }
      for (const event of events) {
        cursor = event.sequence;
        yield event;
      }
    }
  }
}
