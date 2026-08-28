import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { info } from "../../src/commands/info.js";

function tempProject(pkg: Record<string, unknown>): string {
  const dir = mkdtempSync(join(tmpdir(), "kaji-info-"));
  writeFileSync(join(dir, "package.json"), JSON.stringify(pkg));
  return dir;
}

describe("info command", () => {
  it("emits json with detected frameworks and kaji packages", async () => {
    const dir = tempProject({
      name: "x",
      dependencies: { next: "15.0.0", kaji: "0.1.0", openai: "6.0.0" },
    });
    const logs: string[] = [];
    const orig = console.log;
    console.log = (...a) => logs.push(a.join(" "));
    try {
      await info.parseAsync(["node", "kaji", "--cwd", dir, "--json"]);
    } finally {
      console.log = orig;
    }
    const out = JSON.parse(logs.join(""));
    expect(out.frameworks).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "next", version: "15.0.0" })]),
    );
    expect(out.kaji.packages).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "kaji", version: "0.1.0" })]),
    );
    expect(out.providers).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "openai", version: "6.0.0" })]),
    );
  });
});
