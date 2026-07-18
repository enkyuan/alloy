import { describe, expect, it } from "vitest";

import {
  INTEGRATION_RECOVERY,
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationPolicyError,
  IntegrationRateLimitedError,
  IntegrationTransientReadError,
  closedRecoveryFields,
  createGitHubRequester,
  createGmailRequester,
  snapshotIntegrationResult,
  type IntegrationRecoveryFields,
  type IntegrationRecoveryReason,
} from "@kaji/sdk/integrations";
import * as integrations from "@kaji/sdk/integrations";

import { INTEGRATION_RECOVERY as INTERNAL_INTEGRATION_RECOVERY } from "@/contracts/integration-recovery";

describe("experimental integrations subpath", () => {
  it("exports exactly the certified runtime surface", () => {
    expect(Object.keys(integrations).sort()).toEqual(
      [
        "INTEGRATION_RECOVERY",
        "IntegrationAuthRequiredError",
        "IntegrationExecutionError",
        "IntegrationPolicyError",
        "IntegrationRateLimitedError",
        "IntegrationTransientReadError",
        "closedRecoveryFields",
        "createGitHubRequester",
        "createGmailRequester",
        "snapshotIntegrationResult",
      ].sort(),
    );
    expect(new IntegrationExecutionError("api_rejected")).toMatchObject({
      error_code: "INTEGRATION_API_ERROR",
      retryable: false,
      outcome: "failed",
      reason_code: "api_rejected",
    });
    expect(new IntegrationAuthRequiredError("github_token_missing")).toBeInstanceOf(Error);
    expect(new IntegrationRateLimitedError()).toMatchObject({
      error_code: "INTEGRATION_RATE_LIMITED",
      retryable: true,
      reason_code: "rate_limited",
    });
    expect(new IntegrationTransientReadError()).toMatchObject({
      error_code: "INTEGRATION_API_ERROR",
      retryable: true,
      reason_code: "transient_read_failed",
    });
    expect(new IntegrationPolicyError()).toBeInstanceOf(Error);
  });

  it("exports the exact frozen canonical recovery table", () => {
    const reason: IntegrationRecoveryReason = "github_token_missing";
    const fields = {
      reason_code: reason,
      recovery_code: "CONFIGURE_GITHUB_TOKEN",
      doc_url: "https://kaji.dev/docs/integrations/recovery-v1#github-token",
    } satisfies IntegrationRecoveryFields;

    expect(INTEGRATION_RECOVERY).toBe(INTERNAL_INTEGRATION_RECOVERY);
    expect(Object.isFrozen(INTEGRATION_RECOVERY)).toBe(true);
    expect(Object.keys(INTEGRATION_RECOVERY)).toHaveLength(15);
    expect(Object.values(INTEGRATION_RECOVERY).every(Object.isFrozen)).toBe(true);
    expect(
      new Set(Object.values(INTEGRATION_RECOVERY).flatMap((value) => Object.keys(value))),
    ).toEqual(new Set(["cause", "docUrl", "errorCode", "fix", "problem", "recoveryCode"]));
    expect(INTEGRATION_RECOVERY.github_token_missing.docUrl).toBe(fields.doc_url);
    expect(INTEGRATION_RECOVERY.rate_limited.docUrl).toBe(
      "https://kaji.dev/docs/integrations/recovery-v1#rate-limited",
    );
  });

  it("accepts only canonical recovery tuples and returns closed safe fields", () => {
    const recovery = INTEGRATION_RECOVERY.github_token_missing;
    const fields = {
      reason_code: "github_token_missing",
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    } as const;

    expect(closedRecoveryFields(fields)).toEqual(fields);
    expect(closedRecoveryFields({ ...fields, error_code: recovery.errorCode })).toEqual(fields);

    for (const candidate of [
      {},
      { reason_code: "unknown", recovery_code: fields.recovery_code, doc_url: fields.doc_url },
      { reason_code: fields.reason_code },
      { ...fields, recovery_code: "RECONNECT_GMAIL" },
      { ...fields, doc_url: INTEGRATION_RECOVERY.rate_limited.docUrl },
      { ...fields, error_code: INTEGRATION_RECOVERY.rate_limited.errorCode },
    ]) {
      expect(closedRecoveryFields(candidate)).toBeUndefined();
    }
    const closed = closedRecoveryFields({
      ...fields,
      error_code: recovery.errorCode,
      token: "secret",
      headers: { authorization: "Bearer secret" },
      principal: "user@example.com",
      repository: "owner/repo",
      arguments: { path: "secret" },
      result: { secret: true },
      raw_error: new Error("secret"),
    });
    expect(closed).toEqual(fields);
    expect(Object.keys(closed ?? {}).sort()).toEqual(["doc_url", "reason_code", "recovery_code"]);
    expect(integrations).not.toHaveProperty("isClosedRecoveryTuple");
  });

  it("fails closed when callers try to certify an unknown transport outcome", () => {
    const callerControlledConstructor = () => {
      return new IntegrationExecutionError(
        "github_mutation_unknown",
        // @ts-expect-error callers cannot select an error code or retryability
        "TOOL_EXECUTION_FAILED",
        true,
      );
    };
    expect(callerControlledConstructor).toBeTypeOf("function");
    const UnsafeConstructor = IntegrationExecutionError as unknown as new (
      reasonCode: string,
      errorCode?: string,
      retryable?: boolean,
    ) => IntegrationExecutionError;
    for (const reason of [
      "github_mutation_unknown",
      "gmail_mutation_unknown",
      "redirect_rejected",
      "response_limit_exceeded",
      "rate_limited",
      "transient_read_failed",
      "untrusted_reason",
    ]) {
      expect(() => new UnsafeConstructor(reason, "TOOL_EXECUTION_FAILED", true)).toThrow(TypeError);
    }
  });

  it("exposes provider-fixed requester factories", () => {
    const github = createGitHubRequester();
    const gmail = createGmailRequester();

    expect(github).toBeDefined();
    expect(gmail).toBeDefined();

    github.close();
    gmail.close();
  });

  it("returns a detached, deeply frozen durable snapshot", () => {
    const source = { nested: { value: [1, 2, 3] } };
    const snapshot = snapshotIntegrationResult(source) as typeof source;

    source.nested.value.push(4);
    expect(snapshot).toEqual({ nested: { value: [1, 2, 3] } });
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.nested)).toBe(true);
    expect(Object.isFrozen(snapshot.nested.value)).toBe(true);
  });

  it("rejects results beyond the durable 65536-byte cap", () => {
    expect(() => snapshotIntegrationResult("x".repeat(65_536))).toThrow();
  });
});
