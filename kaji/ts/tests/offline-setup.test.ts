import { lookup } from "node:dns";
import { lookup as lookupPromise } from "node:dns/promises";
import { get as httpGet, request as httpRequest } from "node:http";
import { get as httpsGet, request as httpsRequest } from "node:https";
import { connect, createConnection } from "node:net";

import { describe, expect, it, vi } from "vitest";

import type { ToolExecutionContext } from "@/runtime/context";
import { fixedOriginForTest, type FixedOriginTestTransport } from "@/integrations/fixed-origin";

const offline = process.env.KAJI_OFFLINE_GATE === "1";
const blocked = "KAJI offline gate blocked network access";

function context(): ToolExecutionContext {
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
  };
}

describe.runIf(offline)("offline setup", () => {
  it("blocks global fetch before dispatch", async () => {
    await expect(fetch("https://example.invalid/")).rejects.toThrow(blocked);
  });

  it.each([
    ["net.connect", () => connect(9, "127.0.0.1")],
    ["net.createConnection", () => createConnection(9, "127.0.0.1")],
    ["dns.lookup", () => lookup("example.invalid", () => undefined)],
    ["http.request", () => httpRequest("http://127.0.0.1:9")],
    ["http.get", () => httpGet("http://127.0.0.1:9")],
    ["https.request", () => httpsRequest("https://example.invalid/")],
    ["https.get", () => httpsGet("https://example.invalid/")],
  ])("blocks %s before I/O", (_name, operation) => {
    expect(operation).toThrow(blocked);
  });

  it("blocks promise DNS before I/O", async () => {
    await expect(lookupPromise("example.invalid")).rejects.toThrow(blocked);
  });

  it("allows an injected fixed-origin transport", async () => {
    const transport: FixedOriginTestTransport = {
      request: vi.fn(async () => ({
        status: 200,
        headers: [],
        body: (async function* () {
          yield new TextEncoder().encode("offline");
        })(),
        close: vi.fn(),
      })),
    };
    const requester = fixedOriginForTest("https://api.github.com", transport);
    await expect(
      requester.request("/x", { method: "GET", headers: {} }, context()),
    ).resolves.toMatchObject({ status: 200 });
    expect(transport.request).toHaveBeenCalledOnce();
  });
});
