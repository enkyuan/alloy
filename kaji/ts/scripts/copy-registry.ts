/**
 * Copy the on-disk integration registry from the SDK (`kaji/sdk/...`) into
 * `kaji/ts/registry/` so the npm package can ship it alongside `dist/`.
 *
 * Runs as `prebuild`. Idempotent. Errors out loudly if the source registry
 * is missing — that happens only outside the monorepo (e.g. an isolated
 * `kaji/ts` checkout). CI that builds the standalone TS package will need
 * to vendor the registry separately.
 */
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "sdk", "kaji", "integrations", "registry");
const dest = join(here, "..", "registry");

if (!existsSync(src)) {
  console.error(`Source registry missing: ${src}`);
  console.error(
    "This script only runs inside the monorepo. A standalone kaji/ts checkout must vendor the registry separately.",
  );
  process.exit(1);
}

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
console.log(`Copied registry: ${src} -> ${dest}`);
