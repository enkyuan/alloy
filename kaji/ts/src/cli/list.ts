/**
 * `kaji list-integrations`: enumerate every integration in the registry
 * catalog (`registry/index.json`) and print `name  description`.
 *
 * Follows the same flow as `kaji add` so the two commands agree on what
 * "available" means: an entry in `index.json`, not just a directory under
 * `registry/`.
 */
import type { RunOptions } from "@/cli/index";
import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
} from "@/integrations/registry-loader";

export async function listIntegrations(_rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  let index;
  try {
    index = await loadRegistryIndex(opts.registryRoot, { schemaRoot: opts.schemaRoot });
  } catch (error) {
    err(formatIntegrationError(error));
    return 1;
  }
  const entries = Object.keys(index.integrations).sort((a, b) => a.localeCompare(b));
  if (entries.length === 0) {
    log("No integrations found.");
    return 0;
  }
  const rows: Array<[string, string]> = [];
  for (const name of entries) {
    try {
      const manifest = await loadManifest(opts.registryRoot, name, {
        schemaRoot: opts.schemaRoot,
        index,
      });
      rows.push([manifest.name, manifest.description]);
    } catch (error) {
      err(formatIntegrationError(error));
      return 1;
    }
  }
  const width = Math.max(...rows.map(([n]) => n.length));
  for (const [name, desc] of rows) {
    log(`${name.padEnd(width)}  ${desc}`);
  }
  return 0;
}
