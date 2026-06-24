import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { runChecks } from "../../src/commands/doctor.js";

describe("doctor.runChecks", () => {
  it("flags missing provider env", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "@kaji/sdk": "0.1.0" } }),
    );
    const out = runChecks({ cwd: dir, env: {}, nodeVersion: "v22.0.0" });
    expect(out.failed).toBe(true);
    expect(out.checks.find((c) => c.name === "provider key")?.ok).toBe(false);
  });

  it("passes when sdk and provider key are present", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "@kaji/sdk": "0.1.0" } }),
    );
    const out = runChecks({ cwd: dir, env: { OPENAI_API_KEY: "sk" }, nodeVersion: "v22.0.0" });
    expect(out.failed).toBe(false);
  });
});
