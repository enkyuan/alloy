import { existsSync, mkdtempSync, readdirSync, readFileSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  init,
  ScaffoldRollbackError,
  scaffoldRecoveryDirectory,
  writeScaffoldFiles,
} from "@/cli/init";
import type { RunOptions } from "@/cli/index";

function makeOptions(overrides: Partial<RunOptions> = {}): RunOptions {
  return {
    registryRoot: "unused-by-init",
    log: () => {},
    err: () => {},
    initWorkerRunner: (target, files, force) => writeScaffoldFiles(target, files, force),
    ...overrides,
  };
}

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "kaji-init-scaffold-"));
}

const expectedScaffoldFiles = ["package.json", "tsconfig.json", "capability.ts", ".env.example"];

describe("kaji init scaffold (in-process)", () => {
  it("writes the capability scaffold and prints next steps", async () => {
    const out = scratch();
    const logs: string[] = [];
    const exit = await init([out], makeOptions({ log: (m) => logs.push(m) }));

    expect(exit).toBe(0);
    expect(readdirSync(out).sort()).toEqual([...expectedScaffoldFiles].sort());
    const capability = readFileSync(join(out, "capability.ts"), "utf8");
    expect(capability).toContain("Kaji.execute");
    expect(capability).toContain("principal");
    expect(capability).toContain("capabilityResult");
    expect(capability).not.toContain("AgentBuilder");
    const manifest = JSON.parse(readFileSync(join(out, "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      scripts?: Record<string, string>;
    };
    expect(manifest.dependencies?.zod).toContain(">=4.3");
    expect(manifest.dependencies?.["@irogane/kaji"]).toBeDefined();
    expect(manifest.scripts?.start ?? "").toContain("dotenvx");
    expect(logs.some((m) => m.includes("Next: "))).toBe(true);
  });

  it("refuses to overwrite existing scaffold files without --force", async () => {
    const out = scratch();
    const errors: string[] = [];
    const first = await init([out], makeOptions());
    expect(first).toBe(0);

    const exit = await init([out], makeOptions({ err: (m) => errors.push(m) }));
    expect(exit).toBe(1);
    expect(errors.some((m) => m.includes("refusing to overwrite without --force"))).toBe(true);
  });

  it("overwrites existing scaffold files with --force", async () => {
    const out = scratch();
    expect(await init([out], makeOptions())).toBe(0);
    const capability = join(out, "capability.ts");
    const tampered = "// custom\n" + readFileSync(capability, "utf8");
    const forceErrors: string[] = [];
    const exit = await init([out, "--force"], makeOptions({ err: (m) => forceErrors.push(m) }));

    expect(forceErrors).toEqual([]);
    expect(exit).toBe(0);
    expect(readFileSync(capability, "utf8")).not.toBe(tampered);
    expect(existsSync(join(out, "capability.ts"))).toBe(true);
  });

  it("rejects --template agent, unknown options, and unknown providers with usage exit code", async () => {
    const out = scratch();
    for (const argv of [
      ["--template", "agent"],
      ["--template", "capability", "--provider", "mock"],
      ["--unknown"],
    ]) {
      const errors: string[] = [];
      const exit = await init([out, ...argv], makeOptions({ err: (m) => errors.push(m) }));
      expect(exit).toBe(2);
      expect(errors.some((m) => m.startsWith("Error:"))).toBe(true);
      expect(existsSync(join(out, "capability.ts"))).toBe(false);
    }
  });

  it("refuses symbolic-link scaffold destinations", async () => {
    const out = scratch();
    symlinkSync(join(out, "elsewhere"), join(out, "capability.ts"));

    const errors: string[] = [];
    const exit = await init([out], makeOptions({ err: (m) => errors.push(m) }));
    expect(exit).toBe(1);
    expect(errors.some((m) => m.includes("symbolic links are not allowed"))).toBe(true);
  });

  it("fails cleanly and leaves no scaffold when writing is interrupted", async () => {
    const out = scratch();
    const failures: string[] = [];
    const exit = await init(
      [out],
      makeOptions({
        initWorkerRunner: (target, files, force) =>
          writeScaffoldFiles(target, files, force, {
            beforePublish: () => {
              throw new Error("simulated publish failure");
            },
          }),
        err: (m) => failures.push(m),
      }),
    );

    expect(exit).toBe(1);
    expect(failures.some((m) => m.includes("kaji init failed while writing the scaffold"))).toBe(
      true,
    );
    expect(existsSync(join(out, "capability.ts"))).toBe(false);
    expect(readdirSync(out).filter((name) => name.startsWith(".kaji"))).toEqual([]);
  });

  it("preserves the original scaffold when a forced publication fails", async () => {
    const out = scratch();
    expect(await init([out], makeOptions())).toBe(0);
    const original = readFileSync(join(out, "capability.ts"), "utf8");

    const failures: string[] = [];
    const exit = await init(
      [out, "--force"],
      makeOptions({
        initWorkerRunner: (target, files, force) =>
          writeScaffoldFiles(target, files, force, {
            publish: async () => {
              throw new Error("simulated publication drift");
            },
          }),
        err: (m) => failures.push(m),
      }),
    );

    expect(exit).toBe(1);
    expect(failures.some((m) => m.includes("kaji init failed while writing the scaffold"))).toBe(
      true,
    );
    expect(readFileSync(join(out, "capability.ts"), "utf8")).toBe(original);
    expect(readdirSync(out).filter((name) => name.startsWith(".kaji"))).toEqual([]);
  });

  it("surfaces the recovery directory helper for rollback errors", () => {
    const error = new ScaffoldRollbackError(".kaji-scaffold-backup-abc123");
    expect(scaffoldRecoveryDirectory(error)).toBe(".kaji-scaffold-backup-abc123");
    expect(scaffoldRecoveryDirectory(new Error("other"))).toBeUndefined();
  });
});
