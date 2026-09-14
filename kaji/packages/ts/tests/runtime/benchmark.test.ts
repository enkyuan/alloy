import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const benchmark = fileURLToPath(new URL("../../benchmarks/runtime/benchmark.ts", import.meta.url));
const soak = fileURLToPath(new URL("../../benchmarks/runtime/soak.ts", import.meta.url));

describe("removed runtime benchmark harness", () => {
  it("keeps the benchmark harness and soak runner out of the TypeScript package", () => {
    expect(existsSync(benchmark)).toBe(false);
    expect(existsSync(soak)).toBe(false);
  });
});
