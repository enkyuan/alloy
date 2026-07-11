#!/usr/bin/env bun
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
} from "../src/integrations/registry-loader";

const here = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(here, "..", "registry");

export async function validateRegistry(root = registryRoot): Promise<string[]> {
  const index = await loadRegistryIndex(root);
  const names = Object.keys(index.integrations).sort();
  for (const name of names) {
    await loadManifest(root, name, { index });
  }
  return names;
}

async function main(): Promise<number> {
  try {
    const names = await validateRegistry();
    for (const name of names) console.log(`OK   ${name}/manifest.json`);
    return 0;
  } catch (error) {
    console.error(`FAIL ${formatIntegrationError(error)}`);
    return 1;
  }
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  process.exit(await main());
}
