import { Buffer } from "node:buffer";

import { describe, expect, it } from "vitest";

import { type ToolExecutionContext } from "kaji-sdk";
import {
  IntegrationAuthRequiredError,
  IntegrationPolicyError,
  IntegrationRateLimitedError,
  type BoundedResponse,
  type FixedOriginRequester,
} from "kaji-sdk/integrations";
import { GmailClient } from "../registry/gmail/client";

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
    if (response.transport_error === "connection") throw new Error("private connection detail");
    return {
      status: response.status as number,
      headers: Object.freeze({ ...(response.headers as Record<string, string> | undefined) }),
      bytes: new TextEncoder().encode(JSON.stringify(response.json)),
    };
  }
}

function b64url(text: string): string {
  return Buffer.from(text).toString("base64url");
}

function client(
  responses: readonly Readonly<Record<string, unknown>>[],
  options: { tokenFor?: () => Promise<unknown>; sleeps?: number[] } = {},
): { gmail: GmailClient; http: ScriptedRequester } {
  const http = new ScriptedRequester(responses);
  const sleep = async (delayMs: number): Promise<void> => {
    options.sleeps?.push(delayMs);
  };
  const gmail = new GmailClient(
    {
      tokenFor: (options.tokenFor ?? (async () => "ya29.token")) as () => Promise<string>,
      http,
    },
    { sleep, monotonicNow: () => 0 },
  );
  return { gmail, http };
}

describe("GmailClient", () => {
  it("normalizes and bounds list_messages", async () => {
    const { gmail, http } = client([
      {
        status: 200,
        json: {
          messages: [
            { id: "abc123", threadId: "thread1" },
            { id: "def456", threadId: "thread2" },
          ],
          resultSizeEstimate: 2,
          nextPageToken: "should-be-dropped",
        },
      },
    ]);
    const result = await gmail.listMessages(context(), { query: "from:alice", maxResults: 5 });
    expect(result).toEqual({
      messages: [
        { id: "abc123", thread_id: "thread1" },
        { id: "def456", thread_id: "thread2" },
      ],
      result_size_estimate: 2,
    });
    expect(http.requests[0]!.path_and_query).toBe(
      "/gmail/v1/users/me/messages?maxResults=5&q=from%3Aalice",
    );
  });

  it("decodes the text/plain body in get_message", async () => {
    const { gmail } = client([
      {
        status: 200,
        json: {
          id: "abc123",
          threadId: "thread1",
          snippet: "hello there",
          payload: {
            headers: [
              { name: "From", value: "alice@example.com" },
              { name: "Subject", value: "Hi" },
              { name: "X-Noise", value: "dropped" },
            ],
            mimeType: "multipart/alternative",
            parts: [
              { mimeType: "text/html", body: { data: b64url("<p>ignored</p>") } },
              { mimeType: "text/plain", body: { data: b64url("plain body") } },
            ],
          },
        },
      },
    ]);
    const result = await gmail.getMessage(context(), { messageId: "abc123" });
    expect(result).toEqual({
      id: "abc123",
      thread_id: "thread1",
      snippet: "hello there",
      headers: { from: "alice@example.com", subject: "Hi" },
      body: "plain body",
      body_truncated: false,
    });
  });

  it("returns ids and sends raw in send_message", async () => {
    const raw = b64url("From: me@example.com\r\nTo: you@example.com\r\n\r\nHi");
    const { gmail, http } = client([{ status: 200, json: { id: "sent1", threadId: "thread9" } }]);
    const result = await gmail.sendMessage(context(), { raw });
    expect(result).toEqual({ id: "sent1", thread_id: "thread9" });
    expect(http.requests[0]!.method).toBe("POST");
    expect(http.requests[0]!.path_and_query).toBe("/gmail/v1/users/me/messages/send");
    expect(JSON.parse(http.requests[0]!.body!)).toEqual({ raw });
  });

  it("maps a transport failure on send to an unknown mutation", async () => {
    const raw = b64url("From: me@example.com\r\n\r\nHi");
    const { gmail } = client([{ transport_error: "connection" }]);
    await expect(gmail.sendMessage(context(), { raw })).rejects.toMatchObject({
      reason_code: "gmail_mutation_unknown",
    });
  });

  it("maps a 5xx on send to an unknown mutation", async () => {
    const raw = b64url("From: me@example.com\r\n\r\nHi");
    const { gmail } = client([{ status: 500, json: {} }]);
    await expect(gmail.sendMessage(context(), { raw })).rejects.toMatchObject({
      reason_code: "gmail_mutation_unknown",
    });
  });

  it("rejects an invalid message id with a policy error", async () => {
    const { gmail } = client([]);
    await expect(gmail.getMessage(context(), { messageId: "not/a/valid/id" })).rejects.toBeInstanceOf(
      IntegrationPolicyError,
    );
  });

  it("rejects non-base64url raw with a policy error", async () => {
    const { gmail } = client([]);
    await expect(gmail.sendMessage(context(), { raw: "!!! not base64 !!!" })).rejects.toBeInstanceOf(
      IntegrationPolicyError,
    );
  });

  it("surfaces auth-required on 401", async () => {
    const { gmail } = client([{ status: 401, json: {} }]);
    await expect(gmail.listMessages(context(), {})).rejects.toBeInstanceOf(
      IntegrationAuthRequiredError,
    );
  });

  it("surfaces auth-required when tokenFor returns a non-string", async () => {
    const { gmail } = client([{ status: 200, json: { messages: [] } }], {
      tokenFor: async () => null,
    });
    await expect(gmail.listMessages(context(), {})).rejects.toBeInstanceOf(
      IntegrationAuthRequiredError,
    );
  });

  it("retries a rate-limited GET once when Retry-After allows", async () => {
    const sleeps: number[] = [];
    const { gmail, http } = client(
      [
        { status: 429, headers: { "retry-after": "1" }, json: {} },
        { status: 200, json: { messages: [{ id: "abc123", threadId: "thread1" }] } },
      ],
      { sleeps },
    );
    const result = await gmail.listMessages(context(), {});
    expect(result).toEqual({ messages: [{ id: "abc123", thread_id: "thread1" }] });
    expect(sleeps).toEqual([1000]);
    expect(http.requests).toHaveLength(2);
  });

  it("does not retry a rate-limited send (mutation)", async () => {
    const raw = b64url("From: me@example.com\r\n\r\nHi");
    const { gmail, http } = client([{ status: 429, headers: { "retry-after": "1" }, json: {} }]);
    await expect(gmail.sendMessage(context(), { raw })).rejects.toBeInstanceOf(
      IntegrationRateLimitedError,
    );
    expect(http.requests).toHaveLength(1);
  });
});
