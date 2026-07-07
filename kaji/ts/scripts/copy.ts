/**
 * Copy the on-disk integration registry from the SDK (`kaji/sdk/...`) into
 * `kaji/ts/registry/` so the npm package can ship it alongside `dist/`.
 *
 * Runs as `prebuild`. Idempotent. Skipped when the TS-native registry already
 * exists (indicated by `kaji/ts/registry/index.json`). In that case the
 * registry is maintained directly as permanent files in `kaji/ts/registry/`
 * and does not need to be copied from the Python SDK.
 */
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dest = join(here, "..", "registry");
const tsIndex = join(dest, "index.json");

if (existsSync(tsIndex)) {
  console.log(
    "Using standalone TS registry (registry/index.json exists). Skipping Python registry copy.",
  );
  process.exit(0);
}

const src = join(here, "..", "..", "sdk", "kaji", "integrations", "registry");

if (!existsSync(src)) {
  console.error(`Source registry missing: ${src}`);
  console.error(
    "This script only runs inside the monorepo. A standalone kaji/ts checkout must vendor the registry separately.",
  );
  process.exit(1);
}

const { cpSync, mkdirSync, rmSync } = await import("node:fs");
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
console.log(`Copied registry: ${src} -> ${dest}`);
