/**
 * Tests for the web registry integration pattern.
 *
 * Validates HTML-stripping reader mode and missing BRAVE_API_KEY behavior by
 * importing the implementation consumers receive.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolExecutionContext } from "@/index";
import { createWebIntegration } from "../registry/web/index";

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

describe("web integration: fetch (reader mode)", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strips HTML tags and returns readable text", async () => {
    const html = `<!DOCTYPE html>
<html>
  <head><title>Test Page</title></head>
  <body>
    <h1>Hello World</h1>
    <p>This is <strong>some</strong> text.</p>
    <script>alert("ignored")</script>
  </body>
</html>`;

    mockFetch.mockResolvedValueOnce({
      text: async () => html,
    } as Partial<Response>);

    const { fetch: tool } = createWebIntegration();
    const result = await tool.handler({ url: "https://example.com" }, ctx);

    expect(result["url"]).toBe("https://example.com");
    const text = result["text"] as string;
    expect(text).toContain("Hello World");
    expect(text).toContain("This is");
    expect(text).toContain("some");
    expect(text).not.toContain("<h1>");
    expect(text).not.toContain("<p>");
    expect(text).not.toContain("alert");
    expect(text).not.toContain("<script>");
  });

  it("extracts the page title", async () => {
    const html = "<html><head><title>My Great Page</title></head><body>content</body></html>";

    mockFetch.mockResolvedValueOnce({
      text: async () => html,
    } as Partial<Response>);

    const { fetch: tool } = createWebIntegration();
    const result = await tool.handler({ url: "https://example.com" }, ctx);

    expect(result["title"]).toBe("My Great Page");
  });

  it("normalizes whitespace in stripped content", async () => {
    const html = "<p>  lots   of   whitespace  </p>";

    mockFetch.mockResolvedValueOnce({
      text: async () => html,
    } as Partial<Response>);

    const { fetch: tool } = createWebIntegration();
    const result = await tool.handler({ url: "https://example.com" }, ctx);
    const text = result["text"] as string;

    expect(text).toBe("lots of whitespace");
  });
});

describe("web integration: search", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env["BRAVE_API_KEY"];
  });

  it("throws a clear error when BRAVE_API_KEY is not set", async () => {
    delete process.env["BRAVE_API_KEY"];

    const { search: tool } = createWebIntegration();
    await expect(tool.handler({ query: "test query", count: 5 }, ctx)).rejects.toThrow(
      /BRAVE_API_KEY not set/i,
    );
  });

  it("calls Brave API with the provided key and returns results", async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        web: {
          results: [{ title: "Result A", url: "https://a.com", description: "desc A" }],
        },
      }),
    } as Partial<Response>);
    vi.stubGlobal("fetch", mockFetch);

    const { search: tool } = createWebIntegration({ braveApiKey: "test-api-key" });
    const result = await tool.handler({ query: "hello", count: 1 }, ctx);

    expect(result["results"]).toHaveLength(1);
    const firstResult = (result["results"] as { title: string }[])[0];
    expect(firstResult?.title).toBe("Result A");

    expect(mockFetch).toHaveBeenCalledOnce();
    const callArgs = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(callArgs[0]).toContain("q=hello");
    expect((callArgs[1]?.headers as Record<string, string>)?.["X-Subscription-Token"]).toBe(
      "test-api-key",
    );
  });

  it("applies the default count in the shipped registry handler", async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ web: { results: [] } }),
    } as Partial<Response>);
    vi.stubGlobal("fetch", mockFetch);

    const { search } = createWebIntegration({ braveApiKey: "test-api-key" });
    await search.handler({ query: "hello" }, ctx);

    expect(mockFetch).toHaveBeenCalledOnce();
    expect(mockFetch.mock.calls[0]?.[0]).toContain("q=hello&count=5");
  });
});
