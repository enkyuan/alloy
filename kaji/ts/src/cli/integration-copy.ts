/** Rollback-safe copied integration bundle provenance and publication. */
import { createHash, randomUUID } from "node:crypto";
import {
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, resolve, sep } from "node:path";

import Ajv2020, { type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import {
  resolveManifestFile,
  type LoadedIntegrationManifest,
  type RegistryIndexEntry,
} from "@/integrations/registry-loader";

export type BundleState = "current" | "absent" | "outdated" | "modified" | "demoted";

export interface BundleStatus {
  readonly state: BundleState;
  readonly reasonCode: string;
  readonly destination: string;
  readonly written: readonly string[];
  /** @internal Used only to reject a destination race before publication. */
  readonly observed: string;
}

export class BundleTransitionError extends Error {
  constructor(readonly status: BundleStatus) {
    super(`Integration bundle is ${status.state}: ${status.reasonCode}`);
    this.name = "BundleTransitionError";
  }
}

interface CopyContext {
  readonly manifest: LoadedIntegrationManifest;
  readonly entry: RegistryIndexEntry;
  readonly destination: string;
  readonly runtime: "typescript";
}

interface InstallOptions extends CopyContext {
  readonly force?: boolean;
  /** @internal Deterministic rollback test seam. */
  readonly renameEntry?: (source: string, destination: string) => Promise<void>;
}

interface Provenance {
  readonly schemaVersion: "1.0.0";
  readonly integration: string;
  readonly sdkVersion: string;
  readonly runtime: "typescript";
  readonly stability: "experimental" | "beta";
  readonly registryEntrySha256: string;
  readonly abiSha256: string | null;
  readonly manifestSha256: string;
  readonly license: Readonly<{ identifier: string; url: string; sha256: string }>;
  readonly files: Readonly<Record<string, string>>;
}

const SIDECAR = ".kaji-integration-provenance.json";
const LEGACY_NULL_ABI = new Set(["fs", "http", "sqlite", "web"]);
const PACKAGE_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const CONTRACTS_ROOT = join(PACKAGE_ROOT, "contracts/integrations");
const PACKAGE_LICENSE = join(PACKAGE_ROOT, "LICENSE");
const LICENSE_IDENTIFIER = "PolyForm-Noncommercial-1.0.0";
const LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0";

function digest(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

let provenanceValidator: ValidateFunction | undefined;

async function validateProvenance(value: unknown): Promise<boolean> {
  if (provenanceValidator === undefined) {
    const schema = JSON.parse(
      await readFile(join(CONTRACTS_ROOT, "copy-provenance-v1.schema.json"), "utf8"),
    );
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    provenanceValidator = ajv.compile(schema);
  }
  return provenanceValidator(value) as boolean;
}

async function packageVersion(): Promise<string> {
  const value = JSON.parse(await readFile(join(PACKAGE_ROOT, "package.json"), "utf8")) as {
    version?: unknown;
  };
  if (typeof value.version !== "string" || value.version.length === 0) {
    throw new Error("Installed @kaji/sdk package metadata is incomplete");
  }
  return value.version;
}

async function abiDigest(name: string): Promise<string | null> {
  const index = JSON.parse(await readFile(join(CONTRACTS_ROOT, "abi-index-v1.json"), "utf8")) as {
    integrations: Record<string, string>;
  };
  const relativePath = index.integrations[name];
  if (relativePath === undefined) {
    if (LEGACY_NULL_ABI.has(name)) return null;
    throw new Error(`Integration '${name}' has no canonical ABI contract`);
  }
  const path = resolve(CONTRACTS_ROOT, relativePath);
  const rel = relative(CONTRACTS_ROOT, path);
  if (rel.startsWith("..") || rel.split(sep).includes("..")) {
    throw new Error("Canonical ABI path is unsafe");
  }
  return digest(await readFile(path));
}

async function safeSource(manifest: LoadedIntegrationManifest, index: number): Promise<string> {
  const source = await resolveManifestFile(manifest, index);
  const metadata = await lstat(source);
  if (metadata.isSymbolicLink() || !metadata.isFile()) {
    throw new Error("Integration source asset is unsafe");
  }
  const resolvedSource = await realpath(source);
  const resolvedRoot = await realpath(manifest.root);
  const rel = relative(resolvedRoot, resolvedSource);
  if (rel.startsWith("..") || rel.split(sep).includes("..")) {
    throw new Error("Integration source asset is unsafe");
  }
  return resolvedSource;
}

async function expectedProvenance(context: CopyContext): Promise<Provenance> {
  const { manifest, entry, runtime } = context;
  if (!manifest.runtimes.includes(runtime)) {
    throw new Error(`Integration '${manifest.name}' does not support ${runtime}`);
  }
  const files: Record<string, string> = {};
  let nestedLicense: string | undefined;
  for (const [index, relativePath] of manifest.files.entries()) {
    const source = await safeSource(manifest, index);
    files[relativePath] = digest(await readFile(source));
    if (relativePath === "LICENSE") nestedLicense = source;
  }
  const provenance: Provenance = {
    schemaVersion: "1.0.0",
    integration: manifest.name,
    sdkVersion: await packageVersion(),
    runtime,
    stability: manifest.stability,
    registryEntrySha256: digest(
      canonicalJson({
        manifest: entry.manifest,
        runtimes: [...entry.runtimes],
        stability: entry.stability,
      }),
    ),
    abiSha256: await abiDigest(manifest.name),
    manifestSha256: digest(await readFile(manifest.path)),
    license: {
      identifier: LICENSE_IDENTIFIER,
      url: LICENSE_URL,
      sha256: digest(await readFile(nestedLicense ?? PACKAGE_LICENSE)),
    },
    files: Object.fromEntries(
      Object.entries(files).sort(([left], [right]) => left.localeCompare(right)),
    ),
  };
  if (!(await validateProvenance(provenance))) {
    throw new Error("Integration provenance failed schema validation");
  }
  return provenance;
}

async function exists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

async function readProvenance(path: string): Promise<[Provenance | undefined, string]> {
  if (!(await exists(path))) return [undefined, "missing_provenance"];
  try {
    const metadata = await lstat(path);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > 64 * 1024) {
      return [undefined, "invalid_provenance"];
    }
    const value: unknown = JSON.parse(await readFile(path, "utf8"));
    if (!(await validateProvenance(value))) return [undefined, "invalid_provenance"];
    return [value as Provenance, ""];
  } catch {
    return [undefined, "invalid_provenance"];
  }
}

async function destinationFiles(root: string, directory = root): Promise<Set<string>> {
  const files = new Set<string>();
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    const metadata = await lstat(path);
    if (metadata.isSymbolicLink()) throw new Error("symlink");
    if (metadata.isDirectory()) {
      const nested = await destinationFiles(root, path);
      for (const relativePath of nested) files.add(relativePath);
    } else if (metadata.isFile() && entry.name !== SIDECAR) {
      files.add(relative(root, path).split(sep).join("/"));
    }
  }
  return files;
}

async function observedToken(provenance: Provenance, destination: string): Promise<string> {
  const files: Record<string, string> = {};
  for (const relativePath of Object.keys(provenance.files).sort()) {
    const path = join(destination, relativePath);
    try {
      const metadata = await lstat(path);
      if (metadata.isSymbolicLink() || !metadata.isFile()) return "changed";
      files[relativePath] = digest(await readFile(path));
    } catch {
      return "changed";
    }
  }
  return digest(canonicalJson({ provenance, files }));
}

function status(
  state: BundleState,
  reasonCode: string,
  destination: string,
  observed: string,
  written: readonly string[] = [],
): BundleStatus {
  return { state, reasonCode, destination, observed, written };
}

export async function classifyIntegrationBundle(context: CopyContext): Promise<BundleStatus> {
  const destination = resolve(context.destination);
  if (!(await exists(destination))) return status("absent", "not_installed", destination, "absent");
  const metadata = await lstat(destination);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    return status("modified", "unsafe_destination", destination, "unsafe");
  }
  try {
    if ((await readdir(destination)).length === 0) {
      return status("absent", "not_installed", destination, "empty");
    }
  } catch {
    return status("modified", "unsafe_destination", destination, "unreadable");
  }
  const [provenance, failure] = await readProvenance(join(destination, SIDECAR));
  if (provenance === undefined) return status("modified", failure, destination, failure);
  if (provenance.integration !== context.manifest.name) {
    return status("modified", "cross_provider", destination, "cross_provider");
  }
  if (provenance.runtime !== context.runtime) {
    return status("modified", "runtime_mismatch", destination, "runtime_mismatch");
  }
  let actual: Set<string>;
  try {
    actual = await destinationFiles(destination);
  } catch {
    return status("modified", "local_changes", destination, "symlink");
  }
  const tracked = new Set(Object.keys(provenance.files));
  if (actual.size !== tracked.size || [...actual].some((path) => !tracked.has(path))) {
    return status("modified", "local_changes", destination, "files");
  }
  const observed = await observedToken(provenance, destination);
  if (
    observed === "changed" ||
    Object.entries(provenance.files).some(
      ([relativePath, expected]) => actual.has(relativePath) && expected.length !== 64,
    )
  ) {
    return status("modified", "local_changes", destination, observed);
  }
  for (const [relativePath, expected] of Object.entries(provenance.files)) {
    if (digest(await readFile(join(destination, relativePath))) !== expected) {
      return status("modified", "local_changes", destination, observed);
    }
  }
  const expected = await expectedProvenance({ ...context, destination });
  if (provenance.stability === "beta" && context.manifest.stability === "experimental") {
    return status("demoted", "stability_demoted", destination, observed);
  }
  if (canonicalJson(provenance) === canonicalJson(expected)) {
    return status("current", "up_to_date", destination, observed);
  }
  return status("outdated", "upstream_changed", destination, observed);
}

async function safeParent(destination: string): Promise<string> {
  const parent = dirname(destination);
  let probe = parent;
  while (!(await exists(probe)) && probe !== dirname(probe)) probe = dirname(probe);
  if ((await lstat(probe)).isSymbolicLink()) throw new Error("Destination parent is unsafe");
  await mkdir(parent, { recursive: true });
  const metadata = await lstat(parent);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error("Destination parent is unsafe");
  }
  return parent;
}

export async function installIntegrationBundle(options: InstallOptions): Promise<BundleStatus> {
  const context = { ...options, destination: resolve(options.destination) };
  const initial = await classifyIntegrationBundle(context);
  if (initial.state === "current") return initial;
  if (initial.state === "outdated" && options.force !== true) {
    throw new BundleTransitionError(initial);
  }
  if (initial.state === "modified" || initial.state === "demoted") {
    throw new BundleTransitionError(initial);
  }

  const provenance = await expectedProvenance(context);
  const parent = await safeParent(context.destination);
  const staging = await mkdtemp(join(parent, `.${options.manifest.name}.kaji-stage-`));
  const backup = join(parent, `.${options.manifest.name}.kaji-backup-${randomUUID()}`);
  const renameEntry = options.renameEntry ?? rename;
  let wroteBackup = false;
  try {
    for (const [index, relativePath] of options.manifest.files.entries()) {
      const source = await safeSource(options.manifest, index);
      const target = join(staging, relativePath);
      await mkdir(dirname(target), { recursive: true });
      await copyFile(source, target);
    }
    await writeFile(join(staging, SIDECAR), `${canonicalJson(provenance)}\n`, "utf8");
    const staged = await classifyIntegrationBundle({ ...context, destination: staging });
    if (staged.state !== "current") throw new Error("Staged integration bundle failed validation");

    const live = await classifyIntegrationBundle(context);
    if (
      live.state !== initial.state ||
      live.reasonCode !== initial.reasonCode ||
      live.observed !== initial.observed
    ) {
      throw new Error("Destination changed during integration copy");
    }
    if (initial.state === "outdated" || initial.observed === "empty") {
      await renameEntry(context.destination, backup);
      wroteBackup = true;
    }
    try {
      await renameEntry(staging, context.destination);
    } catch (error) {
      if (wroteBackup && !(await exists(context.destination))) {
        await renameEntry(backup, context.destination);
        wroteBackup = false;
      }
      throw error;
    }
    if (wroteBackup) {
      await rm(backup, { recursive: true, force: true });
      wroteBackup = false;
    }
    return status(
      "current",
      initial.state === "absent" ? "installed" : "updated",
      context.destination,
      await observedToken(provenance, context.destination),
      options.manifest.files.map((relativePath) => join(context.destination, relativePath)),
    );
  } finally {
    await rm(staging, { recursive: true, force: true }).catch(() => undefined);
    if (wroteBackup && !(await exists(context.destination)) && (await exists(backup))) {
      await renameEntry(backup, context.destination);
    }
  }
}
