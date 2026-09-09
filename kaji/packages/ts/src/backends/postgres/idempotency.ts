import { randomUUID } from "node:crypto";

import { durableJsonSnapshot } from "@/events/json";
import { closedRecoveryFields } from "@/integrations/recovery";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/schemas";
import {
  IdempotencyConflictError,
  ToolExecutionError,
  type ToolFailureOutcome,
} from "@/tools/execution/errors";
import type {
  ToolClaimResult,
  ToolIdempotencyClaim,
  ToolIdempotencyLedger,
  ToolLedgerOutcome,
} from "@/tools/idempotency";

type Sql = any;
type Row = {
  fingerprint: string;
  status: "running" | "completed" | "unknown";
  claim_token: string;
  result_json: unknown;
  error_json: unknown;
  started_at: Date | null;
};

function decodeJson(value: unknown): unknown {
  return typeof value === "string" ? JSON.parse(value) : value;
}

function errorJson(error: ToolExecutionError): Record<string, unknown> {
  const result: Record<string, unknown> = {
    error: error.message,
    error_code: error.error_code,
    retryable: error.retryable,
    outcome: error.outcome,
  };
  for (const key of ["reason_code", "recovery_code", "doc_url"] as const) {
    if (error[key] !== undefined) result[key] = error[key];
  }
  const subject = (error as ToolExecutionError & { subject?: unknown }).subject;
  if (subject !== undefined) result.subject = subject;
  return result;
}

function ambiguousError(): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution outcome is unknown",
    "TOOL_EXECUTION_UNKNOWN",
    false,
    "unknown",
  );
}

function errorFromJson(value: unknown): ToolExecutionError {
  const data = decodeJson(value);
  if (data === null || typeof data !== "object") return ambiguousError();
  const fields = data as Record<string, unknown>;
  if (
    typeof fields.error !== "string" ||
    typeof fields.error_code !== "string" ||
    typeof fields.retryable !== "boolean" ||
    !["not_started", "failed", "unknown"].includes(fields.outcome as string)
  ) {
    return ambiguousError();
  }
  return new ToolExecutionError(
    fields.error,
    fields.error_code,
    fields.retryable,
    fields.outcome as ToolFailureOutcome,
    closedRecoveryFields(fields),
  );
}

/** Durable, fail-closed tool claims backed by ``kaji_tool_idempotency``. */
export class PostgresToolIdempotencyLedger implements ToolIdempotencyLedger {
  private sql: Sql | undefined;
  private readonly running = new Map<string, { resolve: (outcome: ToolLedgerOutcome) => void }>();

  constructor(
    private readonly url: string,
    private readonly pollIntervalMs = 50,
  ) {
    if (url.trim().length === 0) throw new TypeError("url must be a non-empty string");
    if (!Number.isInteger(pollIntervalMs) || pollIntervalMs < 1) {
      throw new RangeError("pollIntervalMs must be a positive integer");
    }
  }

  private async client(): Promise<Sql> {
    if (this.sql === undefined) {
      const { default: postgres } = await import("postgres");
      this.sql = postgres(this.url);
    }
    return this.sql;
  }

  async claim(
    sessionId: string,
    toolCallId: string,
    fingerprint: string,
  ): Promise<ToolClaimResult> {
    const sql = await this.client();
    const token = randomUUID();
    while (true) {
      const inserted = (await sql`
        INSERT INTO kaji_tool_idempotency
          (session_id, tool_call_id, fingerprint, status, claim_token)
        VALUES (${sessionId}, ${toolCallId}, ${fingerprint}, 'running', ${token})
        ON CONFLICT (session_id, tool_call_id) DO NOTHING
        RETURNING claim_token
      `) as Array<{ claim_token: string }>;
      if (inserted[0] !== undefined) {
        let resolve!: (outcome: ToolLedgerOutcome) => void;
        new Promise<ToolLedgerOutcome>((done) => {
          resolve = done;
        });
        const claim = Object.freeze({ sessionId, toolCallId, fingerprint, claimToken: token });
        this.running.set(token, { resolve });
        return { status: "owner", claim };
      }
      const rows = (await sql`
        SELECT fingerprint, status, claim_token, result_json, error_json, started_at
        FROM kaji_tool_idempotency
        WHERE session_id = ${sessionId} AND tool_call_id = ${toolCallId}
      `) as Row[];
      const row = rows[0];
      if (row === undefined) continue;
      if (row.fingerprint !== fingerprint) throw new IdempotencyConflictError();
      if (row.status === "completed")
        return { status: "completed", result: decodeJson(row.result_json) };
      if (row.status === "unknown")
        return { status: "unknown", error: errorFromJson(row.error_json) };
      return {
        status: "running",
        outcome: this.runningOutcome(sessionId, toolCallId, row.claim_token),
      };
    }
  }

  async complete(claim: ToolIdempotencyClaim, result: unknown): Promise<void> {
    const detached = durableJsonSnapshot(result, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES);
    await this.transition(
      (sql: Sql) => sql`
        UPDATE kaji_tool_idempotency
        SET status = 'completed', result_json = ${JSON.stringify(detached)}::jsonb,
            error_json = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ${claim.sessionId} AND tool_call_id = ${claim.toolCallId}
          AND claim_token = ${this.claimToken(claim)} AND status = 'running'
      `,
    );
    this.settle(claim, { status: "completed", result: detached });
  }

  async retryableFailure(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    await this.transition(
      (sql: Sql) => sql`
        DELETE FROM kaji_tool_idempotency
        WHERE session_id = ${claim.sessionId} AND tool_call_id = ${claim.toolCallId}
          AND claim_token = ${this.claimToken(claim)} AND status = 'running'
      `,
    );
    this.settle(claim, { status: "failed", error });
  }

  async unknownOutcome(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    await this.transition(
      (sql: Sql) => sql`
        UPDATE kaji_tool_idempotency
        SET status = 'unknown', error_json = ${JSON.stringify(errorJson(error))}::jsonb,
            result_json = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ${claim.sessionId} AND tool_call_id = ${claim.toolCallId}
          AND claim_token = ${this.claimToken(claim)} AND status = 'running'
      `,
    );
    this.settle(claim, { status: "failed", error });
  }

  async releaseCompleted(sessionId: string): Promise<number> {
    return this.release(sessionId, "status = 'completed'");
  }

  async releaseSettled(sessionId: string): Promise<number> {
    return this.release(sessionId, "status <> 'running'");
  }

  async reconcileCompleted(
    sessionId: string,
    toolCallId: string,
    result: unknown,
  ): Promise<boolean> {
    const sql = await this.client();
    const detached = durableJsonSnapshot(result, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES);
    const updated = await sql`
      UPDATE kaji_tool_idempotency
      SET status = 'completed', result_json = ${JSON.stringify(detached)}::jsonb,
          error_json = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE session_id = ${sessionId} AND tool_call_id = ${toolCallId} AND status = 'running'
    `;
    return updated.count === 1;
  }

  async reconcileRelease(sessionId: string, toolCallId: string): Promise<boolean> {
    const sql = await this.client();
    const deleted = await sql`
      DELETE FROM kaji_tool_idempotency
      WHERE session_id = ${sessionId} AND tool_call_id = ${toolCallId} AND status = 'running'
    `;
    return deleted.count === 1;
  }

  async close(): Promise<void> {
    await this.sql?.end({ timeout: 5 });
    this.sql = undefined;
  }

  private async transition(execute: (sql: Sql) => Promise<{ count: number }>): Promise<void> {
    const result = await execute(await this.client());
    if (result.count !== 1) throw new Error("Tool idempotency claim is no longer running");
  }

  private claimToken(claim: ToolIdempotencyClaim): string {
    const token = (claim as ToolIdempotencyClaim & { claimToken?: unknown }).claimToken;
    if (typeof token !== "string")
      throw new Error("Tool idempotency claim does not belong to this ledger");
    return token;
  }

  private settle(claim: ToolIdempotencyClaim, outcome: ToolLedgerOutcome): void {
    const token = this.claimToken(claim);
    const running = this.running.get(token);
    this.running.delete(token);
    running?.resolve(outcome);
  }

  private async runningOutcome(
    sessionId: string,
    toolCallId: string,
    token: string,
  ): Promise<ToolLedgerOutcome> {
    const local = this.running.get(token);
    if (local !== undefined) {
      return new Promise<ToolLedgerOutcome>((resolve) => {
        const original = local.resolve;
        local.resolve = (outcome) => {
          original(outcome);
          resolve(outcome);
        };
      });
    }
    const sql = await this.client();
    while (true) {
      const rows = (await sql`
        SELECT status, result_json, error_json FROM kaji_tool_idempotency
        WHERE session_id = ${sessionId} AND tool_call_id = ${toolCallId} AND claim_token = ${token}
      `) as Array<Pick<Row, "status" | "result_json" | "error_json">>;
      const row = rows[0];
      if (row === undefined) return { status: "failed", error: ambiguousError() };
      if (row.status === "completed")
        return { status: "completed", result: decodeJson(row.result_json) };
      if (row.status === "unknown")
        return { status: "failed", error: errorFromJson(row.error_json) };
      await new Promise<void>((resolve) => setTimeout(resolve, this.pollIntervalMs));
    }
  }

  private async release(sessionId: string, condition: string): Promise<number> {
    const sql = await this.client();
    const deleted = await sql.unsafe(
      `DELETE FROM kaji_tool_idempotency WHERE session_id = $1 AND ${condition}`,
      [sessionId],
    );
    return deleted.count;
  }
}
