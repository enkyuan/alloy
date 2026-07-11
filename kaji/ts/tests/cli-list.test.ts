/** Tests for `kaji list-integrations` against ephemeral registries. */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { listIntegrations } from "@/cli/list";

const here = dirname(fileURLToPath(import.meta.url));
const schemaRoot = join(here, "..", "registry");

type FixtureIndexEntry =
  | string
  | { readonly manifest: string; readonly stability: "experimental" | "beta" };

function registryIndex(integrations: Record<string, FixtureIndexEntry>): object {
  return {
    $schema: "./index.schema.json",
    version: "0.1.0",
    integrations: Object.fromEntries(
      Object.entries(integrations).map(([name, value]) => {
        const entry =
          typeof value === "string" ? { manifest: value, stability: "beta" as const } : value;
        return [name, { ...entry, runtimes: ["typescript"] }];
      }),
    ),
  };
}

function writeIntegration(root: string, name: string, description: string): void {
  const integrationRoot = join(root, name);
  mkdirSync(integrationRoot, { recursive: true });
  writeFileSync(
    join(integrationRoot, "manifest.json"),
    JSON.stringify({
      name,
      version: "0.1.0",
      namespace: name.replaceAll("-", "_"),
      description,
      auth: { kind: "none" },
      files: ["index.ts"],
      tools: [{ name: "run", description: "Run the integration.", risk: "read" }],
    }),
  );
  writeFileSync(join(integrationRoot, "index.ts"), "// fixture\n");
}

describe("kaji list-integrations", () => {
  let registryRoot: string;

  beforeEach(() => {
    registryRoot = mkdtempSync(join(tmpdir(), "kaji-list-"));
  });

  afterEach(() => rmSync(registryRoot, { recursive: true, force: true }));

  it("prints every validated index entry with its description", async () => {
    writeIntegration(registryRoot, "echo", "Echo a string back.");
    writeIntegration(registryRoot, "weather", "Look up the weather.");
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify(
        registryIndex({
          echo: "echo/manifest.json",
          weather: "weather/manifest.json",
        }),
      ),
    );

    const lines: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => lines.push(message),
    });
    expect(code).toBe(0);
    const output = lines.join("\n");
    expect(output).toMatch(/echo\s+Echo a string back\./);
    expect(output).toMatch(/weather\s+Look up the weather\./);
  });

  it("marks experimental entries while leaving beta entries unmarked", async () => {
    writeIntegration(registryRoot, "echo", "Echo a string back.");
    writeIntegration(registryRoot, "weather", "Look up the weather.");
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify(
        registryIndex({
          echo: { manifest: "echo/manifest.json", stability: "beta" },
          weather: { manifest: "weather/manifest.json", stability: "experimental" },
        }),
      ),
    );

    const lines: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => lines.push(message),
    });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/^echo\s+Echo a string back\./m);
    expect(lines.join("\n")).toMatch(/^weather \[experimental\]\s+Look up the weather\./m);
  });

  it("returns 1 when the packaged index is missing", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/INVALID_INTEGRATION_INDEX at \/:/);
    expect(stdout).toEqual([]);
  });

  it("returns 0 and a friendly note when index.json has zero integrations", async () => {
    writeFileSync(join(registryRoot, "index.json"), JSON.stringify(registryIndex({})));
    const lines: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => lines.push(message),
    });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/No integrations found/);
  });

  it("exits 1 and reports malformed index JSON", async () => {
    writeFileSync(join(registryRoot, "index.json"), "{not valid json");
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/INVALID_INTEGRATION_INDEX at \/:/);
    expect(stdout.join("\n")).not.toMatch(/No integrations found/);
  });

  it("exits 1 when an indexed manifest is missing", async () => {
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify(registryIndex({ ghost: "ghost/manifest.json" })),
    );
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(
      /INVALID_INTEGRATION_INDEX at \/integrations\/ghost\/manifest/,
    );
    expect(stdout).toEqual([]);
  });

  it("exits 1 when an indexed manifest is corrupt", async () => {
    mkdirSync(join(registryRoot, "broken"));
    writeFileSync(join(registryRoot, "broken", "manifest.json"), "{not valid json");
    writeFileSync(
      join(registryRoot, "index.json"),
      JSON.stringify(registryIndex({ broken: "broken/manifest.json" })),
    );
    const stderr: string[] = [];
    const code = await listIntegrations([], {
      registryRoot,
      schemaRoot,
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/INVALID_INTEGRATION_MANIFEST at \/:/);
  });
});
