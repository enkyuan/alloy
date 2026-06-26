/**
 * Tests for the `kaji` CLI dispatch table.
 *
 * Drives `runCli(argv, opts)` directly so we exercise the dispatch shape
 * without spawning a node subprocess.
 */
import { describe, expect, it } from "vitest";
import { COMMANDS, runCli } from "../src/cli/index";

describe("kaji cli dispatch", () => {
  it("prints help and exits 0 on --help", async () => {
    const lines: string[] = [];
    const code = await runCli(["--help"], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(0);
    const out = lines.join("\n");
    expect(out).toMatch(/usage: kaji/);
    expect(out).toMatch(/\badd\b/);
  });

  it("exits 1 with usage when no command given", async () => {
    const lines: string[] = [];
    const code = await runCli([], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(1);
    expect(lines.join("\n")).toMatch(/usage: kaji/);
  });

  it("exits 1 on unknown command and prints help to stderr", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await runCli(["frobnicate"], {
      registryRoot: "/tmp",
      log: (m) => stdout.push(m),
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/Unknown command: frobnicate/);
    expect(stderr.join("\n")).toMatch(/usage: kaji/);
  });

  it("prints per-command usage on `<cmd> --help`", async () => {
    const lines: string[] = [];
    const code = await runCli(["add", "--help"], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(0);
    expect(lines.join("\n")).toBe(`usage: ${COMMANDS.add!.usage}`);
  });
});
