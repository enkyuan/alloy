import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const distPath = resolve(__dirname, "..", "dist", "index.js");
const sdkPath = resolve(__dirname, "..", "..", "..", "kaji", "sdk");

function hasPoetry(): boolean {
  try {
    execFileSync("poetry", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

const canRun = existsSync(distPath) && hasPoetry();

describe.skipIf(!canRun)("CLI parity", () => {
  it("ts and python share the same subcommands (mcp is ts-only)", () => {
    const ts = execFileSync("node", [distPath, "--help"], { encoding: "utf-8" });
    const py = execFileSync("poetry", ["run", "kaji", "--help"], {
      cwd: sdkPath,
      encoding: "utf-8",
    });
    for (const cmd of ["init", "gen", "info", "secret", "upgrade", "doctor"]) {
      expect(ts).toContain(cmd);
      expect(py).toContain(cmd);
    }
    expect(ts).toContain("mcp");
  });
});
