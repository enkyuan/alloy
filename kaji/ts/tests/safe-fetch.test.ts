import { describe, expect, it, vi } from "vitest";

import type { ToolExecutionContext } from "@/runtime/context";
import {
  safeRequest,
  type AddressResolver,
  type BoundNetworkTransport,
  type SafeFetchPolicy,
} from "@/integrations/safe-fetch";

const publicIpv4 = "93.184.216.34";

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

function resolver(addresses: readonly string[] = [publicIpv4]): AddressResolver {
  return vi.fn(async () => addresses);
}

function policy(overrides: Partial<SafeFetchPolicy> = {}): SafeFetchPolicy {
  return { allowedHosts: ["example.com"], ...overrides };
}

function transport(
  response: Response | ((init: RequestInit) => Promise<Response>),
): BoundNetworkTransport & { request: ReturnType<typeof vi.fn> } {
  const request = vi.fn(async (_target, init: RequestInit) =>
    typeof response === "function" ? response(init) : response,
  );
  return { request };
}

async function settlesWithin<T>(promise: Promise<T>, milliseconds = 500): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_resolve, reject) => {
        timeout = setTimeout(() => reject(new Error("operation did not settle")), milliseconds);
      }),
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

describe("safeRequest policy", () => {
  it("requires an exact host allowlist unless public internet is explicit", async () => {
    const bound = transport(new Response("ok"));
    await expect(
      safeRequest(new URL("https://sub.example.com"), {}, context(), policy(), bound, resolver()),
    ).rejects.toThrow(/explicitly allowed/i);
    expect(bound.request).not.toHaveBeenCalled();

    await expect(
      safeRequest(
        new URL("https://sub.example.com"),
        {},
        context(),
        policy({ allowPublicInternet: true }),
        bound,
        resolver(),
      ),
    ).resolves.toMatchObject({ status: 200 });
  });

  it.each(["http://example.com", "ftp://example.com/file", "https://user:secret@example.com"])(
    "rejects unsafe URL %s",
    async (url) => {
      const bound = transport(new Response("unused"));
      await expect(
        safeRequest(new URL(url), {}, context(), policy(), bound, resolver()),
      ).rejects.toThrow();
      expect(bound.request).not.toHaveBeenCalled();
    },
  );

  it("allows HTTP only when the policy explicitly opts in", async () => {
    const bound = transport(new Response("ok"));
    await expect(
      safeRequest(
        new URL("http://example.com"),
        {},
        context(),
        policy({ allowHttp: true }),
        bound,
        resolver(),
      ),
    ).resolves.toMatchObject({ status: 200 });
  });

  it.each([
    "0.0.0.0",
    "10.0.0.1",
    "100.64.0.1",
    "127.0.0.1",
    "169.254.1.1",
    "172.16.0.1",
    "192.0.2.1",
    "192.168.1.1",
    "198.18.0.1",
    "198.51.100.1",
    "203.0.113.1",
    "224.0.0.1",
    "255.255.255.255",
    "::",
    "::1",
    "::ffff:127.0.0.1",
    "64:ff9b::1",
    "100::1",
    "2001:2::1",
    "2001:db8::1",
    "2002::1",
    "3fff::1",
    "fc00::1",
    "fe80::1",
    "ff00::1",
  ])("rejects non-public resolver address %s", async (address) => {
    const bound = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy(),
        bound,
        resolver([address]),
      ),
    ).rejects.toThrow(/non-public/i);
    expect(bound.request).not.toHaveBeenCalled();
  });

  it("rejects a mixed public/private DNS answer instead of filtering it", async () => {
    const bound = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy(),
        bound,
        resolver([publicIpv4, "10.0.0.1"]),
      ),
    ).rejects.toThrow(/10\.0\.0\.1/);
  });

  it("normalizes IPv4 URL spellings before address classification", async () => {
    const bound = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://127.1"),
        {},
        context(),
        { allowedHosts: ["127.0.0.1"] },
        bound,
        resolver(),
      ),
    ).rejects.toThrow(/non-public/i);
  });

  it("rejects authority and framing headers controlled by the caller", async () => {
    const bound = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        { headers: { Host: "internal", "Content-Length": "12" } },
        context(),
        policy(),
        bound,
        resolver(),
      ),
    ).rejects.toThrow(/header is not allowed/i);
    expect(bound.request).not.toHaveBeenCalled();
  });

  it.each(["bad_host.example", "-bad.example", "bad-.example"])(
    "rejects non-LDH hostname label %s",
    async (hostname) => {
      const bound = transport(new Response("unused"));
      await expect(
        safeRequest(
          new URL("https://example.com"),
          {},
          context(),
          { allowedHosts: [hostname] },
          bound,
          resolver(),
        ),
      ).rejects.toThrow(/Invalid hostname/);
      expect(bound.request).not.toHaveBeenCalled();
    },
  );
});

describe("safeRequest transport and redirects", () => {
  it("passes all validated addresses and forces manual redirects", async () => {
    const bound = transport(
      new Response("hello", {
        status: 201,
        headers: { "Content-Type": "text/plain;charset=UTF-8", "X-Trace": "value" },
      }),
    );
    const result = await safeRequest(
      new URL("https://EXAMPLE.com./path"),
      { method: "POST", body: "body" },
      context(),
      policy(),
      bound,
      resolver([publicIpv4, publicIpv4, "2606:4700:4700::1111"]),
    );

    expect(result.status).toBe(201);
    expect(new TextDecoder().decode(result.bytes)).toBe("hello");
    expect(result.headers).toEqual({
      "content-type": "text/plain;charset=UTF-8",
      "x-trace": "value",
    });
    expect(bound.request).toHaveBeenCalledOnce();
    const [target, init] = bound.request.mock.calls[0]!;
    expect(target.url.href).toBe("https://example.com/path");
    expect(target.validatedAddresses).toEqual([publicIpv4, "2606:4700:4700::1111"]);
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("revalidates a redirect target and rejects a private destination", async () => {
    const bound = transport(
      new Response(null, { status: 302, headers: { Location: "https://internal.example/path" } }),
    );
    const resolve = vi.fn(async (hostname: string) =>
      hostname === "example.com" ? [publicIpv4] : ["10.0.0.1"],
    );
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        { allowedHosts: ["example.com", "internal.example"] },
        bound,
        resolve,
      ),
    ).rejects.toThrow(/non-public/i);
    expect(bound.request).toHaveBeenCalledOnce();
  });

  it("strips authorization and POST entity headers on a cross-origin 302", async () => {
    const bound: BoundNetworkTransport & { request: ReturnType<typeof vi.fn> } = {
      request: vi
        .fn()
        .mockResolvedValueOnce(
          new Response(null, { status: 302, headers: { Location: "https://next.example/done" } }),
        )
        .mockResolvedValueOnce(new Response("ok")),
    };
    await safeRequest(
      new URL("https://example.com/start"),
      {
        method: "POST",
        body: "payload",
        headers: { Authorization: "Bearer secret", "Content-Type": "text/plain" },
      },
      context(),
      { allowedHosts: ["example.com", "next.example"] },
      bound,
      resolver(),
    );

    const [, secondInit] = bound.request.mock.calls[1]!;
    expect(secondInit.method).toBe("GET");
    expect(secondInit.body).toBeNull();
    expect(new Headers(secondInit.headers).has("authorization")).toBe(false);
    expect(new Headers(secondInit.headers).has("content-type")).toBe(false);
  });

  it("strips built-in and declared secret headers on a cross-origin 307", async () => {
    const bound: BoundNetworkTransport & { request: ReturnType<typeof vi.fn> } = {
      request: vi
        .fn()
        .mockResolvedValueOnce(
          new Response(null, { status: 307, headers: { Location: "https://next.example/done" } }),
        )
        .mockResolvedValueOnce(new Response("ok")),
    };
    await safeRequest(
      new URL("https://example.com/start"),
      {
        method: "POST",
        body: "payload",
        headers: {
          "Content-Type": "text/plain",
          "X-Subscription-Token": "brave-secret",
          "X-Tenant-Session": "tenant-secret",
        },
      },
      context(),
      {
        allowedHosts: ["example.com", "next.example"],
        sensitiveHeaders: ["x-tenant-session"],
      },
      bound,
      resolver(),
    );

    const [, secondInit] = bound.request.mock.calls[1]!;
    const headers = new Headers(secondInit.headers);
    expect(secondInit.method).toBe("POST");
    expect(secondInit.body).toBe("payload");
    expect(headers.get("content-type")).toBe("text/plain");
    expect(headers.has("x-subscription-token")).toBe(false);
    expect(headers.has("x-tenant-session")).toBe(false);
  });

  it("does not await redirect-body cancellation cleanup", async () => {
    const cancel = vi.fn(() => new Promise<void>(() => undefined));
    const redirectBody = new ReadableStream<Uint8Array>({ cancel });
    const bound: BoundNetworkTransport = {
      request: vi
        .fn()
        .mockResolvedValueOnce(
          new Response(redirectBody, {
            status: 302,
            headers: { Location: "https://example.com/done" },
          }),
        )
        .mockResolvedValueOnce(new Response("done")),
    };

    const result = await settlesWithin(
      safeRequest(new URL("https://example.com/start"), {}, context(), policy(), bound, resolver()),
    );
    expect(new TextDecoder().decode(result.bytes)).toBe("done");
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("enforces redirect caps and malformed Location values", async () => {
    const capped = transport(new Response(null, { status: 302, headers: { Location: "/again" } }));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy({ maxRedirects: 0 }),
        capped,
        resolver(),
      ),
    ).rejects.toThrow(/redirect limit/i);

    const malformed = transport(
      new Response(null, { status: 302, headers: { Location: "https://[invalid" } }),
    );
    await expect(
      safeRequest(new URL("https://example.com"), {}, context(), policy(), malformed, resolver()),
    ).rejects.toThrow(/malformed Location/i);
  });
});

describe("safeRequest bounds and cancellation", () => {
  it("trusts the linked outer signal instead of reinterpreting its clock origin", async () => {
    const bound = transport(new Response("ok"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context({ deadlineMonotonicMs: 0 }),
        policy(),
        bound,
        resolver(),
      ),
    ).resolves.toMatchObject({ status: 200 });
    expect(bound.request).toHaveBeenCalledOnce();
  });

  it("fails a pre-cancelled context before invoking transport", async () => {
    const controller = new AbortController();
    controller.abort(new Error("caller cancelled"));
    const bound = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context({ signal: controller.signal }),
        policy(),
        bound,
        resolver(),
      ),
    ).rejects.toThrow("caller cancelled");
    expect(bound.request).not.toHaveBeenCalled();
  });

  it("composes the policy timeout into the transport signal", async () => {
    const bound = transport(
      (init) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
        }),
    );
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy({ timeoutMs: 1 }),
        bound,
        resolver(),
      ),
    ).rejects.toMatchObject({ name: "TimeoutError" });
  });

  it("bounds an uncooperative resolver and transport instead of only signalling them", async () => {
    const neverResolve: AddressResolver = async () =>
      new Promise<readonly string[]>(() => undefined);
    const unused = transport(new Response("unused"));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy({ timeoutMs: 1 }),
        unused,
        neverResolve,
      ),
    ).rejects.toMatchObject({ name: "TimeoutError" });
    expect(unused.request).not.toHaveBeenCalled();

    const uncooperative = transport(() => new Promise<Response>(() => undefined));
    await expect(
      safeRequest(
        new URL("https://example.com"),
        {},
        context(),
        policy({ timeoutMs: 1 }),
        uncooperative,
        resolver(),
      ),
    ).rejects.toMatchObject({ name: "TimeoutError" });
  });

  it("streams only through maxResponseBytes + 1 and cancels an oversized body", async () => {
    const cancel = vi.fn(() => new Promise<void>(() => undefined));
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.enqueue(new Uint8Array([3, 4]));
      },
      cancel,
    });
    const bound = transport(new Response(body));
    await expect(
      settlesWithin(
        safeRequest(
          new URL("https://example.com"),
          {},
          context(),
          policy({ maxResponseBytes: 3 }),
          bound,
          resolver(),
        ),
      ),
    ).rejects.toThrow(/maxResponseBytes/);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("cancels a pending response reader when the caller aborts", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const controller = new AbortController();
    const bound = transport(new Response(body));
    const pending = safeRequest(
      new URL("https://example.com"),
      {},
      context({ signal: controller.signal }),
      policy(),
      bound,
      resolver(),
    );
    while (bound.request.mock.calls.length === 0) {
      await new Promise<void>((resolve) => queueMicrotask(resolve));
    }
    await new Promise<void>((resolve) => setImmediate(resolve));
    controller.abort(new Error("stop body"));

    await expect(pending).rejects.toThrow("stop body");
    expect(cancel).toHaveBeenCalledOnce();
  });
});
