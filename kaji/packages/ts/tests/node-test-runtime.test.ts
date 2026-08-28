import { describe, expect, it } from "vitest";

describe("canonical package test runtime", () => {
  it("runs Vitest on Node even when launched through bun run", () => {
    expect({
      bunGlobal: "Bun" in globalThis,
      runtime: process.release.name,
      executable: process.execPath,
    }).toEqual({
      bunGlobal: false,
      runtime: "node",
      executable: expect.stringContaining("node"),
    });
  });
});
