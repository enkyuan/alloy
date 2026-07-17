// This is YOUR GitHub integration client. Edit it.

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
} from "@kaji/sdk/integrations";

type ToolExecutionContext = Parameters<FixedOriginRequester["request"]>[2];

const REPOSITORY = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;
const SCOPE_QUALIFIER = /(?:repo|org|user):/i;
const MAX_SEARCH_RESULT_BYTES = 32 * 1024;
const MAX_FILE_BYTES = 48 * 1024;
const MAX_TOKEN_CHARACTERS = 4_096;
const MAX_URL_CHARACTERS = 2_048;
const GENERAL_ACCEPT = "application/vnd.github+json";
const SEARCH_ACCEPT = "application/vnd.github.text-match+json";
const GITHUB_API_VERSION = "2026-03-10";
const GITHUB_CATALOG_VERSION = "0.2.0";
const GITHUB_USER_AGENT = `@kaji/sdk-github/${GITHUB_CATALOG_VERSION}`;

type Route =
  | "search_code"
  | "get_file"
  | "list_issues"
  | "get_issue"
  | "create_issue"
  | "add_comment";

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
  if (typeof value !== "string" || !REPOSITORY.test(value) || !allowed.has(value)) {
    throw policyError();
  }
  return value;
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

function encodeContentPath(value: unknown): string {
  const path = policyString(value, 1, 512);
  const parts = path.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    throw policyError();
  }
  return parts.map(encodeComponent).join("/");
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
  policyInteger(page, 1, 1_000);
  policyInteger(perPage, 1, 20);
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
    if (repositories.some((repository) => !REPOSITORY.test(repository))) throw policyError();
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
      return snapshotIntegrationResult(this.normalize(route, repository, document));
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

  private normalize(route: Route, repository: string, document: unknown): unknown {
    if (route === "search_code") return this.normalizeSearch(repository, document);
    if (route === "get_file") return this.normalizeFile(document);
    if (route === "list_issues") return this.normalizeIssueList(document);
    if (route === "get_issue" || route === "create_issue") return this.normalizeIssue(document);
    return this.normalizeComment(document);
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
}
