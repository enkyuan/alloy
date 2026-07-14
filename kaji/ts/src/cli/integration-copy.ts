/** Rollback-safe copied integration bundle provenance and publication. */
import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { constants } from "node:fs";
import {
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readlink,
  readdir,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, parse, relative, resolve, sep } from "node:path";

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
  /** @internal Deterministic absent-reservation race seams. */
  readonly beforeReservationCreate?: (destination: string) => Promise<void>;
  readonly beforeReservationPublish?: (destination: string) => Promise<void>;
  readonly afterReservationCheck?: (destination: string) => Promise<void>;
  readonly beforeReservationCleanup?: (destination: string) => Promise<void>;
}

interface Provenance {
  readonly schemaVersion: "1.0.0";
  readonly integration: string;
  readonly sdkVersion: string;
  readonly runtime: "typescript";
  readonly stability: "experimental" | "beta";
  readonly registryEntrySha256: string;
  readonly abiSha256: string;
  readonly manifestSha256: string;
  readonly license: Readonly<{ identifier: string; url: string; sha256: string }>;
  readonly files: Readonly<Record<string, string>>;
}

interface ReservationIdentity {
  readonly dev: number;
  readonly ino: number;
  readonly ctimeMs: number;
}

const SIDECAR = ".kaji-integration-provenance.json";
const PACKAGE_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const CONTRACTS_ROOT = join(PACKAGE_ROOT, "contracts/integrations");
const PACKAGE_LICENSE = join(PACKAGE_ROOT, "LICENSE");
const LICENSE_IDENTIFIER = "PolyForm-Noncommercial-1.0.0";
const LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0";
const SYSTEM_ROOT_ALIASES = [
  ["/var", "/private/var"],
  ["/tmp", "/private/tmp"],
] as const;
const RESERVATION_WORKER_TIMEOUT_MS = 15_000;
const RESERVATION_WORKER_OUTPUT_LIMIT = 8 * 1024;

class UnsafeDestinationError extends Error {}

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

async function abiDigest(name: string): Promise<string> {
  const index = JSON.parse(await readFile(join(CONTRACTS_ROOT, "abi-index-v1.json"), "utf8")) as {
    integrations: Record<string, string>;
  };
  const relativePath = index.integrations[name];
  if (relativePath === undefined) {
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

function errno(error: unknown, code: string): boolean {
  return (error as NodeJS.ErrnoException).code === code;
}

async function lexicalDestination(input: string): Promise<string> {
  let destination = resolve(input);
  for (const [alias, target] of SYSTEM_ROOT_ALIASES) {
    const suffix = relative(alias, destination);
    if (suffix.startsWith("..") || suffix.split(sep).includes("..")) continue;
    let metadata;
    try {
      metadata = await lstat(alias);
    } catch (error) {
      if (errno(error, "ENOENT")) continue;
      throw new UnsafeDestinationError("Destination path is unsafe");
    }
    if (!metadata.isSymbolicLink()) return destination;
    let linked: string;
    try {
      linked = resolve(dirname(alias), await readlink(alias));
    } catch {
      throw new UnsafeDestinationError("Destination path is unsafe");
    }
    if (linked !== target) throw new UnsafeDestinationError("Destination path is unsafe");
    destination = resolve(target, suffix);
    break;
  }
  return destination;
}

async function validatedDestination(input: string): Promise<string> {
  const destination = await lexicalDestination(input);
  const root = parse(destination).root;
  const parts = relative(root, destination).split(sep).filter(Boolean);
  let current = root;
  for (const [index, part] of parts.entries()) {
    current = join(current, part);
    let metadata;
    try {
      metadata = await lstat(current);
    } catch (error) {
      if (errno(error, "ENOENT")) break;
      throw new UnsafeDestinationError("Destination path is unsafe");
    }
    if (metadata.isSymbolicLink() || (index < parts.length - 1 && !metadata.isDirectory())) {
      throw new UnsafeDestinationError("Destination path is unsafe");
    }
  }
  return destination;
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
  const lexical = resolve(context.destination);
  let destination: string;
  try {
    destination = await validatedDestination(lexical);
  } catch (error) {
    if (error instanceof UnsafeDestinationError) {
      return status("modified", "unsafe_destination", lexical, "unsafe");
    }
    throw error;
  }
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
  destination = await validatedDestination(destination);
  const parent = dirname(destination);
  await mkdir(parent, { recursive: true });
  destination = await validatedDestination(destination);
  const canonicalParent = dirname(destination);
  const metadata = await lstat(canonicalParent);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error("Destination parent is unsafe");
  }
  return canonicalParent;
}

async function reservationIdentity(destination: string): Promise<ReservationIdentity> {
  let metadata;
  let entries: string[];
  try {
    metadata = await lstat(destination);
    entries = await readdir(destination);
  } catch {
    throw new Error("Destination changed during integration copy");
  }
  if (metadata.isSymbolicLink() || !metadata.isDirectory() || entries.length !== 0) {
    throw new Error("Destination changed during integration copy");
  }
  return { dev: metadata.dev, ino: metadata.ino, ctimeMs: metadata.ctimeMs };
}

async function matchesEmptyReservation(
  destination: string,
  identity: ReservationIdentity,
): Promise<boolean> {
  try {
    const metadata = await lstat(destination);
    return (
      !metadata.isSymbolicLink() &&
      metadata.isDirectory() &&
      metadata.dev === identity.dev &&
      metadata.ino === identity.ino &&
      metadata.ctimeMs === identity.ctimeMs &&
      (await readdir(destination)).length === 0
    );
  } catch {
    return false;
  }
}

async function pathHasReservationIdentity(
  destination: string,
  identity: ReservationIdentity,
): Promise<boolean> {
  try {
    const metadata = await lstat(destination);
    return (
      !metadata.isSymbolicLink() &&
      metadata.isDirectory() &&
      metadata.dev === identity.dev &&
      metadata.ino === identity.ino
    );
  } catch {
    return false;
  }
}

function reservationWorkerPath(): string {
  return fileURLToPath(
    new URL(
      import.meta.url.endsWith(".ts")
        ? "./integration-copy-worker.mjs"
        : "./integration-copy-worker.js",
      import.meta.url,
    ),
  );
}

async function invokeReservationWorker(
  destination: string,
  staging: string,
  relativePaths: readonly string[],
  identity: ReservationIdentity,
  afterCheck: (() => Promise<void>) | undefined,
): Promise<void> {
  const environment = { ...process.env };
  delete environment.NODE_OPTIONS;
  delete environment.NODE_PATH;

  await new Promise<void>((resolveWorker, rejectWorker) => {
    const child = spawn(
      process.execPath,
      [
        reservationWorkerPath(),
        identity.dev.toString(),
        identity.ino.toString(),
        staging,
        ...relativePaths,
      ],
      {
        cwd: destination,
        env: environment,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    let output = "";
    let outputBytes = 0;
    let prepared = false;
    let succeeded = false;
    let settled = false;
    let hookError: Error | undefined;
    const timer = setTimeout(() => child.kill("SIGTERM"), RESERVATION_WORKER_TIMEOUT_MS);

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error === undefined) resolveWorker();
      else rejectWorker(error);
    };
    const authorize = async () => {
      try {
        await afterCheck?.();
        if (!child.stdin.destroyed && child.stdin.writable) child.stdin.end("commit\n");
      } catch (error) {
        hookError = error instanceof Error ? error : new Error(String(error));
        child.kill("SIGTERM");
      }
    };
    const consumeLine = (line: string) => {
      if (!prepared && line === "prepared") {
        prepared = true;
        void authorize();
      } else if (prepared && !succeeded && line === "ok") {
        succeeded = true;
      } else {
        child.kill("SIGTERM");
      }
    };

    child.stdout.on("data", (chunk: Buffer) => {
      outputBytes += chunk.byteLength;
      if (outputBytes > RESERVATION_WORKER_OUTPUT_LIMIT) {
        child.kill("SIGTERM");
        return;
      }
      output += chunk.toString("utf8");
      for (;;) {
        const newline = output.indexOf("\n");
        if (newline < 0) break;
        const line = output.slice(0, newline);
        output = output.slice(newline + 1);
        consumeLine(line);
      }
    });
    child.stderr.on("data", (chunk: Buffer) => {
      outputBytes += chunk.byteLength;
      if (outputBytes > RESERVATION_WORKER_OUTPUT_LIMIT) child.kill("SIGTERM");
    });
    child.stdin.on("error", () => child.kill("SIGTERM"));
    child.on("error", () => finish(new Error("Destination changed during integration copy")));
    child.on("close", (code) => {
      if (hookError !== undefined) finish(hookError);
      else if (code === 0 && prepared && succeeded && output.length === 0) finish();
      else finish(new Error("Destination changed during integration copy"));
    });
  });
}

async function populateReservation(
  destination: string,
  staging: string,
  relativePaths: readonly string[],
  identity: ReservationIdentity,
  afterCheck: (() => Promise<void>) | undefined,
): Promise<void> {
  let directory;
  try {
    directory = await open(
      destination,
      constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW,
    );
  } catch {
    throw new Error("Destination changed during integration copy");
  }
  try {
    const metadata = await directory.stat();
    if (!metadata.isDirectory() || metadata.dev !== identity.dev || metadata.ino !== identity.ino) {
      throw new Error("Destination changed during integration copy");
    }
    await invokeReservationWorker(destination, staging, relativePaths, identity, afterCheck);
  } finally {
    await directory.close();
  }
}

export async function installIntegrationBundle(options: InstallOptions): Promise<BundleStatus> {
  const lexicalContext = { ...options, destination: resolve(options.destination) };
  const initial = await classifyIntegrationBundle(lexicalContext);
  if (initial.state === "current") return initial;
  if (initial.state === "outdated" && options.force !== true) {
    throw new BundleTransitionError(initial);
  }
  if (initial.state === "modified" || initial.state === "demoted") {
    throw new BundleTransitionError(initial);
  }
  const context = { ...lexicalContext, destination: initial.destination };

  const provenance = await expectedProvenance(context);
  const parent = await safeParent(context.destination);
  const staging = await mkdtemp(join(parent, `.${options.manifest.name}.kaji-stage-`));
  const backup = join(parent, `.${options.manifest.name}.kaji-backup-${randomUUID()}`);
  const renameEntry = options.renameEntry ?? rename;
  let wroteBackup = false;
  let reservation: ReservationIdentity | undefined;
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
      const moved = await classifyIntegrationBundle({ ...context, destination: backup });
      if (
        moved.state !== initial.state ||
        moved.reasonCode !== initial.reasonCode ||
        moved.observed !== initial.observed
      ) {
        if (!(await exists(context.destination))) {
          await renameEntry(backup, context.destination);
          wroteBackup = false;
        }
        throw new Error("Destination changed during integration copy");
      }
    } else if (initial.state === "absent" && initial.observed === "absent") {
      await options.beforeReservationCreate?.(context.destination);
      try {
        await mkdir(context.destination);
      } catch (error) {
        if (errno(error, "EEXIST")) {
          throw new Error("Destination changed during integration copy");
        }
        throw error;
      }
      reservation = await reservationIdentity(context.destination);
    }
    if (reservation !== undefined) {
      await options.beforeReservationPublish?.(context.destination);
      if (!(await matchesEmptyReservation(context.destination, reservation))) {
        throw new Error("Destination changed during integration copy");
      }
      await populateReservation(
        context.destination,
        staging,
        [...options.manifest.files, SIDECAR],
        reservation,
        options.afterReservationCheck === undefined
          ? undefined
          : () => options.afterReservationCheck!(context.destination),
      );
      const installed = await classifyIntegrationBundle(context);
      if (
        installed.state !== "current" ||
        !(await pathHasReservationIdentity(context.destination, reservation))
      ) {
        throw new Error("Destination changed during integration copy");
      }
      reservation = undefined;
      return status(
        "current",
        "installed",
        context.destination,
        installed.observed,
        options.manifest.files.map((relativePath) => join(context.destination, relativePath)),
      );
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
    if (reservation !== undefined) {
      // Node has no identity-conditional rmdir. Leave a failed reservation
      // fail-closed rather than risk deleting a concurrently replaced path.
      await options.beforeReservationCleanup?.(context.destination);
    }
  }
}
