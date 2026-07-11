/** Validate the TS registry and its copyable-source header policy. */
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
} from "../src/integrations/registry-loader";

const here = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(here, "..", "registry");
const requiredHeaderPrefix = "// This is YOUR";

async function main(): Promise<number> {
  try {
    const index = await loadRegistryIndex(registryRoot);
    const names = Object.keys(index.integrations).sort();
    for (const name of names) {
      const manifest = await loadManifest(registryRoot, name, { index });
      for (const file of manifest.files.filter((candidate) => candidate.endsWith(".ts"))) {
        const source = await readFile(join(manifest.root, file), "utf8");
        if (!source.startsWith(requiredHeaderPrefix)) {
          throw new Error(
            `${file} for integration '${name}' must start with '${requiredHeaderPrefix}...'`,
          );
        }
      }
      console.log(`  ✓ ${name}`);
    }
    console.log(`\ncheck passed: ${names.length}/${names.length} integrations OK`);
    return 0;
  } catch (error) {
    console.error(`\ncheck FAILED: ${formatIntegrationError(error)}`);
    return 1;
  }
}

process.exit(await main());
