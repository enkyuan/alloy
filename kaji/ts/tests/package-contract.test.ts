import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { assertCliListOutput, EXPECTED_ECHO_DESCRIPTION } from "../scripts/cli_assertions";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, "..");
const canonicalRoot = resolve(packageRoot, "../contracts");
const repositoryRoot = resolve(packageRoot, "../..");
const SYNC_CHILD_TIMEOUT_MS = 20_000;
const SYNC_CHILD_MAX_BUFFER = 16 * 1024 * 1024;

interface SyncChildOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

function runText(command: string, args: string[], options: SyncChildOptions = {}): string {
  return execFileSync(command, args, {
    ...options,
    encoding: "utf8",
    timeout: SYNC_CHILD_TIMEOUT_MS,
    maxBuffer: SYNC_CHILD_MAX_BUFFER,
  });
}

function runBytes(command: string, args: string[], options: SyncChildOptions = {}): Buffer {
  return execFileSync(command, args, {
    ...options,
    timeout: SYNC_CHILD_TIMEOUT_MS,
    maxBuffer: SYNC_CHILD_MAX_BUFFER,
  });
}

function contractFiles(root: string, directory = root): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...contractFiles(root, path));
    } else if (entry.name.endsWith(".json") || entry.name.endsWith(".md")) {
      files.push(relative(root, path).replaceAll("\\", "/"));
    }
  }
  return files.sort();
}

function exportTargets(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value !== "object" || value === null) return [];
  return Object.values(value).flatMap(exportTargets);
}

describe("npm contract artifact", () => {
  it("accepts only the exact canonical Echo list row", () => {
    expect(() =>
      assertCliListOutput(
        `echo  [beta]  v0.1.0  ${EXPECTED_ECHO_DESCRIPTION}\n` +
          "fs    [experimental]  v0.1.0  Filesystem integration.",
      ),
    ).not.toThrow();
  });

  it.each([
    ["experimental Echo", `echo  [experimental]  v0.1.0  ${EXPECTED_ECHO_DESCRIPTION}`],
    ["wrong Echo version", `echo  [beta]  v9.9.9  ${EXPECTED_ECHO_DESCRIPTION}`],
    ["wrong Echo description", "echo  [beta]  v0.1.0  Almost Echo."],
    ["legacy incomplete row", `echo  ${EXPECTED_ECHO_DESCRIPTION}`],
    [
      "duplicate Echo row",
      `echo  [beta]  v0.1.0  ${EXPECTED_ECHO_DESCRIPTION}\n` +
        `echo  [beta]  v0.1.0  ${EXPECTED_ECHO_DESCRIPTION}`,
    ],
    ["malformed sibling row", `echo  [beta]  v0.1.0  ${EXPECTED_ECHO_DESCRIPTION}\nmalformed`],
  ])("rejects the %s", (_label, output) => {
    expect(() => assertCliListOutput(output)).toThrow();
  });

  it("keeps every synchronous artifact child bounded below the test timeout", () => {
    const source = readFileSync(fileURLToPath(import.meta.url), "utf8");

    expect([...source.matchAll(/\bexecFileSync\(/g)]).toHaveLength(2);
    expect(source).toContain("timeout: SYNC_CHILD_TIMEOUT_MS");
    expect(source).toContain("maxBuffer: SYNC_CHILD_MAX_BUFFER");
    expect(SYNC_CHILD_TIMEOUT_MS).toBeLessThan(30_000);
  });

  it("declares the tested runtime/compiler matrix and canonical package URLs", () => {
    const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));

    expect(manifest.engines.node).toBe("22.x || 24.x");
    expect(manifest.devDependencies.typescript57).toBe("npm:typescript@5.7.3");
    expect(manifest.repository).toEqual({
      type: "git",
      url: "https://github.com/enkyuan/alloy.git",
      directory: "kaji/ts",
    });
    expect(manifest.homepage).toBe(
      "https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md",
    );
    expect(manifest.bugs).toEqual({ url: "https://github.com/enkyuan/alloy/issues" });
  });

  it("smokes generated npm and Bun projects with both supported compiler lines", () => {
    const source = readFileSync(join(packageRoot, "scripts/smoke_package.mts"), "utf8");
    const tiers = JSON.parse(
      readFileSync(join(canonicalRoot, "feature-tiers-v1.json"), "utf8"),
    ) as { cliCommands: { typescript: { stable: string[] } } };

    expect(tiers.cliCommands.typescript.stable).toEqual([
      "add",
      "init",
      "list-integrations",
      "replay",
    ]);

    for (const required of [
      "assertGeneratedVersions",
      'runScaffold("npm"',
      'runScaffold("bun"',
      "typescript57",
      '"typescript"',
      "skipLibCheck: false",
      'types: ["node"]',
      "coldSetupToOutputMs",
      "warmRunMs",
      "assertRootDeclarationsVendorNeutral",
      'generated.devDependencies["@types/node"]',
      'installed.devDependencies["@types/node"]',
      "const nodeTypesPackage = `@types/node@${nodeTypesRange}`",
      "type SmokePhase =",
      "error instanceof CommandError",
      "package smoke failed at phase ${phase}",
      "`${manager}:${stage}-install`",
      "`${manager}:cli-init`",
      "`${manager}:cli-add`",
      "`${manager}:cli-list`",
      "`${manager}:cli-replay`",
      "assertCliInitOutput(initOutput, generated)",
      "assertCliAddOutput(addOutput, echo, installedPackageRoot)",
      "assertCliListOutput(listOutput)",
      "assertCliReplayOutput(replayOutput)",
      '[cli, "--no-color", "add", "echo", "--out", echo]',
      '[cli, "--no-color", "list-integrations"]',
      '[cli, "--no-color", "replay", replayFixture, "--format", "summary"]',
      'join(installedPackageRoot, "registry/echo/index.ts")',
      "readFileSync(copied).equals(readFileSync(packaged))",
      'type: "session.created"',
      "sequence: 1",
      "errors=0, seq=1-1",
      "packages.length === 0",
      '["install", "--ignore-scripts"]',
      'await install(manager, "generated"',
      "`${manager}:compile-typescript-5.7`",
      "`${manager}:compile-typescript-current`",
      "`${manager}:cold-run`",
      "`${manager}:warm-run`",
      'const EXPECTED_MOCK_REPLY = "The mock provider has completed the tool loop."',
      'fields.get("text") !== EXPECTED_MOCK_REPLY',
      "coldResult.text !== warmResult.text",
      "coldResult.finalSequence !== warmResult.finalSequence",
    ]) {
      expect(source).toContain(required);
    }

    expect(source).not.toContain("completed.stderr");
    expect(source).not.toContain("JSON.stringify(args)");
    expect(source).not.toContain('if (!fields.get("text")');
    expect(source).toMatch(
      /await install\(\s*manager,\s*"bootstrap",[\s\S]*?nodeTypesPackage[\s\S]*?environment,\s*\)/,
    );
  });

  it("contains exactly the canonical contract files and bytes", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-contract-pack-"));
    try {
      const packed = JSON.parse(
        runText("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", workdir], {
          cwd: packageRoot,
          env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
        }),
      ) as Array<{ filename: string; files: Array<{ path: string }> }>;
      const tarball = join(workdir, packed[0]!.filename);
      const paths = new Set(packed[0]!.files.map(({ path }) => path));
      const manifest = JSON.parse(runText("tar", ["-xOf", tarball, "package/package.json"])) as {
        version: string;
        license: string;
        files: string[];
        exports: Record<string, unknown>;
        bin: Record<string, string>;
        dependencies?: Record<string, string>;
        devDependencies?: Record<string, string>;
        peerDependencies?: Record<string, string>;
      };
      const sourceVersion = readFileSync(join(packageRoot, "src/index.ts"), "utf8").match(
        /export const VERSION = "([^"]+)"/,
      );

      expect(sourceVersion).not.toBeNull();
      expect(manifest.version).toBe(sourceVersion![1]);
      expect(manifest.version).toBe("0.2.0-beta.1");
      expect(manifest.license).toBe("SEE LICENSE IN LICENSE");
      expect(manifest.files).toContain("LICENSE");
      expect(paths).toContain("LICENSE");
      expect(runBytes("tar", ["-xOf", tarball, "package/LICENSE"])).toEqual(
        readFileSync(join(repositoryRoot, "LICENSE")),
      );
      for (const required of [
        "dist/cli/bin.js",
        "dist/cli/init-worker.js",
        "dist/integrations.js",
        "dist/integrations.cjs",
        "dist/integrations.d.ts",
        "dist/integrations.d.cts",
        "registry/index.json",
        "registry/schema.json",
      ]) {
        expect(paths).toContain(required);
      }
      for (const target of exportTargets(manifest.exports)) {
        expect(paths, `missing export target ${target}`).toContain(target.replace(/^\.\//, ""));
      }
      for (const target of Object.values(manifest.bin)) {
        expect(paths, `missing CLI target ${target}`).toContain(target.replace(/^\.\//, ""));
      }
      for (const declarationPath of ["dist/index.d.ts", "dist/index.d.cts"]) {
        const declaration = runText("tar", ["-xOf", tarball, `package/${declarationPath}`]);
        expect(declaration).not.toMatch(/from ["']openai["']/);
        expect(declaration).not.toMatch(/from ["']@anthropic-ai\/sdk["']/);
        expect(declaration).not.toContain("Promise<OpenAI>");
        expect(declaration).not.toContain("Promise<Anthropic>");
      }
      const forbidden = [...paths].filter(
        (path) =>
          /(^|\/)(src|scripts|tests?|__pycache__|logs?|\.cache)(\/|$)/i.test(path) ||
          /(^|\/)(?:tsconfig(?:\.[^/]+)?\.json|tsup\.config\.[cm]?ts|vitest(?:\.[^/]+)?\.config\.[cm]?ts)$/i.test(
            path,
          ) ||
          /\.(?:pyc|pyo|log)$/.test(path),
      );
      expect(forbidden).toEqual([]);

      const registryIndex = JSON.parse(
        runText("tar", ["-xOf", tarball, "package/registry/index.json"]),
      ) as { integrations?: Record<string, { manifest?: string } | string> };
      const integrations = registryIndex.integrations ?? {};
      expect(Object.keys(integrations).length).toBeGreaterThan(0);
      for (const [name, entry] of Object.entries(integrations)) {
        const manifestPath = typeof entry === "string" ? entry : entry.manifest;
        expect(manifestPath, `${name} has no manifest`).toBeTruthy();
        const packedManifest = `registry/${manifestPath!}`;
        expect(paths, `missing ${packedManifest}`).toContain(packedManifest);
        const manifest = JSON.parse(
          runText("tar", ["-xOf", tarball, `package/${packedManifest}`]),
        ) as { files?: string[] };
        expect(manifest.files?.length, `${name} manifest has no files`).toBeGreaterThan(0);
        const manifestDirectory = dirname(packedManifest);
        for (const file of manifest.files ?? []) {
          expect(paths, `missing ${name} manifest file ${file}`).toContain(
            join(manifestDirectory, file).replaceAll("\\", "/"),
          );
        }
      }
      expect(manifest.dependencies).toEqual({
        ajv: "^8.20.0",
        "ajv-formats": "^3.0.1",
      });
      expect(manifest.peerDependencies?.zod).toBe(">=4.3 <5");
      expect(manifest.devDependencies?.zod).toBe("^4.3.6");
      const sourceManifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
      expect(manifest.devDependencies?.["@types/node"]).toBe(
        sourceManifest.devDependencies["@types/node"],
      );
      expect(manifest.dependencies).not.toHaveProperty("zod");
      const prefix = "package/contracts/";
      const actual = runText("tar", ["-tzf", tarball])
        .split("\n")
        .filter((path) => path.startsWith(prefix) && /\.(json|md)$/.test(path))
        .map((path) => path.slice(prefix.length))
        .sort();
      const expected = contractFiles(canonicalRoot);

      expect(actual).toEqual(expected);
      for (const path of expected) {
        const packaged = runBytes("tar", ["-xOf", tarball, `${prefix}${path}`]);
        expect(packaged).toEqual(readFileSync(join(canonicalRoot, path)));
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);
});
