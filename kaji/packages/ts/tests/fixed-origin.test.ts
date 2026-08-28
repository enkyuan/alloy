import { describe, expect, it, vi } from "vitest";

import type { ToolExecutionContext } from "@/runtime/context";
import { ToolExecutionError } from "@/tools/execution-errors";
import { IntegrationPolicyError, IntegrationTransportError } from "@/integrations/errors";
import {
  createGitHubRequester,
  createGmailRequester,
  fixedOriginForTest,
  type FixedOriginTestResponse,
  type FixedOriginTestTransport,
} from "@/integrations/fixed-origin";

function context(overrides: Partial<ToolExecutionContext> = {}): ToolExecutionContext {
  return {
    principalId: "tester",
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

function response(
  chunks: readonly Uint8Array[] = [new TextEncoder().encode("ok")],
  overrides: Partial<FixedOriginTestResponse> = {},
): FixedOriginTestResponse {
  return {
    status: 200,
    headers: [],
    body: (async function* () {
      yield* chunks;
    })(),
    close: vi.fn(),
    ...overrides,
  };
}

function transport(
  value: FixedOriginTestResponse | ((url: URL) => Promise<FixedOriginTestResponse>),
): FixedOriginTestTransport & { request: ReturnType<typeof vi.fn> } {
  return {
    request: vi.fn(async (url) => (typeof value === "function" ? value(url) : value)),
  };
}

describe("fixed-origin preflight", () => {
  it.each([
    "",
    "https://evil.example/x",
    "//evil.example/x",
    "\\\\evil.example\\x",
    "/x#secret",
    "/%2f%2fevil.example/x",
    "/%5cevil.example/x",
  ])("rejects unsafe path %s before transport", async (pathAndQuery) => {
    const direct = transport(response());
    const requester = fixedOriginForTest("https://api.github.com", direct);
    await expect(
      requester.request(pathAndQuery, { method: "GET", headers: {} }, context()),
    ).rejects.toBeInstanceOf(IntegrationPolicyError);
    expect(direct.request).not.toHaveBeenCalled();
  });

  it("keeps URL-looking query data on the fixed origin", async () => {
    const direct = transport(response());
    const requester = fixedOriginForTest("https://api.github.com", direct);
    await requester.request(
      "/search/code?q=https%3A%2F%2Fevil.example",
      { method: "GET", headers: {} },
      context(),
    );
    expect(direct.request.mock.calls[0]![0].toString()).toBe(
      "https://api.github.com/search/code?q=https%3A%2F%2Fevil.example",
    );
  });

  it.each(["host", "content-length", "connection", "proxy-authorization"])(
    "rejects forbidden %s before transport",
    async (header) => {
      const direct = transport(response());
      const requester = fixedOriginForTest("https://api.github.com", direct);
      await expect(
        requester.request(
          "/x",
          { method: "GET", headers: { [header]: "private-value" } },
          context(),
        ),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      expect(direct.request).not.toHaveBeenCalled();
    },
  );
});

describe("fixed-origin response boundaries", () => {
  it.each(["/next", "https://evil.example/next"])(
    "rejects redirect %s as a non-certified transport error",
    async (location) => {
      const direct = transport(response([], { status: 302, headers: [["location", location]] }));
      const requester = fixedOriginForTest("https://api.github.com", direct);
      const caught = await requester
        .request(
          "/start",
          { method: "POST", headers: {}, body: new TextEncoder().encode("payload") },
          context(),
        )
        .catch((error: unknown) => error);
      expect(caught).toBeInstanceOf(IntegrationTransportError);
      expect(caught).not.toBeInstanceOf(ToolExecutionError);
      expect(caught).toMatchObject({ error_code: "INTEGRATION_REDIRECT_REJECTED" });
      expect(String(caught)).not.toContain(location);
    },
  );

  it.each([
    [[["content-length", "bad"]] as const],
    [[["content-length", "33"]] as const],
    [Array.from({ length: 65 }, (_, index) => [`x-${index}`, "v"] as const)],
    [[["x-large", "x".repeat(64 * 1024)]] as const],
  ])("rejects malformed or oversized headers", async (headers) => {
    const direct = transport(response([], { headers }));
    const requester = fixedOriginForTest("https://api.github.com", direct, {
      maxResponseBytes: 32,
    });
    await expect(
      requester.request("/x", { method: "GET", headers: {} }, context()),
    ).rejects.toMatchObject({ error_code: "INTEGRATION_RESPONSE_LIMIT" });
  });

  it("closes after reading one byte over the body limit", async () => {
    const close = vi.fn();
    const direct = transport(response([new Uint8Array(16), new Uint8Array(17)], { close }));
    const requester = fixedOriginForTest("https://api.github.com", direct, {
      maxResponseBytes: 32,
    });
    await expect(
      requester.request("/x", { method: "GET", headers: {} }, context()),
    ).rejects.toMatchObject({ error_code: "INTEGRATION_RESPONSE_LIMIT" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("cancels a response stream that never finishes", async () => {
    const abort = new AbortController();
    const close = vi.fn();
    const entered = Promise.withResolvers<void>();
    const body: AsyncIterable<Uint8Array> = {
      [Symbol.asyncIterator]: () => {
        entered.resolve();
        return { next: () => new Promise<IteratorResult<Uint8Array>>(() => undefined) };
      },
    };
    const direct = transport(response([], { body, close }));
    const requester = fixedOriginForTest("https://api.github.com", direct);
    const pending = requester.request(
      "/x",
      { method: "GET", headers: {} },
      context({ signal: abort.signal }),
    );
    await entered.promise;
    abort.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("applies the smaller context deadline", async () => {
    const close = vi.fn();
    const body: AsyncIterable<Uint8Array> = {
      [Symbol.asyncIterator]: () => ({
        next: () => new Promise<IteratorResult<Uint8Array>>(() => undefined),
      }),
    };
    const direct = transport(response([], { body, close }));
    const requester = fixedOriginForTest("https://api.github.com", direct, { timeoutMs: 10_000 });
    await expect(
      requester.request(
        "/x",
        { method: "GET", headers: {} },
        context({ deadlineMonotonicMs: performance.now() + 1 }),
      ),
    ).rejects.toMatchObject({ name: "TimeoutError" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("closes a response that arrives after the smaller context deadline", async () => {
    vi.useFakeTimers();
    try {
      const late = Promise.withResolvers<FixedOriginTestResponse>();
      const close = vi.fn();
      const direct = transport(async () => late.promise);
      const requester = fixedOriginForTest("https://api.github.com", direct, {
        timeoutMs: 10_000,
      });
      const pending = requester.request(
        "/x",
        { method: "GET", headers: {} },
        context({ deadlineMonotonicMs: performance.now() + 1 }),
      );
      const rejected = expect(pending).rejects.toMatchObject({ name: "TimeoutError" });

      await vi.advanceTimersByTimeAsync(1);
      await rejected;
      expect(close).not.toHaveBeenCalled();

      late.resolve(response([], { close }));
      await direct.request.mock.results[0]!.value;
      expect(close).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("provider-fixed production factories", () => {
  it("closes its owned transport exactly once and rejects reuse", async () => {
    const close = vi.fn();
    const direct = { ...transport(response()), close };
    const requester = fixedOriginForTest("https://api.github.com", direct);

    requester.close();
    requester.close();

    expect(close).toHaveBeenCalledOnce();
    await expect(
      requester.request("/x", { method: "GET", headers: {} }, context()),
    ).rejects.toBeInstanceOf(IntegrationPolicyError);
    expect(direct.request).not.toHaveBeenCalled();
  });

  it("allows teardown to be retried after a transport close failure", () => {
    const close = vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("close failed");
      })
      .mockImplementationOnce(() => undefined);
    const requester = fixedOriginForTest("https://api.github.com", {
      ...transport(response()),
      close,
    });

    expect(() => requester.close()).toThrow("close failed");
    requester.close();
    requester.close();

    expect(close).toHaveBeenCalledTimes(2);
  });

  it("takes no configuration and never consults global fetch or proxy settings", async () => {
    const originalFetch = globalThis.fetch;
    const poisoned = vi.fn(async () => {
      throw new Error("global fetch used");
    });
    globalThis.fetch = poisoned as unknown as typeof fetch;
    process.env.HTTP_PROXY = "http://127.0.0.1:1";
    process.env.HTTPS_PROXY = "http://127.0.0.1:1";
    process.env.NODE_USE_ENV_PROXY = "1";
    const github = createGitHubRequester();
    const gmail = createGmailRequester();
    try {
      expect(createGitHubRequester.length).toBe(0);
      expect(createGmailRequester.length).toBe(0);
      await expect(
        github.request("", { method: "GET", headers: {} }, context()),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      await expect(
        gmail.request("", { method: "GET", headers: {} }, context()),
      ).rejects.toBeInstanceOf(IntegrationPolicyError);
      expect(poisoned).not.toHaveBeenCalled();

      const direct = transport(response());
      await expect(
        fixedOriginForTest("https://api.github.com", direct).request(
          "/x",
          { method: "GET", headers: {} },
          context(),
        ),
      ).resolves.toMatchObject({ status: 200 });
    } finally {
      github.close();
      gmail.close();
      globalThis.fetch = originalFetch;
      delete process.env.HTTP_PROXY;
      delete process.env.HTTPS_PROXY;
      delete process.env.NODE_USE_ENV_PROXY;
    }
  });
});
