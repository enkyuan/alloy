import { Agent, request as httpsRequest } from "node:https";

type HeaderInput = ConstructorParameters<typeof Headers>[0];

import type { ToolExecutionContext } from "@/runtime/context";
import type { BoundedResponse } from "@/integrations/safe-fetch";
import { IntegrationPolicyError, IntegrationTransportError } from "@/integrations/errors";
import {
  NOOP_METRICS,
  NOOP_TRACE,
  recordMetric,
  startSpan,
  type MetricsSink,
  type TraceSink,
} from "@/observability";

const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576;
const MAX_RESPONSE_HEADER_FIELDS = 64;
const MAX_RESPONSE_HEADER_BYTES = 64 * 1024;
const FORBIDDEN_REQUEST_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

interface FixedOriginPolicy {
  readonly origin: URL;
  readonly integration: "github" | "gmail";
  readonly timeoutMs?: number;
  readonly maxResponseBytes?: number;
  readonly allowedMethods?: readonly ("GET" | "POST")[];
}

interface FixedOriginObservability {
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
  readonly monotonicNow?: () => number;
}

export interface FixedOriginRequester {
  request(
    pathAndQuery: string,
    init: Readonly<{
      method: "GET" | "POST";
      headers: HeaderInput;
      body?: Uint8Array;
    }>,
    context: ToolExecutionContext,
  ): Promise<BoundedResponse>;
}

interface FixedOriginTransportInit {
  readonly method: "GET" | "POST";
  readonly headers: Readonly<Record<string, string>>;
  readonly body?: Uint8Array;
  readonly signal: AbortSignal;
}

/** @internal Relative source tests only; absent from the package subpath. */
export interface FixedOriginTestResponse {
  readonly status: number;
  readonly headers: readonly (readonly [string, string])[];
  readonly body: AsyncIterable<Uint8Array>;
  readonly close: () => void;
}

/** @internal Relative source tests only; absent from the package subpath. */
export interface FixedOriginTestTransport {
  request(url: URL, init: FixedOriginTransportInit): Promise<FixedOriginTestResponse>;
  close?(): void;
}

function policyError(): IntegrationPolicyError {
  return new IntegrationPolicyError();
}

function responseLimit(): IntegrationTransportError {
  return new IntegrationTransportError("INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded");
}

function positiveInteger(value: number | undefined, fallback: number): number {
  const resolved = value ?? fallback;
  if (!Number.isSafeInteger(resolved) || resolved < 1) throw policyError();
  return resolved;
}

function validatedOrigin(input: URL): URL {
  const origin = new URL(input.href);
  if (
    origin.protocol !== "https:" ||
    origin.username !== "" ||
    origin.password !== "" ||
    origin.pathname !== "/" ||
    origin.search !== "" ||
    origin.hash !== ""
  ) {
    throw policyError();
  }
  return origin;
}

function validatedPath(origin: URL, pathAndQuery: string): URL {
  if (
    typeof pathAndQuery !== "string" ||
    !pathAndQuery.startsWith("/") ||
    pathAndQuery.startsWith("//") ||
    pathAndQuery.includes("\\") ||
    pathAndQuery.includes("#")
  ) {
    throw policyError();
  }
  const rawPath = pathAndQuery.split("?", 1)[0]!;
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(rawPath);
  } catch {
    throw policyError();
  }
  if (decodedPath.startsWith("//") || decodedPath.includes("\\")) throw policyError();
  const target = new URL(pathAndQuery, origin);
  if (target.origin !== origin.origin) throw policyError();
  return target;
}

function validatedRequestHeaders(input: HeaderInput): Readonly<Record<string, string>> {
  let headers: Headers;
  try {
    headers = new Headers(input);
  } catch {
    throw policyError();
  }
  const result: Record<string, string> = {};
  for (const [name, value] of headers) {
    const normalized = name.toLowerCase();
    if (FORBIDDEN_REQUEST_HEADERS.has(normalized) || normalized.startsWith("proxy-")) {
      throw policyError();
    }
    result[normalized] = value;
  }
  return Object.freeze(result);
}

function boundedResponseHeaders(
  input: readonly (readonly [string, string])[],
): Readonly<Record<string, string>> {
  if (input.length > MAX_RESPONSE_HEADER_FIELDS) throw responseLimit();
  const encoder = new TextEncoder();
  let size = 0;
  const result: Record<string, string> = {};
  const contentLengths: string[] = [];
  for (const [name, value] of input) {
    size += encoder.encode(name).byteLength + encoder.encode(value).byteLength;
    if (size > MAX_RESPONSE_HEADER_BYTES) throw responseLimit();
    const normalized = name.toLowerCase();
    if (normalized === "content-length") contentLengths.push(value);
    result[normalized] = value;
  }
  if (
    contentLengths.length > 1 ||
    (contentLengths.length === 1 && !/^\d+$/.test(contentLengths[0]!))
  ) {
    throw responseLimit();
  }
  return Object.freeze(result);
}

function safeAbort(name: "AbortError" | "TimeoutError"): DOMException {
  return new DOMException(
    name === "AbortError" ? "Integration request cancelled" : "Integration request timed out",
    name,
  );
}

function requestSignal(context: ToolExecutionContext, timeoutMs: number) {
  if (context.signal.aborted) throw safeAbort("AbortError");
  const remaining =
    context.deadlineMonotonicMs === undefined
      ? timeoutMs
      : Math.min(timeoutMs, context.deadlineMonotonicMs - performance.now());
  if (remaining <= 0) throw safeAbort("TimeoutError");
  const controller = new AbortController();
  const onAbort = () => controller.abort(safeAbort("AbortError"));
  context.signal.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(safeAbort("TimeoutError")), remaining);
  return {
    signal: controller.signal,
    dispose() {
      clearTimeout(timer);
      context.signal.removeEventListener("abort", onAbort);
    },
  };
}

async function withAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) throw signal.reason;
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      cleanup();
      reject(signal.reason);
    };
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    signal.addEventListener("abort", onAbort, { once: true });
    void operation.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

class NodeHttpsTransport implements FixedOriginTestTransport {
  private readonly agent = new Agent({ keepAlive: true });

  request(url: URL, init: FixedOriginTransportInit): Promise<FixedOriginTestResponse> {
    return new Promise((resolve, reject) => {
      const request = httpsRequest(
        url,
        { method: init.method, headers: init.headers, agent: this.agent },
        (response) => {
          const headers: Array<readonly [string, string]> = [];
          for (let index = 0; index < response.rawHeaders.length; index += 2) {
            headers.push([response.rawHeaders[index]!, response.rawHeaders[index + 1] ?? ""]);
          }
          resolve({
            status: response.statusCode ?? 0,
            headers,
            body: response,
            close: () => response.destroy(),
          });
        },
      );
      const onAbort = () => request.destroy(init.signal.reason);
      init.signal.addEventListener("abort", onAbort, { once: true });
      request.once("error", reject);
      request.once("close", () => init.signal.removeEventListener("abort", onAbort));
      request.end(init.body);
    });
  }

  close(): void {
    this.agent.destroy();
  }
}

class FixedOriginRequesterImpl implements FixedOriginRequester {
  private readonly origin: URL;
  private readonly timeoutMs: number;
  private readonly maxResponseBytes: number;
  private readonly allowedMethods: ReadonlySet<"GET" | "POST">;
  private readonly integration: "github" | "gmail";
  private readonly metrics: MetricsSink;
  private readonly trace: TraceSink;
  private readonly monotonicNow: () => number;
  private closed = false;

  constructor(
    policy: FixedOriginPolicy,
    private readonly transport: FixedOriginTestTransport,
    observability: FixedOriginObservability = {},
  ) {
    this.origin = validatedOrigin(policy.origin);
    this.integration = policy.integration;
    this.timeoutMs = positiveInteger(policy.timeoutMs, DEFAULT_TIMEOUT_MS);
    this.maxResponseBytes = positiveInteger(policy.maxResponseBytes, DEFAULT_MAX_RESPONSE_BYTES);
    const allowedMethods = policy.allowedMethods ?? ["GET", "POST"];
    if (
      allowedMethods.length === 0 ||
      allowedMethods.some((method) => method !== "GET" && method !== "POST")
    ) {
      throw policyError();
    }
    this.allowedMethods = new Set(allowedMethods);
    this.metrics = observability.metricsSink ?? NOOP_METRICS;
    this.trace = observability.traceSink ?? NOOP_TRACE;
    this.monotonicNow = observability.monotonicNow ?? (() => performance.now());
  }

  async request(
    pathAndQuery: string,
    init: Readonly<{
      method: "GET" | "POST";
      headers: HeaderInput;
      body?: Uint8Array;
    }>,
    context: ToolExecutionContext,
  ): Promise<BoundedResponse> {
    const started = this.monotonicNow();
    const operation = init.method === "GET" ? "read" : "mutation";
    const span = startSpan(this.trace, "kaji.integration.request", {
      "integration.name": this.integration,
      "integration.operation": operation,
      "http.status_family": "none",
    });
    let outcome: "success" | "error" | "cancelled" = "error";
    let scope: ReturnType<typeof requestSignal> | undefined;
    let response: FixedOriginTestResponse | undefined;
    try {
      if (this.closed) throw policyError();
      if (!this.allowedMethods.has(init.method)) throw policyError();
      if (init.body !== undefined && !(init.body instanceof Uint8Array)) throw policyError();
      const url = validatedPath(this.origin, pathAndQuery);
      const headers = validatedRequestHeaders(init.headers);
      scope = requestSignal(context, this.timeoutMs);
      response = await withAbort(
        this.transport.request(url, {
          method: init.method,
          headers,
          ...(init.body === undefined ? {} : { body: init.body }),
          signal: scope.signal,
        }),
        scope.signal,
      );
      const boundedHeaders = boundedResponseHeaders(response.headers);
      if (response.status >= 300 && response.status < 400) {
        throw new IntegrationTransportError("INTEGRATION_REDIRECT_REJECTED", "redirect_rejected");
      }
      const contentLength = boundedHeaders["content-length"];
      if (contentLength !== undefined && Number(contentLength) > this.maxResponseBytes) {
        throw responseLimit();
      }
      const iterator = response.body[Symbol.asyncIterator]();
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const next = await withAbort(iterator.next(), scope.signal);
        if (next.done) break;
        if (!(next.value instanceof Uint8Array)) throw responseLimit();
        size += next.value.byteLength;
        if (size > this.maxResponseBytes) {
          throw responseLimit();
        }
        chunks.push(next.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      const family = Math.floor(response.status / 100);
      span.setAttribute("http.status_family", family >= 1 && family <= 5 ? `${family}xx` : "none");
      outcome = response.status >= 200 && response.status < 300 ? "success" : "error";
      return { status: response.status, headers: boundedHeaders, bytes };
    } catch (error) {
      response?.close();
      if (error instanceof DOMException && error.name === "AbortError") outcome = "cancelled";
      span.recordError(error);
      throw error;
    } finally {
      scope?.dispose();
      recordMetric(
        this.metrics,
        "kaji.integration.request_ms",
        Math.max(0, this.monotonicNow() - started),
        { integration: this.integration, operation, outcome },
      );
      span.end();
    }
  }

  close(): void {
    if (this.closed) return;
    this.transport.close?.();
    this.closed = true;
  }
}

const productionTransport = () => new NodeHttpsTransport();

export function createGitHubRequester(
  observability: FixedOriginObservability = {},
): FixedOriginRequester & { close(): void } {
  return new FixedOriginRequesterImpl(
    { origin: new URL("https://api.github.com/"), integration: "github" },
    productionTransport(),
    observability,
  );
}

export function createGmailRequester(
  observability: FixedOriginObservability = {},
): FixedOriginRequester & { close(): void } {
  return new FixedOriginRequesterImpl(
    { origin: new URL("https://gmail.googleapis.com/"), integration: "gmail" },
    productionTransport(),
    observability,
  );
}

/** @internal Relative source tests only; absent from the package subpath. */
export function fixedOriginForTest(
  origin: string,
  transport: FixedOriginTestTransport,
  policy: Omit<Partial<FixedOriginPolicy>, "origin"> = {},
  observability: FixedOriginObservability = {},
): FixedOriginRequester & { close(): void } {
  return new FixedOriginRequesterImpl(
    { origin: new URL(origin), integration: "github", ...policy },
    transport,
    observability,
  );
}
