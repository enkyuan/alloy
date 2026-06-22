import { describe, expect, it } from "vitest";
import { secret } from "../../src/commands/secret.js";

describe("secret command", () => {
  it("prints a 64-hex-char secret with the default name", async () => {
    const logs: string[] = [];
    const orig = console.log;
    console.log = (...a) => logs.push(a.join(" "));
    try {
      await secret.parseAsync(["node", "agentkit"]);
    } finally {
      console.log = orig;
    }
    const joined = logs.join("\n");
    expect(joined).toMatch(/AGENTKIT_SECRET=[0-9a-f]{64}/);
  });

  it("supports --json", async () => {
    const logs: string[] = [];
    const orig = console.log;
    console.log = (...a) => logs.push(a.join(" "));
    try {
      await secret.parseAsync(["node", "agentkit", "--json"]);
    } finally {
      console.log = orig;
    }
    const json = JSON.parse(logs.join(""));
    expect(json.name).toBe("AGENTKIT_SECRET");
    expect(json.value).toMatch(/^[0-9a-f]{64}$/);
  });
});
