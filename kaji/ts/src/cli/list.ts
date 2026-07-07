/**
 * `kaji list-integrations`: enumerate every integration in the registry
 * catalog (`registry/index.json`) and print `name  description`.
 *
 * Follows the same flow as `kaji add` so the two commands agree on what
 * "available" means: an entry in `index.json`, not just a directory under
 * `registry/`.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";
import { readTextFile } from "@/cli/bun-io";
import type { RunOptions } from "@/cli/index";

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
  const err = opts.err ?? ((m: string) => console.error(m));
  const indexPath = join(opts.registryRoot, "index.json");
  if (!existsSync(indexPath)) {
    log("No integrations found.");
    return 0;
  }
  let index: IndexFile;
  try {
    index = JSON.parse(await readTextFile(indexPath)) as IndexFile;
  } catch (e) {
    // Distinguish corruption from absence so a broken catalog is fixable
    // instead of silently invisible.
    const msg = e instanceof Error ? e.message : String(e);
    err(`Registry index is not valid JSON (${indexPath}): ${msg}`);
    return 1;
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
      manifest = JSON.parse(await readTextFile(manifestPath)) as Manifest;
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
