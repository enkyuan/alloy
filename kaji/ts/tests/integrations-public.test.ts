import { describe, expect, it } from "vitest";

import {
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationPolicyError,
  IntegrationRateLimitedError,
  IntegrationTransientReadError,
  createGitHubRequester,
  createGmailRequester,
  snapshotIntegrationResult,
} from "@kaji/sdk/integrations";
import * as integrations from "@kaji/sdk/integrations";

describe("experimental integrations subpath", () => {
  it("exports exactly the five certified classes at runtime", () => {
    expect(Object.keys(integrations).sort()).toEqual(
      [
        "IntegrationAuthRequiredError",
        "IntegrationExecutionError",
        "IntegrationPolicyError",
        "IntegrationRateLimitedError",
        "IntegrationTransientReadError",
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
