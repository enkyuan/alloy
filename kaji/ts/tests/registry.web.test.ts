/**
 * Tests for the web registry integration pattern.
 *
 * Validates HTML-stripping reader mode, and error on missing BRAVE_API_KEY.
 * Reconstructs key logic inline (like registry.echo.test.ts) so tests run
 * against the local source tree without the registry files needing to be
 * in tsconfig.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { functionTool, type ToolContext } from "../src/index";

const ctx: ToolContext = { userId: "_" };

function extractReadableText(html: string): { text: string; title?: string } {
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  const rawTitle = titleMatch?.[1]?.trim();
  const title = rawTitle
    ? rawTitle.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    : undefined;

  const text = html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, " ")
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return { text, ...(title ? { title } : {}) };
}

function createWebFetch() {
  return functionTool(
    {
      name: "fetch",
      namespace: "web",
      description: "Fetch a URL and extract readable text (reader mode).",
      parameters: z.object({ url: z.string().url() }),
      risk: "read",
    },
    async ({ url }) => {
      const resp = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; KajiBot/1.0)" },
      });
      const html = await resp.text();
      const { text, title } = extractReadableText(html);
      return { url, text, ...(title ? { title } : {}) };
    },
  );
}

function createWebSearch(braveApiKey?: string) {
  return functionTool(
    {
      name: "search",
      namespace: "web",
      description: "Web search via Brave Search API.",
      parameters: z.object({ query: z.string(), count: z.number().default(5) }),
      risk: "read",
    },
    async ({ query, count }) => {
      const apiKey = braveApiKey ?? process.env["BRAVE_API_KEY"];
      if (!apiKey) {
        throw new Error("BRAVE_API_KEY not set. Get one at https://brave.com/search/api/");
      }
      const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}`;
      const resp = await fetch(url, {
        headers: { "X-Subscription-Token": apiKey, Accept: "application/json" },
      });
      if (!resp.ok) {
        throw new Error(`Brave Search API error: ${resp.status} ${resp.statusText}`);
      }
      const data = (await resp.json()) as {
        web?: { results?: { title: string; url: string; description: string }[] };
      };
      const results = (data.web?.results ?? []).map(({ title, url, description }) => ({
        title,
        url,
        description,
      }));
      return { results };
    },
  );
}

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

    const tool = createWebFetch();
    const result = await tool.handler(ctx, { url: "https://example.com" });

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

    const tool = createWebFetch();
    const result = await tool.handler(ctx, { url: "https://example.com" });

    expect(result["title"]).toBe("My Great Page");
  });

  it("normalizes whitespace in stripped content", async () => {
    const html = "<p>  lots   of   whitespace  </p>";

    mockFetch.mockResolvedValueOnce({
      text: async () => html,
    } as Partial<Response>);

    const tool = createWebFetch();
    const result = await tool.handler(ctx, { url: "https://example.com" });
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

    const tool = createWebSearch(/* no key */);
    await expect(tool.handler(ctx, { query: "test query", count: 5 })).rejects.toThrow(
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

    const tool = createWebSearch("test-api-key");
    const result = await tool.handler(ctx, { query: "hello", count: 1 });

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
});
