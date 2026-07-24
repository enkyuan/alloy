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
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { rename as renameAsync } from "node:fs/promises";
import { add } from "@/cli/add";
import { classifyIntegrationBundle, installIntegrationBundle } from "@/cli/integration-copy";
import { loadManifest, loadRegistryIndex } from "@/integrations/registry-loader";

const __dirname = dirname(fileURLToPath(import.meta.url));
const schemaRoot = join(__dirname, "..", "registry");

function registryIndex(
  integrations: Record<string, string>,
  stability: "experimental" | "beta" = "beta",
): object {
  return {
    $schema: "./index.schema.json",
    version: "0.1.0",
    integrations: Object.fromEntries(
      Object.entries(integrations).map(([name, manifest]) => [
        name,
        { manifest, stability, runtimes: ["typescript"] },
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
    mkdirSync(join(registry, "echo"), { recursive: true });
    mkdirSync(join(registry, "github"), { recursive: true });
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(
        registryIndex({
          echo: "echo/manifest.json",
          github: "github/manifest.json",
        }),
      ),
    );
    writeFileSync(
      join(registry, "echo/manifest.json"),
      JSON.stringify({
        name: "echo",
        version: "0.1.0",
        namespace: "demo",
        description: "demo ts",
        auth: { kind: "env", env: "DEMO_API_KEY" },
        files: ["demo.ts"],
        tools: [
          {
            name: "ping",
            description: "ping",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
      }),
    );
    writeFileSync(join(registry, "echo/demo.ts"), "export const x = 1;\n");
    writeFileSync(
      join(registry, "github/manifest.json"),
      JSON.stringify({
        name: "github",
        version: "0.1.0",
        namespace: "demo",
        description: "demo py",
        auth: { kind: "none" },
        files: ["demo.py"],
        tools: [
          {
            name: "noop",
            description: "noop",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
      }),
    );
    writeFileSync(join(registry, "github/demo.py"), "# py\n");
  });
  afterEach(() => rmSync(tmp, { recursive: true, force: true }));

  it.each([
    { arguments_: [] },
    { arguments_: ["echo", "--out"] },
    { arguments_: ["echo", "--unknown"] },
  ])("rejects malformed usage on stderr without writing: $arguments_", async ({ arguments_ }) => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const destination = join(tmp, "malformed");
    const code = await add(arguments_, {
      registryRoot: registry,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(2);
    expect(stdout).toEqual([]);
    expect(stderr.join("\n")).toContain("usage: kaji add");
    expect(existsSync(destination)).toBe(false);
  });

  it("reports unknown integrations on stderr without usage or writes", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const destination = join(tmp, "unknown");
    const code = await add(["unknown", "--out", destination], {
      registryRoot: registry,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(1);
    expect(stdout).toEqual([]);
    expect(stderr.join("\n")).toContain("Unknown integration");
    expect(stderr.join("\n")).not.toContain("usage:");
    expect(existsSync(destination)).toBe(false);
  });

  it("copies .ts files into --out", async () => {
    const out = join(tmp, "integrations");
    const code = await add(["echo", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("refuses experimental integrations without creating the output directory", async () => {
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ echo: "echo/manifest.json" }, "experimental")),
    );
    const out = join(tmp, "experimental-out");
    const errors: string[] = [];
    const code = await add(["echo", "--out", out], {
      registryRoot: registry,
      schemaRoot,
      err: (message) => errors.push(message),
    });
    expect(code).toBe(1);
    expect(existsSync(out)).toBe(false);
    expect(errors).toEqual([
      "INTEGRATION_EXPERIMENTAL at /integrations/echo/stability: Integration 'echo' is experimental and outside the beta guarantee. Re-run with --allow-experimental to copy it.",
    ]);
  });

  it("copies an experimental integration only with explicit opt-in", async () => {
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ echo: "echo/manifest.json" }, "experimental")),
    );
    const out = join(tmp, "experimental-out");
    const code = await add(["echo", "--allow-experimental", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toContain("export const x = 1;");
  });

  it("prints OAuth setup only after a successful copy", async () => {
    mkdirSync(join(registry, "github"), { recursive: true });
    writeFileSync(
      join(registry, "github/manifest.json"),
      JSON.stringify({
        name: "github",
        version: "0.1.0",
        namespace: "github",
        description: "oauth fixture",
        auth: {
          kind: "oauth",
          provider: "google",
          clientIdEnv: "GOOGLE_CLIENT_ID",
          clientSecretEnv: "GOOGLE_CLIENT_SECRET",
          scopes: ["scope.a", "scope.b"],
          docs: "https://example.test/oauth",
        },
        files: ["github.ts"],
        tools: [
          {
            name: "ping",
            description: "fixture tool",
            parameters: {},
            risk: "read",
            parallel_safe: true,
          },
        ],
        extras: ["oauth-keyring"],
      }),
    );
    writeFileSync(join(registry, "github/github.ts"), "export {};\n");
    writeFileSync(
      join(registry, "index.json"),
      JSON.stringify(registryIndex({ github: "github/manifest.json" }, "experimental")),
    );
    const out = join(tmp, "oauth-out");
    const logs: string[] = [];
    expect(
      await add(["github", "--allow-experimental", "--out", out], {
        registryRoot: registry,
        schemaRoot,
        log: (message) => logs.push(message),
      }),
      logs.join("\n"),
    ).toBe(0);
    const rendered = logs.join("\n");
    for (const expected of [
      "client ID env: GOOGLE_CLIENT_ID",
      "client secret env: GOOGLE_CLIENT_SECRET",
      "scopes: scope.a, scope.b",
      "docs: https://example.test/oauth",
      "python -m kaji.cli connect github --principal <stable-host-principal-id>",
      "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- connect github --principal <stable-host-principal-id>",
    ]) {
      expect(rendered).toContain(expected);
    }
    expect(rendered).not.toContain("oauth-keyring");

    const current: string[] = [];
    expect(
      await add(["github", "--allow-experimental", "--out", out], {
        registryRoot: registry,
        schemaRoot,
        log: (message) => current.push(message),
      }),
    ).toBe(0);
    expect(current.join("\n")).not.toContain("connect github");
  });

  it("rejects unknown flags before loading or copying", async () => {
    const out = join(tmp, "unknown-flag-out");
    const stdout: string[] = [];
    const stderr: string[] = [];
    const code = await add(["echo", "--unsafe", "--out", out], {
      registryRoot: registry,
      schemaRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
    });
    expect(code).toBe(2);
    expect(existsSync(out)).toBe(false);
    expect(stdout).toEqual([]);
    expect(stderr.join("\n")).toMatch(/Unknown argument: --unsafe/);
    expect(stderr.join("\n")).toContain("usage: kaji add");
  });

  it("copies every manifest-declared native asset", async () => {
    const out = join(tmp, "integrations");
    const logs: string[] = [];
    const code = await add(["github", "--out", out], {
      registryRoot: registry,
      schemaRoot,
      log: (m) => logs.push(m),
    });
    expect(code).toBe(0);
    expect(existsSync(join(out, "demo.py"))).toBe(true);
    expect(existsSync(join(out, ".kaji-integration-provenance.json"))).toBe(true);
  });

  it("returns 1 on unknown name", async () => {
    const code = await add(["unknown", "--out", join(tmp, "integrations")], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(1);
  });

  it("classifies an unprovenanced collision as modified", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["echo", "--out", out], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(5);
  });

  it("overwrites on collision with --force", async () => {
    const out = join(tmp, "integrations");
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "demo.ts"), "existing\n");
    const code = await add(["echo", "--out", out, "--force"], {
      registryRoot: registry,
      schemaRoot,
    });
    expect(code).toBe(5);
    expect(readFileSync(join(out, "demo.ts"), "utf8")).toBe("existing\n");
  });

  it("rejects a final destination symlink with --force without changing its victim", async () => {
    const out = join(tmp, "integrations");
    const victim = join(tmp, "victim.ts");
    mkdirSync(out, { recursive: true });
    writeFileSync(victim, "do not overwrite\n");
    symlinkSync(victim, join(out, "demo.ts"));
    const logs: string[] = [];

    const code = await add(["echo", "--out", out, "--force"], {
      registryRoot: registry,
      schemaRoot,
      log: (message) => logs.push(message),
    });

    expect(code).toBe(5);
    expect(readFileSync(victim, "utf8")).toBe("do not overwrite\n");
    expect(lstatSync(join(out, "demo.ts")).isSymbolicLink()).toBe(true);
    expect(logs.join("\n")).toMatch(/missing_provenance/);
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
        tools: [
          {
            name: "x",
            description: "x",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
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
        tools: [
          {
            name: "x",
            description: "x",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
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
        tools: [
          {
            name: "x",
            description: "x",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
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
        tools: [
          {
            name: "x",
            description: "x",
            parameters: {},
            risk: "read",
            parallel_safe: false,
          },
        ],
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
    expect(code).toBe(5);
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
    expect(existsSync(join(realRegistry, "github"))).toBe(true);
    expect(existsSync(join(realRegistry, "gmail"))).toBe(false);
  });

  it("uses a provider-scoped default destination", async () => {
    const previous = process.cwd();
    process.chdir(tmp);
    try {
      const code = await add(["echo"], {
        registryRoot: join(__dirname, "..", "registry"),
      });
      expect(code).toBe(0);
      expect(existsSync(join(tmp, "integrations/echo/index.ts"))).toBe(true);
      expect(existsSync(join(tmp, "integrations/index.ts"))).toBe(false);
    } finally {
      process.chdir(previous);
    }
  });

  it("quarantines GitHub then copies every declared owner asset with provenance", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const out = join(tmp, "github");
    expect(await add(["github", "--out", out], { registryRoot: realRegistry })).toBe(1);
    expect(existsSync(out)).toBe(false);

    const logs: string[] = [];
    expect(
      await add(["github", "--allow-experimental", "--out", out], {
        registryRoot: realRegistry,
        log: (message) => logs.push(message),
      }),
    ).toBe(0);
    for (const name of [
      "index.ts",
      "client.ts",
      "tests/github.test.ts",
      "owner-fixtures.json",
      "LICENSE",
      ".kaji-integration-provenance.json",
    ]) {
      expect(existsSync(join(out, name))).toBe(true);
    }
    const provenance = JSON.parse(
      readFileSync(join(out, ".kaji-integration-provenance.json"), "utf8"),
    );
    expect(provenance).toMatchObject({
      integration: "github",
      runtime: "typescript",
      stability: "experimental",
    });
    expect(provenance.abiSha256).toMatch(/^[a-f0-9]{64}$/u);
    expect(logs.join("\n")).toContain("fine-grained token");
  });

  it("renders the closed JSON shape for absent, current, modified, and outdated", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const out = join(tmp, "echo-states");
    const run = async (args: string[]) => {
      const logs: string[] = [];
      const code = await add(args, {
        registryRoot: realRegistry,
        log: (message) => logs.push(message),
      });
      return { code, row: JSON.parse(logs.at(-1)!) as Record<string, unknown> };
    };

    const absent = await run(["echo", "--check", "--json", "--out", out]);
    expect(absent.code).toBe(3);
    expect(Object.keys(absent.row)).toEqual([
      "state",
      "integration",
      "runtime",
      "destination",
      "reason_code",
      "next_command",
    ]);
    expect(absent.row.state).toBe("absent");

    expect(await add(["echo", "--out", out], { registryRoot: realRegistry })).toBe(0);
    expect((await run(["echo", "--check", "--json", "--out", out])).row.reason_code).toBe(
      "up_to_date",
    );

    writeFileSync(join(out, "index.ts"), "// owner edit\n");
    const modified = await run(["echo", "--force", "--json", "--out", out]);
    expect(modified).toMatchObject({ code: 5, row: { reason_code: "local_changes" } });
    expect(readFileSync(join(out, "index.ts"), "utf8")).toBe("// owner edit\n");

    const outdatedOut = join(tmp, "echo-outdated");
    expect(await add(["echo", "--out", outdatedOut], { registryRoot: realRegistry })).toBe(0);
    const sidecar = join(outdatedOut, ".kaji-integration-provenance.json");
    const provenance = JSON.parse(readFileSync(sidecar, "utf8"));
    provenance.sdkVersion = "0.0.0-old";
    writeFileSync(sidecar, JSON.stringify(provenance));
    expect(await run(["echo", "--check", "--json", "--out", outdatedOut])).toMatchObject({
      code: 4,
      row: { reason_code: "upstream_changed" },
    });
    expect(
      await add(["echo", "--force", "--out", outdatedOut], { registryRoot: realRegistry }),
    ).toBe(0);
  });

  it("classifies runtime mismatch, cross-provider content, and demotion", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "classification");
    await installIntegrationBundle({
      manifest: echo,
      entry: index.integrations.echo!,
      destination: out,
      runtime: "typescript",
    });

    const sidecar = join(out, ".kaji-integration-provenance.json");
    const provenance = JSON.parse(readFileSync(sidecar, "utf8"));
    provenance.runtime = "python";
    writeFileSync(sidecar, JSON.stringify(provenance));
    expect(
      await classifyIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: out,
        runtime: "typescript",
      }),
    ).toMatchObject({ state: "modified", reasonCode: "runtime_mismatch" });

    const cross = join(tmp, "cross");
    await installIntegrationBundle({
      manifest: echo,
      entry: index.integrations.echo!,
      destination: cross,
      runtime: "typescript",
    });
    const github = await loadManifest(realRegistry, "github", { index });
    expect(
      await classifyIntegrationBundle({
        manifest: github,
        entry: index.integrations.github!,
        destination: cross,
        runtime: "typescript",
      }),
    ).toMatchObject({ state: "modified", reasonCode: "cross_provider" });

    expect(
      await classifyIntegrationBundle({
        manifest: { ...echo, stability: "experimental" },
        entry: { ...index.integrations.echo!, stability: "experimental" },
        destination: cross,
        runtime: "typescript",
      }),
    ).toMatchObject({ state: "demoted", reasonCode: "stability_demoted" });
  });

  it("restores the old bundle when the staged publish rename fails", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "rollback");
    const context = {
      manifest: echo,
      entry: index.integrations.echo!,
      destination: out,
      runtime: "typescript" as const,
    };
    await installIntegrationBundle(context);
    const sidecar = join(out, ".kaji-integration-provenance.json");
    const provenance = JSON.parse(readFileSync(sidecar, "utf8"));
    provenance.sdkVersion = "0.0.0-old";
    writeFileSync(sidecar, JSON.stringify(provenance));
    const before = {
      source: readFileSync(join(out, "index.ts")),
      sidecar: readFileSync(sidecar),
    };

    await expect(
      installIntegrationBundle({
        ...context,
        force: true,
        renameEntry: async (source, destination) => {
          if (source.includes(".echo.kaji-stage-")) throw new Error("publish failed");
          await renameAsync(source, destination);
        },
      }),
    ).rejects.toThrow("publish failed");
    expect(readFileSync(join(out, "index.ts"))).toEqual(before.source);
    expect(readFileSync(sidecar)).toEqual(before.sidecar);
    expect(existsSync(out)).toBe(true);
  });

  it("rejects a final destination symlink without writing its victim", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const victim = join(tmp, "final-symlink-victim");
    const out = join(tmp, "final-symlink");
    mkdirSync(victim);
    symlinkSync(victim, out, "dir");

    await expect(
      installIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: out,
        runtime: "typescript",
      }),
    ).rejects.toThrow("unsafe_destination");
    expect(existsSync(join(victim, "index.ts"))).toBe(false);
    expect(lstatSync(out).isSymbolicLink()).toBe(true);
  });

  it("rejects a nested ancestor symlink without writing its victim", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const victim = join(tmp, "ancestor-symlink-victim");
    const ancestor = join(tmp, "ancestor-symlink");
    mkdirSync(victim);
    symlinkSync(victim, ancestor, "dir");

    await expect(
      installIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: join(ancestor, "nested", "echo"),
        runtime: "typescript",
      }),
    ).rejects.toThrow("unsafe_destination");
    expect(existsSync(join(victim, "nested"))).toBe(false);
    expect(lstatSync(ancestor).isSymbolicLink()).toBe(true);
  });

  it("restores an edit made between live recheck and backup rename", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "rename-race");
    const context = {
      manifest: echo,
      entry: index.integrations.echo!,
      destination: out,
      runtime: "typescript" as const,
    };
    await installIntegrationBundle(context);
    const sidecar = join(out, ".kaji-integration-provenance.json");
    const provenance = JSON.parse(readFileSync(sidecar, "utf8"));
    provenance.sdkVersion = "0.0.0-old";
    writeFileSync(sidecar, JSON.stringify(provenance));
    const concurrent = "// concurrent owner edit\n";

    await expect(
      installIntegrationBundle({
        ...context,
        force: true,
        renameEntry: async (source, destination) => {
          if (source.endsWith("rename-race")) {
            writeFileSync(join(source, "index.ts"), concurrent);
          }
          await renameAsync(source, destination);
        },
      }),
    ).rejects.toThrow("Destination changed");
    expect(readFileSync(join(out, "index.ts"), "utf8")).toBe(concurrent);
    expect(existsSync(out)).toBe(true);
  });

  it("does not delete a destination created as an absent stage publishes", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "absent-race");
    const concurrent = "concurrent owner bytes\n";

    await expect(
      installIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: out,
        runtime: "typescript",
        afterReservationCheck: async (destination) => {
          rmSync(destination, { recursive: true });
          mkdirSync(destination);
          writeFileSync(join(destination, "owner.txt"), concurrent);
        },
      }),
    ).rejects.toThrow("Destination changed");
    expect(readFileSync(join(out, "owner.txt"), "utf8")).toBe(concurrent);
  });

  it.each([false, true])(
    "rejects concurrent destination creation before absent reservation (nonempty=%s)",
    async (nonempty) => {
      const realRegistry = join(__dirname, "..", "registry");
      const index = await loadRegistryIndex(realRegistry);
      const echo = await loadManifest(realRegistry, "echo", { index });
      const out = join(tmp, `reservation-create-${nonempty}`);
      const concurrent = "concurrent owner bytes\n";

      await expect(
        installIntegrationBundle({
          manifest: echo,
          entry: index.integrations.echo!,
          destination: out,
          runtime: "typescript",
          beforeReservationCreate: async (destination) => {
            mkdirSync(destination);
            if (nonempty) writeFileSync(join(destination, "owner.txt"), concurrent);
          },
        }),
      ).rejects.toThrow("Destination changed");
      expect(existsSync(out)).toBe(true);
      if (nonempty) {
        expect(readFileSync(join(out, "owner.txt"), "utf8")).toBe(concurrent);
      } else {
        expect(readdirSync(out)).toEqual([]);
      }
    },
  );

  it.each(["mutate", "replace"] as const)(
    "preserves reservation %s before absent publish",
    async (mode) => {
      const realRegistry = join(__dirname, "..", "registry");
      const index = await loadRegistryIndex(realRegistry);
      const echo = await loadManifest(realRegistry, "echo", { index });
      const out = join(tmp, `reservation-${mode}`);
      const concurrent = "concurrent owner bytes\n";
      let replacementIdentity: string | undefined;

      await expect(
        installIntegrationBundle({
          manifest: echo,
          entry: index.integrations.echo!,
          destination: out,
          runtime: "typescript",
          beforeReservationPublish: async (destination) => {
            if (mode === "mutate") {
              writeFileSync(join(destination, "owner.txt"), concurrent);
            } else {
              rmSync(destination, { recursive: true });
              mkdirSync(destination);
              const metadata = lstatSync(destination);
              replacementIdentity = `${metadata.dev}:${metadata.ino}`;
            }
          },
        }),
      ).rejects.toThrow("Destination changed");
      expect(existsSync(out)).toBe(true);
      if (mode === "mutate") {
        expect(readFileSync(join(out, "owner.txt"), "utf8")).toBe(concurrent);
      } else {
        const metadata = lstatSync(out);
        expect(`${metadata.dev}:${metadata.ino}`).toBe(replacementIdentity);
        expect(readdirSync(out)).toEqual([]);
      }
    },
  );

  it("does not write to an empty replacement after the reservation check", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "reservation-postcheck-replacement");
    let replacementIdentity: string | undefined;

    await expect(
      installIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: out,
        runtime: "typescript",
        afterReservationCheck: async (destination) => {
          rmSync(destination, { recursive: true });
          mkdirSync(destination);
          const metadata = lstatSync(destination);
          replacementIdentity = `${metadata.dev}:${metadata.ino}`;
        },
      }),
    ).rejects.toThrow("Destination changed");

    const metadata = lstatSync(out);
    expect(`${metadata.dev}:${metadata.ino}`).toBe(replacementIdentity);
    expect(readdirSync(out)).toEqual([]);
  });

  it("does not remove an empty replacement during failed reservation cleanup", async () => {
    const realRegistry = join(__dirname, "..", "registry");
    const index = await loadRegistryIndex(realRegistry);
    const echo = await loadManifest(realRegistry, "echo", { index });
    const out = join(tmp, "reservation-cleanup-replacement");
    let replacementIdentity: string | undefined;

    await expect(
      installIntegrationBundle({
        manifest: echo,
        entry: index.integrations.echo!,
        destination: out,
        runtime: "typescript",
        afterReservationCheck: async () => {
          throw new Error("stop before publication");
        },
        beforeReservationCleanup: async (destination) => {
          rmSync(destination, { recursive: true });
          mkdirSync(destination);
          const metadata = lstatSync(destination);
          replacementIdentity = `${metadata.dev}:${metadata.ino}`;
        },
      }),
    ).rejects.toThrow("stop before publication");

    const metadata = lstatSync(out);
    expect(`${metadata.dev}:${metadata.ino}`).toBe(replacementIdentity);
    expect(readdirSync(out)).toEqual([]);
  });

  it("rejects --check --force before creating the default destination", async () => {
    const previous = process.cwd();
    process.chdir(tmp);
    try {
      const stdout: string[] = [];
      const stderr: string[] = [];
      expect(
        await add(["echo", "--check", "--force"], {
          registryRoot: join(__dirname, "..", "registry"),
          log: (message) => stdout.push(message),
          err: (message) => stderr.push(message),
        }),
      ).toBe(2);
      expect(stdout).toEqual([]);
      expect(stderr.join("\n")).toContain("--check cannot be combined with --force");
      expect(stderr.join("\n")).toContain("usage: kaji add");
      expect(existsSync(join(tmp, "integrations/echo"))).toBe(false);
    } finally {
      process.chdir(previous);
    }
  });
});
