/** Validate the TS registry and its copyable-source header policy. */
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
  type LoadedIntegrationManifest,
} from "../src/integrations/registry-loader";
import { compareExecutableIntegrationAbi, loadExecutableIntegrationAbi } from "./integration-abi";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(scriptsDirectory, "..", "registry");
const abiIndexPath = join(
  scriptsDirectory,
  "..",
  "..",
  "..",
  "contracts",
  "integrations",
  "abi-index-v1.json",
);
const requiredHeaderPrefix = "// This is YOUR";

async function checkIntegrationSources(): Promise<number> {
  try {
    const registryIndex = await loadRegistryIndex(registryRoot);
    const integrationNames = Object.keys(registryIndex.integrations).sort();
    const manifests = new Map<string, LoadedIntegrationManifest>();
    for (const name of integrationNames) {
      const manifest = await loadManifest(registryRoot, name, { index: registryIndex });
      manifests.set(name, manifest);
      for (const file of manifest.files.filter((candidate) => candidate.endsWith(".ts"))) {
        const sourceText = await readFile(join(manifest.root, file), "utf8");
        if (!sourceText.startsWith(requiredHeaderPrefix)) {
          throw new Error(
            `${file} for integration '${name}' must start with '${requiredHeaderPrefix}...'`,
          );
        }
      }
      console.log(`  ✓ ${name}`);
    }
    const abiIndex = JSON.parse(await readFile(abiIndexPath, "utf8")) as {
      integrations: Record<string, string>;
    };
    for (const name of Object.keys(abiIndex.integrations).sort()) {
      const manifest = manifests.get(name);
      if (manifest === undefined) throw new Error(`indexed integration '${name}' is missing`);
      compareExecutableIntegrationAbi(manifest, await loadExecutableIntegrationAbi(name));
    }
    console.log(
      `\ncheck passed: ${integrationNames.length}/${integrationNames.length} integrations OK`,
    );
    return 0;
  } catch (error) {
    console.error(`\ncheck FAILED: ${formatIntegrationError(error)}`);
    return 1;
  }
}

process.exit(await checkIntegrationSources());
