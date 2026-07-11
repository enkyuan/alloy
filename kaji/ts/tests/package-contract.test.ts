import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, "..");
const canonicalRoot = resolve(packageRoot, "../contracts");
const repositoryRoot = resolve(packageRoot, "../..");

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
  it("contains exactly the canonical contract files and bytes", () => {
    const workdir = mkdtempSync(join(tmpdir(), "kaji-contract-pack-"));
    try {
      const packed = JSON.parse(
        execFileSync("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", workdir], {
          cwd: packageRoot,
          encoding: "utf8",
          env: { ...process.env, npm_config_cache: join(workdir, "npm-cache") },
        }),
      ) as Array<{ filename: string; files: Array<{ path: string }> }>;
      const tarball = join(workdir, packed[0]!.filename);
      const paths = new Set(packed[0]!.files.map(({ path }) => path));
      const manifest = JSON.parse(
        execFileSync("tar", ["-xOf", tarball, "package/package.json"], {
          encoding: "utf8",
        }),
      ) as {
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
      expect(execFileSync("tar", ["-xOf", tarball, "package/LICENSE"])).toEqual(
        readFileSync(join(repositoryRoot, "LICENSE")),
      );
      for (const required of ["dist/cli/bin.js", "registry/index.json", "registry/schema.json"]) {
        expect(paths).toContain(required);
      }
      for (const target of exportTargets(manifest.exports)) {
        expect(paths, `missing export target ${target}`).toContain(target.replace(/^\.\//, ""));
      }
      for (const target of Object.values(manifest.bin)) {
        expect(paths, `missing CLI target ${target}`).toContain(target.replace(/^\.\//, ""));
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
        execFileSync("tar", ["-xOf", tarball, "package/registry/index.json"], {
          encoding: "utf8",
        }),
      ) as { integrations?: Record<string, { manifest?: string } | string> };
      const integrations = registryIndex.integrations ?? {};
      expect(Object.keys(integrations).length).toBeGreaterThan(0);
      for (const [name, entry] of Object.entries(integrations)) {
        const manifestPath = typeof entry === "string" ? entry : entry.manifest;
        expect(manifestPath, `${name} has no manifest`).toBeTruthy();
        const packedManifest = `registry/${manifestPath!}`;
        expect(paths, `missing ${packedManifest}`).toContain(packedManifest);
        const manifest = JSON.parse(
          execFileSync("tar", ["-xOf", tarball, `package/${packedManifest}`], {
            encoding: "utf8",
          }),
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
      expect(manifest.dependencies).not.toHaveProperty("zod");
      const prefix = "package/contracts/";
      const actual = execFileSync("tar", ["-tzf", tarball], { encoding: "utf8" })
        .split("\n")
        .filter((path) => path.startsWith(prefix) && /\.(json|md)$/.test(path))
        .map((path) => path.slice(prefix.length))
        .sort();
      const expected = contractFiles(canonicalRoot);

      expect(actual).toEqual(expected);
      for (const path of expected) {
        const packaged = execFileSync("tar", ["-xOf", tarball, `${prefix}${path}`]);
        expect(packaged).toEqual(readFileSync(join(canonicalRoot, path)));
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);
});
