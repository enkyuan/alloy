// This is YOUR web integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Swap Brave Search for a different search provider
//   4. Add helper tools your agent wants (e.g. screenshot, PDF extraction)
// Updates: re-run `kaji add web` to diff against the latest version we ship.

import {
  functionTool,
  safeRequest,
  type BoundNetworkTransport,
  type SafeFetchPolicy,
  type ToolExecutionContext,
} from "@kaji/sdk";
import * as z from "zod";

export interface WebIntegrationOptions {
  readonly policy: SafeFetchPolicy;
  readonly transport: BoundNetworkTransport;
  readonly braveApiKey?: string;
  /** @internal Deterministic resolver seam for tests and pinned egress adapters. */
  readonly resolver?: (hostname: string) => Promise<readonly string[]>;
}

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

interface BraveResult {
  readonly title: string;
  readonly url: string;
  readonly description: string;
}

function braveResults(bytes: Uint8Array): BraveResult[] {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  } catch (error) {
    throw new Error("Brave Search API returned malformed JSON", { cause: error });
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Brave Search API returned a non-object response");
  }
  const web = (value as Record<string, unknown>)["web"];
  if (web === undefined) return [];
  if (typeof web !== "object" || web === null || Array.isArray(web)) {
    throw new Error("Brave Search API returned an invalid web result object");
  }
  const results = (web as Record<string, unknown>)["results"];
  if (results === undefined) return [];
  if (!Array.isArray(results)) throw new Error("Brave Search API returned invalid results");
  return results.map((result, index) => {
    if (typeof result !== "object" || result === null || Array.isArray(result)) {
      throw new Error(`Brave Search API result ${index} is not an object`);
    }
    const { title, url, description } = result as Record<string, unknown>;
    if (typeof title !== "string" || typeof url !== "string" || typeof description !== "string") {
      throw new Error(`Brave Search API result ${index} has an invalid shape`);
    }
    return { title, url, description };
  });
}

export function createWebIntegration(opts: WebIntegrationOptions): {
  fetch: ReturnType<typeof functionTool>;
  fetch_raw: ReturnType<typeof functionTool>;
  search: ReturnType<typeof functionTool>;
} {
  if (typeof opts?.policy !== "object") throw new TypeError("Web safe fetch policy is required");
  if (typeof opts.transport?.request !== "function") {
    throw new TypeError("Web bound network transport is required");
  }
  const networkPolicy: SafeFetchPolicy = {
    ...opts.policy,
    sensitiveHeaders: [...(opts.policy.sensitiveHeaders ?? []), "x-subscription-token"],
  };

  const request = async (url: string, init: RequestInit, context: ToolExecutionContext) =>
    safeRequest(new URL(url), init, context, networkPolicy, opts.transport, opts.resolver);

  const webFetch = functionTool(
    {
      name: "fetch",
      namespace: "web",
      description: "Fetch a URL and extract readable text (reader mode).",
      parameters: z.object({ url: z.string().url() }),
      risk: "read",
    },
    async ({ url }, context) => {
      const response = await request(
        url,
        {
          headers: { "User-Agent": "Mozilla/5.0 (compatible; KajiBot/1.0)" },
        },
        context,
      );
      const html = new TextDecoder().decode(response.bytes);
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
    async ({ url }, context) => {
      const response = await request(
        url,
        {
          headers: { "User-Agent": "Mozilla/5.0 (compatible; KajiBot/1.0)" },
        },
        context,
      );
      const body = new TextDecoder().decode(response.bytes);
      const contentType = response.headers["content-type"] ?? "text/html";
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
    async ({ query, count }, context) => {
      const resultCount = count ?? 5;
      const apiKey = opts.braveApiKey ?? process.env["BRAVE_API_KEY"];
      if (!apiKey) {
        throw new Error("BRAVE_API_KEY not set. Get one at https://brave.com/search/api/");
      }
      const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${resultCount}`;
      const response = await request(
        url,
        { headers: { "X-Subscription-Token": apiKey, Accept: "application/json" } },
        context,
      );
      if (response.status < 200 || response.status >= 300) {
        throw new Error(`Brave Search API error: ${response.status}`);
      }
      return { results: braveResults(response.bytes) };
    },
  );

  return { fetch: webFetch, fetch_raw: webFetchRaw, search: webSearch };
}
