/**
 * Tests for the `kaji add` CLI library.
 *
 * Drives `add(argv, opts)` against an ephemeral fixture registry on disk,
 * then a final case against the real registry shipped with the SDK.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { add } from "@/cli/add";

const __dirname = dirname(fileURLToPath(import.meta.url));
const schemaRoot = join(__dirname, "..", "registry");

function registryIndex(integrations: Record<string, string>): object {
  return {
    $schema: "./index.schema.json",
    version: "0.1.0",
    integrations: Object.fromEntries(
      Object.entries(integrations).map(([name, manifest]) => [
        name,
        { manifest, stability: "experimental", runtimes: ["typescript"] },
      ]),
    ),
  };
}

describe("kaji add", () => {
  let tmp: string;
  let registry: string;

  beforeEach(() => {
    tmp = mkdtempSync(join(tmpdir(), "kaji-add-"));
    registry = join(tmp, "registry");
    mkdirSync(join(registry, "demo-ts"), { recursive: true });
    mkdirSync(join(registry, "demo-py"), { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(
        registryIndex({
          "demo-ts": "demo-ts/manifest.json",
          "demo-py": "demo-py/manifest.json",
        }),
      ),
    );
    writeFileSync(
      join(registry, "demo-ts/manifest.json"),
      JSON.stringify({
        name: "demo-ts",
        version: "0.1.0",
        namespace: "demo",
        description: "demo ts",
        auth: { kind: "env", env: "DEMO_API_KEY" },
        files: ["demo.ts"],
        tools: [{ name: "ping", description: "ping", risk: "read" }],
      }),
    );
    writeFileSync(join(registry, "demo-ts/demo.ts"), "export const x = 1;\n");
    writeFileSync(
      join(registry, "demo-py/manifest.json"),
      JSON.stringify({
        name: "demo-py",
        version: "0.1.0",
        namespace: "demo",
        description: "demo py",
        auth: { kind: "none" },
        files: ["demo.py"],
        tools: [{ name: "noop", description: "noop", risk: "read" }],
      }),
    );
    writeFileSync(join(registry, "demo-py/demo.py"), "# py\n");
  });
  afterEach(() => rmSync(tmp, { recursive: true, force: true }));

  it("copies .ts files into --out", async () => {
    const out = join(tmp, "integrations");
    const code = await add(["demo-ts", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("skips integrations with no .ts files", async () => {
    const out = join(tmp, "integrations");
    const logs: string[] = [];
    const code = await add(["demo-py", "--out", out], {
      registryRoot: registry,
      schemaRoot,
      log: (m) => logs.push(m),
    });
    expect(code).toBe(0);
    expect(existsSync(join(out, "demo.py"))).toBe(false);
    expect(logs.some((l) => l.toLowerCase().includes("no typescript"))).toBe(true);
  });

  it("returns 1 on unknown name", async () => {
    const code = await add(["unknown", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("returns 1 on collision without --force", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["demo-ts", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("overwrites on collision with --force", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["demo-ts", "--out", out, "--force"], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("rejects a final destination symlink with --force without changing its victim", async () => {
    const out = join(tmp, "integrations");
    const victim = join(tmp, "victim.ts");
    mkdirSync(out, { recursive: true });
    writeFileSync(victim, "do not overwrite\n");
    symlinkSync(victim, join(out, "demo.ts"));
    const logs: string[] = [];

    const code = await add(["demo-ts", "--out", out, "--force"], {
      registryRoot: registry,
      schemaRoot,
      log: (message) => logs.push(message),
    });

    expect(code).toBe(1);
    expect(readFileSync(victim, "utf8")).toBe("do not overwrite\n");
    expect(lstatSync(join(out, "demo.ts")).isSymbolicLink()).toBe(true);
    expect(logs.join("\n")).toMatch(/symlink/i);
  });

  it("rejects manifests with path-traversal in files[]", async () => {
    const evilDir = join(registry, "evil");
    mkdirSync(evilDir, { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ evil: "evil/manifest.json" })),
    );
    writeFileSync(
      join(evilDir, "manifest.json"),
      JSON.stringify({
        name: "evil",
        version: "0.1.0",
        namespace: "evil",
        description: "evil",
        auth: { kind: "none" },
        files: ["../../../etc/foo.ts"],
        tools: [{ name: "x", description: "x", risk: "read" }],
      }),
    );
    const code = await add(["evil", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("rejects manifests with absolute paths in files[]", async () => {
    const evilDir = join(registry, "evil-abs");
    mkdirSync(evilDir, { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ "evil-abs": "evil-abs/manifest.json" })),
    );
    writeFileSync(
      join(evilDir, "manifest.json"),
      JSON.stringify({
        name: "evil-abs",
        version: "0.1.0",
        namespace: "evil-abs",
        description: "evil",
        auth: { kind: "none" },
        files: ["/etc/foo.ts"],
        tools: [{ name: "x", description: "x", risk: "read" }],
      }),
    );
    const code = await add(["evil-abs", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("rejects manifests with invalid auth.kind", async () => {
    const bad = join(registry, "bad-auth");
    mkdirSync(bad, { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ "bad-auth": "bad-auth/manifest.json" })),
    );
    writeFileSync(
      join(bad, "manifest.json"),
      JSON.stringify({
        name: "bad-auth",
        version: "0.1.0",
        namespace: "bad_auth",
        description: "bad",
        auth: { kind: "magic" },
        files: ["bad.ts"],
        tools: [{ name: "x", description: "x", risk: "read" }],
      }),
    );
    writeFileSync(join(bad, "bad.ts"), "// bad\n");
    const code = await add(["bad-auth", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("rejects writes through a symlinked subdir even when path is lexically inside --out", async () => {
    // Manifest declares sub/foo.ts. We pre-create --out/sub as a symlink to
    // a directory OUTSIDE the project; copyFileSync would follow the symlink
    // and write outside --out. The realpath check must catch it.
    const { symlinkSync } = await import("node:fs");
    const evilDir = join(registry, "sym-evil");
    mkdirSync(evilDir, { recursive: true });
    mkdirSync(join(evilDir, "sub"), { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ "sym-evil": "sym-evil/manifest.json" })),
    );
    writeFileSync(
      join(evilDir, "manifest.json"),
      JSON.stringify({
        name: "sym-evil",
        version: "0.1.0",
        namespace: "sym_evil",
        description: "evil",
        auth: { kind: "none" },
        files: ["sub/foo.ts"],
        tools: [{ name: "x", description: "x", risk: "read" }],
      }),
    );
    writeFileSync(join(evilDir, "sub/foo.ts"), "// evil\n");

    const out = join(tmp, "integrations");
    const outsideTarget = join(tmp, "outside-target");
    mkdirSync(outsideTarget, { recursive: true });
    mkdirSync(out, { recursive: true });
    symlinkSync(outsideTarget, join(out, "sub"));

    const code = await add(["sym-evil", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
    // The file must NOT have been written to the symlink target.
    expect(existsSync(join(outsideTarget, "foo.ts"))).toBe(false);
  });

  it("ships the echo integration in the real registry", async () => {
    const out = join(tmp, "real-out");
    // Use the TS-native registry that ships with kaji/ts
    const realRegistry = join(__dirname, "..", "registry");
    const code = await add(["echo", "--out", out], {
      registryRoot: realRegistry,
    });
    expect(code).toBe(0);
    // TS-native echo ships index.ts (not echo.ts)
    expect(existsSync(join(out, "index.ts"))).toBe(true);
  });

  it("does not ship unindexed Python-only integrations in the real TS registry", () => {
    const realRegistry = join(__dirname, "..", "registry");
    expect(existsSync(join(realRegistry, "gcal"))).toBe(false);
    expect(existsSync(join(realRegistry, "github"))).toBe(false);
    expect(existsSync(join(realRegistry, "gmail"))).toBe(false);
  });
});
