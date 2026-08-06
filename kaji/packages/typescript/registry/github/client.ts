// This is YOUR GitHub integration client. Edit it.
//
// This client implements all 15 GitHub routes, but index.ts in this directory
// (the CLI-copied registry bundle) only registers 6 as tools. The other 9
// (get_commit, get_pull_request, list_pull_request_files, list_check_runs,
// get_workflow_run, list_workflow_jobs, list_file_commits, get_release,
// list_deployments) are exposed separately via the npm package surface at
// ts/src/integrations/github.ts + package-tools.ts, which composes the
// CLI-copied 6 with these 9 for the full 15-tool catalog. See
// ts/tests/github-registry.test.ts for coverage of both surfaces.

import { Buffer } from "node:buffer";

import {
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationPolicyError,
  IntegrationRateLimitedError,
  IntegrationTransientReadError,
  snapshotIntegrationResult,
  type BoundedResponse,
  type FixedOriginRequester,
} from "kaji-sdk/integrations";

type ToolExecutionContext = Parameters<FixedOriginRequester["request"]>[2];

const REPOSITORY = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;
const SCOPE_QUALIFIER = /(?:repo|org|user):/i;
const MAX_SEARCH_RESULT_BYTES = 32 * 1024;
const MAX_FILE_BYTES = 48 * 1024;
const MAX_MODEL_RESULT_BYTES = 60 * 1024;
const MAX_MODEL_TEXT_BYTES = 8 * 1024;
const MAX_PROVIDER_TEXT_BYTES = 1024 * 1024;
const MAX_TOKEN_CHARACTERS = 4_096;
const MAX_URL_CHARACTERS = 2_048;
const GENERAL_ACCEPT = "application/vnd.github+json";
const SEARCH_ACCEPT = "application/vnd.github.text-match+json";
const GITHUB_API_VERSION = "2026-03-10";
const GITHUB_CATALOG_VERSION = "0.2.0";
const GITHUB_USER_AGENT = `kaji-sdk-github/${GITHUB_CATALOG_VERSION}`;

type Route =
  | "search_code"
  | "get_file"
  | "list_issues"
  | "get_issue"
  | "create_issue"
  | "add_comment"
  | "get_commit"
  | "get_pull_request"
  | "list_pull_request_files"
  | "list_check_runs"
  | "get_workflow_run"
  | "list_workflow_jobs"
  | "list_file_commits"
  | "get_release"
  | "list_deployments";

type Query = Readonly<Record<string, string | number>>;
type RequestBody = Readonly<Record<string, unknown>>;

export interface GitHubClientOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  readonly http: FixedOriginRequester;
}

interface GitHubClientRuntime {
  readonly sleep: (delayMs: number, signal: AbortSignal) => Promise<void>;
  readonly monotonicNow: () => number;
}

interface RequestJsonOptions {
  readonly method: "GET" | "POST";
  readonly repository: string;
  readonly path: string;
  readonly query?: Query;
  readonly body?: RequestBody;
  readonly mutation?: boolean;
}

class ProviderShapeError extends Error {}

class UnknownMutationError extends Error {
  readonly error_code = "TOOL_EXECUTION_FAILED";
  readonly reason_code = "github_mutation_unknown";
  readonly recovery_code = "RECONCILE_GITHUB_MUTATION";
  readonly doc_url = "https://kaji.dev/docs/integrations/recovery-v1#github-mutation-unknown";

  constructor() {
    super("GitHub mutation outcome is unknown");
    this.name = "UnknownMutationError";
  }
}

interface PageInput {
  readonly page?: number;
  readonly perPage?: number;
}

interface BoundedText {
  readonly text: string | null;
  readonly truncated: boolean;
}

interface TextFieldPath {
  readonly path: readonly string[];
  readonly truncatedPath: readonly string[];
}

function policyError(): IntegrationPolicyError {
  return new IntegrationPolicyError();
}

function authError(): IntegrationAuthRequiredError {
  return new IntegrationAuthRequiredError("github_token_missing");
}

function apiError(): IntegrationExecutionError {
  return new IntegrationExecutionError("api_rejected");
}

function transientError(): IntegrationTransientReadError {
  return new IntegrationTransientReadError();
}

function rateError(): IntegrationRateLimitedError {
  return new IntegrationRateLimitedError();
}

function requireRepository(value: unknown, allowed: ReadonlySet<string>): string {
  if (
    typeof value !== "string" ||
    !REPOSITORY.test(value) ||
    !repositoryComponentsAreSafe(value) ||
    !allowed.has(value)
  ) {
    throw policyError();
  }
  return value;
}

function repositoryComponentsAreSafe(value: string): boolean {
  return value.split("/").every((part) => part !== "." && part !== "..");
}

function policyString(value: unknown, minimum: number, maximum: number): string {
  if (typeof value !== "string") {
    throw policyError();
  }
  assertScalarString(value, policyError);
  const length = Array.from(value).length;
  if (length < minimum || length > maximum) throw policyError();
  return value;
}

function policyInteger(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw policyError();
  }
  return value as number;
}

function providerCharacterString(value: unknown, minimum: number, maximum: number): string {
  if (typeof value !== "string") {
    throw new ProviderShapeError();
  }
  assertScalarString(value, () => new ProviderShapeError());
  const length = Array.from(value).length;
  if (length < minimum || length > maximum) throw new ProviderShapeError();
  return value;
}

function providerGitHubUrl(
  value: unknown,
  origin: "https://github.com" | "https://api.github.com",
  pathSegments: readonly string[],
): string {
  const raw = providerCharacterString(value, 1, MAX_URL_CHARACTERS);
  const encodedSegments = pathSegments.map((segment) => {
    providerCharacterString(segment, 1, MAX_URL_CHARACTERS);
    if (
      segment === "." ||
      segment === ".." ||
      segment.includes("\\") ||
      Array.from(segment, (character) => character.charCodeAt(0)).some(
        (codePoint) => codePoint < 0x20 || codePoint === 0x7f,
      )
    ) {
      throw new ProviderShapeError();
    }
    return encodeURIComponent(segment).replace(
      /[!'()*]/g,
      (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
    );
  });
  const expected = `${origin}/${encodedSegments.join("/")}`;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ProviderShapeError();
  }
  if (
    raw !== expected ||
    parsed.href !== raw ||
    parsed.protocol !== "https:" ||
    parsed.origin !== origin ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.port !== "" ||
    parsed.search !== "" ||
    parsed.hash !== ""
  ) {
    throw new ProviderShapeError();
  }
  return raw;
}

function providerByteString(value: unknown, minimum: number, maximum: number): string {
  if (typeof value !== "string") {
    throw new ProviderShapeError();
  }
  assertScalarString(value, () => new ProviderShapeError());
  if (Array.from(value).length < minimum || utf8Size(value) > maximum) {
    throw new ProviderShapeError();
  }
  return value;
}

function providerInteger(value: unknown, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new ProviderShapeError();
  }
  return value as number;
}

function providerBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw new ProviderShapeError();
  return value;
}

function providerNullableCharacterString(
  value: unknown,
  minimum: number,
  maximum: number,
): string | null {
  return value === null ? null : providerCharacterString(value, minimum, maximum);
}

function providerOptionalNullableCharacterString(
  value: unknown,
  minimum: number,
  maximum: number,
): string | null {
  return value === undefined || value === null
    ? null
    : providerCharacterString(value, minimum, maximum);
}

function objectValue(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProviderShapeError();
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw new ProviderShapeError();
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new ProviderShapeError();
  return value;
}

function assertScalarString(value: string, makeError: () => Error): void {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) throw makeError();
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw makeError();
    }
  }
}

function utf8Size(value: string): number {
  assertScalarString(value, () => new ProviderShapeError());
  return new TextEncoder().encode(value).byteLength;
}

function truncateUtf8(value: string, maximum: number): string {
  const bytes = new TextEncoder().encode(value);
  if (bytes.byteLength <= maximum) return value;
  for (let end = maximum; end >= Math.max(0, maximum - 3); end -= 1) {
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes.slice(0, end));
    } catch {
      // A UTF-8 sequence is at most four bytes, so three backtracks are sufficient.
    }
  }
  throw new ProviderShapeError();
}

function serializedBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

function boundedText(value: unknown, nullable = false): BoundedText {
  if (value === null && nullable) return { text: null, truncated: false };
  const text = providerByteString(value, 0, MAX_PROVIDER_TEXT_BYTES);
  const truncated = utf8Size(text) > MAX_MODEL_TEXT_BYTES;
  return {
    text: truncated ? truncateUtf8(text, MAX_MODEL_TEXT_BYTES) : text,
    truncated,
  };
}

function valueAtPath(root: Record<string, unknown>, path: readonly string[]): unknown {
  let value: unknown = root;
  for (const segment of path) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new ProviderShapeError();
    }
    value = (value as Record<string, unknown>)[segment];
  }
  return value;
}

function setValueAtPath(
  root: Record<string, unknown>,
  path: readonly string[],
  value: unknown,
): void {
  let target = root;
  for (const segment of path.slice(0, -1)) {
    const next = target[segment];
    if (next === null || typeof next !== "object" || Array.isArray(next)) {
      throw new ProviderShapeError();
    }
    target = next as Record<string, unknown>;
  }
  target[path.at(-1)!] = value;
}

function shrinkTextFieldsToFit<T extends Record<string, unknown>>(
  row: T,
  fields: readonly TextFieldPath[],
  fits: (candidate: T) => boolean,
): T | undefined {
  const candidate = structuredClone(row);
  if (fits(candidate)) return candidate;
  for (const field of fields) {
    const current = valueAtPath(candidate, field.path);
    if (current === null) continue;
    if (typeof current !== "string") throw new ProviderShapeError();
    const byteLength = utf8Size(current);
    let low = 0;
    let high = byteLength;
    let best: string | undefined;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      const text = truncateUtf8(current, middle);
      const trial = structuredClone(candidate);
      setValueAtPath(trial, field.path, text);
      setValueAtPath(trial, field.truncatedPath, true);
      if (fits(trial)) {
        best = text;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    if (best !== undefined) {
      setValueAtPath(candidate, field.path, best);
      setValueAtPath(candidate, field.truncatedPath, true);
      return candidate;
    }
    setValueAtPath(candidate, field.path, "");
    setValueAtPath(candidate, field.truncatedPath, true);
  }
  return fits(candidate) ? candidate : undefined;
}

function boundedRows(
  value: unknown,
  maximum = 20,
): Readonly<{
  rows: readonly unknown[];
  omitted: number;
}> {
  const rows = arrayValue(value);
  return {
    rows: rows.slice(0, maximum),
    omitted: Math.max(0, rows.length - maximum),
  };
}

function fitRows<T extends Record<string, unknown>, R extends Record<string, unknown>>(
  rows: readonly T[],
  build: (items: readonly T[], omittedCount: number) => R,
  options: Readonly<{
    initialOmitted?: number;
    textFields?: readonly TextFieldPath[];
    shrink?: (row: T, fits: (candidate: T) => boolean) => T | undefined;
  }> = {},
): R {
  const items: T[] = [];
  let omitted = options.initialOmitted ?? 0;
  for (const row of rows) {
    const fits = (candidate: T): boolean =>
      serializedBytes(build([...items, candidate], omitted)) <= MAX_MODEL_RESULT_BYTES;
    let candidate: T | undefined = row;
    if (!fits(candidate)) {
      if (options.shrink !== undefined) {
        candidate = options.shrink(candidate, fits);
      } else if (options.textFields !== undefined) {
        candidate = shrinkTextFieldsToFit(candidate, options.textFields, fits);
      }
    }
    if (candidate === undefined || !fits(candidate)) {
      omitted += 1;
    } else {
      items.push(candidate);
    }
  }
  let result = build(items, omitted);
  while (serializedBytes(result) > MAX_MODEL_RESULT_BYTES && items.length > 0) {
    items.pop();
    omitted += 1;
    result = build(items, omitted);
  }
  if (serializedBytes(result) > MAX_MODEL_RESULT_BYTES) throw new ProviderShapeError();
  return result;
}

function assertModelResultBudget<T extends Record<string, unknown>>(value: T): T {
  if (serializedBytes(value) > MAX_MODEL_RESULT_BYTES) throw new ProviderShapeError();
  return value;
}

function fitObjectToModelBudget<T extends Record<string, unknown>>(
  value: T,
  textFields: readonly TextFieldPath[],
): T | undefined {
  return shrinkTextFieldsToFit(
    value,
    textFields,
    (candidate) => serializedBytes(candidate) <= MAX_MODEL_RESULT_BYTES,
  );
}

function requireObjectWithinModelBudget<T extends Record<string, unknown>>(
  value: T,
  textFields: readonly TextFieldPath[],
): T {
  const fitted = fitObjectToModelBudget(value, textFields);
  if (fitted === undefined) throw new ProviderShapeError();
  return fitted;
}

function encodeComponent(value: string | number): string {
  try {
    return encodeURIComponent(String(value)).replace(
      /[!'()*]/g,
      (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
    );
  } catch {
    throw policyError();
  }
}

function queryString(query: Query | undefined): string {
  if (query === undefined || Object.keys(query).length === 0) return "";
  const pairs: string[] = [];
  for (const key of Object.keys(query).sort()) {
    const value = query[key];
    if (key.length === 0 || (typeof value !== "string" && typeof value !== "number")) {
      throw policyError();
    }
    pairs.push(`${encodeComponent(key)}=${encodeComponent(value)}`);
  }
  return `?${pairs.join("&")}`;
}

function validateContentPath(value: unknown): string {
  const path = policyString(value, 1, 512);
  const parts = path.split("/");
  if (path.includes("\\") || parts.some((part) => part === "" || part === "." || part === "..")) {
    throw policyError();
  }
  return path;
}

function encodeContentPath(value: unknown): string {
  return validateContentPath(value).split("/").map(encodeComponent).join("/");
}

function validateEncodedContentPath(value: string): void {
  const decoded: string[] = [];
  for (const part of value.split("/")) {
    let plain: string;
    try {
      plain = decodeURIComponent(part);
    } catch {
      throw policyError();
    }
    if (
      plain === "" ||
      plain === "." ||
      plain === ".." ||
      plain.includes("/") ||
      plain.includes("\\") ||
      encodeComponent(plain) !== part
    ) {
      throw policyError();
    }
    decoded.push(plain);
  }
  policyString(decoded.join("/"), 1, 512);
}

function encodePathSegment(value: unknown, maximum = 100): string {
  const segment = policyString(value, 1, maximum);
  if (segment === "." || segment === ".." || segment.includes("\\")) throw policyError();
  return encodeComponent(segment);
}

function validateEncodedPathSegment(value: string, maximum = 100): void {
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    throw policyError();
  }
  if (
    decoded === "." ||
    decoded === ".." ||
    decoded.includes("\\") ||
    encodeComponent(decoded) !== value
  ) {
    throw policyError();
  }
  policyString(decoded, 1, maximum);
}

function validatePage(page: unknown, perPage: unknown): void {
  policyInteger(page, 1, 1_000);
  policyInteger(perPage, 1, 20);
}

function validateFilter(value: unknown): asserts value is "latest" | "all" {
  if (value !== "latest" && value !== "all") throw policyError();
}

function validateDeploymentSha(value: unknown): string {
  const sha = policyString(value, 1, 64);
  if (!/^[0-9A-Fa-f]{1,64}$/.test(sha)) throw policyError();
  return sha;
}

function normalizedToken(value: unknown): string {
  if (typeof value !== "string" || value.includes("\r") || value.includes("\n")) {
    throw authError();
  }
  const token = value.trim();
  if (token.length === 0 || Array.from(token).length > MAX_TOKEN_CHARACTERS) throw authError();
  assertScalarString(token, authError);
  return token;
}

function retryAfter(headers: Readonly<Record<string, string>>): number | undefined {
  const raw = headers["retry-after"];
  if (raw === undefined) return undefined;
  const normalized = raw.trim();
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(normalized)) return undefined;
  const delaySeconds = Number(normalized);
  if (!Number.isFinite(delaySeconds) || delaySeconds < 0 || delaySeconds > 2) return undefined;
  return delaySeconds;
}

function isRateLimited(response: BoundedResponse): boolean {
  return (
    response.status === 429 ||
    (response.status === 403 &&
      (retryAfter(response.headers) !== undefined ||
        response.headers["x-ratelimit-remaining"] === "0"))
  );
}

function validateSearchInput(query: unknown, page: unknown, perPage: unknown): string {
  const value = policyString(query, 1, 256);
  if (SCOPE_QUALIFIER.test(value)) throw policyError();
  policyInteger(page, 1, 50);
  policyInteger(perPage, 1, 20);
  return value;
}

function validateListInput(state: unknown, page: unknown, perPage: unknown): void {
  if (state !== "open" && state !== "closed" && state !== "all") throw policyError();
  validatePage(page, perPage);
}

function validateCreateInput(title: unknown, body: unknown): void {
  policyString(title, 1, 256);
  const value = policyString(body, 0, 16_384);
  if (new TextEncoder().encode(value).byteLength > 16_384) throw policyError();
}

function validateCommentBody(body: unknown): void {
  const value = policyString(body, 1, 16_384);
  if (new TextEncoder().encode(value).byteLength > 16_384) throw policyError();
}

function routeFor(options: RequestJsonOptions): Route {
  const { method, repository, path, query, body, mutation = false } = options;
  const prefix = `/repos/${repository}`;
  const queryKeys = Object.keys(query ?? {}).sort();
  const bodyKeys = Object.keys(body ?? {}).sort();
  if (method === "GET" && !mutation && path === "/search/code") {
    if (query === undefined || queryKeys.join(",") !== "page,per_page,q" || body !== undefined) {
      throw policyError();
    }
    const suffix = ` repo:${repository}`;
    const value = query.q;
    if (typeof value !== "string" || !value.endsWith(suffix)) throw policyError();
    validateSearchInput(value.slice(0, -suffix.length), query.page, query.per_page);
    return "search_code";
  }
  if (method === "GET" && !mutation && path.startsWith(`${prefix}/contents/`)) {
    if (body !== undefined || queryKeys.some((key) => key !== "ref")) throw policyError();
    validateEncodedContentPath(path.slice(`${prefix}/contents/`.length));
    if (query?.ref !== undefined) policyString(query.ref, 1, 100);
    return "get_file";
  }
  if (path === `${prefix}/issues`) {
    if (method === "GET" && !mutation) {
      if (
        query === undefined ||
        queryKeys.join(",") !== "page,per_page,state" ||
        body !== undefined
      ) {
        throw policyError();
      }
      validateListInput(query.state, query.page, query.per_page);
      return "list_issues";
    }
    if (method === "POST" && mutation) {
      if (query !== undefined || body === undefined || bodyKeys.join(",") !== "body,title") {
        throw policyError();
      }
      validateCreateInput(body.title, body.body);
      return "create_issue";
    }
  }
  const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const issue = new RegExp(`^${escaped}/issues/([1-9][0-9]*)$`).exec(path);
  if (
    issue !== null &&
    method === "GET" &&
    !mutation &&
    query === undefined &&
    body === undefined
  ) {
    policyInteger(Number(issue[1]), 1, Number.MAX_SAFE_INTEGER);
    return "get_issue";
  }
  const comment = new RegExp(`^${escaped}/issues/([1-9][0-9]*)/comments$`).exec(path);
  if (comment !== null && method === "POST" && mutation && query === undefined) {
    if (body === undefined || bodyKeys.join(",") !== "body") throw policyError();
    policyInteger(Number(comment[1]), 1, Number.MAX_SAFE_INTEGER);
    validateCommentBody(body.body);
    return "add_comment";
  }
  const commit = new RegExp(`^${escaped}/commits/([^/]+)$`).exec(path);
  if (commit !== null && method === "GET" && !mutation && body === undefined) {
    if (query === undefined || queryKeys.join(",") !== "page,per_page") throw policyError();
    validateEncodedPathSegment(commit[1]!);
    validatePage(query.page, query.per_page);
    return "get_commit";
  }
  const pull = new RegExp(`^${escaped}/pulls/([1-9][0-9]*)$`).exec(path);
  if (pull !== null && method === "GET" && !mutation && query === undefined && body === undefined) {
    policyInteger(Number(pull[1]), 1, Number.MAX_SAFE_INTEGER);
    return "get_pull_request";
  }
  const pullFiles = new RegExp(`^${escaped}/pulls/([1-9][0-9]*)/files$`).exec(path);
  if (pullFiles !== null && method === "GET" && !mutation && body === undefined) {
    if (query === undefined || queryKeys.join(",") !== "page,per_page") throw policyError();
    policyInteger(Number(pullFiles[1]), 1, Number.MAX_SAFE_INTEGER);
    validatePage(query.page, query.per_page);
    return "list_pull_request_files";
  }
  const checks = new RegExp(`^${escaped}/commits/([^/]+)/check-runs$`).exec(path);
  if (checks !== null && method === "GET" && !mutation && body === undefined) {
    if (query === undefined || queryKeys.join(",") !== "filter,page,per_page") {
      throw policyError();
    }
    validateEncodedPathSegment(checks[1]!);
    validateFilter(query.filter);
    validatePage(query.page, query.per_page);
    return "list_check_runs";
  }
  const workflowRun = new RegExp(`^${escaped}/actions/runs/([1-9][0-9]*)$`).exec(path);
  if (
    workflowRun !== null &&
    method === "GET" &&
    !mutation &&
    query === undefined &&
    body === undefined
  ) {
    policyInteger(Number(workflowRun[1]), 1, Number.MAX_SAFE_INTEGER);
    return "get_workflow_run";
  }
  const workflowJobs = new RegExp(`^${escaped}/actions/runs/([1-9][0-9]*)/jobs$`).exec(path);
  if (workflowJobs !== null && method === "GET" && !mutation && body === undefined) {
    if (query === undefined || queryKeys.join(",") !== "filter,page,per_page") {
      throw policyError();
    }
    policyInteger(Number(workflowJobs[1]), 1, Number.MAX_SAFE_INTEGER);
    validateFilter(query.filter);
    validatePage(query.page, query.per_page);
    return "list_workflow_jobs";
  }
  if (path === `${prefix}/commits` && method === "GET" && !mutation && body === undefined) {
    if (
      query === undefined ||
      (queryKeys.join(",") !== "page,path,per_page" &&
        queryKeys.join(",") !== "page,path,per_page,sha")
    ) {
      throw policyError();
    }
    validateContentPath(query.path);
    validatePage(query.page, query.per_page);
    if (query.sha !== undefined) policyString(query.sha, 1, 100);
    return "list_file_commits";
  }
  const release = new RegExp(`^${escaped}/releases/tags/([^/]+)$`).exec(path);
  if (
    release !== null &&
    method === "GET" &&
    !mutation &&
    query === undefined &&
    body === undefined
  ) {
    validateEncodedPathSegment(release[1]!);
    return "get_release";
  }
  if (path === `${prefix}/deployments` && method === "GET" && !mutation && body === undefined) {
    if (query === undefined || !queryKeys.includes("page") || !queryKeys.includes("per_page")) {
      throw policyError();
    }
    if (
      queryKeys.some(
        (key) => !["environment", "page", "per_page", "ref", "sha", "task"].includes(key),
      )
    ) {
      throw policyError();
    }
    validatePage(query.page, query.per_page);
    for (const key of ["environment", "ref", "task"] as const) {
      if (query[key] !== undefined) policyString(query[key], 1, 100);
    }
    if (query.sha !== undefined) validateDeploymentSha(query.sha);
    return "list_deployments";
  }
  throw policyError();
}

function defaultSleep(delayMs: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function isAbortOrTimeout(error: unknown): boolean {
  return (
    error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

export class GitHubClient {
  private readonly repositories: ReadonlySet<string>;
  private readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  private readonly http: FixedOriginRequester;
  private readonly sleep: GitHubClientRuntime["sleep"];
  private readonly monotonicNow: GitHubClientRuntime["monotonicNow"];

  constructor(
    options: GitHubClientOptions,
    runtime: GitHubClientRuntime = { sleep: defaultSleep, monotonicNow: () => performance.now() },
  ) {
    if (
      typeof options?.tokenFor !== "function" ||
      !Array.isArray(options.repositories) ||
      typeof options.http?.request !== "function" ||
      typeof runtime.sleep !== "function" ||
      typeof runtime.monotonicNow !== "function"
    ) {
      throw policyError();
    }
    const repositories = Object.freeze([...options.repositories]);
    if (
      repositories.some(
        (repository) => !REPOSITORY.test(repository) || !repositoryComponentsAreSafe(repository),
      )
    ) {
      throw policyError();
    }
    this.repositories = new Set(repositories);
    this.tokenFor = options.tokenFor;
    this.http = options.http;
    this.sleep = runtime.sleep;
    this.monotonicNow = runtime.monotonicNow;
  }

  async searchCode(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; query: string; page?: number; perPage?: number }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    const query = validateSearchInput(input.query, page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: "/search/code",
      query: { q: `${query} repo:${repository}`, page, per_page: perPage },
    });
  }

  async getFile(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; path: string; ref?: string }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const path = encodeContentPath(input.path);
    const query = input.ref === undefined ? undefined : { ref: policyString(input.ref, 1, 100) };
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/contents/${path}`,
      ...(query === undefined ? {} : { query }),
    });
  }

  async listIssues(
    context: ToolExecutionContext,
    input: Readonly<{
      repository: string;
      state?: "open" | "closed" | "all";
      page?: number;
      perPage?: number;
    }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const state = input.state ?? "open";
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validateListInput(state, page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/issues`,
      query: { state, page, per_page: perPage },
    });
  }

  async getIssue(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; issueNumber: number }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const issueNumber = policyInteger(input.issueNumber, 1, Number.MAX_SAFE_INTEGER);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/issues/${issueNumber}`,
    });
  }

  async createIssue(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; title: string; body: string }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    validateCreateInput(input.title, input.body);
    return this.requestJson(context, {
      method: "POST",
      repository,
      path: `/repos/${repository}/issues`,
      body: { title: input.title, body: input.body },
      mutation: true,
    });
  }

  async addComment(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; issueNumber: number; body: string }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const issueNumber = policyInteger(input.issueNumber, 1, Number.MAX_SAFE_INTEGER);
    validateCommentBody(input.body);
    return this.requestJson(context, {
      method: "POST",
      repository,
      path: `/repos/${repository}/issues/${issueNumber}/comments`,
      body: { body: input.body },
      mutation: true,
    });
  }

  async getCommit(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; ref: string } & PageInput>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const ref = encodePathSegment(input.ref);
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validatePage(page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/commits/${ref}`,
      query: { page, per_page: perPage },
    });
  }

  async getPullRequest(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; pullNumber: number }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const pullNumber = policyInteger(input.pullNumber, 1, Number.MAX_SAFE_INTEGER);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/pulls/${pullNumber}`,
    });
  }

  async listPullRequestFiles(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; pullNumber: number } & PageInput>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const pullNumber = policyInteger(input.pullNumber, 1, Number.MAX_SAFE_INTEGER);
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validatePage(page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/pulls/${pullNumber}/files`,
      query: { page, per_page: perPage },
    });
  }

  async listCheckRuns(
    context: ToolExecutionContext,
    input: Readonly<{
      repository: string;
      ref: string;
      filter?: "latest" | "all";
    }> &
      PageInput,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const ref = encodePathSegment(input.ref);
    const filter = input.filter ?? "latest";
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validateFilter(filter);
    validatePage(page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/commits/${ref}/check-runs`,
      query: { filter, page, per_page: perPage },
    });
  }

  async getWorkflowRun(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; runId: number }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const runId = policyInteger(input.runId, 1, Number.MAX_SAFE_INTEGER);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/actions/runs/${runId}`,
    });
  }

  async listWorkflowJobs(
    context: ToolExecutionContext,
    input: Readonly<{
      repository: string;
      runId: number;
      filter?: "latest" | "all";
    }> &
      PageInput,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const runId = policyInteger(input.runId, 1, Number.MAX_SAFE_INTEGER);
    const filter = input.filter ?? "latest";
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validateFilter(filter);
    validatePage(page, perPage);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/actions/runs/${runId}/jobs`,
      query: { filter, page, per_page: perPage },
    });
  }

  async listFileCommits(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; path: string; ref?: string } & PageInput>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const path = validateContentPath(input.path);
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validatePage(page, perPage);
    const ref = input.ref === undefined ? undefined : policyString(input.ref, 1, 100);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/commits`,
      query: { page, path, per_page: perPage, ...(ref === undefined ? {} : { sha: ref }) },
    });
  }

  async getRelease(
    context: ToolExecutionContext,
    input: Readonly<{ repository: string; tag: string }>,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const tag = encodePathSegment(input.tag);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/releases/tags/${tag}`,
    });
  }

  async listDeployments(
    context: ToolExecutionContext,
    input: Readonly<{
      repository: string;
      ref?: string;
      sha?: string;
      environment?: string;
      task?: string;
    }> &
      PageInput,
  ): Promise<unknown> {
    const repository = requireRepository(input.repository, this.repositories);
    const page = input.page ?? 1;
    const perPage = input.perPage ?? 10;
    validatePage(page, perPage);
    const ref = input.ref === undefined ? undefined : policyString(input.ref, 1, 100);
    const sha = input.sha === undefined ? undefined : validateDeploymentSha(input.sha);
    const environment =
      input.environment === undefined ? undefined : policyString(input.environment, 1, 100);
    const task = input.task === undefined ? undefined : policyString(input.task, 1, 100);
    return this.requestJson(context, {
      method: "GET",
      repository,
      path: `/repos/${repository}/deployments`,
      query: {
        page,
        per_page: perPage,
        ...(ref === undefined ? {} : { ref }),
        ...(sha === undefined ? {} : { sha }),
        ...(environment === undefined ? {} : { environment }),
        ...(task === undefined ? {} : { task }),
      },
    });
  }

  async requestJson(context: ToolExecutionContext, options: RequestJsonOptions): Promise<unknown> {
    const repository = requireRepository(options.repository, this.repositories);
    const route = routeFor({ ...options, repository });
    const mutation = options.mutation ?? false;
    const pathAndQuery = options.path + queryString(options.query);
    const requestBody =
      options.body === undefined
        ? undefined
        : new TextEncoder().encode(JSON.stringify(snapshotIntegrationResult(options.body)));
    const identityHeaders = {
      accept: route === "search_code" ? SEARCH_ACCEPT : GENERAL_ACCEPT,
      "user-agent": GITHUB_USER_AGENT,
      "x-github-api-version": GITHUB_API_VERSION,
    } as const;

    if (context.signal.aborted) throw context.signal.reason;
    let token: string;
    try {
      token = await this.tokenFor(context);
    } catch (error) {
      if (isAbortOrTimeout(error) || error instanceof IntegrationExecutionError) throw error;
      throw authError();
    }
    if (context.signal.aborted) throw context.signal.reason;
    const headers = Object.freeze({
      ...identityHeaders,
      authorization: `Bearer ${normalizedToken(token)}`,
      ...(requestBody === undefined ? {} : { "content-type": "application/json" }),
    });

    let response: BoundedResponse | undefined;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        response = await this.http.request(
          pathAndQuery,
          {
            method: options.method,
            headers,
            ...(requestBody === undefined ? {} : { body: requestBody }),
          },
          context,
        );
      } catch (error) {
        if (isAbortOrTimeout(error) || error instanceof IntegrationExecutionError) throw error;
        if (mutation) throw new UnknownMutationError();
        throw transientError();
      }

      if (isRateLimited(response)) {
        const delay = retryAfter(response.headers);
        if (
          options.method === "GET" &&
          attempt === 0 &&
          delay !== undefined &&
          this.deadlineAllows(context, delay * 1_000)
        ) {
          await this.sleep(delay * 1_000, context.signal);
          if (context.signal.aborted) throw context.signal.reason;
          continue;
        }
        throw rateError();
      }
      break;
    }
    if (response === undefined) throw rateError();

    if (response.status === 401) throw authError();
    if (response.status === 403) throw apiError();
    if (response.status < 200 || response.status >= 300) {
      if (mutation && response.status >= 500) throw new UnknownMutationError();
      if (response.status === 404 || response.status === 422 || response.status < 500) {
        throw apiError();
      }
      if (mutation) throw new UnknownMutationError();
      throw transientError();
    }

    try {
      const decoded = new TextDecoder("utf-8", { fatal: true }).decode(response.bytes);
      const document: unknown = JSON.parse(decoded);
      return snapshotIntegrationResult(this.normalize(route, repository, document, options));
    } catch {
      if (mutation) throw new UnknownMutationError();
      throw transientError();
    }
  }

  private deadlineAllows(context: ToolExecutionContext, delayMs: number): boolean {
    return (
      context.deadlineMonotonicMs === undefined ||
      context.deadlineMonotonicMs - this.monotonicNow() > delayMs
    );
  }

  private normalize(
    route: Route,
    repository: string,
    document: unknown,
    options: RequestJsonOptions,
  ): unknown {
    if (route === "search_code") return this.normalizeSearch(repository, document);
    if (route === "get_file") return this.normalizeFile(document);
    if (route === "list_issues") return this.normalizeIssueList(document);
    if (route === "get_issue" || route === "create_issue") return this.normalizeIssue(document);
    if (route === "add_comment") return this.normalizeComment(document);
    const page = options.query?.page as number | undefined;
    const perPage = options.query?.per_page as number | undefined;
    if (route === "get_commit") return this.normalizeCommit(repository, document, page!, perPage!);
    if (route === "get_pull_request") return this.normalizePullRequest(repository, document);
    if (route === "list_pull_request_files") {
      return this.normalizePullRequestFiles(document, page!, perPage!);
    }
    if (route === "list_check_runs") {
      return this.normalizeCheckRuns(repository, document, page!, perPage!);
    }
    if (route === "get_workflow_run") return this.normalizeWorkflowRun(repository, document);
    if (route === "list_workflow_jobs") {
      return this.normalizeWorkflowJobs(
        repository,
        options.path.split("/").at(-2)!,
        document,
        page!,
        perPage!,
      );
    }
    if (route === "list_file_commits") {
      return this.normalizeFileCommits(repository, document, page!, perPage!);
    }
    if (route === "get_release") return this.normalizeRelease(repository, document);
    return this.normalizeDeployments(repository, document, page!, perPage!);
  }

  private normalizeSearch(repository: string, document: unknown): unknown {
    const root = objectValue(document);
    const totalCount = providerInteger(root.total_count);
    const rows = arrayValue(root.items);
    for (const value of rows) {
      const item = objectValue(value);
      if (objectValue(item.repository).full_name !== repository) throw new ProviderShapeError();
    }
    const items = rows.slice(0, 20).map((value) => {
      const item = objectValue(value);
      const matches = item.text_matches ?? [];
      let fragment = "";
      if (matches !== null) {
        const matchRows = arrayValue(matches);
        if (matchRows.length > 0) {
          fragment = providerByteString(objectValue(matchRows[0]).fragment, 0, 1_048_576);
        }
      }
      return {
        path: providerCharacterString(item.path, 1, 512),
        sha: providerCharacterString(item.sha, 1, 64),
        fragment: truncateUtf8(fragment, 1_024),
      };
    });
    const result = snapshotIntegrationResult({ total_count: totalCount, items });
    if (new TextEncoder().encode(JSON.stringify(result)).byteLength > MAX_SEARCH_RESULT_BYTES) {
      throw new ProviderShapeError();
    }
    return result;
  }

  private normalizeFile(document: unknown): unknown {
    const root = objectValue(document);
    if (root.type !== "file" || root.encoding !== "base64") throw new ProviderShapeError();
    const path = providerCharacterString(root.path, 1, 512);
    const sha = providerCharacterString(root.sha, 1, 64);
    const size = providerInteger(root.size);
    const content = providerCharacterString(root.content, 0, 1_048_576);
    if (size > MAX_FILE_BYTES) return { path, sha, size, content_omitted: true };
    const normalized = content.replace(/[\r\n]/g, "");
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(normalized)) {
      throw new ProviderShapeError();
    }
    const decoded = Buffer.from(normalized, "base64");
    if (decoded.toString("base64") !== normalized || decoded.byteLength !== size) {
      throw new ProviderShapeError();
    }
    if (decoded.byteLength > MAX_FILE_BYTES) return { path, sha, size, content_omitted: true };
    const text = new TextDecoder("utf-8", { fatal: true }).decode(decoded);
    return { path, sha, size, content: text, content_omitted: false };
  }

  private normalizeIssueList(document: unknown): unknown {
    const items = arrayValue(document)
      .slice(0, 20)
      .map((value) => {
        const issue = objectValue(value);
        const body = issue.body === null ? "" : providerByteString(issue.body, 0, 1_048_576);
        const state = issue.state;
        if (state !== "open" && state !== "closed") throw new ProviderShapeError();
        return {
          number: providerInteger(issue.number, 1),
          state,
          title: providerCharacterString(issue.title, 1, 256),
          body_preview: truncateUtf8(body, 1_024),
        };
      });
    return { items };
  }

  private normalizeIssue(document: unknown): unknown {
    const issue = objectValue(document);
    const state = issue.state;
    if (state !== "open" && state !== "closed") throw new ProviderShapeError();
    const body = issue.body === null ? "" : providerByteString(issue.body, 0, 16_384);
    if (utf8Size(body) > 16_384) throw new ProviderShapeError();
    return {
      number: providerInteger(issue.number, 1),
      state,
      title: providerCharacterString(issue.title, 1, 256),
      body,
      url: providerCharacterString(issue.html_url, 1, MAX_URL_CHARACTERS),
    };
  }

  private normalizeComment(document: unknown): unknown {
    const comment = objectValue(document);
    return {
      id: providerInteger(comment.id, 1),
      url: providerCharacterString(comment.html_url, 1, MAX_URL_CHARACTERS),
    };
  }

  private normalizeCommit(
    repository: string,
    document: unknown,
    page: number,
    perPage: number,
  ): unknown {
    const root = objectValue(document);
    const commit = objectValue(root.commit);
    const message = boundedText(commit.message);
    const repositorySegments = repository.split("/");
    const authorValue = commit.author;
    const author =
      authorValue === null || authorValue === undefined
        ? null
        : (() => {
            const value = objectValue(authorValue);
            return {
              name: providerCharacterString(value.name, 1, 256),
              date: providerCharacterString(value.date, 1, 100),
            };
          })();
    const statsValue = objectValue(root.stats);
    const sha = providerCharacterString(root.sha, 1, 64);
    const base = {
      sha,
      url: providerGitHubUrl(root.html_url, "https://github.com", [
        ...repositorySegments,
        "commit",
        sha,
      ]),
      author,
      message: message.text!,
      message_truncated: message.truncated,
      stats: {
        additions: providerInteger(statsValue.additions),
        deletions: providerInteger(statsValue.deletions),
        total: providerInteger(statsValue.total),
      },
      page,
      per_page: perPage,
    };
    const parentSource = boundedRows(root.parents);
    const parents = parentSource.rows.map((value) => {
      const parent = objectValue(value);
      const parentSha = providerCharacterString(parent.sha, 1, 64);
      return {
        sha: parentSha,
        url: providerGitHubUrl(parent.html_url, "https://github.com", [
          ...repositorySegments,
          "commit",
          parentSha,
        ]),
      };
    });
    const fileSource = boundedRows(root.files);
    const files = fileSource.rows.map((value) => {
      const file = objectValue(value);
      return {
        filename: providerCharacterString(file.filename, 1, 512),
        status: providerCharacterString(file.status, 1, 100),
        additions: providerInteger(file.additions),
        deletions: providerInteger(file.deletions),
        changes: providerInteger(file.changes),
      };
    });
    const complete = {
      ...base,
      parents,
      parents_omitted_count: parentSource.omitted,
      files,
      files_omitted_count: fileSource.omitted,
    };
    const fittedComplete = fitObjectToModelBudget(complete, [
      { path: ["message"], truncatedPath: ["message_truncated"] },
    ]);
    if (fittedComplete !== undefined) return fittedComplete;
    const rowFittingBase = { ...base, message: "", message_truncated: true };
    const parentResult = fitRows(
      parents,
      (items, omittedCount) => ({
        ...rowFittingBase,
        parents: items,
        parents_omitted_count: omittedCount,
        files: [] as readonly Record<string, unknown>[],
        files_omitted_count: 0,
      }),
      { initialOmitted: parentSource.omitted },
    );
    return fitRows(
      files,
      (items, omittedCount) => ({
        ...rowFittingBase,
        parents: parentResult.parents,
        parents_omitted_count: parentResult.parents_omitted_count,
        files: items,
        files_omitted_count: omittedCount,
      }),
      { initialOmitted: fileSource.omitted },
    );
  }

  private normalizePullRequest(repository: string, document: unknown): unknown {
    const root = objectValue(document);
    const title = boundedText(root.title);
    const body = boundedText(root.body ?? null, true);
    const base = objectValue(root.base);
    const head = objectValue(root.head);
    const number = providerInteger(root.number, 1);
    return requireObjectWithinModelBudget(
      {
        number,
        state: providerCharacterString(root.state, 1, 100),
        title: title.text!,
        title_truncated: title.truncated,
        body: body.text,
        body_truncated: body.truncated,
        base_sha: providerCharacterString(base.sha, 1, 64),
        head_sha: providerCharacterString(head.sha, 1, 64),
        merge_sha: providerNullableCharacterString(root.merge_commit_sha, 1, 64),
        url: providerGitHubUrl(root.html_url, "https://github.com", [
          ...repository.split("/"),
          "pull",
          String(number),
        ]),
      },
      [
        { path: ["body"], truncatedPath: ["body_truncated"] },
        { path: ["title"], truncatedPath: ["title_truncated"] },
      ],
    );
  }

  private normalizePullRequestFiles(document: unknown, page: number, perPage: number): unknown {
    const source = boundedRows(document);
    const rows = source.rows.map((value) => {
      const root = objectValue(value);
      const patch = boundedText(root.patch ?? null, true);
      return {
        filename: providerCharacterString(root.filename, 1, 512),
        status: providerCharacterString(root.status, 1, 100),
        additions: providerInteger(root.additions),
        deletions: providerInteger(root.deletions),
        changes: providerInteger(root.changes),
        patch: patch.text,
        patch_truncated: patch.truncated,
      };
    });
    return fitRows(
      rows,
      (items, omittedCount) => ({ items, omitted_count: omittedCount, page, per_page: perPage }),
      {
        initialOmitted: source.omitted,
        textFields: [{ path: ["patch"], truncatedPath: ["patch_truncated"] }],
      },
    );
  }

  private normalizeCheckRuns(
    repository: string,
    document: unknown,
    page: number,
    perPage: number,
  ): unknown {
    const root = objectValue(document);
    const totalCount = providerInteger(root.total_count);
    const source = boundedRows(root.check_runs);
    const rows = source.rows.map((value) => {
      const run = objectValue(value);
      const output = objectValue(run.output);
      const title = boundedText(output.title ?? null, true);
      const summary = boundedText(output.summary ?? null, true);
      const text = boundedText(output.text ?? null, true);
      const id = providerInteger(run.id, 1);
      return {
        id,
        name: providerCharacterString(run.name, 1, 256),
        status: providerCharacterString(run.status, 1, 100),
        conclusion: providerNullableCharacterString(run.conclusion, 1, 100),
        url: providerGitHubUrl(run.html_url, "https://github.com", [
          ...repository.split("/"),
          "runs",
          String(id),
        ]),
        output: {
          title: title.text,
          title_truncated: title.truncated,
          summary: summary.text,
          summary_truncated: summary.truncated,
          text: text.text,
          text_truncated: text.truncated,
        },
      };
    });
    return fitRows(
      rows,
      (items, omittedCount) => ({
        total_count: totalCount,
        items,
        omitted_count: omittedCount,
        page,
        per_page: perPage,
      }),
      {
        initialOmitted: source.omitted,
        textFields: [
          {
            path: ["output", "title"],
            truncatedPath: ["output", "title_truncated"],
          },
          {
            path: ["output", "summary"],
            truncatedPath: ["output", "summary_truncated"],
          },
          { path: ["output", "text"], truncatedPath: ["output", "text_truncated"] },
        ],
      },
    );
  }

  private normalizeWorkflowRun(repository: string, document: unknown): unknown {
    const root = objectValue(document);
    const id = providerInteger(root.id, 1);
    return assertModelResultBudget({
      id,
      workflow: providerCharacterString(root.name, 1, 256),
      event: providerCharacterString(root.event, 1, 100),
      status: providerCharacterString(root.status, 1, 100),
      conclusion: providerNullableCharacterString(root.conclusion, 1, 100),
      head_sha: providerCharacterString(root.head_sha, 1, 64),
      attempt: providerInteger(root.run_attempt, 1),
      url: providerGitHubUrl(root.html_url, "https://github.com", [
        ...repository.split("/"),
        "actions",
        "runs",
        String(id),
      ]),
    });
  }

  private normalizeWorkflowJobs(
    repository: string,
    runId: string,
    document: unknown,
    page: number,
    perPage: number,
  ): unknown {
    const root = objectValue(document);
    const totalCount = providerInteger(root.total_count);
    const source = boundedRows(root.jobs);
    const rows = source.rows.map((value) => {
      const job = objectValue(value);
      const stepSource =
        job.steps === undefined || job.steps === null
          ? { rows: [] as readonly unknown[], omitted: 0 }
          : boundedRows(job.steps);
      const steps = stepSource.rows.map((stepValue) => {
        const step = objectValue(stepValue);
        return {
          number: providerInteger(step.number, 1),
          name: providerCharacterString(step.name, 1, 256),
          status: providerCharacterString(step.status, 1, 100),
          conclusion: providerOptionalNullableCharacterString(step.conclusion, 1, 100),
          started_at: providerOptionalNullableCharacterString(step.started_at, 1, 100),
          completed_at: providerOptionalNullableCharacterString(step.completed_at, 1, 100),
        };
      });
      const id = providerInteger(job.id, 1);
      return {
        id,
        name: providerCharacterString(job.name, 1, 256),
        status: providerCharacterString(job.status, 1, 100),
        conclusion: providerOptionalNullableCharacterString(job.conclusion, 1, 100),
        started_at: providerOptionalNullableCharacterString(job.started_at, 1, 100),
        completed_at: providerOptionalNullableCharacterString(job.completed_at, 1, 100),
        url: providerGitHubUrl(job.html_url, "https://github.com", [
          ...repository.split("/"),
          "actions",
          "runs",
          runId,
          "job",
          String(id),
        ]),
        steps,
        steps_omitted_count: stepSource.omitted,
      };
    });
    return fitRows(
      rows,
      (items, omittedCount) => ({
        total_count: totalCount,
        items,
        omitted_count: omittedCount,
        page,
        per_page: perPage,
      }),
      {
        initialOmitted: source.omitted,
        shrink: (row, fits) => {
          const candidate = structuredClone(row);
          const steps = candidate.steps as Record<string, unknown>[];
          while (!fits(candidate) && steps.length > 0) {
            steps.pop();
            candidate.steps_omitted_count = (candidate.steps_omitted_count as number) + 1;
          }
          return fits(candidate) ? candidate : undefined;
        },
      },
    );
  }

  private normalizeFileCommits(
    repository: string,
    document: unknown,
    page: number,
    perPage: number,
  ): unknown {
    const source = boundedRows(document);
    const rows = source.rows.map((value) => {
      const root = objectValue(value);
      const commit = objectValue(root.commit);
      const message = boundedText(commit.message);
      const authorValue = commit.author;
      const authorDate =
        authorValue === null || authorValue === undefined
          ? null
          : providerOptionalNullableCharacterString(objectValue(authorValue).date, 1, 100);
      const sha = providerCharacterString(root.sha, 1, 64);
      return {
        sha,
        message: message.text!,
        message_truncated: message.truncated,
        author_date: authorDate,
        url: providerGitHubUrl(root.html_url, "https://github.com", [
          ...repository.split("/"),
          "commit",
          sha,
        ]),
      };
    });
    return fitRows(
      rows,
      (items, omittedCount) => ({ items, omitted_count: omittedCount, page, per_page: perPage }),
      {
        initialOmitted: source.omitted,
        textFields: [{ path: ["message"], truncatedPath: ["message_truncated"] }],
      },
    );
  }

  private normalizeRelease(repository: string, document: unknown): unknown {
    const root = objectValue(document);
    const body = boundedText(root.body ?? null, true);
    const tag = providerCharacterString(root.tag_name, 1, 100);
    return requireObjectWithinModelBudget(
      {
        tag,
        target: providerCharacterString(root.target_commitish, 1, 100),
        draft: providerBoolean(root.draft),
        prerelease: providerBoolean(root.prerelease),
        published_at: providerOptionalNullableCharacterString(root.published_at, 1, 100),
        body: body.text,
        body_truncated: body.truncated,
        url: providerGitHubUrl(root.html_url, "https://github.com", [
          ...repository.split("/"),
          "releases",
          "tag",
          ...tag.split("/"),
        ]),
      },
      [{ path: ["body"], truncatedPath: ["body_truncated"] }],
    );
  }

  private normalizeDeployments(
    repository: string,
    document: unknown,
    page: number,
    perPage: number,
  ): unknown {
    const source = boundedRows(document);
    const rows = source.rows.map((value) => {
      const root = objectValue(value);
      const id = providerInteger(root.id, 1);
      return {
        id,
        ref: providerCharacterString(root.ref, 1, 100),
        sha: providerCharacterString(root.sha, 1, 64),
        environment: providerCharacterString(root.environment, 1, 100),
        task: providerCharacterString(root.task, 1, 100),
        created_at: providerCharacterString(root.created_at, 1, 100),
        url: providerGitHubUrl(root.url, "https://api.github.com", [
          "repos",
          ...repository.split("/"),
          "deployments",
          String(id),
        ]),
      };
    });
    return fitRows(
      rows,
      (items, omittedCount) => ({ items, omitted_count: omittedCount, page, per_page: perPage }),
      { initialOmitted: source.omitted },
    );
  }
}
