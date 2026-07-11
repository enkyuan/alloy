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
import { randomUUID } from "node:crypto";
import { constants, existsSync, mkdirSync, realpathSync } from "node:fs";
import { copyFile, lstat, rename, rm } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import {
  formatIntegrationError,
  IntegrationExperimentalError,
  loadManifest,
  loadRegistryIndex,
  resolveManifestFile,
  type LoadedIntegrationManifest,
  type RegistryIndexDocument,
} from "@/integrations/registry-loader";

export interface AddOptions {
  /** Absolute path to a registry directory (one with `index.json`). */
  registryRoot: string;
  /** Directory containing the packaged integration schemas. Defaults to registryRoot. */
  schemaRoot?: string;
  /** Sink for human-readable progress + error messages. Defaults to console.log. */
  log?: (msg: string) => void;
}

function errorCode(error: unknown): string | undefined {
  return error instanceof Error && "code" in error
    ? (error as NodeJS.ErrnoException).code
    : undefined;
}

async function rejectDestinationSymlink(destination: string): Promise<void> {
  try {
    if ((await lstat(destination)).isSymbolicLink()) {
      throw new Error(`Refusing to overwrite destination symlink: ${destination}`);
    }
  } catch (error) {
    if (errorCode(error) !== "ENOENT") throw error;
  }
}

async function copyToDestination(
  source: string,
  destination: string,
  force: boolean,
): Promise<void> {
  await rejectDestinationSymlink(destination);
  if (!force) {
    // COPYFILE_EXCL makes a final-component swap fail instead of following it.
    await copyFile(source, destination, constants.COPYFILE_EXCL);
    return;
  }

  // Build the replacement beside the destination, then rename it atomically.
  // rename(2) replaces a raced-in final symlink entry; it never follows that
  // symlink to the victim. The second lstat still rejects symlinks observed
  // before the atomic replacement.
  const temporary = join(
    dirname(destination),
    `.${basename(destination)}.kaji-${randomUUID()}.tmp`,
  );
  try {
    await copyFile(source, temporary, constants.COPYFILE_EXCL);
    await rejectDestinationSymlink(destination);
    await rename(temporary, destination);
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
  }
}

export async function add(argv: string[], opts: AddOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const name = argv[0];
  if (!name || name.startsWith("-")) {
    log("usage: kaji add <name> [--out <dir>] [--force] [--allow-experimental]");
    return 1;
  }

  let out = "./integrations";
  let force = false;
  let allowExperimental = false;
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
    } else if (argv[i] === "--allow-experimental") {
      allowExperimental = true;
    } else {
      log(`Unknown argument: ${argv[i]}`);
      return 1;
    }
  }

  let index: RegistryIndexDocument;
  try {
    index = await loadRegistryIndex(opts.registryRoot, { schemaRoot: opts.schemaRoot });
  } catch (error) {
    log(formatIntegrationError(error));
    return 1;
  }

  const entry = index.integrations[name];
  if (entry === undefined) {
    const available = Object.keys(index.integrations).sort().join(", ") || "(none)";
    log(`Unknown integration: '${name}'. Available: ${available}`);
    return 1;
  }
  if (entry.stability === "experimental" && !allowExperimental) {
    log(formatIntegrationError(new IntegrationExperimentalError(name)));
    return 1;
  }

  let manifest: LoadedIntegrationManifest;
  try {
    manifest = await loadManifest(opts.registryRoot, name, {
      schemaRoot: opts.schemaRoot,
      index,
    });
  } catch (error) {
    log(formatIntegrationError(error));
    return 1;
  }

  const tsFiles = manifest.files
    .map((file, index) => ({ file, index }))
    .filter(({ file }) => file.endsWith(".ts"));
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
  for (const { file: f, index } of tsFiles) {
    try {
      await resolveManifestFile(manifest, index);
    } catch (error) {
      log(formatIntegrationError(error));
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

  for (const { file: f, index } of tsFiles) {
    let src: string;
    try {
      // Re-resolve immediately before copying so a swapped source symlink is
      // rechecked against the manifest directory containment boundary.
      src = await resolveManifestFile(manifest, index);
    } catch (error) {
      log(formatIntegrationError(error));
      return 1;
    }
    const dest = resolve(resolvedOut, f);
    mkdirSync(dirname(dest), { recursive: true });
    try {
      await copyToDestination(src, dest, force);
    } catch (error) {
      log(formatIntegrationError(error));
      return 1;
    }
  }
  log(`Wrote ${tsFiles.length} file(s) to ${resolvedOut}`);
  return 0;
}
