/**
 * Tests for `kaji list-integrations`. Drives the handler against ephemeral
 * fixture registries on disk, matching the `cli.add.test.ts` style.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { listIntegrations } from "@/cli/list";

describe("kaji list-integrations", () => {
  let registryRoot: string;

  beforeEach(() => {
    registryRoot = mkdtempSync(join(tmpdir(), "kaji-list-"));
  });

  it("prints every integration listed in index.json with its description", async () => {
    mkdirSync(join(registryRoot, "echo"));
    writeFileSync(
      join(registryRoot, "echo", "manifest.json"),
      JSON.stringify({ name: "echo", description: "Echo a string back." }),
    );
    mkdirSync(join(registryRoot, "weather"));
    writeFileSync(
      join(registryRoot, "weather", "manifest.json"),
      JSON.stringify({ name: "weather", description: "Look up the weather." }),
    );
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify({
        version: "0.1.0",
        integrations: {
          echo: "echo/manifest.json",
          weather: "weather/manifest.json",
        },
      }),
    );

    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    const out = lines.join("\n");
    expect(out).toMatch(/echo\s+Echo a string back\./);
    expect(out).toMatch(/weather\s+Look up the weather\./);
  });

  it("returns 0 and a friendly note when index.json is missing", async () => {
    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/No integrations found/);
  });

  it("returns 0 and a friendly note when index.json has zero integrations", async () => {
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify({ version: "0.1.0", integrations: {} }),
    );
    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/No integrations found/);
  });

  it("exits 1 and reports the parse error when index.json is malformed JSON", async () => {
    writeFileSync(join(registryRoot, "index.json"), "{not valid json");
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      log: (m) => stdout.push(m),
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    // Real corruption surfaces on stderr so the user can fix it; the
    // friendly "No integrations found." message is reserved for missing /
    // empty catalogs.
    expect(stderr.join("\n")).toMatch(/Registry index is not valid JSON/);
    expect(stdout.join("\n")).not.toMatch(/No integrations found/);
  });

  it("falls back to the catalog key when a manifest is missing or unreadable", async () => {
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify({
        version: "0.1.0",
        integrations: { ghost: "ghost/manifest.json" },
      }),
    );
    // ghost/manifest.json deliberately not created.
    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    // Catalog key surfaces, no crash; description is blank.
    expect(lines.join("\n")).toMatch(/^ghost\b/m);
  });
});
