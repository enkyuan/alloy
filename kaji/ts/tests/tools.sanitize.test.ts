import { describe, expect, it, vi } from "vitest";
import { providerSafeToolName } from "../src/tools/registry";

describe("providerSafeToolName", () => {
  it("invokes onMutate when the name is changed", () => {
    const onMutate = vi.fn();
    const out = providerSafeToolName("weather-api.v2", { onMutate });
    expect(out).not.toBe("weather-api.v2");
    expect(onMutate).toHaveBeenCalledTimes(1);
    expect(onMutate).toHaveBeenCalledWith("weather-api.v2", out);
  });

  it("does not invoke onMutate when the name is already provider-safe", () => {
    const onMutate = vi.fn();
    const out = providerSafeToolName("weather_api", { onMutate });
    expect(out).toBe("weather_api");
    expect(onMutate).not.toHaveBeenCalled();
  });

  it("emits no side effect when onMutate is omitted", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const out = providerSafeToolName("weather.api");
      expect(out).toBe("weather_api");
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });

  it("preserves the existing transform (dots, dashes, leading underscores)", () => {
    expect(providerSafeToolName("a.b.c")).toBe("a_b_c");
    expect(providerSafeToolName("a-b-c")).toBe("a-b-c");
    expect(providerSafeToolName("___foo___")).toBe("foo");
    expect(providerSafeToolName("$$$")).toBe("tool");
  });
});
