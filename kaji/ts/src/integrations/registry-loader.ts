/** Shared integration-registry contract loading and validation. */
import { readFile, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import type { JSONSchema, ToolRisk } from "@/tools/registry";

export type IntegrationValidationCode = "INTEGRATION_SCHEMA_INVALID";
export type IntegrationStability = "experimental" | "beta";
export type IntegrationRuntime = "python" | "typescript";
export type IntegrationToolRisk = ToolRisk;

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
    super("INTEGRATION_SCHEMA_INVALID", path, message);
  }
}

export class IndexValidationError extends IntegrationValidationError {
  constructor(path: string, message: string) {
    super("INTEGRATION_SCHEMA_INVALID", path, message);
  }
}

export class IntegrationExperimentalError extends Error {
  readonly code = "INTEGRATION_EXPERIMENTAL" as const;
  readonly path: string;

  constructor(readonly integrationName: string) {
    super(
      `Integration '${integrationName}' is experimental and outside the beta guarantee. Re-run with --allow-experimental to copy it.`,
    );
    this.name = "IntegrationExperimentalError";
    this.path = `/integrations/${pointerPart(integrationName)}/stability`;
  }

  normalized(): { code: "INTEGRATION_EXPERIMENTAL"; path: string } {
    return { code: this.code, path: this.path };
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
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "env"; env: string; optional?: boolean; docs?: string }>
  | Readonly<{
      kind: "oauth";
      provider: "google";
      clientIdEnv: string;
      clientSecretEnv?: string;
      scopes: readonly string[];
      docs?: string;
    }>;

export interface IntegrationManifestTool {
  readonly name: string;
  readonly description: string;
  readonly parameters: JSONSchema;
  readonly risk: IntegrationToolRisk;
  readonly parallel_safe: boolean;
  readonly timeout_ms?: number;
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
  parameterSchemaErrors(schema: unknown): readonly ErrorObject[];
  uriReference(value: string): boolean;
  regex(value: string): boolean;
}

const validatorCache = new Map<string, Promise<SchemaValidators>>();
const validatorCacheLimit = 16;
const draft202012 = "https://json-schema.org/draft/2020-12/schema";
const singleSubschemaKeys = [
  "additionalProperties",
  "contains",
  "contentSchema",
  "else",
  "if",
  "items",
  "not",
  "propertyNames",
  "then",
  "unevaluatedItems",
  "unevaluatedProperties",
] as const;
const mappingSubschemaKeys = [
  "$defs",
  "dependentSchemas",
  "patternProperties",
  "properties",
] as const;
const arraySubschemaKeys = ["allOf", "anyOf", "oneOf", "prefixItems"] as const;
const portablePatternEscapes = new Set("\\.^$*+?{}[]()|/-");
const portableClassEscapes = new Set("\\[]-^");
const portableRepeatLimit = 9999;

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validate Kaji's deliberately small Python/ECMAScript regex intersection.
 *
 * The subset is printable ASCII literals, capturing groups, alternation,
 * ^/$, ASCII character classes/ranges, greedy quantifiers, and escapes of
 * regex punctuation. It excludes (? extensions, dot, shorthand/Unicode
 * classes, backreferences, lazy/possessive quantifiers, and non-ASCII syntax.
 */
function isPortablePattern(pattern: string): boolean {
  if (
    pattern.length === 0 ||
    [...pattern].some((character) => {
      const code = character.codePointAt(0)!;
      return code < 0x20 || code > 0x7e;
    })
  ) {
    return false;
  }

  let index = 0;

  function consumeClass(): boolean {
    index += 1;
    if (pattern[index] === "^") index += 1;
    const tokens: Array<readonly [value: string, range: boolean, escaped: boolean]> = [];
    while (index < pattern.length && pattern[index] !== "]") {
      const character = pattern[index]!;
      if (character === "[") return false;
      if (character === "\\") {
        const escaped = pattern[index + 1];
        if (escaped === undefined || !portableClassEscapes.has(escaped)) return false;
        tokens.push([escaped, false, true]);
        index += 2;
        continue;
      }
      tokens.push([character, character === "-", false]);
      index += 1;
    }
    if (index >= pattern.length || tokens.length === 0) return false;
    index += 1;

    for (let token = 0; token + 1 < tokens.length; token++) {
      const left = tokens[token]!;
      const right = tokens[token + 1]!;
      if (!left[2] && !right[2] && left[0] === right[0] && "&|~".includes(left[0])) {
        return false;
      }
    }

    let cursor = tokens[0]![1] ? 1 : 0;
    while (cursor < tokens.length) {
      if (tokens[cursor]![1]) {
        if (cursor !== tokens.length - 1) return false;
        cursor += 1;
        continue;
      }
      if (cursor + 1 < tokens.length && tokens[cursor + 1]![1]) {
        if (cursor + 1 === tokens.length - 1) {
          cursor += 2;
          continue;
        }
        const endpoint = tokens[cursor + 2]!;
        if (endpoint[1] || tokens[cursor]![0].codePointAt(0)! > endpoint[0].codePointAt(0)!) {
          return false;
        }
        cursor += 3;
        continue;
      }
      cursor += 1;
    }
    return true;
  }

  function consumeQuantifier(): boolean {
    if (index >= pattern.length) return true;
    if ("*+?".includes(pattern[index]!)) {
      index += 1;
    } else if (pattern[index] === "{") {
      index += 1;
      const lowerStart = index;
      while (index < pattern.length && /[0-9]/.test(pattern[index]!)) index += 1;
      const lowerText = pattern.slice(lowerStart, index);
      if (lowerText.length === 0 || lowerText.length > 4) return false;
      const lower = Number(lowerText);
      let upper: number | undefined = lower;
      if (pattern[index] === ",") {
        index += 1;
        const upperStart = index;
        while (index < pattern.length && /[0-9]/.test(pattern[index]!)) index += 1;
        const upperText = pattern.slice(upperStart, index);
        if (upperText.length > 4) return false;
        upper = upperText.length === 0 ? undefined : Number(upperText);
      }
      if (pattern[index] !== "}") return false;
      index += 1;
      if (
        lower > portableRepeatLimit ||
        (upper !== undefined && (upper > portableRepeatLimit || upper < lower))
      ) {
        return false;
      }
    } else {
      return true;
    }
    return index >= pattern.length || !"*+?{".includes(pattern[index]!);
  }

  function consumeExpression(nested: boolean): boolean {
    let branchHasAtom = false;
    while (index < pattern.length) {
      const character = pattern[index]!;
      if (character === ")") return nested && branchHasAtom;
      if (character === "|") {
        if (!branchHasAtom) return false;
        branchHasAtom = false;
        index += 1;
        continue;
      }
      if ("*+?{.]}".includes(character) || character === "}") return false;
      if ("^$".includes(character)) {
        index += 1;
        continue;
      }
      if (character === "(") {
        if (pattern[index + 1] === "?") return false;
        index += 1;
        if (!consumeExpression(true) || pattern[index] !== ")") return false;
        index += 1;
      } else if (character === "[") {
        if (!consumeClass()) return false;
      } else if (character === "\\") {
        const escaped = pattern[index + 1];
        if (escaped === undefined || !portablePatternEscapes.has(escaped)) return false;
        index += 2;
      } else {
        index += 1;
      }
      branchHasAtom = true;
      if (!consumeQuantifier()) return false;
    }
    return !nested && branchHasAtom;
  }

  return consumeExpression(false) && index === pattern.length;
}

function parameterSchemaIssue(
  schema: Record<string, unknown>,
  validators: Pick<SchemaValidators, "regex" | "uriReference">,
  path: readonly (string | number)[] = [],
): readonly (string | number)[] | undefined {
  const dialect = schema["$schema"];
  if (typeof dialect === "string" && dialect !== draft202012) return [...path, "$schema"];
  const identifier = schema["$id"];
  if (typeof identifier === "string" && !validators.uriReference(identifier)) {
    return [...path, "$id"];
  }
  const pattern = schema["pattern"];
  if (typeof pattern === "string" && (!isPortablePattern(pattern) || !validators.regex(pattern))) {
    return [...path, "pattern"];
  }

  for (const keyword of singleSubschemaKeys) {
    const child = schema[keyword];
    if (!isRecord(child)) continue;
    const issue = parameterSchemaIssue(child, validators, [...path, keyword]);
    if (issue !== undefined) return issue;
  }
  for (const keyword of mappingSubschemaKeys) {
    const children = schema[keyword];
    if (!isRecord(children)) continue;
    for (const name of Object.keys(children).sort()) {
      const child = children[name];
      if (!isRecord(child)) continue;
      const issue = parameterSchemaIssue(child, validators, [...path, keyword, name]);
      if (issue !== undefined) return issue;
    }
  }
  for (const keyword of arraySubschemaKeys) {
    const children = schema[keyword];
    if (!Array.isArray(children)) continue;
    for (const [index, child] of children.entries()) {
      if (!isRecord(child)) continue;
      const issue = parameterSchemaIssue(child, validators, [...path, keyword, index]);
      if (issue !== undefined) return issue;
    }
  }
  return undefined;
}

function schemaIssuePointer(path: readonly (string | number)[]): string {
  return `/${path.map((part) => pointerPart(String(part))).join("/")}`;
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
      const uriReference = ajv.compile({ type: "string", format: "uri-reference" });
      const regex = ajv.compile({ type: "string", format: "regex" });
      return {
        manifest: ajv.compile(manifestSchema),
        index: ajv.compile(indexSchema),
        parameterSchemaErrors(schema: unknown): readonly ErrorObject[] {
          if (ajv.validateSchema(schema as object)) return [];
          return [...(ajv.errors ?? [])];
        },
        uriReference(value: string): boolean {
          return uriReference(value) as boolean;
        },
        regex(value: string): boolean {
          return regex(value) as boolean;
        },
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
  const validators = await schemaValidators(options.schemaRoot);
  const validate = validators.manifest;
  if (!validate(document)) {
    throw validationError("manifest", validate.errors ?? []);
  }
  const manifest = document as IntegrationManifestDocument;
  const seen = new Set<string>();
  for (const [index, tool] of manifest.tools.entries()) {
    const issue = parameterSchemaIssue(tool.parameters, validators);
    if (issue !== undefined) {
      const path = `/tools/${index}/parameters${schemaIssuePointer(issue)}`;
      throw new ManifestValidationError(
        path,
        `Integration manifest has an unsupported parameter schema at ${path}`,
      );
    }
    const parameterErrors = validators.parameterSchemaErrors(tool.parameters);
    if (parameterErrors.length > 0) {
      const error = firstError(parameterErrors);
      const suffix = jsonPointer(error.instancePath);
      const path = `/tools/${index}/parameters${suffix === "/" ? "" : suffix}`;
      throw new ManifestValidationError(
        path,
        `Integration manifest has an invalid parameter schema at ${path}`,
      );
    }
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
  if (
    error instanceof IntegrationValidationError ||
    error instanceof IntegrationExperimentalError
  ) {
    return `${error.code} at ${error.path}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}
