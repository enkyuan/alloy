import { describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { inspect } from "node:util";

import { ToolExecutionError, type ToolExecutionContext } from "@irogane/kaji";
import {
  GoogleOAuthClient,
  type OAuthCredentialRecord,
  type OAuthTokenStorage,
  _createGoogleOAuthClientForTest,
} from "../src/auth/oauth";

const scopes = ["scope/a", "scope/b"] as const;

function context(
  principalId = "user-123",
  overrides: Partial<ToolExecutionContext> = {},
): ToolExecutionContext {
  return {
    principalId,
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal: new AbortController().signal,
    metadata: {},
    ...overrides,
  };
}

function record(
  overrides: Partial<OAuthCredentialRecord["tokens"]> & {
    state?: OAuthCredentialRecord["state"];
  } = {},
): OAuthCredentialRecord {
  return Object.freeze({
    schemaVersion: 1,
    state: overrides.state ?? "active",
    tokens: Object.freeze({
      accessToken: overrides.accessToken ?? "access",
      refreshToken: overrides.refreshToken ?? "refresh",
      expiresAtEpochMs: overrides.expiresAtEpochMs ?? 1_700_003_600_000,
      grantedScopes: Object.freeze([...(overrides.grantedScopes ?? scopes)]),
      tokenType: "Bearer" as const,
    }),
  });
}

class MemoryStorage implements OAuthTokenStorage {
  readonly records = new Map<string, OAuthCredentialRecord>();
  readonly calls: string[] = [];

  constructor(records: Readonly<Record<string, OAuthCredentialRecord>> = {}) {
    for (const [principal, value] of Object.entries(records)) this.records.set(principal, value);
  }

  async load(principalId: string, signal: AbortSignal): Promise<OAuthCredentialRecord | undefined> {
    if (signal.aborted) throw signal.reason;
    this.calls.push(`load:${principalId}`);
    return this.records.get(principalId);
  }

  async save(
    principalId: string,
    value: OAuthCredentialRecord,
    signal: AbortSignal,
  ): Promise<void> {
    if (signal.aborted) throw signal.reason;
    this.calls.push(`save:${principalId}`);
    this.records.set(principalId, value);
  }

  async delete(principalId: string, signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw signal.reason;
    this.calls.push(`delete:${principalId}`);
    this.records.delete(principalId);
  }
}

class PausingDeleteStorage extends MemoryStorage {
  readonly deleteEntered = Promise.withResolvers<void>();
  readonly releaseDelete = Promise.withResolvers<void>();

  override async delete(principalId: string, signal: AbortSignal): Promise<void> {
    this.deleteEntered.resolve();
    await this.releaseDelete.promise;
    await super.delete(principalId, signal);
  }
}

class PausingSaveStorage extends MemoryStorage {
  readonly saveEntered = Promise.withResolvers<void>();
  readonly saveReaped = Promise.withResolvers<void>();

  override async save(
    _principalId: string,
    _value: OAuthCredentialRecord,
    signal: AbortSignal,
  ): Promise<void> {
    this.saveEntered.resolve();
    try {
      await new Promise<never>((_, reject) => {
        if (signal.aborted) {
          reject(signal.reason);
          return;
        }
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    } finally {
      this.saveReaped.resolve();
    }
  }
}

interface OAuthResponse {
  readonly status: number;
  readonly bytes: Uint8Array;
}

class Http {
  readonly calls: Array<readonly [string, Readonly<Record<string, string>>]> = [];
  readonly responses: OAuthResponse[];
  readonly deadlines: number[] = [];
  pause = false;
  readonly entered = Promise.withResolvers<void>();
  readonly release = Promise.withResolvers<void>();
  readonly aborted = Promise.withResolvers<void>();

  constructor(responses: readonly OAuthResponse[] = []) {
    this.responses = [...responses];
  }

  async postForm(
    endpoint: string,
    form: Readonly<Record<string, string>>,
    signal: AbortSignal,
    deadlineMonotonicMs: number,
  ): Promise<OAuthResponse> {
    this.calls.push([endpoint, { ...form }]);
    this.deadlines.push(deadlineMonotonicMs);
    this.entered.resolve();
    signal.addEventListener("abort", () => this.aborted.resolve(), { once: true });
    if (this.pause) {
      await Promise.race([
        this.release.promise,
        new Promise<never>((_, reject) =>
          signal.addEventListener("abort", () => reject(signal.reason), { once: true }),
        ),
      ]);
    }
    return this.responses.shift()!;
  }
}

class Callback {
  readonly redirectUri = "http://127.0.0.1:43117/oauth/callback";
  expectedState?: string;
  closed = false;

  async waitForCode(
    expectedState: string,
    signal: AbortSignal,
    _deadlineMonotonicMs: number,
  ): Promise<string> {
    if (signal.aborted) throw signal.reason;
    this.expectedState = expectedState;
    return "auth-code";
  }

  async close(): Promise<void> {
    this.closed = true;
  }
}

class CallbackFactory {
  calls = 0;
  constructor(readonly callback: Callback) {}
  async open(signal: AbortSignal, _deadlineMonotonicMs: number): Promise<Callback> {
    if (signal.aborted) throw signal.reason;
    this.calls += 1;
    return this.callback;
  }
}

function makeClient(options: {
  storage: MemoryStorage;
  http?: Http;
  callback?: Callback;
  browser?: (url: string, signal: AbortSignal, deadlineMonotonicMs: number) => Promise<void>;
  clientId?: string;
}): GoogleOAuthClient {
  const callback = options.callback ?? new Callback();
  return _createGoogleOAuthClientForTest(
    {
      ...(options.clientId === undefined
        ? { clientId: "client-id" }
        : { clientId: options.clientId }),
      scopes,
      storage: options.storage,
    },
    {
      http: options.http ?? new Http(),
      callbackFactory: new CallbackFactory(callback),
      browser: { open: options.browser ?? vi.fn(async () => {}) },
      clock: { nowWallSeconds: () => 1_700_000_000, nowMonotonic: () => 100_000 },
      randomBytes: (count) => Uint8Array.from({ length: count }, (_, index) => index),
    },
  );
}

function slotCount(client: GoogleOAuthClient): number {
  return (client as unknown as { slots: Map<string, unknown> }).slots.size;
}

const response = (status: number, body: unknown): OAuthResponse => ({
  status,
  bytes: new TextEncoder().encode(typeof body === "string" ? body : JSON.stringify(body)),
});

describe("GoogleOAuthClient", () => {
  it.each(["", " user", "user@example.com", "üser", "a".repeat(129)])(
    "rejects principal %j before dependencies",
    async (principalId) => {
      const storage = new MemoryStorage();
      const http = new Http();
      const browser = vi.fn(
        async (_url: string, _signal: AbortSignal, _deadlineMonotonicMs: number) => {},
      );
      const client = makeClient({ storage, http, browser });
      await expect(client.accessToken(context(principalId))).rejects.toBeInstanceOf(
        ToolExecutionError,
      );
      await expect(
        client.connect(principalId, new AbortController().signal),
      ).rejects.toBeInstanceOf(ToolExecutionError);
      await expect(
        client.disconnect(principalId, new AbortController().signal),
      ).rejects.toBeInstanceOf(ToolExecutionError);
      expect(storage.calls).toEqual([]);
      expect(http.calls).toEqual([]);
      expect(browser).not.toHaveBeenCalled();
    },
  );

  it("never starts consent from accessToken", async () => {
    const storage = new MemoryStorage();
    const browser = vi.fn(
      async (_url: string, _signal: AbortSignal, _deadlineMonotonicMs: number) => {},
    );
    const client = makeClient({ storage, browser });
    await expect(client.accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });
    expect(browser).not.toHaveBeenCalled();
  });

  it("returns a fresh principal-bound token without a client id or request", async () => {
    const storage = new MemoryStorage({ "user-123": record() });
    const http = new Http();
    const client = makeClient({ storage, http, clientId: "" });
    await expect(client.accessToken(context())).resolves.toBe("access");
    expect(http.calls).toEqual([]);
  });

  it("rejects pending and deletes scope-drifted grants", async () => {
    const pending = new MemoryStorage({ "user-123": record({ state: "revocation_pending" }) });
    await expect(makeClient({ storage: pending }).accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });
    const drift = new MemoryStorage({
      "user-123": record({ grantedScopes: ["scope/a"] }),
    });
    await expect(makeClient({ storage: drift }).accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });
    expect(drift.records.has("user-123")).toBe(false);
  });

  it("single-flights refresh and preserves omitted refresh token and scope", async () => {
    const storage = new MemoryStorage({
      "user-123": record({ accessToken: "old", expiresAtEpochMs: 1 }),
    });
    const http = new Http([
      response(200, { access_token: "new", expires_in: 3600, token_type: "Bearer" }),
    ]);
    http.pause = true;
    const client = makeClient({ storage, http });
    const first = client.accessToken(context());
    await http.entered.promise;
    const second = client.accessToken(context());
    await Promise.resolve();
    http.release.resolve();
    await expect(Promise.all([first, second])).resolves.toEqual(["new", "new"]);
    expect(http.calls).toHaveLength(1);
    expect(storage.records.get("user-123")?.tokens).toMatchObject({
      refreshToken: "refresh",
      grantedScopes: scopes,
    });
  });

  it("allows refreshes for different principals to overlap", async () => {
    const storage = new MemoryStorage({
      "user-a": record({ accessToken: "old-a", refreshToken: "refresh-a", expiresAtEpochMs: 1 }),
      "user-b": record({ accessToken: "old-b", refreshToken: "refresh-b", expiresAtEpochMs: 1 }),
    });
    const http = new Http([
      response(200, { access_token: "new-a", expires_in: 3600, token_type: "Bearer" }),
      response(200, { access_token: "new-b", expires_in: 3600, token_type: "Bearer" }),
    ]);
    http.pause = true;
    const client = makeClient({ storage, http });
    const first = client.accessToken(context("user-a"));
    const second = client.accessToken(context("user-b"));
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(http.calls).toHaveLength(2);
    http.release.resolve();
    await expect(Promise.all([first, second])).resolves.toEqual(
      expect.arrayContaining(["new-a", "new-b"]),
    );
  });

  it("lets one refresh waiter abort without cancelling another", async () => {
    const storage = new MemoryStorage({ "user-123": record({ expiresAtEpochMs: 1 }) });
    const http = new Http([
      response(200, { access_token: "new", expires_in: 3600, token_type: "Bearer" }),
    ]);
    http.pause = true;
    const client = makeClient({ storage, http });
    const firstController = new AbortController();
    const first = client.accessToken(context("user-123", { signal: firstController.signal }));
    await http.entered.promise;
    const second = client.accessToken(context());
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(http.calls).toHaveLength(1);
    firstController.abort(new Error("abort-secret"));
    await expect(first).rejects.toThrow("OAuth operation cancelled");
    let secondSettled = false;
    void second.then(
      () => {
        secondSettled = true;
      },
      () => {
        secondSettled = true;
      },
    );
    await Promise.resolve();
    expect(secondSettled).toBe(false);
    http.release.resolve();
    await expect(second).resolves.toBe("new");
  });

  it("aborts the shared refresh when its last waiter detaches", async () => {
    const storage = new MemoryStorage({ "user-123": record({ expiresAtEpochMs: 1 }) });
    const http = new Http();
    http.pause = true;
    const controller = new AbortController();
    const pending = makeClient({ storage, http }).accessToken(
      context("user-123", { signal: controller.signal }),
    );
    await http.entered.promise;
    controller.abort(new Error("abort-secret"));
    await expect(pending).rejects.toThrow("OAuth operation cancelled");
    await http.aborted.promise;
  });

  it("aborts and reaps a refresh whose persistence exceeds its owned deadline", async () => {
    vi.useFakeTimers();
    try {
      const storage = new PausingSaveStorage({
        "user-123": record({ accessToken: "old", expiresAtEpochMs: 1 }),
      });
      const http = new Http([
        response(200, { access_token: "new", expires_in: 3600, token_type: "Bearer" }),
      ]);
      const pending = makeClient({ storage, http }).accessToken(context());
      await storage.saveEntered.promise;
      const rejected = expect(pending).rejects.toThrow("OAuth operation timed out");

      await vi.advanceTimersByTimeAsync(30_000);

      await storage.saveReaped.promise;
      await rejected;
      expect(http.deadlines).toEqual([130_000]);
      expect(storage.records.get("user-123")?.tokens.accessToken).toBe("old");
    } finally {
      vi.useRealTimers();
    }
  });

  it("detaches a short-deadline waiter without cancelling a longer waiter", async () => {
    vi.useFakeTimers();
    try {
      const storage = new MemoryStorage({ "user-123": record({ expiresAtEpochMs: 1 }) });
      const http = new Http([
        response(200, { access_token: "new", expires_in: 3600, token_type: "Bearer" }),
      ]);
      http.pause = true;
      const client = makeClient({ storage, http });
      const longer = client.accessToken(context());
      await http.entered.promise;
      const shorter = client.accessToken(context("user-123", { deadlineMonotonicMs: 100_001 }));
      const timedOut = expect(shorter).rejects.toThrow("OAuth operation timed out");
      await vi.advanceTimersByTimeAsync(2);
      await timedOut;
      expect(http.calls).toHaveLength(1);
      http.release.resolve();
      await expect(longer).resolves.toBe("new");
    } finally {
      vi.useRealTimers();
    }
  });

  it("deletes invalid_grant instead of consenting", async () => {
    const storage = new MemoryStorage({ "user-123": record({ expiresAtEpochMs: 1 }) });
    const http = new Http([response(400, { error: "invalid_grant" })]);
    await expect(makeClient({ storage, http }).accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });
    expect(storage.records.has("user-123")).toBe(false);
  });

  it("deletes refresh scope drift and requires explicit reconnect", async () => {
    const storage = new MemoryStorage({
      "user-123": record({ expiresAtEpochMs: 1 }),
    });
    const http = new Http([
      response(200, {
        access_token: "new",
        expires_in: 3600,
        token_type: "Bearer",
        scope: "scope/a",
      }),
    ]);
    await expect(makeClient({ storage, http }).accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
      reason_code: "gmail_scope_drift",
    });
    expect(storage.records.has("user-123")).toBe(false);
  });

  it("finishes a scope-drift delete before a new connect can save", async () => {
    const storage = new PausingDeleteStorage({
      "user-123": record({ grantedScopes: ["scope/a"] }),
    });
    const http = new Http([
      response(200, {
        access_token: "new",
        refresh_token: "new-refresh",
        expires_in: 3600,
        token_type: "Bearer",
        scope: "scope/a scope/b",
      }),
    ]);
    const client = makeClient({ storage, http });
    const stale = client.accessToken(context());
    await storage.deleteEntered.promise;
    const reconnect = client.connect("user-123", new AbortController().signal);
    await Promise.resolve();
    expect(http.calls).toEqual([]);
    storage.releaseDelete.resolve();
    await expect(stale).rejects.toMatchObject({ error_code: "INTEGRATION_AUTH_REQUIRED" });
    await reconnect;
    expect(storage.records.get("user-123")?.tokens.accessToken).toBe("new");
  });

  it.each([new Error("abort-secret"), "abort-secret", { secret: "abort-secret" }])(
    "redacts arbitrary abort reason %#",
    async (reason) => {
      const controller = new AbortController();
      controller.abort(reason);
      let captured: unknown;
      try {
        await makeClient({ storage: new MemoryStorage() }).accessToken(
          context("user-123", { signal: controller.signal }),
        );
      } catch (error) {
        captured = error;
      }
      expect(String(captured) + inspect(captured) + JSON.stringify(captured)).not.toContain(
        "abort-secret",
      );
    },
  );

  it("connects through fixed endpoint with PKCE and closes callback", async () => {
    const storage = new MemoryStorage();
    const callback = new Callback();
    const browser = vi.fn(
      async (_url: string, _signal: AbortSignal, _deadlineMonotonicMs: number) => {},
    );
    const http = new Http([
      response(200, {
        access_token: "access",
        refresh_token: "refresh",
        expires_in: 3600,
        token_type: "Bearer",
        scope: "scope/b scope/a",
      }),
    ]);
    await makeClient({ storage, callback, browser, http }).connect(
      "user-123",
      new AbortController().signal,
    );
    expect(callback.closed).toBe(true);
    const url = new URL(browser.mock.calls[0]![0]!);
    expect(url.origin + url.pathname).toBe("https://accounts.google.com/o/oauth2/v2/auth");
    const verifier = Buffer.from(Uint8Array.from({ length: 64 }, (_, index) => index)).toString(
      "base64url",
    );
    const challenge = createHash("sha256").update(verifier, "ascii").digest("base64url");
    expect(url.searchParams.get("code_challenge")).toBe(challenge);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(http.calls[0]?.[0]).toBe("https://oauth2.googleapis.com/token");
    expect(http.calls[0]?.[1]).toMatchObject({ code_verifier: verifier });
    expect(http.calls[0]?.[1]).not.toHaveProperty("client_secret");
  });

  it("blocks access to the old token until the active connect saves", async () => {
    const storage = new MemoryStorage({ "user-123": record({ accessToken: "old" }) });
    const http = new Http([
      response(200, {
        access_token: "new",
        refresh_token: "new-refresh",
        expires_in: 3600,
        token_type: "Bearer",
        scope: "scope/a scope/b",
      }),
    ]);
    http.pause = true;
    const client = makeClient({ storage, http });
    const connecting = client.connect("user-123", new AbortController().signal);
    await http.entered.promise;

    await expect(client.accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });

    http.release.resolve();
    await connecting;
    await expect(client.accessToken(context())).resolves.toBe("new");
  });

  it("restores the old token and releases the slot after connect fails", async () => {
    const storage = new MemoryStorage({ "user-123": record({ accessToken: "old" }) });
    const client = makeClient({ storage, http: new Http([response(400, "")]) });

    await expect(client.connect("user-123", new AbortController().signal)).rejects.toThrow(
      "OAuth operation failed",
    );

    expect(slotCount(client)).toBe(0);
    await expect(client.accessToken(context())).resolves.toBe("old");
    expect(slotCount(client)).toBe(0);
  });

  it("restores the old token and releases the slot after connect is cancelled", async () => {
    const storage = new MemoryStorage({ "user-123": record({ accessToken: "old" }) });
    const http = new Http();
    http.pause = true;
    const client = makeClient({ storage, http });
    const controller = new AbortController();
    const connecting = client.connect("user-123", controller.signal);
    await http.entered.promise;
    controller.abort(new Error("abort-secret"));

    await expect(connecting).rejects.toThrow("OAuth operation cancelled");

    expect(slotCount(client)).toBe(0);
    await expect(client.accessToken(context())).resolves.toBe("old");
    expect(slotCount(client)).toBe(0);
  });

  it("disconnects without client id and persists ambiguous revocation", async () => {
    const storage = new MemoryStorage({ "user-123": record() });
    const http = new Http([response(503, "private-provider-body")]);
    const client = makeClient({ storage, http, clientId: "" });
    await expect(client.disconnect("user-123", new AbortController().signal)).resolves.toEqual({
      localState: "revocation_pending",
      remoteRevoked: false,
    });
    expect(storage.records.get("user-123")?.state).toBe("revocation_pending");
    await expect(
      client.disconnect("user-123", new AbortController().signal, { forceLocal: true }),
    ).resolves.toEqual({ localState: "deleted", remoteRevoked: false });
    expect(storage.records.has("user-123")).toBe(false);
  });

  it("uses internal cleanup after confirmed revoke even when the caller aborts", async () => {
    const controller = new AbortController();
    class CancellingHttp extends Http {
      override async postForm(
        endpoint: string,
        form: Readonly<Record<string, string>>,
        signal: AbortSignal,
        deadlineMonotonicMs: number,
      ): Promise<OAuthResponse> {
        const result = await super.postForm(endpoint, form, signal, deadlineMonotonicMs);
        controller.abort(new Error("abort-secret"));
        return result;
      }
    }
    const storage = new MemoryStorage({ "user-123": record() });
    const client = makeClient({
      storage,
      clientId: "",
      http: new CancellingHttp([response(200, "")]),
    });
    await expect(client.disconnect("user-123", controller.signal)).resolves.toEqual({
      localState: "deleted",
      remoteRevoked: true,
    });
    expect(storage.records.has("user-123")).toBe(false);
  });

  it("keeps old tokens blocked while connect waits for disconnect", async () => {
    const storage = new MemoryStorage({ "user-123": record() });
    const http = new Http([
      response(200, ""),
      response(200, {
        access_token: "new",
        refresh_token: "new-refresh",
        expires_in: 3600,
        token_type: "Bearer",
        scope: "scope/a scope/b",
      }),
    ]);
    http.pause = true;
    const browser = vi.fn(
      async (_url: string, _signal: AbortSignal, _deadlineMonotonicMs: number) => {},
    );
    const client = makeClient({ storage, http, browser });
    const disconnect = client.disconnect("user-123", new AbortController().signal);
    await http.entered.promise;
    const reconnect = client.connect("user-123", new AbortController().signal);
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(browser).not.toHaveBeenCalled();
    await expect(client.accessToken(context())).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_REQUIRED",
    });
    http.release.resolve();
    await expect(disconnect).resolves.toEqual({ localState: "deleted", remoteRevoked: true });
    await reconnect;
    await expect(client.accessToken(context())).resolves.toBe("new");
  });
});
