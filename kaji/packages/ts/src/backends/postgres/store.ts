import { EventIdConflictError } from "@/events/errors";
import { structurallyEqualJson } from "@/events/json";
import {
  type NewKajiEvent,
  type StoredKajiEvent,
  snapshotNewEvent,
  snapshotStoredEventForAppend,
  validateStoredEvent,
} from "@/events/schemas";
import type { AppendResult, EventStore } from "@/events/store";

type Sql = any;

function draftOf(event: NewKajiEvent | StoredKajiEvent): unknown {
  if (!("sequence" in event)) return event;
  const { sequence: _, ...draft } = event;
  return draft;
}

function decodeEvent(value: unknown): StoredKajiEvent {
  return validateStoredEvent(typeof value === "string" ? JSON.parse(value) : value);
}

export class PostgresEventStore implements EventStore {
  private sql: Sql | undefined;

  constructor(private readonly url: string) {
    if (url.trim().length === 0) throw new TypeError("url must be a non-empty string");
  }

  private async client(): Promise<Sql> {
    if (this.sql === undefined) {
      const { default: postgres } = await import("postgres");
      this.sql = postgres(this.url);
    }
    return this.sql;
  }

  private async existing(eventId: string): Promise<StoredKajiEvent | undefined> {
    const sql = await this.client();
    const rows = (await sql`
      SELECT event_json FROM kaji_events WHERE event_id = ${eventId}
    `) as Array<{ event_json: unknown }>;
    return rows[0] === undefined ? undefined : decodeEvent(rows[0].event_json);
  }

  async append(input: NewKajiEvent): Promise<AppendResult> {
    const event = snapshotNewEvent(input);
    const sql = await this.client();
    try {
      return await sql.begin(async (transaction: Sql) => {
        const [sequenceRow] = (await transaction`
          INSERT INTO kaji_event_sequences (session_id, next_sequence)
          VALUES (${event.session_id}, 2)
          ON CONFLICT (session_id)
          DO UPDATE SET next_sequence = kaji_event_sequences.next_sequence + 1
          RETURNING next_sequence - 1 AS next_sequence
        `) as Array<{ next_sequence: number }>;
        if (sequenceRow === undefined) throw new Error("sequence allocation returned no row");
        const stored = snapshotStoredEventForAppend({
          ...event,
          sequence: Number(sequenceRow.next_sequence),
        });
        await transaction`
          INSERT INTO kaji_events (session_id, sequence, event_id, event_json)
          VALUES (
            ${stored.session_id},
            ${stored.sequence},
            ${stored.id},
            ${JSON.stringify(stored)}::jsonb
          )
        `;
        return { event: stored, inserted: true };
      });
    } catch (error) {
      if ((error as { code?: string }).code !== "23505") throw error;
      const existing = await this.existing(event.id);
      if (existing !== undefined && structurallyEqualJson(draftOf(existing), event)) {
        return { event: existing, inserted: false };
      }
      throw new EventIdConflictError(event.id);
    }
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
    if (limit === 0) return [];
    const sql = await this.client();
    const rows =
      limit === undefined
        ? ((await sql`
            SELECT event_json FROM kaji_events
            WHERE session_id = ${sessionId} AND sequence > ${afterSequence}
            ORDER BY sequence
          `) as Array<{ event_json: unknown }>)
        : ((await sql`
            SELECT event_json FROM kaji_events
            WHERE session_id = ${sessionId} AND sequence > ${afterSequence}
            ORDER BY sequence LIMIT ${limit}
          `) as Array<{ event_json: unknown }>);
    return rows.map((row) => decodeEvent(row.event_json));
  }

  async lastSequence(sessionId: string): Promise<number> {
    const sql = await this.client();
    const rows = (await sql`
      SELECT sequence FROM kaji_events
      WHERE session_id = ${sessionId} ORDER BY sequence DESC LIMIT 1
    `) as Array<{ sequence: number }>;
    return rows[0] === undefined ? 0 : Number(rows[0].sequence);
  }

  async purgeSession(sessionId: string): Promise<boolean> {
    if (sessionId.trim().length === 0) throw new TypeError("sessionId must be a non-empty string");
    const sql = await this.client();
    return sql.begin(async (transaction: Sql) => {
      const deleted = await transaction`
        DELETE FROM kaji_events WHERE session_id = ${sessionId}
      `;
      await transaction`DELETE FROM kaji_event_sequences WHERE session_id = ${sessionId}`;
      return deleted.count > 0;
    });
  }

  async close(): Promise<void> {
    await this.sql?.end({ timeout: 5 });
    this.sql = undefined;
  }
}
