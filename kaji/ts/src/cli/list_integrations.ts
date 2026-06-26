/**
 * `kaji list-integrations`: enumerate every integration in the registry
 * catalog (`registry/index.json`) and print `name  description`.
 *
 * Follows the same flow as `kaji add` so the two commands agree on what
 * "available" means: an entry in `index.json`, not just a directory under
 * `registry/`.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { RunOptions } from "./index";

interface IndexFile {
  version?: string;
  integrations?: Record<string, string>;
}

interface Manifest {
  name?: string;
  description?: string;
}

export async function listIntegrations(_rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const indexPath = join(opts.registryRoot, "index.json");
  if (!existsSync(indexPath)) {
    log("No integrations found.");
    return 0;
  }
  let index: IndexFile;
  try {
    index = JSON.parse(readFileSync(indexPath, "utf8")) as IndexFile;
  } catch {
    log("No integrations found.");
    return 0;
  }
  const entries = Object.entries(index.integrations ?? {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) {
    log("No integrations found.");
    return 0;
  }
  const rows: Array<[string, string]> = [];
  for (const [name, manifestRel] of entries) {
    const manifestPath = join(opts.registryRoot, manifestRel);
    let manifest: Manifest = {};
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest;
    } catch {
      // Treat missing/unreadable manifest as a still-listable integration.
    }
    rows.push([manifest.name ?? name, manifest.description ?? ""]);
  }
  const width = Math.max(...rows.map(([n]) => n.length));
  for (const [name, desc] of rows) {
    log(`${name.padEnd(width)}  ${desc}`);
  }
  return 0;
}
