/**
 * Tests for the http registry integration pattern.
 *
 * Validates the SSRF allowlist, fetch invocation, and POST content-type
 * behaviours that kaji/ts/registry/http/index.ts ships.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolExecutionContext } from "@/index";
import { createHttpIntegration } from "../registry/http/index";

const ctx: ToolExecutionContext = {
  principalId: "_",
  sessionId: "test-session",
  turnId: "test-turn",
  requestId: "test-request",
  traceId: "test-trace",
  toolCallId: "test-call",
  idempotencyKey: "test-session:test-call",
  signal: new AbortController().signal,
  metadata: {},
};

describe("http integration: fetch", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns status and body from a successful GET", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 200,
      text: async () => "Hello, world!",
    } as Partial<Response>);

    const { fetch: tool } = createHttpIntegration();
    const result = await tool.handler({ url: "https://example.com" }, ctx);

    expect(result).toEqual({ status: 200, body: "Hello, world!" });
    expect(mockFetch).toHaveBeenCalledOnce();
    const [calledUrl] = mockFetch.mock.calls[0] as [string, ...unknown[]];
    expect(calledUrl).toBe("https://example.com");
  });

  it("SSRF block: throws when host is not in allowedHosts", async () => {
    const { fetch: tool } = createHttpIntegration({ allowedHosts: ["example.com"] });

    await expect(tool.handler({ url: "https://evil.internal" }, ctx)).rejects.toThrow(
      /SSRF protection/i,
    );

    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("SSRF pass: allows requests to whitelisted host", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 200,
      text: async () => "ok",
    } as Partial<Response>);

    const { fetch: tool } = createHttpIntegration({ allowedHosts: ["example.com"] });
    const result = await tool.handler({ url: "https://example.com/path" }, ctx);

    expect(result).toMatchObject({ status: 200 });
  });

  it("SSRF disabled: no allowedHosts allows all hosts", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 200,
      text: async () => "ok",
    } as Partial<Response>);

    const { fetch: tool } = createHttpIntegration(); // no allowedHosts
    await expect(tool.handler({ url: "https://any.internal.host" }, ctx)).resolves.toMatchObject({
      status: 200,
    });
  });
});

describe("http integration: post", () => {
  let mockFetch: ReturnType<typeof vi.fn>;
  let capturedInit: RequestInit | undefined;

  beforeEach(() => {
    capturedInit = undefined;
    mockFetch = vi.fn((_url: string, init?: RequestInit) => {
      capturedInit = init;
      return Promise.resolve({ status: 201, text: async () => '{"id":1}' } as Partial<Response>);
    });
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends JSON body with correct Content-Type header", async () => {
    const { post: tool } = createHttpIntegration();
    const result = await tool.handler(
      {
        url: "https://api.example.com/items",
        body: { name: "widget" },
      },
      ctx,
    );

    expect(result).toMatchObject({ status: 201 });
    expect(capturedInit?.method).toBe("POST");
    expect((capturedInit?.headers as Record<string, string>)?.["Content-Type"]).toBe(
      "application/json",
    );
    const sentBody = capturedInit?.body as string;
    expect(JSON.parse(sentBody)).toEqual({ name: "widget" });
  });

  it("SSRF block on post: throws when host is not in allowedHosts", async () => {
    const { post: tool } = createHttpIntegration({ allowedHosts: ["safe.example.com"] });

    await expect(tool.handler({ url: "https://evil.com/steal", body: {} }, ctx)).rejects.toThrow(
      /SSRF protection/i,
    );

    expect(mockFetch).not.toHaveBeenCalled();
  });
});
