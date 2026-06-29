import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validateAllManifests, validateOne } from "../scripts/validate-manifests";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REGISTRY_DIR = join(__dirname, "..", "registry");

describe("registry manifests validate against schema.json", () => {
  const results = validateAllManifests();
  for (const r of results) {
    it(`${r.dir}/manifest.json is valid`, () => {
      if (!r.ok) {
        throw new Error(`${r.dir} invalid: ${JSON.stringify(r.errors, null, 2)}`);
      }
      expect(r.ok).toBe(true);
    });
  }

  // T-G2: named load-bearing case. sqlite's peerDeps is the only non-empty one.
  it("sqlite's peerDeps shape (object<string,string>) validates", () => {
    const manifest = JSON.parse(
      readFileSync(join(REGISTRY_DIR, "sqlite", "manifest.json"), "utf8"),
    );
    const { ok, errors } = validateOne(manifest);
    expect(ok, `errors: ${JSON.stringify(errors)}`).toBe(true);
  });
});

// T-G3: negative tests. Schema must reject mistakes, not just accept current files.
describe("schema rejects malformed manifests", () => {
  const base = {
    name: "x",
    version: "0.1.0",
    namespace: "x",
    description: "x",
    auth: { kind: "none" },
    files: ["index.ts"],
    tools: [{ name: "y", description: "y" }],
  };

  it("rejects the Python-era 'extras' field (additionalProperties: false at root)", () => {
    const { ok } = validateOne({ ...base, extras: ["httpx"] });
    expect(ok).toBe(false);
  });

  it("rejects peerDeps as array instead of object", () => {
    const { ok } = validateOne({ ...base, peerDeps: ["better-sqlite3"] });
    expect(ok).toBe(false);
  });

  it("rejects peerDeps with non-string version", () => {
    const { ok } = validateOne({ ...base, peerDeps: { "better-sqlite3": 9 } });
    expect(ok).toBe(false);
  });
});
