import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { domainToASCII } from "node:url";

import type { ToolExecutionContext } from "@/runtime/context";

const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576;
const DEFAULT_MAX_REDIRECTS = 3;

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

const SENSITIVE_REQUEST_HEADERS = [
  "api-key",
  "authorization",
  "cookie",
  "cookie2",
  "x-access-token",
  "x-api-key",
  "x-auth-token",
  "x-subscription-token",
] as const;

export interface SafeFetchPolicy {
  readonly allowedHosts: readonly string[];
  readonly allowPublicInternet?: boolean;
  readonly allowHttp?: boolean;
  readonly timeoutMs?: number;
  readonly maxResponseBytes?: number;
  readonly maxRedirects?: number;
  /** Additional credential-bearing request headers to remove on cross-origin redirects. */
  readonly sensitiveHeaders?: readonly string[];
}

export interface BoundNetworkTransport {
  request(
    target: { readonly url: URL; readonly validatedAddresses: readonly string[] },
    init: RequestInit & { readonly signal: AbortSignal },
  ): Promise<Response>;
}

export interface BoundedResponse {
  readonly status: number;
  readonly headers: Readonly<Record<string, string>>;
  readonly bytes: Uint8Array;
}

/** Injectable only so registry tests and application egress adapters never need public DNS. */
export type AddressResolver = (hostname: string) => Promise<readonly string[]>;

const defaultResolver: AddressResolver = async (hostname) =>
  (await lookup(hostname, { all: true, verbatim: true })).map(({ address }) => address);

function integerLimit(
  value: number | undefined,
  fallback: number,
  name: string,
  allowZero = false,
): number {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < (allowZero ? 0 : 1)) {
    throw new RangeError(`${name} must be ${allowZero ? "a non-negative" : "a positive"} integer`);
  }
  return result;
}

function canonicalIp(address: string): string {
  const family = isIP(address);
  if (family === 4) return new URL(`http://${address}/`).hostname;
  if (family === 6) return new URL(`http://[${address}]/`).hostname.slice(1, -1).toLowerCase();
  throw new Error(`Address resolver returned an invalid IP address: ${JSON.stringify(address)}`);
}

function canonicalHost(input: string): string {
  let host = input.trim().toLowerCase();
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (isIP(host) !== 0) return canonicalIp(host);
  let parsed: URL;
  try {
    parsed = new URL(`http://${host}/`);
  } catch (error) {
    throw new Error(`Invalid hostname: ${JSON.stringify(input)}`, { cause: error });
  }
  if (
    parsed.username.length > 0 ||
    parsed.password.length > 0 ||
    parsed.port.length > 0 ||
    parsed.pathname !== "/" ||
    parsed.search.length > 0 ||
    parsed.hash.length > 0
  ) {
    throw new Error(`Invalid hostname: ${JSON.stringify(input)}`);
  }
  const parsedHost = parsed.hostname.toLowerCase();
  if (isIP(parsedHost) !== 0) return canonicalIp(parsedHost);
  const ascii = domainToASCII(parsedHost).toLowerCase();
  const canonical = ascii.endsWith(".") ? ascii.slice(0, -1) : ascii;
  if (
    canonical.length === 0 ||
    canonical.length > 253 ||
    canonical.startsWith(".") ||
    canonical.endsWith(".") ||
    canonical
      .split(".")
      .some(
        (label) =>
          label.length === 0 ||
          label.length > 63 ||
          !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label),
      )
  ) {
    throw new Error(`Invalid hostname: ${JSON.stringify(input)}`);
  }
  return canonical;
}

function ipv4Number(address: string): number {
  return address.split(".").reduce((value, octet) => value * 256 + Number.parseInt(octet, 10), 0);
}

function ipv4InCidr(value: number, base: string, prefix: number): boolean {
  const divisor = 2 ** (32 - prefix);
  return Math.floor(value / divisor) === Math.floor(ipv4Number(base) / divisor);
}

function publicIpv4(address: string): boolean {
  const value = ipv4Number(address);
  const denied: ReadonlyArray<readonly [string, number]> = [
    ["0.0.0.0", 8],
    ["10.0.0.0", 8],
    ["100.64.0.0", 10],
    ["127.0.0.0", 8],
    ["169.254.0.0", 16],
    ["172.16.0.0", 12],
    ["192.0.0.0", 24],
    ["192.0.2.0", 24],
    ["192.31.196.0", 24],
    ["192.52.193.0", 24],
    ["192.88.99.0", 24],
    ["192.168.0.0", 16],
    ["192.175.48.0", 24],
    ["198.18.0.0", 15],
    ["198.51.100.0", 24],
    ["203.0.113.0", 24],
    ["224.0.0.0", 4],
    ["240.0.0.0", 4],
  ];
  return !denied.some(([base, prefix]) => ipv4InCidr(value, base, prefix));
}

function ipv6Number(address: string): bigint {
  const sides = address.split("::");
  if (sides.length > 2) throw new Error(`Invalid IPv6 address: ${address}`);
  const left = sides[0] === "" ? [] : sides[0]!.split(":");
  const right = sides.length === 1 || sides[1] === "" ? [] : sides[1]!.split(":");
  const missing = 8 - left.length - right.length;
  if (missing < 0 || (sides.length === 1 && missing !== 0)) {
    throw new Error(`Invalid IPv6 address: ${address}`);
  }
  const groups = [...left, ...Array.from({ length: missing }, () => "0"), ...right];
  return groups.reduce((value, group) => (value << 16n) | BigInt(`0x${group}`), 0n);
}

function ipv6InCidr(value: bigint, base: string, prefix: number): boolean {
  const shift = BigInt(128 - prefix);
  return value >> shift === ipv6Number(base) >> shift;
}

function publicIpv6(address: string): boolean {
  const value = ipv6Number(address);
  if (!ipv6InCidr(value, "2000::", 3)) return false;
  const denied: ReadonlyArray<readonly [string, number]> = [
    ["2001::", 23],
    ["2001:db8::", 32],
    ["2002::", 16],
    ["3fff::", 20],
  ];
  return !denied.some(([base, prefix]) => ipv6InCidr(value, base, prefix));
}

function publicAddress(address: string): boolean {
  const family = isIP(address);
  if (family === 4) return publicIpv4(address);
  if (family === 6) return publicIpv6(address);
  return false;
}

async function withAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) abortReason(signal, "Request cancelled");
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      cleanup();
      try {
        abortReason(signal, "Request cancelled");
      } catch (error) {
        reject(error);
      }
    };
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    signal.addEventListener("abort", onAbort, { once: true });
    void promise.then(
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

async function validatedAddresses(
  hostname: string,
  resolver: AddressResolver,
  signal: AbortSignal,
): Promise<string[]> {
  const family = isIP(hostname);
  let resolved: readonly string[];
  if (family !== 0) {
    resolved = [hostname];
  } else {
    try {
      resolved = await withAbort(resolver(hostname), signal);
    } catch (error) {
      if (signal.aborted) abortReason(signal, "Request cancelled");
      throw new Error(`Address resolution failed for ${hostname}`, { cause: error });
    }
  }
  if (resolved.length === 0)
    throw new Error(`Address resolution returned no results for ${hostname}`);

  const addresses = [...new Set(resolved.map((address) => canonicalIp(address.trim())))];
  const denied = addresses.find((address) => !publicAddress(address));
  if (denied !== undefined) {
    throw new Error(`SSRF protection rejected non-public address ${denied} for ${hostname}`);
  }
  return addresses;
}

function validatedUrl(input: URL, policy: SafeFetchPolicy): { url: URL; hostname: string } {
  const url = new URL(input.href);
  if (url.protocol !== "https:" && (url.protocol !== "http:" || policy.allowHttp !== true)) {
    throw new Error(`URL scheme ${JSON.stringify(url.protocol)} is not allowed`);
  }
  if (url.username.length > 0 || url.password.length > 0) {
    throw new Error("URL credentials are not allowed");
  }
  const hostname = canonicalHost(url.hostname);
  const allowedHosts = policy.allowedHosts.map(canonicalHost);
  if (policy.allowPublicInternet !== true && !allowedHosts.includes(hostname)) {
    throw new Error(`SSRF protection: host ${JSON.stringify(hostname)} is not explicitly allowed`);
  }
  url.hostname = hostname.includes(":") ? `[${hostname}]` : hostname;
  return { url, hostname };
}

function validatedHeaders(input: RequestInit["headers"]): Headers {
  const headers = new Headers(input);
  for (const name of headers.keys()) {
    const normalized = name.toLowerCase();
    if (FORBIDDEN_REQUEST_HEADERS.has(normalized) || normalized.startsWith("proxy-")) {
      throw new Error(`Caller-controlled ${JSON.stringify(name)} header is not allowed`);
    }
  }
  return headers;
}

function abortReason(signal: AbortSignal, fallback: string): never {
  if (signal.reason instanceof Error) throw signal.reason;
  throw new DOMException(fallback, "AbortError");
}

function requestSignal(
  context: ToolExecutionContext,
  init: RequestInit,
  timeoutMs: number,
): { readonly signal: AbortSignal; readonly dispose: () => void } {
  const signals = [context.signal];
  if (init.signal !== undefined && init.signal !== null) signals.push(init.signal);
  for (const signal of signals) {
    if (signal.aborted) abortReason(signal, "Request cancelled");
  }
  const controller = new AbortController();
  const removers: Array<() => void> = [];
  for (const signal of signals) {
    const abort = () => controller.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    removers.push(() => signal.removeEventListener("abort", abort));
  }
  const timer = setTimeout(
    () => controller.abort(new DOMException("Request timed out", "TimeoutError")),
    timeoutMs,
  );
  return {
    signal: controller.signal,
    dispose: () => {
      clearTimeout(timer);
      for (const remove of removers) remove();
    },
  };
}

function responseHeaders(headers: Headers): Readonly<Record<string, string>> {
  const result: Record<string, string> = {};
  headers.forEach((value, name) => {
    result[name.toLowerCase()] = value;
  });
  return Object.freeze(result);
}

function cancelReaderBestEffort(
  reader: { cancel(reason?: unknown): Promise<void> },
  reason: unknown,
): void {
  try {
    void reader.cancel(reason).catch(() => undefined);
  } catch {
    // Cleanup must never become a second blocking or failure boundary.
  }
}

function cancelResponseBestEffort(response: Response, reason: unknown): void {
  try {
    void response.body?.cancel(reason).catch(() => undefined);
  } catch {
    // Cleanup must never become a second blocking or failure boundary.
  }
}

async function boundedBody(
  response: Response,
  maxBytes: number,
  signal: AbortSignal,
): Promise<Uint8Array> {
  if (response.body === null) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const cancel = () => {
    cancelReaderBestEffort(reader, signal.reason);
  };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    while (size <= maxBytes) {
      const { done, value } = await withAbort(reader.read(), signal);
      if (done) break;
      if (!(value instanceof Uint8Array)) throw new TypeError("Response body must contain bytes");
      size += value.byteLength;
      if (size > maxBytes) {
        cancelReaderBestEffort(reader, "response body exceeds configured byte limit");
        throw new RangeError(`Response body exceeds maxResponseBytes (${maxBytes})`);
      }
      chunks.push(value);
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    try {
      reader.releaseLock();
    } catch {
      // A non-cooperative stream may retain a pending read after cancellation.
    }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function redirectStatus(status: number): boolean {
  return status === 301 || status === 302 || status === 303 || status === 307 || status === 308;
}

function sensitiveHeaders(policy: SafeFetchPolicy): ReadonlySet<string> {
  const names = new Set<string>(SENSITIVE_REQUEST_HEADERS);
  for (const name of policy.sensitiveHeaders ?? []) {
    const normalized = name.trim().toLowerCase();
    if (!/^[!#$%&'*+.^_`|~0-9a-z-]+$/.test(normalized)) {
      throw new TypeError(`Invalid sensitive header name ${JSON.stringify(name)}`);
    }
    names.add(normalized);
  }
  return names;
}

function looksCredentialBearing(name: string): boolean {
  return /(?:^|-)(?:credential|key|secret|signature|token)(?:-|$)/.test(name);
}

function redirectedInit(
  current: RequestInit,
  status: number,
  crossOrigin: boolean,
  secrets: ReadonlySet<string>,
): RequestInit {
  const headers = new Headers(current.headers);
  let method = (current.method ?? "GET").toUpperCase();
  let body = current.body;
  if (status === 303 || ((status === 301 || status === 302) && method === "POST")) {
    method = "GET";
    body = undefined;
    // headers.delete() mutates the live keys() iterator; snapshot before iterating.
    // oxlint-disable-next-line no-useless-spread
    for (const name of [...headers.keys()]) {
      if (name.toLowerCase().startsWith("content-")) headers.delete(name);
    }
  }
  if (crossOrigin) {
    // headers.delete() mutates the live keys() iterator; snapshot before iterating.
    // oxlint-disable-next-line no-useless-spread
    for (const name of [...headers.keys()]) {
      const normalized = name.toLowerCase();
      if (secrets.has(normalized) || looksCredentialBearing(normalized)) headers.delete(name);
    }
  }
  return {
    ...current,
    method,
    headers,
    ...(body === undefined ? { body: null } : { body }),
    ...(crossOrigin ? { credentials: "omit" } : {}),
  };
}

/**
 * Execute one bounded request through an address-pinning application transport.
 * The optional resolver argument is intentionally not re-exported from the beta root.
 */
export async function safeRequest(
  input: URL,
  init: RequestInit,
  context: ToolExecutionContext,
  policy: SafeFetchPolicy,
  transport: BoundNetworkTransport,
  resolver: AddressResolver = defaultResolver,
): Promise<BoundedResponse> {
  if (typeof policy !== "object" || policy === null)
    throw new TypeError("safe fetch policy is required");
  if (typeof transport?.request !== "function")
    throw new TypeError("bound network transport is required");
  if (!Array.isArray(policy.allowedHosts)) throw new TypeError("allowedHosts must be an array");

  const timeoutMs = integerLimit(policy.timeoutMs, DEFAULT_TIMEOUT_MS, "timeoutMs");
  if (timeoutMs > 2_147_483_647) {
    throw new RangeError("timeoutMs must not exceed 2147483647");
  }
  const maxResponseBytes = integerLimit(
    policy.maxResponseBytes,
    DEFAULT_MAX_RESPONSE_BYTES,
    "maxResponseBytes",
  );
  const maxRedirects = integerLimit(
    policy.maxRedirects,
    DEFAULT_MAX_REDIRECTS,
    "maxRedirects",
    true,
  );
  const secrets = sensitiveHeaders(policy);
  const signalScope = requestSignal(context, init, timeoutMs);
  const { signal } = signalScope;
  let currentUrl = new URL(input.href);
  let currentInit: RequestInit = {
    ...init,
    headers: validatedHeaders(init.headers),
    redirect: "manual",
    signal,
  };

  try {
    for (let redirects = 0; ; redirects++) {
      if (signal.aborted) abortReason(signal, "Request cancelled");
      const { url, hostname } = validatedUrl(currentUrl, policy);
      const addresses = await validatedAddresses(hostname, resolver, signal);
      if (signal.aborted) abortReason(signal, "Request cancelled");
      const response = await withAbort(
        transport.request(
          { url: new URL(url.href), validatedAddresses: Object.freeze([...addresses]) },
          {
            ...currentInit,
            headers: validatedHeaders(currentInit.headers),
            redirect: "manual",
            signal,
          },
        ),
        signal,
      );
      if (signal.aborted) abortReason(signal, "Request cancelled");

      if (!redirectStatus(response.status)) {
        return {
          status: response.status,
          headers: responseHeaders(response.headers),
          bytes: await boundedBody(response, maxResponseBytes, signal),
        };
      }
      if (redirects >= maxRedirects) {
        cancelResponseBestEffort(response, "redirect limit exceeded");
        throw new Error(`Redirect limit exceeded (${maxRedirects})`);
      }
      const location = response.headers.get("location");
      if (location === null || location.trim().length === 0) {
        cancelResponseBestEffort(response, "redirect location missing");
        throw new Error("Redirect response is missing a valid Location header");
      }
      let nextUrl: URL;
      try {
        nextUrl = new URL(location, url);
      } catch (error) {
        cancelResponseBestEffort(response, "redirect location malformed");
        throw new Error("Redirect response has a malformed Location header", { cause: error });
      }
      cancelResponseBestEffort(response, "redirect response not consumed");
      currentInit = redirectedInit(
        currentInit,
        response.status,
        nextUrl.origin !== url.origin,
        secrets,
      );
      currentUrl = nextUrl;
    }
  } finally {
    signalScope.dispose();
  }
}
