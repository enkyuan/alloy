import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));

function tsHelp(): string {
  return execFileSync("node", [resolve(__dirname, "..", "dist", "index.js"), "--help"], {
    encoding: "utf-8",
  });
}

function pyHelp(): string {
  return execFileSync("poetry", ["run", "agentkit", "--help"], {
    cwd: resolve(__dirname, "..", "..", "..", "agentkit", "sdk"),
    encoding: "utf-8",
  });
}

describe("CLI parity", () => {
  it("ts and python share the same subcommands (mcp is ts-only)", () => {
    const ts = tsHelp();
    const py = pyHelp();
    for (const cmd of ["init", "gen", "info", "secret", "upgrade", "doctor"]) {
      expect(ts).toContain(cmd);
      expect(py).toContain(cmd);
    }
    expect(ts).toContain("mcp");
  });
});
