/**
 * Validate all integrations in the TS-native registry.
 *
 * For each entry in registry/index.json, checks:
 *  - manifest.json exists and has all required fields
 *  - index.ts exists and contains the required header comment
 *
 * Exits 1 with a clear error message on first failure.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(here, "..", "registry");
const indexPath = join(registryRoot, "index.json");

const REQUIRED_MANIFEST_FIELDS = [
  "name",
  "version",
  "namespace",
  "description",
  "auth",
  "files",
  "tools",
] as const;

const REQUIRED_HEADER_PREFIX = "// This is YOUR";

function fail(msg: string): never {
  console.error(`\ncheck-integration FAILED: ${msg}`);
  process.exit(1);
}

function checkField(obj: Record<string, unknown>, field: string, context: string): void {
  if (!(field in obj)) {
    fail(`manifest.json missing required field '${field}' in ${context}`);
  }
}

if (!existsSync(indexPath)) {
  fail(`Registry index missing at ${indexPath}`);
}

let index: { integrations?: Record<string, string> };
try {
  index = JSON.parse(readFileSync(indexPath, "utf8")) as { integrations?: Record<string, string> };
} catch (e) {
  fail(`Registry index.json is not valid JSON: ${(e as Error).message}`);
}

const integrations = index.integrations ?? {};
const names = Object.keys(integrations);

if (names.length === 0) {
  console.log("No integrations listed in registry/index.json. Nothing to check.");
  process.exit(0);
}

let passed = 0;
for (const name of names) {
  const relManifest = integrations[name];
  if (!relManifest) {
    fail(`integrations['${name}'] has no path in index.json`);
  }

  const manifestPath = join(registryRoot, relManifest);
  const integrationDir = dirname(manifestPath);
  const context = `integration '${name}'`;

  if (!existsSync(manifestPath)) {
    fail(`manifest.json missing for ${context} at ${manifestPath}`);
  }

  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
  } catch (e) {
    fail(`manifest.json is not valid JSON for ${context}: ${(e as Error).message}`);
  }

  for (const field of REQUIRED_MANIFEST_FIELDS) {
    checkField(manifest, field, context);
  }

  const files = manifest["files"] as string[] | undefined;
  if (!Array.isArray(files) || files.length === 0) {
    fail(`manifest.json 'files' must be a non-empty array for ${context}`);
  }

  for (const f of files) {
    if (!f.endsWith(".ts")) continue;
    const tsPath = join(integrationDir, f);

    if (!existsSync(tsPath)) {
      fail(`${f} listed in manifest.files not found for ${context} at ${tsPath}`);
    }

    const source = readFileSync(tsPath, "utf8");
    if (!source.startsWith(REQUIRED_HEADER_PREFIX)) {
      fail(
        `${f} for ${context} must start with '${REQUIRED_HEADER_PREFIX}...'\n` +
          `  Found: ${JSON.stringify(source.slice(0, 60))}`,
      );
    }
  }

  console.log(`  ✓ ${name}`);
  passed++;
}

console.log(`\ncheck-integration passed: ${passed}/${names.length} integrations OK`);
