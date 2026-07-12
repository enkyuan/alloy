import { describe, expect, it } from "vitest";

import { EventType } from "@/events/types";
import { ToolCallFailed } from "@/events/schemas";
import {
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationTransportError,
} from "@/integrations/errors";
import { recoveryForReason } from "@/integrations/recovery";
import { ToolPlanner } from "@/tools/planner";
import type { ToolSpec } from "@/tools/registry";

const tool: ToolSpec = {
  name: "integration",
  description: "integration",
  parameters: {},
  risk: "read",
};

async function run(error: Error) {
  const events: unknown[] = [];
  const planner = new ToolPlanner({
    executor: async () => {
      throw error;
    },
    specs: new Map([[tool.name, tool]]),
  });
  const results = await planner.executeBatch(
    "session",
    [{ id: "call", name: "integration", arguments: {} }],
    async (event) => {
      events.push(event);
    },
    "turn",
    { principalId: "principal", requestId: "request", traceId: "trace" },
  );
  return {
    result: results[0]!,
    event: events.find(
      (event): event is Record<string, unknown> =>
        typeof event === "object" &&
        event !== null &&
        (event as { type?: unknown }).type === EventType.TOOL_CALL_FAILED,
    )!,
  };
}

describe("integration failure recovery", () => {
  it("preserves a provider-confirmed API rejection as failed and nonretryable", async () => {
    const recovery = recoveryForReason("api_rejected");
    const { result, event } = await run(new IntegrationExecutionError("api_rejected"));

    const expected = {
      error_code: "INTEGRATION_API_ERROR",
      retryable: false,
      outcome: "failed",
      reason_code: "api_rejected",
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    };
    expect(result).toMatchObject(expected);
    expect(event).toMatchObject(expected);
    expect(() => ToolCallFailed.parse({ ...event, ...expected })).not.toThrow();
  });

  it("preserves certified recovery in results, events, and idempotent storage", async () => {
    const recovery = recoveryForReason("github_token_missing");
    const { result, event } = await run(new IntegrationAuthRequiredError("github_token_missing"));

    expect(result).toMatchObject({
      reason_code: "github_token_missing",
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    });
    expect(event).toMatchObject({
      reason_code: "github_token_missing",
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    });
  });

  it("keeps only the closed tuple for an unknown mutation", async () => {
    const recovery = recoveryForReason("github_mutation_unknown");
    const { result, event } = await run(
      new IntegrationTransportError("TOOL_EXECUTION_FAILED", "github_mutation_unknown"),
    );

    expect(result).toMatchObject({
      error: "Tool execution failed with an unknown outcome",
      outcome: "unknown",
      reason_code: "github_mutation_unknown",
      recovery_code: recovery.recoveryCode,
    });
    expect(event).toMatchObject({ doc_url: recovery.docUrl });
  });

  it.each([
    ["INTEGRATION_REDIRECT_REJECTED", "redirect_rejected"],
    ["INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded"],
  ] as const)(
    "preserves canonical transport code %s with an unknown outcome",
    async (errorCode, reasonCode) => {
      const recovery = recoveryForReason(reasonCode);
      const { result, event } = await run(new IntegrationTransportError(errorCode, reasonCode));

      const expected = {
        error_code: errorCode,
        retryable: false,
        outcome: "unknown",
        reason_code: reasonCode,
        recovery_code: recovery.recoveryCode,
        doc_url: recovery.docUrl,
      };
      expect(result).toMatchObject(expected);
      expect(event).toMatchObject(expected);
    },
  );

  it("does not trust a mismatched transport code", async () => {
    const recovery = recoveryForReason("redirect_rejected");
    const hostile = Object.assign(new Error("hostile transport"), {
      error_code: "INTEGRATION_RESPONSE_LIMIT",
      reason_code: "redirect_rejected",
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    });

    const { result, event } = await run(hostile);

    expect(result).toMatchObject({ error_code: "TOOL_EXECUTION_FAILED", outcome: "unknown" });
    expect(result).not.toHaveProperty("reason_code");
    expect(event).toMatchObject({ error_code: "TOOL_EXECUTION_FAILED" });
    expect(event).not.toHaveProperty("reason_code");
  });

  it("rejects partial or mismatched recovery tuples", () => {
    const base = {
      type: EventType.TOOL_CALL_FAILED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "integration",
      tool_call_id: "call",
      error: "Tool execution failed",
    };
    expect(() => ToolCallFailed.parse({ ...base, reason_code: "github_token_missing" })).toThrow();
    expect(() =>
      ToolCallFailed.parse({
        ...base,
        reason_code: "github_token_missing",
        recovery_code: "CONNECT_GMAIL",
        doc_url: recoveryForReason("github_token_missing").docUrl,
      }),
    ).toThrow();
    const recovery = recoveryForReason("redirect_rejected");
    expect(() =>
      ToolCallFailed.parse({
        ...base,
        error_code: "INTEGRATION_RESPONSE_LIMIT",
        reason_code: "redirect_rejected",
        recovery_code: recovery.recoveryCode,
        doc_url: recovery.docUrl,
      }),
    ).toThrow();
  });
});
