import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

import postgres from "postgres";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PostgresEventCommitter, PostgresEventStore } from "@/backends/postgres";
import { EventIdConflictError } from "@/events/errors";
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";

const url = process.env.KAJI_POSTGRES_URL;
const describePostgres = url === undefined ? describe.skip : describe;

function event(sessionId: string, content: string, id = randomUUID()) {
  return KajiEvent.parse({
    id,
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content,
  });
}

describePostgres("PostgresEventStore", () => {
  let sql: postgres.Sql;

  beforeEach(async () => {
    sql = postgres(url!);
    await sql`DROP TABLE IF EXISTS kaji_event_sequences, kaji_events, kaji_tool_idempotency`;
    await sql.unsafe(
      await readFile(resolve(process.cwd(), "../../contracts/postgres/v1/schema.sql"), "utf8"),
    );
  });

  afterEach(async () => {
    await sql.end({ timeout: 5 });
  });

  it("appends, rejects conflicting duplicate IDs, pages, rolls back, and purges", async () => {
    const store = new PostgresEventStore(url!);
    const first = event("one", "first", "11111111-1111-4111-8111-111111111111");
    await expect(store.append(first)).resolves.toMatchObject({
      inserted: true,
      event: { sequence: 1 },
    });
    await expect(store.append(first)).resolves.toMatchObject({
      inserted: false,
      event: { sequence: 1 },
    });
    await expect(
      store.append(event("one", "different", "11111111-1111-4111-8111-111111111111")),
    ).rejects.toBeInstanceOf(EventIdConflictError);
    await expect(
      store.append(event("one", "second", "22222222-2222-4222-8222-222222222222")),
    ).resolves.toMatchObject({
      event: { sequence: 2 },
    });
    expect(
      (await store.getEvents("one", { afterSequence: 1 })).map((item) => item.sequence),
    ).toEqual([2]);
    await expect(store.purgeSession("one")).resolves.toBe(true);
    await store.close();
    await expect(store.append(event("reconnect", "after close"))).resolves.toMatchObject({
      event: { sequence: 1 },
    });
    await store.close();
  });

  it("allocates contiguous per-session sequences and polls durable subscriptions", async () => {
    const store = new PostgresEventStore(url!);
    const same = await Promise.all(
      Array.from({ length: 20 }, (_, index) => store.append(event("same", String(index)))),
    );
    expect(same.map((item) => item.event.sequence).sort((left, right) => left - right)).toEqual(
      Array.from({ length: 20 }, (_, index) => index + 1),
    );

    const [left, right] = await Promise.all([
      Promise.all(
        Array.from({ length: 10 }, (_, index) => store.append(event("left", String(index)))),
      ),
      Promise.all(
        Array.from({ length: 10 }, (_, index) => store.append(event("right", String(index)))),
      ),
    ]);
    expect(left.map((item) => item.event.sequence).sort((a, b) => a - b)).toEqual(
      Array.from({ length: 10 }, (_, index) => index + 1),
    );
    expect(right.map((item) => item.event.sequence).sort((a, b) => a - b)).toEqual(
      Array.from({ length: 10 }, (_, index) => index + 1),
    );

    const committer = new PostgresEventCommitter(store, { pollIntervalMs: 1 });
    const subscription = committer.subscribe("same");
    expect((await subscription.next()).value.sequence).toBe(1);
    await store.close();
  });
});
