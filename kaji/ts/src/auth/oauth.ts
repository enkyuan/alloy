import { createHash, randomBytes as nodeRandomBytes, timingSafeEqual } from "node:crypto";
import { createServer, type Server } from "node:http";
import { request as httpsRequest } from "node:https";
import type { Socket } from "node:net";
import { spawn } from "node:child_process";

import {
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationPolicyError,
} from "@/integrations/errors";
import type { ToolExecutionContext } from "@/runtime/context";
import { systemClock, type Clock } from "@/internal/uuid";
import {
  NOOP_METRICS,
  NOOP_TRACE,
  recordMetric,
  startSpan,
  type MetricsSink,
  type TraceSink,
} from "@/observability";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke";
const PRINCIPAL = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const MAX_CREDENTIAL_BYTES = 16 * 1024;
const MAX_PROVIDER_BYTES = 64 * 1024;
const MAX_TOKEN_CHARACTERS = 8_192;
const REFRESH_BUFFER_MS = 60_000;
const OPERATION_MS = 30_000;
const CALLBACK_MS = 5 * 60_000;

export interface OAuthTokenSet {
  readonly accessToken: string;
  readonly refreshToken: string;
  readonly expiresAtEpochMs: number;
  readonly grantedScopes: readonly string[];
  readonly tokenType: "Bearer";
}

export interface OAuthCredentialRecord {
  readonly schemaVersion: 1;
  readonly state: "active" | "revocation_pending";
  readonly tokens: OAuthTokenSet;
}

export interface OAuthTokenStorage {
  load(principalId: string, signal: AbortSignal): Promise<OAuthCredentialRecord | undefined>;
  save(principalId: string, record: OAuthCredentialRecord, signal: AbortSignal): Promise<void>;
  delete(principalId: string, signal: AbortSignal): Promise<void>;
}

export interface OAuthAccessTokenProvider {
  accessToken(context: ToolExecutionContext): Promise<string>;
}

export interface GoogleOAuthClientOptions {
  readonly clientId?: string;
  readonly clientSecret?: string;
  readonly scopes: readonly string[];
  readonly storage: OAuthTokenStorage;
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

interface OAuthResponse {
  readonly status: number;
  readonly bytes: Uint8Array;
}

interface OAuthTransport {
  postForm(
    endpoint: string,
    form: Readonly<Record<string, string>>,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<OAuthResponse>;
}

interface AuthorizationCallback {
  readonly redirectUri: string;
  waitForCode(
    expectedState: string,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<string>;
  close(): Promise<void>;
}

interface CallbackFactory {
  open(signal: AbortSignal, deadlineMonotonicMs: number): Promise<AuthorizationCallback>;
}

interface Browser {
  open(url: string, signal: AbortSignal, deadlineMonotonicMs: number): Promise<void>;
}

interface Dependencies {
  readonly http: OAuthTransport;
  readonly callbackFactory: CallbackFactory;
  readonly browser: Browser;
  readonly clock: Clock;
  readonly randomBytes: (count: number) => Uint8Array;
}

class OAuthOperationError extends Error {
  constructor() {
    super("OAuth operation failed");
  }
}

class OAuthScopeDriftError extends OAuthOperationError {}

class Mutex {
  private tail = Promise.resolve();

  async run<T>(operation: () => T | Promise<T>): Promise<T> {
    const previous = this.tail;
    const next = Promise.withResolvers<void>();
    this.tail = next.promise;
    await previous;
    try {
      return await operation();
    } finally {
      next.resolve();
    }
  }
}

interface RefreshFlight {
  readonly identity: object;
  readonly generation: number;
  readonly controller: AbortController;
  readonly promise: Promise<string>;
  waiters: number;
}

interface ConnectOperation {
  readonly generation: number;
  readonly controller: AbortController;
  readonly promise: Promise<void>;
}

interface PrincipalSlot {
  readonly gate: Mutex;
  generation: number;
  blocked: boolean;
  references: number;
  refresh?: RefreshFlight;
  connect?: ConnectOperation;
  disconnect?: Promise<void>;
}

function policyError(): IntegrationPolicyError {
  return new IntegrationPolicyError();
}

function authRequired(reason: "gmail_grant_missing" | "gmail_scope_drift") {
  return new IntegrationAuthRequiredError(reason);
}

export function validateOAuthPrincipal(value: unknown): string {
  if (typeof value !== "string" || !PRINCIPAL.test(value)) throw policyError();
  return value;
}

function scalarLength(value: string): number {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) throw new OAuthOperationError();
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new OAuthOperationError();
    }
  }
  return Array.from(value).length;
}

function boundedString(value: unknown, maximum = MAX_TOKEN_CHARACTERS): string {
  if (typeof value !== "string" || scalarLength(value) < 1 || scalarLength(value) > maximum) {
    throw new OAuthOperationError();
  }
  return value;
}

function normalizedScopes(value: readonly string[], provider = false): readonly string[] {
  if (!Array.isArray(value)) throw provider ? new OAuthOperationError() : policyError();
  const scopes = [...new Set(value)].sort();
  if (
    scopes.length === 0 ||
    scopes.length > 64 ||
    scopes.some(
      (scope) =>
        typeof scope !== "string" ||
        scope.length === 0 ||
        scalarLength(scope) > 2_048 ||
        /\s/.test(scope),
    )
  ) {
    throw provider ? new OAuthOperationError() : policyError();
  }
  return Object.freeze(scopes);
}

export function snapshotOAuthCredentialRecord(value: unknown): OAuthCredentialRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new OAuthOperationError();
  }
  const root = value as Record<string, unknown>;
  if (Object.keys(root).sort().join(",") !== "schemaVersion,state,tokens") {
    throw new OAuthOperationError();
  }
  if (
    root.schemaVersion !== 1 ||
    (root.state !== "active" && root.state !== "revocation_pending")
  ) {
    throw new OAuthOperationError();
  }
  if (root.tokens === null || typeof root.tokens !== "object" || Array.isArray(root.tokens)) {
    throw new OAuthOperationError();
  }
  const tokens = root.tokens as Record<string, unknown>;
  if (
    Object.keys(tokens).sort().join(",") !==
    "accessToken,expiresAtEpochMs,grantedScopes,refreshToken,tokenType"
  ) {
    throw new OAuthOperationError();
  }
  if (
    tokens.tokenType !== "Bearer" ||
    !Number.isSafeInteger(tokens.expiresAtEpochMs) ||
    (tokens.expiresAtEpochMs as number) < 1 ||
    !Array.isArray(tokens.grantedScopes)
  ) {
    throw new OAuthOperationError();
  }
  const grantedScopes = normalizedScopes(tokens.grantedScopes as string[], true);
  if (grantedScopes.length !== tokens.grantedScopes.length) throw new OAuthOperationError();
  const record: OAuthCredentialRecord = {
    schemaVersion: 1,
    state: root.state,
    tokens: {
      accessToken: boundedString(tokens.accessToken),
      refreshToken: boundedString(tokens.refreshToken),
      expiresAtEpochMs: tokens.expiresAtEpochMs as number,
      grantedScopes,
      tokenType: "Bearer",
    },
  };
  return Object.freeze({ ...record, tokens: Object.freeze(record.tokens) });
}

export function canonicalOAuthCredentialJson(value: OAuthCredentialRecord): string {
  const record = snapshotOAuthCredentialRecord(value);
  const encoded = JSON.stringify({
    schemaVersion: 1,
    state: record.state,
    tokens: {
      accessToken: record.tokens.accessToken,
      expiresAtEpochMs: record.tokens.expiresAtEpochMs,
      grantedScopes: record.tokens.grantedScopes,
      refreshToken: record.tokens.refreshToken,
      tokenType: "Bearer",
    },
  });
  if (new TextEncoder().encode(encoded).byteLength > MAX_CREDENTIAL_BYTES) {
    throw new OAuthOperationError();
  }
  return encoded;
}

function parseProviderJson(bytes: Uint8Array): Record<string, unknown> {
  if (bytes.byteLength > MAX_PROVIDER_BYTES) throw new OAuthOperationError();
  try {
    const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new OAuthOperationError();
    }
    return value as Record<string, unknown>;
  } catch {
    throw new OAuthOperationError();
  }
}

function providerErrorCode(bytes: Uint8Array): string | undefined {
  try {
    const error = parseProviderJson(bytes).error;
    return error === "invalid_grant" ? error : undefined;
  } catch {
    return undefined;
  }
}

function abortError(): DOMException {
  return new DOMException("OAuth operation cancelled", "AbortError");
}

function timeoutError(): DOMException {
  return new DOMException("OAuth operation timed out", "TimeoutError");
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw abortError();
}

class NodeOAuthTransport implements OAuthTransport {
  postForm(
    endpoint: string,
    form: Readonly<Record<string, string>>,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<OAuthResponse> {
    if (endpoint !== GOOGLE_TOKEN_URL && endpoint !== GOOGLE_REVOKE_URL) throw policyError();
    throwIfAborted(signal);
    const remaining = Math.min(OPERATION_MS, deadlineMonotonicMs - performance.now());
    if (remaining <= 0) return Promise.reject(timeoutError());
    return new Promise((resolve, reject) => {
      const body = new URLSearchParams(form).toString();
      const request = httpsRequest(
        endpoint,
        {
          method: "POST",
          headers: {
            "content-type": "application/x-www-form-urlencoded",
            "content-length": Buffer.byteLength(body),
          },
          timeout: remaining,
        },
        (response) => {
          const chunks: Buffer[] = [];
          let size = 0;
          response.on("data", (chunk: Buffer) => {
            size += chunk.byteLength;
            if (size > MAX_PROVIDER_BYTES) request.destroy(new OAuthOperationError());
            else chunks.push(chunk);
          });
          response.once("end", () =>
            resolve({ status: response.statusCode ?? 0, bytes: Buffer.concat(chunks) }),
          );
        },
      );
      const onAbort = () => request.destroy(abortError());
      signal.addEventListener("abort", onAbort, { once: true });
      const absoluteTimeout = setTimeout(() => request.destroy(timeoutError()), remaining);
      request.once("timeout", () => request.destroy(timeoutError()));
      request.once("error", (error) =>
        reject(error instanceof DOMException ? error : new OAuthOperationError()),
      );
      request.once("close", () => {
        clearTimeout(absoluteTimeout);
        signal.removeEventListener("abort", onAbort);
      });
      request.end(body);
    });
  }
}

class LoopbackCallback implements AuthorizationCallback {
  readonly redirectUri: string;
  private readonly result = Promise.withResolvers<readonly [string, string]>();

  constructor(
    private readonly server: Server,
    port: number,
    private readonly sockets: Set<Socket>,
  ) {
    this.redirectUri = `http://127.0.0.1:${port}/oauth/callback`;
  }

  accept(target: string): boolean {
    try {
      const url = new URL(target, this.redirectUri);
      const code = url.searchParams.has("error") ? "" : (url.searchParams.get("code") ?? "");
      this.result.resolve([
        (url.searchParams.get("state") ?? "").slice(0, 256),
        code.slice(0, 8_192),
      ]);
      return code.length > 0;
    } catch {
      this.result.resolve(["", ""]);
      return false;
    }
  }

  async waitForCode(
    expectedState: string,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<string> {
    const [state, code] = await raceSignal(this.result.promise, signal, deadlineMonotonicMs);
    const left = Buffer.from(state);
    const right = Buffer.from(expectedState);
    const leftHash = createHash("sha256").update(left).digest();
    const rightHash = createHash("sha256").update(right).digest();
    if (left.byteLength !== right.byteLength || !timingSafeEqual(leftHash, rightHash)) {
      throw new OAuthOperationError();
    }
    return boundedString(code);
  }

  async close(): Promise<void> {
    for (const socket of this.sockets) socket.destroy();
    if (!this.server.listening) return;
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }
}

class LoopbackCallbackFactory implements CallbackFactory {
  open(signal: AbortSignal, deadlineMonotonicMs: number): Promise<AuthorizationCallback> {
    throwIfAborted(signal);
    const remaining = deadlineMonotonicMs - performance.now();
    if (remaining <= 0) return Promise.reject(timeoutError());
    return new Promise((resolve, reject) => {
      let callback: LoopbackCallback | undefined;
      const sockets = new Set<Socket>();
      const server = createServer((request, response) => {
        if (request.method !== "GET" || request.url === undefined || request.url.length > 8_192) {
          response.writeHead(400).end();
          callback?.accept("");
          return;
        }
        let validPath = false;
        try {
          validPath = new URL(request.url, "http://127.0.0.1").pathname === "/oauth/callback";
        } catch {}
        const accepted = validPath && callback !== undefined && callback.accept(request.url);
        response
          .writeHead(accepted ? 200 : 400, { "content-length": "0", connection: "close" })
          .end();
      });
      server.on("connection", (socket) => {
        sockets.add(socket);
        socket.once("close", () => sockets.delete(socket));
      });
      let settled = false;
      const cleanup = () => {
        clearTimeout(timeout);
        signal.removeEventListener("abort", onAbort);
      };
      const fail = (error: Error) => {
        if (settled) return;
        settled = true;
        cleanup();
        try {
          server.close();
        } catch {}
        reject(error);
      };
      const onAbort = () => fail(abortError());
      const timeout = setTimeout(() => fail(timeoutError()), remaining);
      signal.addEventListener("abort", onAbort, { once: true });
      server.once("error", () => fail(new OAuthOperationError()));
      server.listen(0, "127.0.0.1", () => {
        if (settled) {
          for (const socket of sockets) socket.destroy();
          server.close();
          return;
        }
        const address = server.address();
        if (address === null || typeof address === "string") {
          fail(new OAuthOperationError());
          return;
        }
        settled = true;
        cleanup();
        callback = new LoopbackCallback(server, address.port, sockets);
        resolve(callback);
      });
    });
  }
}

class SystemBrowser implements Browser {
  async open(url: string, signal: AbortSignal, deadlineMonotonicMs: number): Promise<void> {
    throwIfAborted(signal);
    const remaining = deadlineMonotonicMs - performance.now();
    if (remaining <= 0) throw timeoutError();
    await new Promise<void>((resolve, reject) => {
      const child = spawn("/usr/bin/open", [url], { stdio: "ignore", shell: false });
      let failure: Error | undefined;
      let grace: ReturnType<typeof setTimeout> | undefined;
      const terminate = (error: Error) => {
        failure ??= error;
        if (child.exitCode !== null || child.signalCode !== null) return;
        child.kill("SIGTERM");
        grace ??= setTimeout(() => {
          if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
        }, 250);
      };
      const onAbort = () => terminate(abortError());
      signal.addEventListener("abort", onAbort, { once: true });
      const timeout = setTimeout(() => terminate(timeoutError()), remaining);
      child.once("error", () => terminate(new OAuthOperationError()));
      child.once("close", (code) => {
        clearTimeout(timeout);
        if (grace !== undefined) clearTimeout(grace);
        signal.removeEventListener("abort", onAbort);
        if (failure !== undefined) reject(failure);
        else if (code === 0) resolve();
        else reject(new OAuthOperationError());
      });
    });
  }
}

async function raceSignal<T>(
  operation: Promise<T>,
  signal: AbortSignal,
  deadlineMonotonicMs?: number,
  nowMonotonic: () => number = () => performance.now(),
): Promise<T> {
  throwIfAborted(signal);
  let remaining: number | undefined;
  if (deadlineMonotonicMs !== undefined) {
    remaining = deadlineMonotonicMs - nowMonotonic();
    if (remaining <= 0) throw timeoutError();
  }
  const cancellation = Promise.withResolvers<never>();
  const onAbort = () => cancellation.reject(abortError());
  signal.addEventListener("abort", onAbort, { once: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const candidates: Promise<T>[] = [operation, cancellation.promise];
  if (remaining !== undefined) {
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(timeoutError()), remaining);
    });
    candidates.push(timeout);
  }
  try {
    return await Promise.race(candidates);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
  }
}

function base64Url(value: Uint8Array): string {
  return Buffer.from(value).toString("base64url");
}

export class GoogleOAuthClient implements OAuthAccessTokenProvider {
  private readonly options: Readonly<{
    clientId?: string;
    clientSecret?: string;
    scopes: readonly string[];
    storage: OAuthTokenStorage;
  }>;
  private readonly dependencies: Dependencies;
  private readonly metrics: MetricsSink;
  private readonly trace: TraceSink;
  private readonly slots = new Map<string, PrincipalSlot>();
  private readonly slotsGate = new Mutex();

  constructor(options: GoogleOAuthClientOptions) {
    this.options = validatedOptions(options);
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.trace = options.traceSink ?? NOOP_TRACE;
    this.dependencies = {
      http: new NodeOAuthTransport(),
      callbackFactory: new LoopbackCallbackFactory(),
      browser: new SystemBrowser(),
      clock: systemClock,
      randomBytes: (count) => nodeRandomBytes(count),
    };
  }

  /** @internal Source-relative tests only. */
  static _create(options: GoogleOAuthClientOptions, dependencies: Dependencies): GoogleOAuthClient {
    const client = Object.create(GoogleOAuthClient.prototype) as GoogleOAuthClient;
    Object.defineProperty(client, "options", { value: validatedOptions(options) });
    Object.defineProperty(client, "dependencies", { value: dependencies });
    Object.defineProperty(client, "metrics", { value: options.metricsSink ?? NOOP_METRICS });
    Object.defineProperty(client, "trace", { value: options.traceSink ?? NOOP_TRACE });
    Object.defineProperty(client, "slots", { value: new Map() });
    Object.defineProperty(client, "slotsGate", { value: new Mutex() });
    return client;
  }

  async connect(principalId: string, signal: AbortSignal): Promise<void> {
    principalId = validateOAuthPrincipal(principalId);
    throwIfAborted(signal);
    const clientId = this.requiredClientId();
    const slot = await this.acquireSlot(principalId);
    try {
      let operation!: ConnectOperation;
      while (operation === undefined) {
        let pendingDisconnect: Promise<void> | undefined;
        await slot.gate.run(() => {
          if (slot.disconnect !== undefined) {
            pendingDisconnect = slot.disconnect;
            return;
          }
          slot.generation += 1;
          slot.blocked = true;
          const previous: Promise<unknown>[] = [];
          if (slot.connect !== undefined) {
            slot.connect.controller.abort(abortError());
            previous.push(slot.connect.promise);
          }
          if (slot.refresh !== undefined) {
            slot.refresh.controller.abort(abortError());
            previous.push(slot.refresh.promise);
          }
          const controller = new AbortController();
          const generation = slot.generation;
          const promise = (async () => {
            await Promise.allSettled(previous);
            throwIfAborted(controller.signal);
            await slot.gate.run(() => {
              if (
                slot.generation !== generation ||
                slot.connect?.generation !== generation ||
                slot.connect.controller !== controller
              ) {
                throw authRequired("gmail_grant_missing");
              }
            });
            await this.runConnect(principalId, slot, generation, clientId, controller.signal);
            await slot.gate.run(() => {
              if (
                slot.generation !== generation ||
                slot.connect?.generation !== generation ||
                slot.connect.controller !== controller
              ) {
                throw authRequired("gmail_grant_missing");
              }
              slot.blocked = false;
            });
          })();
          operation = { generation, controller, promise };
          slot.connect = operation;
        });
        if (pendingDisconnect !== undefined) await raceSignal(pendingDisconnect, signal);
      }
      try {
        await raceSignal(operation.promise, signal);
      } catch (error) {
        operation.controller.abort(abortError());
        await Promise.allSettled([operation.promise]);
        throw error;
      } finally {
        await slot.gate.run(() => {
          if (slot.connect === operation) delete slot.connect;
        });
      }
    } finally {
      await this.releaseSlot(principalId, slot);
    }
  }

  async accessToken(context: ToolExecutionContext): Promise<string> {
    const started = this.dependencies.clock.nowMonotonic();
    const span = startSpan(this.trace, "kaji.integration.auth", {
      "integration.name": "gmail",
      "integration.operation": "token",
      "http.status_family": "none",
    });
    let outcome: "success" | "error" | "cancelled" = "error";
    try {
      const token = await this.accessTokenInternal(context);
      outcome = "success";
      return token;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") outcome = "cancelled";
      span.recordError(error);
      throw error;
    } finally {
      recordMetric(
        this.metrics,
        "kaji.integration.auth_ms",
        Math.max(0, this.dependencies.clock.nowMonotonic() - started),
        { integration: "gmail", operation: "token", outcome },
      );
      span.end();
    }
  }

  private async accessTokenInternal(context: ToolExecutionContext): Promise<string> {
    const principalId = validateOAuthPrincipal(context.principalId);
    throwIfAborted(context.signal);
    this.checkDeadline(context.deadlineMonotonicMs);
    const slot = await this.acquireSlot(principalId);
    try {
      if (slot.blocked) throw authRequired("gmail_grant_missing");
      const generation = await slot.gate.run(() => {
        if (slot.blocked) throw authRequired("gmail_grant_missing");
        return slot.generation;
      });
      const loaded = await raceSignal(
        this.options.storage.load(principalId, context.signal),
        context.signal,
        context.deadlineMonotonicMs,
        () => this.dependencies.clock.nowMonotonic(),
      );
      if (loaded === undefined) throw authRequired("gmail_grant_missing");
      const record = snapshotOAuthCredentialRecord(loaded);
      if (record.state === "revocation_pending") throw authRequired("gmail_grant_missing");
      if (!isSuperset(record.tokens.grantedScopes, this.options.scopes)) {
        this.checkDeadline(context.deadlineMonotonicMs);
        await this.deleteIfCurrent(principalId, slot, generation, context.signal);
        throw authRequired("gmail_scope_drift");
      }
      if (
        record.tokens.expiresAtEpochMs >
        this.dependencies.clock.nowWallSeconds() * 1_000 + REFRESH_BUFFER_MS
      ) {
        return slot.gate.run(() => {
          this.checkDeadline(context.deadlineMonotonicMs);
          if (slot.blocked || slot.generation !== generation) {
            throw authRequired("gmail_grant_missing");
          }
          return record.tokens.accessToken;
        });
      }
      return await this.joinRefresh(principalId, slot, generation, record, context);
    } finally {
      await this.releaseSlot(principalId, slot);
    }
  }

  async disconnect(
    principalId: string,
    signal: AbortSignal,
    options: Readonly<{ forceLocal?: boolean }> = {},
  ): Promise<
    Readonly<{ localState: "deleted" | "revocation_pending" | "missing"; remoteRevoked: boolean }>
  > {
    principalId = validateOAuthPrincipal(principalId);
    throwIfAborted(signal);
    const slot = await this.acquireSlot(principalId);
    const completion = Promise.withResolvers<void>();
    let previousDisconnect: Promise<void> | undefined;
    await slot.gate.run(() => {
      previousDisconnect = slot.disconnect;
      slot.disconnect = completion.promise;
    });
    try {
      if (previousDisconnect !== undefined) await raceSignal(previousDisconnect, signal);
      let generation = 0;
      let operations: Promise<unknown>[] = [];
      await slot.gate.run(() => {
        slot.generation += 1;
        generation = slot.generation;
        slot.blocked = true;
        if (slot.connect !== undefined) {
          slot.connect.controller.abort(abortError());
          operations.push(slot.connect.promise);
        }
        if (slot.refresh !== undefined) {
          slot.refresh.controller.abort(abortError());
          operations.push(slot.refresh.promise);
        }
      });
      await Promise.allSettled(operations);
      const loaded = await this.options.storage.load(principalId, signal);
      if (loaded === undefined)
        return Object.freeze({ localState: "missing", remoteRevoked: false });
      const record = snapshotOAuthCredentialRecord(loaded);
      if (options.forceLocal === true) {
        await this.deleteBlockedIfCurrent(principalId, slot, generation, signal);
        return Object.freeze({ localState: "deleted", remoteRevoked: false });
      }
      const pending = snapshotOAuthCredentialRecord({ ...record, state: "revocation_pending" });
      const cleanup = new AbortController();
      let response: OAuthResponse;
      try {
        response = await this.dependencies.http.postForm(
          GOOGLE_REVOKE_URL,
          { token: record.tokens.refreshToken },
          signal,
          this.dependencies.clock.nowMonotonic() + OPERATION_MS,
        );
      } catch {
        await this.saveIfCurrent(principalId, slot, generation, pending, cleanup.signal);
        if (signal.aborted) throw abortError();
        return Object.freeze({ localState: "revocation_pending", remoteRevoked: false });
      }
      if (response.status === 200) {
        try {
          await this.deleteBlockedIfCurrent(principalId, slot, generation, cleanup.signal);
        } catch {
          await this.saveIfCurrent(principalId, slot, generation, pending, cleanup.signal);
          return Object.freeze({ localState: "revocation_pending", remoteRevoked: true });
        }
        return Object.freeze({ localState: "deleted", remoteRevoked: true });
      }
      await this.saveIfCurrent(principalId, slot, generation, pending, cleanup.signal);
      return Object.freeze({ localState: "revocation_pending", remoteRevoked: false });
    } finally {
      completion.resolve();
      await slot.gate.run(() => {
        if (slot.disconnect === completion.promise) delete slot.disconnect;
      });
      await this.releaseSlot(principalId, slot);
    }
  }

  private requiredClientId(): string {
    if (this.options.clientId === undefined || this.options.clientId.length === 0) {
      throw authRequired("gmail_grant_missing");
    }
    return this.options.clientId;
  }

  private checkDeadline(deadline: number | undefined): void {
    if (deadline !== undefined && deadline <= this.dependencies.clock.nowMonotonic()) {
      throw timeoutError();
    }
  }

  private async runConnect(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    clientId: string,
    signal: AbortSignal,
  ): Promise<void> {
    const callbackDeadline = this.dependencies.clock.nowMonotonic() + CALLBACK_MS;
    const callback = await this.dependencies.callbackFactory.open(signal, callbackDeadline);
    try {
      const state = base64Url(this.dependencies.randomBytes(32));
      const verifier = base64Url(this.dependencies.randomBytes(64));
      if (verifier.length < 43 || verifier.length > 128) throw new OAuthOperationError();
      const challenge = createHash("sha256").update(verifier, "ascii").digest("base64url");
      const authorization = new URL(GOOGLE_AUTH_URL);
      authorization.search = new URLSearchParams({
        client_id: clientId,
        redirect_uri: callback.redirectUri,
        response_type: "code",
        scope: this.options.scopes.join(" "),
        state,
        access_type: "offline",
        prompt: "consent",
        code_challenge: challenge,
        code_challenge_method: "S256",
      }).toString();
      await this.dependencies.browser.open(authorization.href, signal, callbackDeadline);
      const code = boundedString(await callback.waitForCode(state, signal, callbackDeadline));
      const form: Record<string, string> = {
        code,
        code_verifier: verifier,
        client_id: clientId,
        redirect_uri: callback.redirectUri,
        grant_type: "authorization_code",
      };
      if (this.options.clientSecret !== undefined) form.client_secret = this.options.clientSecret;
      const response = await this.dependencies.http.postForm(
        GOOGLE_TOKEN_URL,
        form,
        signal,
        this.dependencies.clock.nowMonotonic() + OPERATION_MS,
      );
      if (response.status !== 200) throw new OAuthOperationError();
      const tokens = this.tokensFromResponse(response.bytes, undefined, true);
      await this.saveIfCurrent(
        principalId,
        slot,
        generation,
        snapshotOAuthCredentialRecord({ schemaVersion: 1, state: "active", tokens }),
        signal,
        true,
      );
    } catch (error) {
      if (error instanceof DOMException || error instanceof IntegrationExecutionError) throw error;
      throw new OAuthOperationError();
    } finally {
      await callback.close();
    }
  }

  private async joinRefresh(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    record: OAuthCredentialRecord,
    context: ToolExecutionContext,
  ): Promise<string> {
    let flight!: RefreshFlight;
    await slot.gate.run(() => {
      if (slot.blocked || slot.generation !== generation) throw authRequired("gmail_grant_missing");
      if (slot.refresh === undefined || slot.refresh.generation !== generation) {
        const controller = new AbortController();
        const identity = {};
        const deadline = this.dependencies.clock.nowMonotonic() + OPERATION_MS;
        const promise = this.runRefreshWithDeadline(
          () => this.runRefresh(principalId, slot, generation, record, controller.signal, deadline),
          controller,
        ).finally(async () => {
          await slot.gate.run(() => {
            if (slot.refresh?.identity === identity) delete slot.refresh;
          });
        });
        slot.refresh = { identity, generation, controller, promise, waiters: 0 };
      }
      flight = slot.refresh;
      flight.waiters += 1;
    });
    try {
      return await raceSignal(flight.promise, context.signal, context.deadlineMonotonicMs, () =>
        this.dependencies.clock.nowMonotonic(),
      );
    } finally {
      let abort = false;
      await slot.gate.run(() => {
        flight.waiters -= 1;
        abort = flight.waiters === 0 && slot.refresh?.identity === flight.identity;
      });
      if (abort) {
        flight.controller.abort(abortError());
        await Promise.allSettled([flight.promise]);
      }
    }
  }

  private async runRefresh(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    record: OAuthCredentialRecord,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<string> {
    const form: Record<string, string> = {
      refresh_token: record.tokens.refreshToken,
      client_id: this.requiredClientId(),
      grant_type: "refresh_token",
    };
    if (this.options.clientSecret !== undefined) form.client_secret = this.options.clientSecret;
    const response = await this.dependencies.http.postForm(
      GOOGLE_TOKEN_URL,
      form,
      signal,
      deadlineMonotonicMs,
    );
    if (response.status !== 200) {
      if (providerErrorCode(response.bytes) === "invalid_grant") {
        await this.deleteIfCurrent(principalId, slot, generation, signal);
        throw authRequired("gmail_grant_missing");
      }
      throw new IntegrationExecutionError("api_rejected");
    }
    let tokens: OAuthTokenSet;
    try {
      tokens = this.tokensFromResponse(response.bytes, record.tokens, false);
    } catch (error) {
      if (!(error instanceof OAuthScopeDriftError)) throw error;
      await this.deleteIfCurrent(principalId, slot, generation, signal);
      throw authRequired("gmail_scope_drift");
    }
    await this.saveIfCurrent(
      principalId,
      slot,
      generation,
      snapshotOAuthCredentialRecord({ schemaVersion: 1, state: "active", tokens }),
      signal,
    );
    return tokens.accessToken;
  }

  private async runRefreshWithDeadline(
    start: () => Promise<string>,
    controller: AbortController,
  ): Promise<string> {
    const operation = start();
    let timedOut = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        timedOut = true;
        controller.abort(abortError());
        reject(timeoutError());
      }, OPERATION_MS);
    });
    try {
      return await Promise.race([operation, timeout]);
    } catch (error) {
      if (!timedOut) throw error;
      await Promise.allSettled([operation]);
      throw timeoutError();
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  private tokensFromResponse(
    bytes: Uint8Array,
    fallback: OAuthTokenSet | undefined,
    requireScope: boolean,
  ): OAuthTokenSet {
    const value = parseProviderJson(bytes);
    if (value.token_type !== "Bearer") throw new OAuthOperationError();
    const expires = value.expires_in;
    if (
      typeof expires !== "number" ||
      !Number.isFinite(expires) ||
      expires <= 0 ||
      expires > 604_800
    ) {
      throw new OAuthOperationError();
    }
    const refreshToken =
      value.refresh_token === undefined && fallback !== undefined
        ? fallback.refreshToken
        : boundedString(value.refresh_token);
    let grantedScopes: readonly string[];
    if (value.scope === undefined) {
      if (requireScope || fallback === undefined) throw new OAuthOperationError();
      grantedScopes = fallback.grantedScopes;
    } else {
      if (typeof value.scope !== "string") throw new OAuthOperationError();
      grantedScopes = normalizedScopes(value.scope.split(/\s+/).filter(Boolean), true);
      if (!isSuperset(grantedScopes, this.options.scopes)) {
        if (fallback !== undefined) throw new OAuthScopeDriftError();
        throw new OAuthOperationError();
      }
    }
    return Object.freeze({
      accessToken: boundedString(value.access_token),
      refreshToken,
      expiresAtEpochMs: Math.floor(
        this.dependencies.clock.nowWallSeconds() * 1_000 + expires * 1_000,
      ),
      grantedScopes,
      tokenType: "Bearer" as const,
    });
  }

  private async saveIfCurrent(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    record: OAuthCredentialRecord,
    signal: AbortSignal,
    allowBlockedActive = false,
  ): Promise<void> {
    await slot.gate.run(() => {
      if (
        slot.generation !== generation ||
        (slot.blocked && record.state === "active" && !allowBlockedActive)
      ) {
        throw authRequired("gmail_grant_missing");
      }
      return this.options.storage.save(principalId, record, signal);
    });
  }

  private async deleteIfCurrent(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    signal: AbortSignal,
  ): Promise<void> {
    await slot.gate.run(() => {
      if (slot.generation !== generation || slot.blocked) throw authRequired("gmail_grant_missing");
      return this.options.storage.delete(principalId, signal);
    });
  }

  private async deleteBlockedIfCurrent(
    principalId: string,
    slot: PrincipalSlot,
    generation: number,
    signal: AbortSignal,
  ): Promise<void> {
    await slot.gate.run(() => {
      if (slot.generation !== generation || !slot.blocked) {
        throw authRequired("gmail_grant_missing");
      }
      return this.options.storage.delete(principalId, signal);
    });
  }

  private async acquireSlot(principalId: string): Promise<PrincipalSlot> {
    return this.slotsGate.run(() => {
      let slot = this.slots.get(principalId);
      if (slot === undefined) {
        slot = { gate: new Mutex(), generation: 0, blocked: false, references: 0 };
        this.slots.set(principalId, slot);
      }
      slot.references += 1;
      return slot;
    });
  }

  private async releaseSlot(principalId: string, slot: PrincipalSlot): Promise<void> {
    await this.slotsGate.run(() => {
      slot.references -= 1;
      if (
        slot.references === 0 &&
        slot.connect === undefined &&
        slot.refresh === undefined &&
        slot.disconnect === undefined &&
        this.slots.get(principalId) === slot
      ) {
        this.slots.delete(principalId);
      }
    });
  }
}

function isSuperset(candidate: readonly string[], required: readonly string[]): boolean {
  const values = new Set(candidate);
  return required.every((scope) => values.has(scope));
}

function validatedOptions(options: GoogleOAuthClientOptions): GoogleOAuthClient["options"] {
  if (options === null || typeof options !== "object" || typeof options.storage !== "object") {
    throw policyError();
  }
  const scopes = normalizedScopes(options.scopes);
  const clientId =
    options.clientId === undefined || options.clientId === ""
      ? undefined
      : boundedString(options.clientId, 4_096);
  const clientSecret =
    options.clientSecret === undefined ? undefined : boundedString(options.clientSecret);
  return Object.freeze({
    ...(clientId === undefined ? {} : { clientId }),
    ...(clientSecret === undefined ? {} : { clientSecret }),
    scopes,
    storage: options.storage,
  });
}

/** @internal Source-relative deterministic tests only. */
export function _createGoogleOAuthClientForTest(
  options: GoogleOAuthClientOptions,
  dependencies: Dependencies,
): GoogleOAuthClient {
  return GoogleOAuthClient._create(options, dependencies);
}
