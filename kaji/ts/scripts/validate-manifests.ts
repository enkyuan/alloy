#!/usr/bin/env bun
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv/dist/2020";

// ESM-safe __dirname (kaji/ts is "type": "module"). Don't use __dirname directly.
const __dirname = dirname(fileURLToPath(import.meta.url));
const REGISTRY_DIR = join(__dirname, "..", "registry");

export type ValidationResult =
  | { dir: string; ok: true }
  | { dir: string; ok: false; errors: unknown };

export function validateAllManifests(): ValidationResult[] {
  const schema = JSON.parse(readFileSync(join(REGISTRY_DIR, "schema.json"), "utf8"));
  const ajv = new Ajv({ strict: false });
  const validate = ajv.compile(schema);

  const dirs = readdirSync(REGISTRY_DIR, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);

  const results: ValidationResult[] = [];
  for (const dir of dirs) {
    const path = join(REGISTRY_DIR, dir, "manifest.json");
    // T-G1 guard: skip directories without a manifest (e.g. future _archive/).
    // Don't fail the whole suite on a stray dir; the integration template lint
    // (separate concern) decides whether a missing manifest is itself an error.
    if (!existsSync(path)) {
      console.warn(`SKIP ${dir}/ - no manifest.json (intentional dir without integration?)`);
      continue;
    }
    const manifest = JSON.parse(readFileSync(path, "utf8"));
    if (validate(manifest)) {
      results.push({ dir, ok: true });
    } else {
      results.push({ dir, ok: false, errors: validate.errors });
    }
  }
  return results;
}

// T-G3 negative-test helper. Confirms the schema rejects shapes we expect to reject.
// Exported so the Vitest suite can assert "schema actually catches mistakes",
// not just "current manifests happen to pass."
export function validateOne(manifest: unknown): { ok: boolean; errors: unknown } {
  const schema = JSON.parse(readFileSync(join(REGISTRY_DIR, "schema.json"), "utf8"));
  const ajv = new Ajv({ strict: false });
  const validate = ajv.compile(schema);
  return { ok: !!validate(manifest), errors: validate.errors ?? null };
}

function main(): number {
  const results = validateAllManifests();
  let failures = 0;
  for (const r of results) {
    if (r.ok) {
      console.log(`OK   ${r.dir}/manifest.json`);
    } else {
      failures++;
      console.error(`FAIL ${r.dir}/manifest.json`);
      for (const err of (r.errors as { instancePath?: string; message?: string }[]) ?? []) {
        console.error(`  ${err.instancePath || "/"} ${err.message}`);
      }
    }
  }
  if (failures > 0) {
    console.error(`\n${failures} manifest(s) failed validation`);
    return 1;
  }
  return 0;
}

// Only run main() when invoked directly (not when imported by the test).
if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main());
}
