import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { findOutdated } from "../../src/commands/upgrade.js";

describe("upgrade.findOutdated", () => {
  it("returns packages where current < latest", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-up-"));
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({
        dependencies: { "@agentkit/sdk": "0.1.0", "@agentkit/cli": "0.1.0", other: "1.0.0" },
      }),
    );
    const fakeFetch = vi.fn(async (name: string) => (name === "@agentkit/sdk" ? "0.2.0" : "0.1.0"));
    const out = await findOutdated(dir, fakeFetch);
    expect(out).toEqual([
      { name: "@agentkit/sdk", current: "0.1.0", latest: "0.2.0", depType: "prod" },
    ]);
  });
});
