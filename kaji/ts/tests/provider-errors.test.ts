import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderError,
  ProviderRateLimitedError,
  normalizeProviderError,
  type NormalizedProviderError,
} from "@kaji/sdk";
import { providerAPIErrorFromUnknown } from "@/providers/errors";
import { inspect } from "node:util";

interface ProviderNormalizationCase {
  name: string;
  source: "api" | "config" | "network";
  status: number | null;
  expected: NormalizedProviderError;
}

const providerNormalizationCases = (
  JSON.parse(
    readFileSync(
      new URL("../../contracts/errors/provider-normalization.json", import.meta.url),
      "utf8",
    ),
  ) as { cases: ProviderNormalizationCase[] }
).cases;

describe("provider error semantics", () => {
  it("exports the normalized error boundary from the package root", () => {
    const normalized: NormalizedProviderError = normalizeProviderError(
      new ProviderConfigError("safe public message"),
    );
    expect(normalized.code).toBe("PROVIDER_CONFIG_ERROR");
  });

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

  it.each(providerNormalizationCases)("matches shared normalization case $name", (testCase) => {
    let error: ProviderError;
    if (testCase.source === "config") {
      error = new ProviderConfigError("private", { service: "fixture" });
    } else if (testCase.source === "network") {
      error = new ProviderConnectionError("private", {
        service: "fixture",
        action: "stream",
      });
    } else {
      error = new ProviderAPIError("private", {
        service: "fixture",
        action: "request",
        ...(testCase.status === null ? {} : { statusCode: testCase.status }),
        responseText: "private response",
        cause: new Error("private cause"),
      });
    }

    expect(error).toBeInstanceOf(ProviderError);
    expect(normalizeProviderError(error)).toEqual(testCase.expected);
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
