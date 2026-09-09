import { expect, it } from "vitest";

import { postgresLockKey } from "@/backends/postgres";

it("derives the shared signed advisory-lock key", () => {
  expect(postgresLockKey("same")).toBe(677529369334489940n);
});
