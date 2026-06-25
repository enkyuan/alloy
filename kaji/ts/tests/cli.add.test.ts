/**
 * Tests for the `kaji add` CLI library.
 *
 * Drives `add(argv, opts)` against an ephemeral fixture registry on disk,
 * then a final case against the real registry shipped with the SDK.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { add } from "../src/cli/add";

const __dirname = dirname(fileURLToPath(import.meta.url));

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
      JSON.stringify({
        integrations: {
          "demo-ts": "demo-ts/manifest.json",
          "demo-py": "demo-py/manifest.json",
        },
      }),
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
        tools: [{ name: "ping", description: "ping" }],
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
        tools: [{ name: "noop", description: "noop" }],
      }),
    );
    writeFileSync(join(registry, "demo-py/demo.py"), "# py\n");
  });
  afterEach(() => rmSync(tmp, { recursive: true, force: true }));

  it("copies .ts files into --out", async () => {
    const out = join(tmp, "integrations");
    const code = await add(["demo-ts", "--out", out], {
      registryRoot: registry,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("skips integrations with no .ts files", async () => {
    const out = join(tmp, "integrations");
    const logs: string[] = [];
    const code = await add(["demo-py", "--out", out], {
      registryRoot: registry,
      log: (m) => logs.push(m),
    });
    expect(code).toBe(0);
    expect(existsSync(join(out, "demo.py"))).toBe(false);
    expect(logs.some((l) => l.toLowerCase().includes("no typescript"))).toBe(true);
  });

  it("returns 1 on unknown name", async () => {
    const code = await add(["unknown", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
    });
    expect(code).toBe(1);
  });

  it("returns 1 on collision without --force", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["demo-ts", "--out", out], {
      registryRoot: registry,
    });
    expect(code).toBe(1);
  });

  it("overwrites on collision with --force", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["demo-ts", "--out", out, "--force"], {
      registryRoot: registry,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("ships the echo integration in the real registry", async () => {
    const out = join(tmp, "real-out");
    const realRegistry = join(__dirname, "..", "..", "sdk", "kaji", "integrations", "registry");
    const code = await add(["echo", "--out", out], {
      registryRoot: realRegistry,
    });
    expect(code).toBe(0);
    expect(existsSync(join(out, "echo.ts"))).toBe(true);
  });
});
