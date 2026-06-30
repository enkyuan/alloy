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
import { existsSync, mkdirSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { copyFileBunFirst, readTextFile } from "@/cli/bun_io";

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
    index = JSON.parse(await readTextFile(indexPath)) as RegistryIndex;
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
    manifest = JSON.parse(await readTextFile(manifestPath)) as Manifest;
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
  // Match the Python loader's auth.kind enum (integrations/__init__.py:111).
  // A manifest accepted here must also be accepted by the Python side.
  if (
    typeof manifest.auth !== "object" ||
    manifest.auth === null ||
    typeof manifest.auth.kind !== "string"
  ) {
    log(`Manifest 'auth.kind' is required at ${manifestPath}`);
    return 1;
  }
  if (!["env", "oauth", "none"].includes(manifest.auth.kind)) {
    log(
      `Manifest auth.kind must be one of env|oauth|none, got '${manifest.auth.kind}' at ${manifestPath}`,
    );
    return 1;
  }
  if (manifest.auth.kind === "env" && !manifest.auth.env) {
    log(`Manifest auth.kind=='env' requires 'auth.env' at ${manifestPath}`);
    return 1;
  }
  if (!Array.isArray(manifest.files) || manifest.files.length === 0) {
    log(`Manifest 'files' must be a non-empty array at ${manifestPath}`);
    return 1;
  }
  // Path traversal guard: reject any file entry that escapes the manifest
  // directory. An attacker-controlled manifest could otherwise drop files
  // anywhere the user has write access via "../../etc/foo.ts".
  for (const f of manifest.files) {
    if (typeof f !== "string" || isAbsolute(f) || f.split(/[\\/]/).includes("..")) {
      log(`Manifest 'files' contains unsafe path: ${JSON.stringify(f)}`);
      return 1;
    }
  }

  const tsFiles = manifest.files.filter((f) => f.endsWith(".ts"));
  if (tsFiles.length === 0) {
    log(`Skipping '${name}': no TypeScript source files in this integration (Python only).`);
    return 0;
  }

  // Anchor every destination under the resolved --out so even a future bug
  // in the manifest check can't escape it. We materialise --out first so
  // realpath can resolve it, then re-check each destination's REAL parent
  // (following symlinks) against the real --out — purely lexical containment
  // is bypassable when --out/sub is a symlink pointing outside.
  const resolvedOut = resolve(out);
  mkdirSync(resolvedOut, { recursive: true });
  const realOut = realpathSync(resolvedOut);
  const manifestDir = dirname(manifestPath);
  for (const f of tsFiles) {
    const src = join(manifestDir, f);
    if (!existsSync(src)) {
      log(`Manifest ${manifestPath} references missing file ${src}`);
      return 1;
    }
    const dest = resolve(resolvedOut, f);
    const rel = relative(resolvedOut, dest);
    if (rel.startsWith("..") || isAbsolute(rel) || rel.split(sep).includes("..")) {
      log(`Refusing to write outside --out: ${dest}`);
      return 1;
    }
    // Realpath check: walk to the deepest existing ancestor of dest and
    // confirm it sits under realOut. Catches symlink escapes that the
    // string-level check above would miss (e.g. --out/sub -> /tmp/elsewhere).
    let probe = dirname(dest);
    while (!existsSync(probe) && probe !== dirname(probe)) {
      probe = dirname(probe);
    }
    if (existsSync(probe)) {
      const realProbe = realpathSync(probe);
      const realRel = relative(realOut, realProbe);
      if (
        realRel !== "" &&
        (realRel.startsWith("..") || isAbsolute(realRel) || realRel.split(sep).includes(".."))
      ) {
        log(`Refusing to write through symlinked parent: ${dest} -> ${realProbe}`);
        return 1;
      }
    }
    if (existsSync(dest) && !force) {
      log(`File exists: ${dest} (use --force to overwrite)`);
      return 1;
    }
  }

  for (const f of tsFiles) {
    const src = join(manifestDir, f);
    const dest = resolve(resolvedOut, f);
    mkdirSync(dirname(dest), { recursive: true });
    await copyFileBunFirst(src, dest);
  }
  log(`Wrote ${tsFiles.length} file(s) to ${resolvedOut}`);
  return 0;
}
