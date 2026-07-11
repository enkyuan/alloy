#!/usr/bin/env bun
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
} from "../src/integrations/registry-loader";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(scriptsDirectory, "..", "registry");

export async function validateRegistry(root = registryRoot): Promise<string[]> {
  const registryIndex = await loadRegistryIndex(root);
  const integrationNames = Object.keys(registryIndex.integrations).sort();
  for (const name of integrationNames) {
    await loadManifest(root, name, { index: registryIndex });
  }
  return integrationNames;
}

async function runRegistryValidation(): Promise<number> {
  try {
    const integrationNames = await validateRegistry();
    for (const name of integrationNames) console.log(`OK   ${name}/manifest.json`);
    return 0;
  } catch (error) {
    console.error(`FAIL ${formatIntegrationError(error)}`);
    return 1;
  }
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  process.exit(await runRegistryValidation());
}
