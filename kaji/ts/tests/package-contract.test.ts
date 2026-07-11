import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, "..");
const canonicalRoot = resolve(packageRoot, "../contracts");

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
      ) as Array<{ filename: string }>;
      const tarball = join(workdir, packed[0]!.filename);
      const manifest = JSON.parse(
        execFileSync("tar", ["-xOf", tarball, "package/package.json"], {
          encoding: "utf8",
        }),
      ) as {
        dependencies?: Record<string, string>;
        devDependencies?: Record<string, string>;
        peerDependencies?: Record<string, string>;
      };
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
