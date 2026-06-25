/**
 * `kaji add <name>` — copy a registry integration's TypeScript source into
 * the consumer's project.
 *
 * Mirrors `kaji.cli.add` in Python: read the on-disk registry index, resolve
 * the manifest, validate its required keys, copy only `.ts` files into
 * `--out`. The Python loader copies every file in `manifest.files` verbatim;
 * the TS CLI is language-scoped because TS consumers don't want `.py` files
 * arriving in their tree.
 *
 * Returns a process exit code:
 *  0  success (or "no TypeScript files; skipped" — a valid outcome).
 *  1  unknown integration, missing manifest, validation failure, or collision
 *     without `--force`.
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

export interface AddOptions {
  /** Absolute path to a registry directory (one with `index.json`). */
  registryRoot: string;
  /** Sink for human-readable progress + error messages. Defaults to console.log. */
  log?: (msg: string) => void;
}

interface RegistryIndex {
  integrations?: Record<string, string>;
}

interface Manifest {
  name: string;
  version: string;
  namespace: string;
  description: string;
  auth: { kind: string; env?: string };
  files: string[];
  tools: { name: string; description: string }[];
}

const REQUIRED_KEYS = [
  "name",
  "version",
  "namespace",
  "description",
  "auth",
  "files",
  "tools",
] as const;

export async function add(argv: string[], opts: AddOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const name = argv[0];
  if (!name || name.startsWith("-")) {
    log("usage: kaji add <name> [--out <dir>] [--force]");
    return 1;
  }

  let out = "./integrations";
  let force = false;
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === "--out") {
      const next = argv[++i];
      if (next === undefined) {
        log("--out requires a value");
        return 1;
      }
      out = next;
    } else if (argv[i] === "--force") {
      force = true;
    } else {
      log(`Unknown argument: ${argv[i]}`);
      return 1;
    }
  }

  const indexPath = join(opts.registryRoot, "index.json");
  if (!existsSync(indexPath)) {
    log(`Registry index missing at ${indexPath}`);
    return 1;
  }
  let index: RegistryIndex;
  try {
    index = JSON.parse(readFileSync(indexPath, "utf8")) as RegistryIndex;
  } catch (e) {
    log(`Registry index is not valid JSON: ${(e as Error).message}`);
    return 1;
  }

  const rel = index.integrations?.[name];
  if (!rel) {
    const available =
      Object.keys(index.integrations ?? {})
        .sort()
        .join(", ") || "(none)";
    log(`Unknown integration: '${name}'. Available: ${available}`);
    return 1;
  }

  const manifestPath = join(opts.registryRoot, rel);
  if (!existsSync(manifestPath)) {
    log(`Manifest missing: ${manifestPath}`);
    return 1;
  }
  let manifest: Manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest;
  } catch (e) {
    log(`Manifest is not valid JSON: ${(e as Error).message}`);
    return 1;
  }
  for (const key of REQUIRED_KEYS) {
    if (!(key in manifest)) {
      log(`Manifest missing key '${key}' at ${manifestPath}`);
      return 1;
    }
  }
  if (!Array.isArray(manifest.files) || manifest.files.length === 0) {
    log(`Manifest 'files' must be a non-empty array at ${manifestPath}`);
    return 1;
  }

  const tsFiles = manifest.files.filter((f) => f.endsWith(".ts"));
  if (tsFiles.length === 0) {
    log(`Skipping '${name}': no TypeScript source files in this integration (Python only).`);
    return 0;
  }

  const manifestDir = dirname(manifestPath);
  for (const f of tsFiles) {
    const src = join(manifestDir, f);
    if (!existsSync(src)) {
      log(`Manifest ${manifestPath} references missing file ${src}`);
      return 1;
    }
    const dest = join(out, f);
    if (existsSync(dest) && !force) {
      log(`File exists: ${dest} (use --force to overwrite)`);
      return 1;
    }
  }

  mkdirSync(out, { recursive: true });
  for (const f of tsFiles) {
    const src = join(manifestDir, f);
    const dest = join(out, f);
    mkdirSync(dirname(dest), { recursive: true });
    copyFileSync(src, dest);
  }
  log(`Wrote ${tsFiles.length} file(s) to ${out}`);
  return 0;
}
