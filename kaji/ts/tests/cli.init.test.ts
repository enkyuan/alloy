/**
 * Tests for `kaji init`. Scaffolds into an ephemeral tmpdir and checks file
 * contents + overwrite semantics.
 */
import { describe, expect, it } from "vitest";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { init } from "@/cli/init";

describe("kaji init", () => {
  it("scaffolds package.json, tsconfig.json, agent.ts, .env.example", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-"));
    const lines: string[] = [];
    const code = await init(["--out", out], { registryRoot: "", log: (m) => lines.push(m) });
    expect(code).toBe(0);
    for (const f of ["package.json", "tsconfig.json", "agent.ts", ".env.example"]) {
      expect(existsSync(join(out, f))).toBe(true);
    }
    const pkg = JSON.parse(readFileSync(join(out, "package.json"), "utf8"));
    expect(pkg.dependencies).toHaveProperty("@kaji/sdk");
    // `openai` is an optional peer dep that OpenAIProvider imports
    // dynamically; without it, `bun install && bun start` fails with
    // "OpenAI provider requires the openai package". The scaffold defaults
    // to the OpenAI provider so the dep must be included.
    expect(pkg.dependencies).toHaveProperty("openai");
    expect(pkg.scripts.start).toBe("tsx agent.ts");
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toMatch(/from "@kaji\/sdk"/);
    expect(lines.join("\n")).toMatch(/Next: cd .* && bun install && bun start/);
  });

  it("refuses to overwrite an existing file without --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-conflict-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const stderr: string[] = [];
    const code = await init(["--out", out], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/refusing to overwrite without --force/);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toBe("// existing");
  });

  it("overwrites with --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const code = await init(["--out", out, "--force"], { registryRoot: "", log: () => {} });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).not.toBe("// existing");
  });

  it("creates the out directory if it does not exist", async () => {
    const parent = mkdtempSync(join(tmpdir(), "kaji-init-parent-"));
    const out = join(parent, "nested", "dir");
    const code = await init(["--out", out], { registryRoot: "", log: () => {} });
    expect(code).toBe(0);
    expect(existsSync(join(out, "package.json"))).toBe(true);
  });

  it("errors when --out has no value (trailing position)", async () => {
    const stderr: string[] = [];
    const code = await init(["--out"], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/--out requires a directory argument/);
  });

  it("errors when --out is followed by another flag", async () => {
    const stderr: string[] = [];
    const code = await init(["--out", "--force"], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/--out requires a directory argument/);
  });

  it("errors on unknown arguments", async () => {
    const stderr: string[] = [];
    const code = await init(["weirdarg"], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/unknown argument: weirdarg/);
  });
});
