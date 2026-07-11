import { describe, expect, it } from "vitest";

import {
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderRateLimitedError,
  normalizeProviderError,
  providerAPIErrorFromUnknown,
} from "@/providers/errors";
import { inspect } from "node:util";

describe("provider error semantics", () => {
  it("classifies network-coded transport failures before normalization", () => {
    const cause = Object.assign(new Error("private transport detail"), {
      code: "ECONNRESET",
    });

    const error = providerAPIErrorFromUnknown("openai", cause, "stream");

    expect(error).toBeInstanceOf(ProviderConnectionError);
    expect(error.cause).toBeUndefined();
    expect(normalizeProviderError(error)).toEqual({
      type: "network",
      code: "PROVIDER_NETWORK_ERROR",
      service: "openai",
      action: "stream",
      status: null,
      retryable: true,
    });
  });

  it("classifies vendor connection errors without importing a vendor SDK", () => {
    class APIConnectionError extends Error {}

    const error = providerAPIErrorFromUnknown(
      "anthropic",
      new APIConnectionError("private vendor detail"),
      "request",
    );

    expect(error).toBeInstanceOf(ProviderConnectionError);
    expect(normalizeProviderError(error).code).toBe("PROVIDER_NETWORK_ERROR");
  });

  it("normalizes HTTP semantics without private response text", () => {
    const error = new ProviderAPIError("private", {
      service: "anthropic",
      statusCode: 429,
      responseText: "private response",
    });

    expect(error.responseText).toBeUndefined();
    expect(normalizeProviderError(error)).toEqual({
      type: "rate_limit",
      code: "PROVIDER_RATE_LIMITED",
      service: "anthropic",
      action: "api call",
      status: 429,
      retryable: true,
    });
  });

  it.each([
    {
      source: new ProviderConfigError("sk-config-secret", { service: "vendor" }),
      expectedType: ProviderConfigError,
      expectedCode: "PROVIDER_CONFIG_ERROR",
    },
    {
      source: new ProviderConnectionError("sk-network-secret", { service: "vendor" }),
      expectedType: ProviderConnectionError,
      expectedCode: "PROVIDER_NETWORK_ERROR",
    },
    {
      source: new ProviderRateLimitedError("sk-rate-secret", {
        service: "vendor",
        retryAfterMs: 250,
        attempts: 2,
      }),
      expectedType: ProviderRateLimitedError,
      expectedCode: "PROVIDER_RATE_LIMITED",
    },
    {
      source: new ProviderAPIError("sk-auth-secret", {
        service: "vendor",
        statusCode: 401,
        responseText: "sk-response-secret",
        cause: new Error("sk-cause-secret"),
      }),
      expectedType: ProviderAPIError,
      expectedCode: "PROVIDER_AUTH_ERROR",
    },
  ])(
    "re-normalizes caller-created $expectedCode errors",
    ({ source, expectedType, expectedCode }) => {
      const normalized = providerAPIErrorFromUnknown("openai", source, "stream");

      expect(normalized).toBeInstanceOf(expectedType);
      expect(normalized).not.toBe(source);
      expect(normalizeProviderError(normalized).code).toBe(expectedCode);
      expect(normalized.service).toBe("openai");
      expect(normalized.cause).toBeUndefined();
      expect(normalized.responseText).toBeUndefined();
      expect(inspect(normalized, { depth: 5 })).not.toContain("sk-");
    },
  );
});
