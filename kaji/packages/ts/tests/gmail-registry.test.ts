import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { ToolRegistry, type ToolExecutionContext } from "@irogane/kaji";
import type { BoundedResponse, FixedOriginRequester } from "@irogane/kaji/integrations";
import { GmailClient } from "../registry/gmail/client";
import {
  GmailIntegration,
  createSharedGmailToolBindings,
  inspectIntegration,
  type SharedGmailClient,
} from "../registry/gmail/index";

const kajiRoot = resolve(import.meta.dirname, "../../..");
const abi = JSON.parse(
  readFileSync(resolve(kajiRoot, "contracts/integrations/gmail-tool-abi-v1.json"), "utf8"),
) as { namespace: string; tools: Array<{ name: string }> };

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

class ScriptedRequester implements FixedOriginRequester {
  readonly requests: { method: string; path_and_query: string; body: string | null }[] = [];
  private readonly responses: Readonly<Record<string, unknown>>[];

  constructor(responses: readonly Readonly<Record<string, unknown>>[]) {
    this.responses = [...responses];
  }

  async request(
    pathAndQuery: string,
    init: Readonly<{ method: "GET" | "POST"; headers: unknown; body?: Uint8Array }>,
  ): Promise<BoundedResponse> {
    this.requests.push({
      method: init.method,
      path_and_query: pathAndQuery,
      body: init.body === undefined ? null : new TextDecoder().decode(init.body),
    });
    const response = this.responses.shift()!;
    return {
      status: response.status as number,
      headers: Object.freeze({ ...(response.headers as Record<string, string> | undefined) }),
      bytes: new TextEncoder().encode(JSON.stringify(response.json)),
    };
  }
}

function realIntegration(responses: readonly Readonly<Record<string, unknown>>[]): {
  integration: GmailIntegration;
  http: ScriptedRequester;
} {
  const http = new ScriptedRequester(responses);
  const client = new GmailClient(
    { tokenFor: async () => "ya29.token", http },
    { sleep: async () => {}, monotonicNow: () => 0 },
  );
  return { integration: new GmailIntegration(client), http };
}

describe("GmailIntegration registry wiring", () => {
  it("registers under the gmail namespace with exactly the ABI tool set", () => {
    const { integration } = realIntegration([]);
    const registry = new ToolRegistry();
    integration.register(registry);
    expect(
      registry
        .listSpecs()
        .map(({ name }) => name)
        .sort(),
    ).toEqual(abi.tools.map((tool) => `gmail_${tool.name}`).sort());
    expect(integration.namespace).toBe("gmail");
  });

  it("maps snake_case tool args to the client's camelCase inputs", async () => {
    const client = {
      listMessages: vi.fn(async () => ({ operation: "list_messages" })),
      getMessage: vi.fn(async () => ({ operation: "get_message" })),
      sendMessage: vi.fn(async () => ({ operation: "send_message" })),
    } satisfies SharedGmailClient;
    const ctx = context();
    const argumentsByName: Record<string, Record<string, unknown>> = {
      list_messages: { query: "from:alice", max_results: 5, page_token: "CURSOR" },
      get_message: { message_id: "abc123" },
      send_message: { raw: "cmF3" },
    };

    for (const [spec, handler] of createSharedGmailToolBindings(client)) {
      await expect(handler(argumentsByName[spec.name]!, ctx)).resolves.toEqual({
        operation: spec.name,
      });
    }

    expect(client.listMessages).toHaveBeenCalledWith(ctx, {
      query: "from:alice",
      maxResults: 5,
      pageToken: "CURSOR",
    });
    expect(client.getMessage).toHaveBeenCalledWith(ctx, { messageId: "abc123" });
    expect(client.sendMessage).toHaveBeenCalledWith(ctx, { raw: "cmF3" });
  });

  it("omits optional list_messages args when the caller does not supply them", async () => {
    const client = {
      listMessages: vi.fn(async () => ({})),
      getMessage: vi.fn(async () => ({})),
      sendMessage: vi.fn(async () => ({})),
    } satisfies SharedGmailClient;
    const bindings = createSharedGmailToolBindings(client);
    const listHandler = bindings.find(([spec]) => spec.name === "list_messages")![1];

    await listHandler({}, context());
    expect(client.listMessages).toHaveBeenCalledWith(expect.anything(), {});
  });

  it("rejects a non-object client result before it reaches the registry", async () => {
    const client = {
      listMessages: vi.fn(async () => [1, 2, 3] as unknown),
      getMessage: vi.fn(async () => ({})),
      sendMessage: vi.fn(async () => ({})),
    } satisfies SharedGmailClient;
    const listHandler = createSharedGmailToolBindings(client).find(
      ([spec]) => spec.name === "list_messages",
    )![1];

    await expect(listHandler({}, context())).rejects.toThrow(/invalid tool result/);
  });

  it("marks send_message as a non-parallel external effect", () => {
    const { integration } = realIntegration([]);
    const send = integration.tools().find(([spec]) => spec.name === "send_message")![0];
    expect(send.risk).toBe("external_effect");
    expect(send.parallel_safe).toBe(false);
  });

  it("dispatches through a real client, mapping max_results to the query", async () => {
    const { integration, http } = realIntegration([
      { status: 200, json: { messages: [{ id: "abc123", threadId: "thread1" }] } },
    ]);
    const listHandler = integration.tools().find(([spec]) => spec.name === "list_messages")![1];
    const result = await listHandler({ max_results: 5 }, context());
    expect(result).toEqual({ messages: [{ id: "abc123", thread_id: "thread1" }] });
    expect(http.requests[0]!.path_and_query).toBe("/gmail/v1/users/me/messages?maxResults=5");
  });

  it("close() runs the owned requester teardown exactly once", () => {
    let closed = 0;
    const client = {
      listMessages: vi.fn(),
      getMessage: vi.fn(),
      sendMessage: vi.fn(),
    } satisfies SharedGmailClient;
    const integration = new GmailIntegration(client, () => {
      closed += 1;
    });
    integration.close();
    integration.close();
    expect(closed).toBe(1);
  });

  it("inspectIntegration exposes specs without executing dependencies", () => {
    const names = inspectIntegration()
      .tools()
      .map(([spec]) => spec.name)
      .sort();
    expect(names).toEqual(["get_message", "list_messages", "send_message"]);
  });
});
