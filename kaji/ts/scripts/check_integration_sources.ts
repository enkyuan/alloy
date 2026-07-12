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
import { compareExecutableIntegrationAbi, echoExecutableAbi } from "./integration-abi";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(scriptsDirectory, "..", "registry");
const requiredHeaderPrefix = "// This is YOUR";

async function checkIntegrationSources(): Promise<number> {
  try {
    const registryIndex = await loadRegistryIndex(registryRoot);
    const integrationNames = Object.keys(registryIndex.integrations).sort();
    let echoManifest: LoadedIntegrationManifest | undefined;
    for (const name of integrationNames) {
      const manifest = await loadManifest(registryRoot, name, { index: registryIndex });
      if (name === "echo") echoManifest = manifest;
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
    if (echoManifest === undefined) throw new Error("stable Echo manifest is missing");
    compareExecutableIntegrationAbi(echoManifest, echoExecutableAbi());
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
