/**
 * Tests for the `kaji` CLI dispatch table.
 *
 * Drives `runCli(argv, opts)` directly so we exercise the dispatch shape
 * without spawning a node subprocess.
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { writeScaffoldFiles } from "@/cli/init";
import { COMMANDS, runCli } from "@/cli/index";

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

  it("prints help and exits 0 when no command is given", async () => {
    const lines: string[] = [];
    const code = await runCli([], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/usage: kaji/);
  });

  it("exits 2 on unknown command and prints help to stderr", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await runCli(["frobnicate"], {
      registryRoot: "/tmp",
      log: (m) => stdout.push(m),
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(2);
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

  it("accepts global no-color and verbose flags before init", async () => {
    const lines: string[] = [];
    const out = mkdtempSync(join(tmpdir(), "kaji-cli-global-"));
    const code = await runCli(["--no-color", "--verbose", "init", out, "--yes"], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
      initWorkerRunner: (target, files, force) => writeScaffoldFiles(target, files, force),
    });

    expect(code).toBe(0);
    expect(lines.join("\n")).not.toContain("\x1b[");
  });

  it("rejects a global flag after the command as usage", async () => {
    const stderr: string[] = [];
    const code = await runCli(["init", "--verbose"], {
      registryRoot: "/tmp",
      log: () => {},
      err: (m) => stderr.push(m),
    });

    expect(code).toBe(2);
    expect(stderr.join("\n")).toContain("unknown argument: --verbose");
  });
});
