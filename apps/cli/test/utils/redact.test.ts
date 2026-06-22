import { describe, expect, it } from "vitest";
import { redact } from "../../src/utils/redact.js";

describe("redact", () => {
  it("redacts keys that match the sensitive list", () => {
    const input = { apiKey: "sk-123", baseURL: "https://x.test", nested: { secret: "abc" } };
    const out = redact(input) as Record<string, unknown>;
    expect(out.apiKey).toBe("[REDACTED]");
    expect(out.baseURL).toBe("https://x.test");
    expect((out.nested as any).secret).toBe("[REDACTED]");
  });

  it("preserves allowlisted keys with sensitive-sounding names", () => {
    const out = redact({ callbackURL: "https://x.test/cb" }) as Record<string, unknown>;
    expect(out.callbackURL).toBe("https://x.test/cb");
  });

  it("handles arrays and primitives", () => {
    expect(redact([1, 2, "x"])).toEqual([1, 2, "x"]);
    expect(redact(null)).toBe(null);
  });
});
