// This is YOUR Gmail integration client. Edit it.

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

const MESSAGE_ID = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_LIST_RESULT_BYTES = 32 * 1024;
const MAX_BODY_BYTES = 48 * 1024;
const MAX_HEADER_VALUE_BYTES = 2 * 1024;
const MAX_RAW_MESSAGE_BYTES = 1024 * 1024;
const MAX_MODEL_RESULT_BYTES = 60 * 1024;
const MAX_TOKEN_CHARACTERS = 4_096;
const MAX_PART_DEPTH = 10;
// Header names we surface, lowercased. Everything else is dropped as noise.
const SURFACED_HEADERS = new Set(["from", "to", "cc", "subject", "date"]);
const ACCEPT = "application/json";

type Route = "list_messages" | "get_message" | "send_message";
type Query = Readonly<Record<string, string | number>>;
type RequestBody = Readonly<Record<string, unknown>>;

export interface GmailClientOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly http: FixedOriginRequester;
}

interface GmailClientRuntime {
  readonly sleep: (delayMs: number, signal: AbortSignal) => Promise<void>;
  readonly monotonicNow: () => number;
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

interface RequestJsonOptions {
  readonly method: "GET" | "POST";
  readonly path: string;
  readonly query?: Query;
  readonly body?: RequestBody;
  readonly mutation?: boolean;
}

class ProviderShapeError extends Error {}

class UnknownMutationError extends Error {
  readonly error_code = "TOOL_EXECUTION_FAILED";
  readonly reason_code = "gmail_mutation_unknown";
  readonly recovery_code = "RECONCILE_GMAIL_MUTATION";
  readonly doc_url = "https://kaji.dev/docs/integrations/recovery-v1#gmail-mutation-unknown";

  constructor() {
    super("Gmail mutation outcome is unknown");
    this.name = "UnknownMutationError";
  }
}

function policyError(): IntegrationPolicyError {
  return new IntegrationPolicyError();
}

function authError(): IntegrationAuthRequiredError {
  return new IntegrationAuthRequiredError("gmail_grant_missing");
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

function truncateUtf8(value: string, maximum: number): string {
  const bytes = new TextEncoder().encode(value);
  if (bytes.byteLength <= maximum) return value;
  for (let end = maximum; end >= Math.max(0, maximum - 3); end -= 1) {
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes.slice(0, end));
    } catch {
      // A UTF-8 sequence is at most four bytes, so three backtracks suffice.
    }
  }
  throw new ProviderShapeError();
}

function requireMessageId(value: unknown): string {
  if (typeof value !== "string" || !MESSAGE_ID.test(value)) throw policyError();
  return value;
}

function providerMessageId(value: unknown): string {
  if (typeof value !== "string" || !MESSAGE_ID.test(value)) throw new ProviderShapeError();
  return value;
}

function policyString(value: unknown, minimum: number, maximum: number): string {
  if (typeof value !== "string") throw policyError();
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
  if (typeof value !== "string") throw new ProviderShapeError();
  assertScalarString(value, () => new ProviderShapeError());
  const length = Array.from(value).length;
  if (length < minimum || length > maximum) throw new ProviderShapeError();
  return value;
}

function providerInteger(value: unknown, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) throw new ProviderShapeError();
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

function serializedBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

/** Decode Gmail's base64url (RFC 4648 §5, unpadded) payloads. */
function b64urlDecode(value: string): Buffer {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const decoded = Buffer.from(normalized, "base64");
  // Round-trip guards against silently-dropped invalid characters.
  if (decoded.toString("base64").replace(/=+$/, "") !== normalized.replace(/=+$/, "")) {
    throw new ProviderShapeError();
  }
  return decoded;
}

function normalizedToken(value: unknown): string {
  if (typeof value !== "string" || value.includes("\r") || value.includes("\n")) throw authError();
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
    (response.status === 403 && retryAfter(response.headers) !== undefined)
  );
}

function validateRawMessage(raw: unknown): string {
  // Caller-supplied, already base64url-encoded. Decode failures are caller
  // error -> policy, not provider shape.
  const value = policyString(raw, 1, MAX_RAW_MESSAGE_BYTES);
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const decoded = Buffer.from(padded, "base64");
  if (
    decoded.byteLength === 0 ||
    decoded.byteLength > MAX_RAW_MESSAGE_BYTES ||
    decoded.toString("base64").replace(/=+$/, "") !== padded.replace(/=+$/, "")
  ) {
    throw policyError();
  }
  return value;
}

function queryString(query: Query | undefined): string {
  if (query === undefined || Object.keys(query).length === 0) return "";
  const pairs: string[] = [];
  for (const key of Object.keys(query).sort()) {
    const value = query[key];
    if (key.length === 0 || (typeof value !== "string" && typeof value !== "number")) {
      throw policyError();
    }
    pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return `?${pairs.join("&")}`;
}

function routeFor(options: RequestJsonOptions): Route {
  const { method, path, query, body, mutation = false } = options;
  const base = "/gmail/v1/users/me/messages";
  const queryKeys = new Set(Object.keys(query ?? {}));
  if (method === "GET" && !mutation && path === base) {
    if (query === undefined || body !== undefined) throw policyError();
    for (const key of queryKeys) if (key !== "q" && key !== "maxResults") throw policyError();
    if (!queryKeys.has("maxResults")) throw policyError();
    policyInteger(query.maxResults, 1, 100);
    if (query.q !== undefined) policyString(query.q, 1, 1_024);
    return "list_messages";
  }
  if (method === "POST" && mutation && path === `${base}/send`) {
    if (query !== undefined || body === undefined) throw policyError();
    if (Object.keys(body).length !== 1 || !("raw" in body)) throw policyError();
    validateRawMessage(body.raw);
    return "send_message";
  }
  if (method === "GET" && !mutation && path.startsWith(`${base}/`)) {
    if (body !== undefined) throw policyError();
    for (const key of queryKeys) if (key !== "format") throw policyError();
    requireMessageId(path.slice(`${base}/`.length));
    if (query?.format !== undefined && query.format !== "full") throw policyError();
    return "get_message";
  }
  throw policyError();
}

function isAbortOrTimeout(error: unknown): boolean {
  return (
    error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

export class GmailClient {
  private readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  private readonly http: FixedOriginRequester;
  private readonly sleep: GmailClientRuntime["sleep"];
  private readonly monotonicNow: GmailClientRuntime["monotonicNow"];

  constructor(
    options: GmailClientOptions,
    runtime: GmailClientRuntime = { sleep: defaultSleep, monotonicNow: () => performance.now() },
  ) {
    if (
      typeof options?.tokenFor !== "function" ||
      typeof options.http?.request !== "function" ||
      typeof runtime.sleep !== "function" ||
      typeof runtime.monotonicNow !== "function"
    ) {
      throw policyError();
    }
    this.tokenFor = options.tokenFor;
    this.http = options.http;
    this.sleep = runtime.sleep;
    this.monotonicNow = runtime.monotonicNow;
  }

  async listMessages(
    context: ToolExecutionContext,
    input: Readonly<{ query?: string; maxResults?: number }>,
  ): Promise<unknown> {
    const maxResults = input.maxResults ?? 10;
    policyInteger(maxResults, 1, 100);
    const query: Record<string, string | number> = { maxResults };
    if (input.query !== undefined) query.q = policyString(input.query, 1, 1_024);
    return this.requestJson(context, {
      method: "GET",
      path: "/gmail/v1/users/me/messages",
      query,
    });
  }

  async getMessage(
    context: ToolExecutionContext,
    input: Readonly<{ messageId: string }>,
  ): Promise<unknown> {
    const identifier = requireMessageId(input.messageId);
    return this.requestJson(context, {
      method: "GET",
      path: `/gmail/v1/users/me/messages/${identifier}`,
      query: { format: "full" },
    });
  }

  async sendMessage(
    context: ToolExecutionContext,
    input: Readonly<{ raw: string }>,
  ): Promise<unknown> {
    validateRawMessage(input.raw);
    return this.requestJson(context, {
      method: "POST",
      path: "/gmail/v1/users/me/messages/send",
      body: { raw: input.raw },
      mutation: true,
    });
  }

  async requestJson(context: ToolExecutionContext, options: RequestJsonOptions): Promise<unknown> {
    const route = routeFor(options);
    const mutation = options.mutation ?? false;
    const pathAndQuery = options.path + queryString(options.query);
    const requestBody =
      options.body === undefined
        ? undefined
        : new TextEncoder().encode(JSON.stringify(snapshotIntegrationResult(options.body)));

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
      accept: ACCEPT,
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
      return snapshotIntegrationResult(this.normalize(route, document));
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

  private normalize(route: Route, document: unknown): unknown {
    if (route === "list_messages") return this.normalizeList(document);
    if (route === "get_message") return this.normalizeMessage(document);
    return this.normalizeSend(document);
  }

  private normalizeList(document: unknown): unknown {
    const root = objectValue(document);
    const rows = root.messages === undefined ? [] : arrayValue(root.messages);
    const messages = rows.slice(0, 100).map((value) => {
      const message = objectValue(value);
      return {
        id: providerMessageId(message.id),
        thread_id: providerMessageId(message.threadId),
      };
    });
    const result: Record<string, unknown> = { messages };
    if (root.resultSizeEstimate !== undefined) {
      result.result_size_estimate = providerInteger(root.resultSizeEstimate);
    }
    if (serializedBytes(result) > MAX_LIST_RESULT_BYTES) throw new ProviderShapeError();
    return result;
  }

  private normalizeMessage(document: unknown): unknown {
    const root = objectValue(document);
    const payload = objectValue(root.payload);
    const headers: Record<string, string> = {};
    const rawHeaders = payload.headers === undefined ? [] : arrayValue(payload.headers);
    for (const value of rawHeaders) {
      const header = objectValue(value);
      const name = providerCharacterString(header.name, 1, 256).toLowerCase();
      if (SURFACED_HEADERS.has(name) && !(name in headers)) {
        headers[name] = truncateUtf8(
          providerCharacterString(header.value, 0, MAX_HEADER_VALUE_BYTES),
          MAX_HEADER_VALUE_BYTES,
        );
      }
    }
    const { text, truncated } = this.extractBody(payload);
    const result = {
      id: providerMessageId(root.id),
      thread_id: providerMessageId(root.threadId),
      snippet: truncateUtf8(providerCharacterString(root.snippet ?? "", 0, MAX_RAW_MESSAGE_BYTES), 1_024),
      headers,
      body: text,
      body_truncated: truncated,
    };
    if (serializedBytes(result) > MAX_MODEL_RESULT_BYTES) throw new ProviderShapeError();
    return result;
  }

  private extractBody(payload: Record<string, unknown>): { text: string; truncated: boolean } {
    for (const part of this.walkParts(payload, 0)) {
      if (part.mimeType !== "text/plain") continue;
      const body = part.body;
      if (body === null || typeof body !== "object" || Array.isArray(body)) continue;
      const data = (body as Record<string, unknown>).data;
      if (typeof data !== "string" || data.length === 0) continue;
      const decoded = b64urlDecode(data);
      if (decoded.byteLength > MAX_BODY_BYTES) {
        const text = new TextDecoder("utf-8", { fatal: false }).decode(
          decoded.subarray(0, MAX_BODY_BYTES),
        );
        return { text: truncateUtf8(text, MAX_BODY_BYTES), truncated: true };
      }
      try {
        return {
          text: new TextDecoder("utf-8", { fatal: true }).decode(decoded),
          truncated: false,
        };
      } catch {
        throw new ProviderShapeError();
      }
    }
    return { text: "", truncated: false };
  }

  private walkParts(part: Record<string, unknown>, depth: number): Record<string, unknown>[] {
    // ponytail: depth cap 10 stops a hostile deeply-nested MIME tree; real mail
    // nests 2-3 levels. Raise if Gmail ever legitimately exceeds it.
    if (depth > MAX_PART_DEPTH) throw new ProviderShapeError();
    const result = [part];
    if (part.parts !== undefined) {
      for (const child of arrayValue(part.parts)) {
        result.push(...this.walkParts(objectValue(child), depth + 1));
      }
    }
    return result;
  }

  private normalizeSend(document: unknown): unknown {
    const message = objectValue(document);
    return {
      id: providerMessageId(message.id),
      thread_id: providerMessageId(message.threadId),
    };
  }
}
