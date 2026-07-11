import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoundNetworkTransport, ToolExecutionContext } from "@/index";
import { createWebIntegration } from "../registry/web/index";

const ctx: ToolExecutionContext = {
  principalId: "tester",
  sessionId: "session",
  turnId: "turn",
  requestId: "request",
  traceId: "trace",
  toolCallId: "call",
  idempotencyKey: "session:call",
  signal: new AbortController().signal,
  metadata: {},
};

function integration(responses: readonly Response[], braveApiKey?: string) {
  const queue = [...responses];
  const request = vi.fn(
    async (
      _target: { readonly url: URL; readonly validatedAddresses: readonly string[] },
      _init: RequestInit & { readonly signal: AbortSignal },
    ) => queue.shift() ?? new Response("missing", { status: 500 }),
  );
  const transport: BoundNetworkTransport = { request };
  return {
    tools: createWebIntegration({
      policy: { allowedHosts: ["example.com", "api.search.brave.com"] },
      transport,
      resolver: async () => ["93.184.216.34"],
      ...(braveApiKey === undefined ? {} : { braveApiKey }),
    }),
    request,
  };
}

afterEach(() => {
  delete process.env["BRAVE_API_KEY"];
});

describe("web registry fetch tools", () => {
  it("requires both an explicit policy and bound transport", () => {
    expect(() => createWebIntegration(undefined as never)).toThrow(/policy is required/i);
    expect(() =>
      createWebIntegration({ policy: { allowedHosts: ["example.com"] } } as never),
    ).toThrow(/transport is required/i);
  });

  it("extracts readable text and a title from bounded HTML", async () => {
    const html = `<!doctype html><html><head><title>Test &amp; Page</title></head>
      <body><h1>Hello World</h1><p>This is <strong>text</strong>.</p>
      <script>alert("ignored")</script></body></html>`;
    const { tools, request } = integration([new Response(html)]);

    const result = await tools.fetch.handler({ url: "https://example.com/page" }, ctx);
    expect(result).toMatchObject({
      url: "https://example.com/page",
      title: "Test & Page",
    });
    expect(result["text"]).toContain("Hello World");
    expect(result["text"]).not.toContain("alert");
    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0]?.[0].validatedAddresses).toEqual(["93.184.216.34"]);
    expect(request.mock.calls[0]?.[1].redirect).toBe("manual");
  });

  it("returns raw bounded content and normalized content type", async () => {
    const { tools } = integration([
      new Response("plain", { headers: { "Content-Type": "text/custom" } }),
    ]);
    await expect(tools.fetch_raw.handler({ url: "https://example.com/raw" }, ctx)).resolves.toEqual(
      {
        url: "https://example.com/raw",
        body: "plain",
        contentType: "text/custom",
      },
    );
  });
});

describe("web registry Brave search", () => {
  it("fails clearly before transport when no API key is configured", async () => {
    const { tools, request } = integration([]);
    await expect(tools.search.handler({ query: "test", count: 5 }, ctx)).rejects.toThrow(
      /BRAVE_API_KEY not set/i,
    );
    expect(request).not.toHaveBeenCalled();
  });

  it("validates and returns Brave results", async () => {
    const payload = {
      web: {
        results: [{ title: "Result A", url: "https://a.example", description: "desc A" }],
      },
    };
    const { tools, request } = integration(
      [new Response(JSON.stringify(payload), { status: 200 })],
      "test-api-key",
    );
    const result = await tools.search.handler({ query: "hello", count: 1 }, ctx);

    expect(result).toEqual({ results: payload.web.results });
    const [target, init] = request.mock.calls[0]!;
    expect(target.url.href).toContain("q=hello&count=1");
    expect(new Headers(init.headers).get("x-subscription-token")).toBe("test-api-key");
  });

  it("applies the handler default count without relying on Zod mutation", async () => {
    const { tools, request } = integration(
      [new Response(JSON.stringify({ web: { results: [] } }))],
      "test-api-key",
    );
    await tools.search.handler({ query: "hello" }, ctx);
    expect(request.mock.calls[0]?.[0].url.href).toContain("q=hello&count=5");
  });

  it.each([
    ["malformed JSON", "not-json", /malformed JSON/i],
    ["non-object JSON", "[]", /non-object/i],
    ["invalid result shape", JSON.stringify({ web: { results: [{ title: 3 }] } }), /shape/i],
  ])("rejects %s", async (_label, body, message) => {
    const { tools } = integration([new Response(body)], "test-api-key");
    await expect(tools.search.handler({ query: "hello", count: 1 }, ctx)).rejects.toThrow(message);
  });

  it("surfaces non-success Brave status without parsing content", async () => {
    const { tools } = integration([new Response("denied", { status: 401 })], "test-api-key");
    await expect(tools.search.handler({ query: "hello", count: 1 }, ctx)).rejects.toThrow(
      /Brave Search API error: 401/,
    );
  });
});
