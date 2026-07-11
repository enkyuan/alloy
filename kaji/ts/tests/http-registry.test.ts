import { describe, expect, it, vi } from "vitest";

import type { BoundNetworkTransport, SafeFetchPolicy, ToolExecutionContext } from "@/index";
import { createHttpIntegration, type HttpIntegrationOptions } from "../registry/http/index";

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

function integration(
  response: Response = new Response("ok", { status: 200 }),
  policy: SafeFetchPolicy = { allowedHosts: ["example.com"] },
): { tools: ReturnType<typeof createHttpIntegration>; request: ReturnType<typeof vi.fn> } {
  const request = vi.fn(async () => response);
  const transport: BoundNetworkTransport = { request };
  return {
    tools: createHttpIntegration({
      policy,
      transport,
      resolver: async () => ["93.184.216.34"],
    }),
    request,
  };
}

describe("http registry integration", () => {
  it("requires both an explicit policy and a bound transport", () => {
    expect(() => createHttpIntegration(undefined as never)).toThrow(/policy is required/i);
    expect(() =>
      createHttpIntegration({ policy: { allowedHosts: ["example.com"] } } as never),
    ).toThrow(/transport is required/i);
  });

  it("routes GET through the bounded transport and decodes the bounded body", async () => {
    const { tools, request } = integration(
      new Response("Hello, world!", { status: 206, headers: { "X-Result": "partial" } }),
    );
    await expect(tools.fetch.handler({ url: "https://example.com/path" }, ctx)).resolves.toEqual({
      status: 206,
      body: "Hello, world!",
    });
    expect(request).toHaveBeenCalledOnce();
    const [target, init] = request.mock.calls[0]!;
    expect(target).toMatchObject({
      url: new URL("https://example.com/path"),
      validatedAddresses: ["93.184.216.34"],
    });
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it.each([
    ["post", "POST"],
    ["put", "PUT"],
  ] as const)("sends %s JSON with the caller context", async (toolName, method) => {
    const { tools, request } = integration(new Response('{"id":1}', { status: 201 }));
    const tool = tools[toolName];
    const result = await tool.handler(
      { url: "https://example.com/items", body: { name: "widget" } },
      ctx,
    );

    expect(result).toEqual({ status: 201, body: '{"id":1}' });
    const [, init] = request.mock.calls[0]!;
    expect(init.method).toBe(method);
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ name: "widget" });
  });

  it("routes DELETE through the same policy boundary", async () => {
    const { tools, request } = integration(new Response(null, { status: 204 }));
    await expect(
      tools.delete.handler({ url: "https://example.com/items/1" }, ctx),
    ).resolves.toEqual({ status: 204, body: "" });
    expect(request.mock.calls[0]?.[1].method).toBe("DELETE");
  });

  it("rejects a non-allowlisted host before transport", async () => {
    const { tools, request } = integration();
    await expect(tools.fetch.handler({ url: "https://evil.example" }, ctx)).rejects.toThrow(
      /explicitly allowed/i,
    );
    expect(request).not.toHaveBeenCalled();
  });

  it("enforces response byte caps through the actual tool", async () => {
    const { tools } = integration(new Response("four"), {
      allowedHosts: ["example.com"],
      maxResponseBytes: 3,
    });
    await expect(tools.fetch.handler({ url: "https://example.com" }, ctx)).rejects.toThrow(
      /maxResponseBytes/,
    );
  });

  it("preserves the factory option contract without a default unsafe instance", () => {
    const opts: HttpIntegrationOptions = {
      policy: { allowedHosts: ["example.com"] },
      transport: { request: async () => new Response("ok") },
    };
    expect(createHttpIntegration(opts).fetch.spec.risk).toBe("read");
  });
});
