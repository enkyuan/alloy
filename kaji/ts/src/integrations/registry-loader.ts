/** Shared integration-registry contract loading and validation. */
import { readFile, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

export type IntegrationValidationCode =
  | "INVALID_INTEGRATION_MANIFEST"
  | "INVALID_INTEGRATION_INDEX";
export type IntegrationStability = "experimental" | "beta";
export type IntegrationRuntime = "python" | "typescript";
export type IntegrationToolRisk =
  | "read"
  | "write"
  | "external_effect"
  | "financial"
  | "destructive"
  | "admin";

export interface NormalizedIntegrationValidationError {
  code: IntegrationValidationCode;
  path: string;
}

export abstract class IntegrationValidationError extends Error {
  protected constructor(
    readonly code: IntegrationValidationCode,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = new.target.name;
  }

  normalized(): NormalizedIntegrationValidationError {
    return { code: this.code, path: this.path };
  }
}

export class ManifestValidationError extends IntegrationValidationError {
  constructor(path: string, message: string) {
    super("INVALID_INTEGRATION_MANIFEST", path, message);
  }
}

export class IndexValidationError extends IntegrationValidationError {
  constructor(path: string, message: string) {
    super("INVALID_INTEGRATION_INDEX", path, message);
  }
}

export class IntegrationNotFoundError extends Error {
  constructor(readonly integrationName: string) {
    super(`Unknown integration: '${integrationName}'`);
    this.name = "IntegrationNotFoundError";
  }
}

export interface RegistryIndexEntry {
  manifest: string;
  stability: IntegrationStability;
  runtimes: IntegrationRuntime[];
}

export interface RegistryIndexDocument {
  $schema: "./index.schema.json";
  version: string;
  integrations: Record<string, RegistryIndexEntry>;
}

export type IntegrationAuth =
  | { kind: "none" }
  | { kind: "env"; env: string; optional?: boolean; docs?: string }
  | { kind: "oauth"; scopes: string[]; docs?: string };

export interface IntegrationManifestTool {
  name: string;
  description: string;
  risk: IntegrationToolRisk;
}

export interface IntegrationManifestDocument {
  name: string;
  version: string;
  namespace: string;
  description: string;
  auth: IntegrationAuth;
  files: string[];
  tools: IntegrationManifestTool[];
  extras?: string[];
  peerDeps?: Record<string, string>;
}

export interface LoadedIntegrationManifest extends IntegrationManifestDocument {
  stability: IntegrationStability;
  runtimes: IntegrationRuntime[];
  /** Absolute path to manifest.json. */
  path: string;
  /** Absolute directory containing manifest.json. */
  root: string;
}

export interface RegistryLoaderOptions {
  /** Directory containing schema.json and index.schema.json. Defaults to registryRoot. */
  schemaRoot?: string;
  /** Reuse an already validated index when loading several manifests. */
  index?: RegistryIndexDocument;
}

interface SchemaValidators {
  manifest: ValidateFunction;
  index: ValidateFunction;
}

const validatorCache = new Map<string, Promise<SchemaValidators>>();
const validatorCacheLimit = 16;

function jsonPointer(path: string): string {
  return path.length === 0 ? "/" : path;
}

function pointerPart(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function firstError(errors: readonly ErrorObject[]): ErrorObject {
  return [...errors].sort((left, right) => {
    const pathOrder = jsonPointer(left.instancePath).localeCompare(jsonPointer(right.instancePath));
    return pathOrder || left.schemaPath.localeCompare(right.schemaPath);
  })[0]!;
}

function validationError(
  kind: "manifest" | "index",
  errors: readonly ErrorObject[],
): IntegrationValidationError {
  const error =
    kind === "manifest"
      ? (errors.find(
          (candidate) => candidate.keyword === "oneOf" && candidate.instancePath === "/auth",
        ) ?? firstError(errors))
      : firstError(errors);
  const path = jsonPointer(error.instancePath);
  const subject = kind === "manifest" ? "Integration manifest" : "Integration index";
  const message = `${subject} failed ${error.keyword} validation at ${path}`;
  return kind === "manifest"
    ? new ManifestValidationError(path, message)
    : new IndexValidationError(path, message);
}

async function readSchema(path: string): Promise<object> {
  const contents = await readFile(path, "utf8");
  return JSON.parse(contents) as object;
}

async function schemaValidators(schemaRoot: string): Promise<SchemaValidators> {
  const root = resolve(schemaRoot);
  let cached = validatorCache.get(root);
  if (cached === undefined) {
    cached = (async () => {
      const [manifestSchema, indexSchema] = await Promise.all([
        readSchema(join(root, "schema.json")),
        readSchema(join(root, "index.schema.json")),
      ]);
      const ajv = new Ajv2020({ allErrors: true, strict: true });
      addFormats(ajv);
      return {
        manifest: ajv.compile(manifestSchema),
        index: ajv.compile(indexSchema),
      };
    })();
    validatorCache.set(root, cached);
    void cached.catch(() => {
      if (validatorCache.get(root) === cached) validatorCache.delete(root);
    });
    if (validatorCache.size > validatorCacheLimit) {
      const oldest = validatorCache.keys().next().value;
      if (oldest !== undefined) validatorCache.delete(oldest);
    }
  }
  return cached;
}

export async function validateManifestDocument(
  document: unknown,
  options: { schemaRoot: string },
): Promise<IntegrationManifestDocument> {
  const validate = (await schemaValidators(options.schemaRoot)).manifest;
  if (!validate(document)) {
    throw validationError("manifest", validate.errors ?? []);
  }
  const manifest = document as IntegrationManifestDocument;
  const seen = new Set<string>();
  for (const [index, tool] of manifest.tools.entries()) {
    if (seen.has(tool.name)) {
      const path = `/tools/${index}/name`;
      throw new ManifestValidationError(
        path,
        `Integration manifest has a duplicate tool name at ${path}`,
      );
    }
    seen.add(tool.name);
  }
  return manifest;
}

export async function validateIndexDocument(
  document: unknown,
  options: { schemaRoot: string },
): Promise<RegistryIndexDocument> {
  const validate = (await schemaValidators(options.schemaRoot)).index;
  if (!validate(document)) {
    throw validationError("index", validate.errors ?? []);
  }
  return document as RegistryIndexDocument;
}

function nodeErrorCode(error: unknown): string | undefined {
  return error instanceof Error && "code" in error
    ? (error as NodeJS.ErrnoException).code
    : undefined;
}

async function readIndexDocument(indexPath: string): Promise<unknown> {
  let contents: string;
  try {
    contents = await readFile(indexPath, "utf8");
  } catch (error) {
    const message =
      nodeErrorCode(error) === "ENOENT"
        ? "Registry index is missing"
        : "Registry index is unreadable";
    throw new IndexValidationError("/", message);
  }
  try {
    return JSON.parse(contents) as unknown;
  } catch {
    throw new IndexValidationError("/", "Registry index is not valid JSON");
  }
}

async function readManifestDocument(manifestPath: string): Promise<unknown> {
  let contents: string;
  try {
    contents = await readFile(manifestPath, "utf8");
  } catch (error) {
    const message =
      nodeErrorCode(error) === "ENOENT"
        ? "Integration manifest is missing"
        : "Integration manifest is unreadable";
    throw new ManifestValidationError("/", message);
  }
  try {
    return JSON.parse(contents) as unknown;
  } catch {
    throw new ManifestValidationError("/", "Integration manifest is not valid JSON");
  }
}

function isContained(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`));
}

async function resolveManifestPath(
  registryRoot: string,
  name: string,
  relativeManifest: string,
): Promise<string> {
  const path = `/integrations/${pointerPart(name)}/manifest`;
  const root = resolve(registryRoot);
  const candidate = resolve(root, relativeManifest);
  if (!isContained(root, candidate)) {
    throw new IndexValidationError(
      path,
      `Integration path resolves outside its allowed root at ${path}`,
    );
  }

  let rootReal: string;
  let candidateReal: string;
  try {
    [rootReal, candidateReal] = await Promise.all([realpath(root), realpath(candidate)]);
  } catch (error) {
    if (nodeErrorCode(error) === "ENOENT") {
      throw new IndexValidationError(path, "Integration index references a missing manifest");
    }
    throw new IndexValidationError(path, "Integration index references an unreadable manifest");
  }
  if (!isContained(rootReal, candidateReal)) {
    throw new IndexValidationError(
      path,
      `Integration path resolves outside its allowed root at ${path}`,
    );
  }
  let isFile: boolean;
  try {
    isFile = (await stat(candidateReal)).isFile();
  } catch {
    throw new IndexValidationError(path, "Integration index references an unreadable manifest");
  }
  if (!isFile) {
    throw new IndexValidationError(path, "Integration index references a missing manifest");
  }
  return candidateReal;
}

export async function resolveManifestFile(
  manifest: Pick<LoadedIntegrationManifest, "files" | "root">,
  index: number,
): Promise<string> {
  const path = `/files/${index}`;
  const relativeFile = manifest.files[index];
  if (relativeFile === undefined) {
    throw new ManifestValidationError(path, "Integration manifest file index is out of range");
  }
  const root = resolve(manifest.root);
  const candidate = resolve(root, relativeFile);
  if (!isContained(root, candidate)) {
    throw new ManifestValidationError(
      path,
      `Integration path resolves outside its allowed root at ${path}`,
    );
  }
  let rootReal: string;
  let candidateReal: string;
  try {
    [rootReal, candidateReal] = await Promise.all([realpath(root), realpath(candidate)]);
  } catch (error) {
    const message =
      nodeErrorCode(error) === "ENOENT"
        ? "Integration manifest references a missing file"
        : "Integration manifest references an unreadable file";
    throw new ManifestValidationError(path, message);
  }
  if (!isContained(rootReal, candidateReal)) {
    throw new ManifestValidationError(
      path,
      `Integration path resolves outside its allowed root at ${path}`,
    );
  }
  let isFile: boolean;
  try {
    isFile = (await stat(candidateReal)).isFile();
  } catch {
    throw new ManifestValidationError(path, "Integration manifest references an unreadable file");
  }
  if (!isFile) {
    throw new ManifestValidationError(path, "Integration manifest references a missing file");
  }
  return candidateReal;
}

async function assertManifestFiles(manifest: LoadedIntegrationManifest): Promise<void> {
  for (const index of manifest.files.keys()) await resolveManifestFile(manifest, index);
}

export async function loadRegistryIndex(
  registryRoot: string,
  options: RegistryLoaderOptions = {},
): Promise<RegistryIndexDocument> {
  const document = await readIndexDocument(join(registryRoot, "index.json"));
  return validateIndexDocument(document, { schemaRoot: options.schemaRoot ?? registryRoot });
}

export async function loadManifest(
  registryRoot: string,
  name: string,
  options: RegistryLoaderOptions = {},
): Promise<LoadedIntegrationManifest> {
  const schemaRoot = options.schemaRoot ?? registryRoot;
  const index =
    options.index === undefined
      ? await loadRegistryIndex(registryRoot, options)
      : await validateIndexDocument(options.index, { schemaRoot });
  const indexedEntry = index.integrations[name];
  if (indexedEntry === undefined) throw new IntegrationNotFoundError(name);
  const entry: RegistryIndexEntry = {
    manifest: indexedEntry.manifest,
    stability: indexedEntry.stability,
    runtimes: [...indexedEntry.runtimes],
  };

  const manifestPath = await resolveManifestPath(registryRoot, name, entry.manifest);
  const manifest = await validateManifestDocument(await readManifestDocument(manifestPath), {
    schemaRoot,
  });
  if (manifest.name !== name) {
    throw new IndexValidationError("/name", "Integration index key does not match manifest name");
  }
  const root = dirname(manifestPath);
  const loaded = {
    ...manifest,
    stability: entry.stability,
    runtimes: [...entry.runtimes],
    path: manifestPath,
    root,
  };
  await assertManifestFiles(loaded);
  return loaded;
}

export function formatIntegrationError(error: unknown): string {
  if (error instanceof IntegrationValidationError) {
    return `${error.code} at ${error.path}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}
