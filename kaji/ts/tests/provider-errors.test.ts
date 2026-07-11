import { describe, expect, it } from "vitest";

import {
  ProviderAPIError,
  ProviderConnectionError,
  normalizeProviderError,
  providerAPIErrorFromUnknown,
} from "@/providers/errors";

describe("provider error semantics", () => {
  it("classifies network-coded transport failures before normalization", () => {
    const cause = Object.assign(new Error("private transport detail"), {
      code: "ECONNRESET",
    });

    const error = providerAPIErrorFromUnknown("openai", cause, "stream");

    expect(error).toBeInstanceOf(ProviderConnectionError);
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

    expect(normalizeProviderError(error)).toEqual({
      type: "rate_limit",
      code: "PROVIDER_RATE_LIMITED",
      service: "anthropic",
      action: "api call",
      status: 429,
      retryable: true,
    });
  });
});
