import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import postgres from "postgres";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  PostgresEventCommitter,
  PostgresEventStore,
  PostgresToolIdempotencyLedger,
} from "@/backends/postgres";
import { EventIdConflictError } from "@/events/errors";
import { IdempotencyConflictError, ToolExecutionError } from "@/tools/execution/errors";
import { toolInvocationFingerprint } from "@/tools/idempotency";
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

  it("keeps tool claims durable, fail-closed, and explicitly reconcilable", async () => {
    const first = new PostgresToolIdempotencyLedger(url!, 1);
    const second = new PostgresToolIdempotencyLedger(url!, 1);
    const fingerprint = toolInvocationFingerprint("echo", { b: 2, a: ["é", true] });
    expect(fingerprint).toBe("ea1cd9c7a8dd71948df4f2a3aeab8e3356ca6feec7bd5601e3e0ba23fd143d0d");

    const owner = await first.claim("ledger", "call", fingerprint);
    expect(owner.status).toBe("owner");
    expect((await second.claim("ledger", "call", fingerprint)).status).toBe("running");
    await expect(second.claim("ledger", "call", "different")).rejects.toBeInstanceOf(
      IdempotencyConflictError,
    );
    if (owner.status !== "owner") throw new Error("expected owner");
    await first.complete(owner.claim, { ok: true });
    await expect(second.claim("ledger", "call", fingerprint)).resolves.toEqual({
      status: "completed",
      result: { ok: true },
    });
    await expect(second.releaseCompleted("ledger")).resolves.toBe(1);

    const retry = await first.claim("ledger", "retry", fingerprint);
    if (retry.status !== "owner") throw new Error("expected owner");
    await first.retryableFailure(
      retry.claim,
      new ToolExecutionError("retry", "RETRY", true, "failed"),
    );
    expect((await second.claim("ledger", "retry", fingerprint)).status).toBe("owner");

    const unknown = await first.claim("ledger", "unknown", fingerprint);
    if (unknown.status !== "owner") throw new Error("expected owner");
    await first.unknownOutcome(
      unknown.claim,
      new ToolExecutionError("unknown", "UNKNOWN", false, "unknown"),
    );
    expect((await second.claim("ledger", "unknown", fingerprint)).status).toBe("unknown");
    await expect(second.releaseSettled("ledger")).resolves.toBe(1);

    const crashed = await first.claim("ledger", "crashed", fingerprint);
    if (crashed.status !== "owner") throw new Error("expected owner");
    const observed = await second.claim("ledger", "crashed", fingerprint);
    expect(observed.status).toBe("running");
    expect(
      await Promise.race([
        observed.status === "running"
          ? observed.outcome.then(() => "settled")
          : Promise.resolve("wrong"),
        new Promise((resolve) => setTimeout(() => resolve("pending"), 20)),
      ]),
    ).toBe("pending");
    await expect(
      second.reconcileCompleted("ledger", "crashed", { reconciled: true }),
    ).resolves.toBe(true);
    if (observed.status === "running") {
      await expect(observed.outcome).resolves.toEqual({
        status: "completed",
        result: { reconciled: true },
      });
    }
    expect((await second.claim("ledger", "crashed", fingerprint)).status).toBe("completed");
    await expect(second.releaseCompleted("ledger")).resolves.toBe(1);

    const release = await first.claim("ledger", "release", fingerprint);
    if (release.status !== "owner") throw new Error("expected owner");
    await expect(second.reconcileRelease("ledger", "release")).resolves.toBe(true);
    expect((await second.claim("ledger", "release", fingerprint)).status).toBe("owner");
    await Promise.all([first.close(), second.close()]);
  });

  it("interoperates with the Python ledger over the same table", async () => {
    const ledger = new PostgresToolIdempotencyLedger(url!);
    const fingerprint = toolInvocationFingerprint("echo", { b: 2, a: ["é", true] });
    const completed = await ledger.claim("interop", "ts-completed", fingerprint);
    if (completed.status !== "owner") throw new Error("expected owner");
    await ledger.complete(completed.claim, { source: "ts" });

    const script = `
import asyncio, json, os
from kaji.backends.postgres import PostgresToolIdempotencyLedger
async def main():
    ledger = PostgresToolIdempotencyLedger(os.environ["KAJI_POSTGRES_URL"])
    completed = await ledger.claim(session_id="interop", tool_call_id="ts-completed", tool_name="echo", tool_args={"b": 2, "a": ["é", True]})
    running = await ledger.claim(session_id="interop", tool_call_id="python-running", tool_name="echo", tool_args={"b": 2, "a": ["é", True]})
    print(json.dumps([completed.kind, completed.resolution.result, running.kind]))
asyncio.run(main())
`;
    expect(
      JSON.parse(
        execFileSync(
          "uv",
          ["run", "--project", "../py", "--extra", "postgres", "python", "-c", script],
          { cwd: process.cwd(), env: process.env, encoding: "utf8" },
        ),
      ),
    ).toEqual(["completed", { source: "ts" }, "owner"]);
    const observed = await ledger.claim("interop", "python-running", fingerprint);
    expect(observed.status).toBe("running");
    await expect(ledger.reconcileRelease("interop", "python-running")).resolves.toBe(true);
    if (observed.status === "running") {
      await expect(observed.outcome).resolves.toMatchObject({ status: "failed" });
    }
    await ledger.close();
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
    await subscription.return?.();
    await store.close();
  });
});
