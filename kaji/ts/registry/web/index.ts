// This is YOUR web integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Swap Brave Search for a different search provider
//   4. Add helper tools your agent wants (e.g. screenshot, PDF extraction)
// Updates: re-run `kaji add web` to diff against the latest version we ship.

import { functionTool } from "@kaji/sdk";
import { z } from "zod";

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

export function createWebIntegration(opts?: { braveApiKey?: string }): {
  fetch: ReturnType<typeof functionTool>;
  fetch_raw: ReturnType<typeof functionTool>;
  search: ReturnType<typeof functionTool>;
} {
  const webFetch = functionTool(
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

  const webFetchRaw = functionTool(
    {
      name: "fetch_raw",
      namespace: "web",
      description: "Fetch a URL and return raw HTML/text.",
      parameters: z.object({ url: z.string().url() }),
      risk: "read",
    },
    async ({ url }) => {
      const resp = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; KajiBot/1.0)" },
      });
      const body = await resp.text();
      const contentType = resp.headers.get("content-type") ?? "text/html";
      return { url, body, contentType };
    },
  );

  const webSearch = functionTool(
    {
      name: "search",
      namespace: "web",
      description: "Web search via Brave Search API.",
      parameters: z.object({
        query: z.string(),
        count: z.number().int().min(1).max(20).default(5),
      }),
      risk: "read",
    },
    async ({ query, count }) => {
      const apiKey = opts?.braveApiKey ?? process.env["BRAVE_API_KEY"];
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

  return { fetch: webFetch, fetch_raw: webFetchRaw, search: webSearch };
}

export const {
  fetch: webFetch,
  fetch_raw: webFetchRaw,
  search: webSearch,
} = createWebIntegration();
