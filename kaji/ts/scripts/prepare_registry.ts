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

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const registryDestination = join(scriptsDirectory, "..", "registry");
const standaloneRegistryIndex = join(registryDestination, "index.json");

async function prepareRegistry(): Promise<number> {
  if (existsSync(standaloneRegistryIndex)) {
    console.log(
      "Using standalone TS registry (registry/index.json exists). Skipping Python registry copy.",
    );
    return 0;
  }

  const registrySource = join(
    scriptsDirectory,
    "..",
    "..",
    "sdk",
    "kaji",
    "integrations",
    "registry",
  );

  if (!existsSync(registrySource)) {
    console.error(`Source registry missing: ${registrySource}`);
    console.error(
      "This script only runs inside the monorepo. A standalone kaji/ts checkout must vendor the registry separately.",
    );
    return 1;
  }

  const { cpSync, mkdirSync, rmSync } = await import("node:fs");
  rmSync(registryDestination, { recursive: true, force: true });
  mkdirSync(registryDestination, { recursive: true });
  cpSync(registrySource, registryDestination, { recursive: true });
  console.log(`Copied registry: ${registrySource} -> ${registryDestination}`);
  return 0;
}

process.exit(await prepareRegistry());
