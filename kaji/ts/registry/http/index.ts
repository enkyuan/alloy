// This is YOUR http integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Map API errors to retry vs surrender for your ToolPlanner policy
//   4. Add helper tools your agent wants but the API doesn't have natively
// Updates: re-run `kaji add http` to diff against the latest version we ship.

import { functionTool } from "@kaji/sdk";
import { z } from "zod";

function checkSSRF(url: string, allowedHosts?: string[]): void {
  if (!allowedHosts || allowedHosts.length === 0) return;
  const hostname = new URL(url).hostname;
  if (!allowedHosts.includes(hostname)) {
    throw new Error(
      `SSRF protection: host '${hostname}' is not in allowedHosts [${allowedHosts.join(", ")}]`,
    );
  }
}

export function createHttpIntegration(opts?: { allowedHosts?: string[] }): {
  fetch: ReturnType<typeof functionTool>;
  post: ReturnType<typeof functionTool>;
  put: ReturnType<typeof functionTool>;
  delete: ReturnType<typeof functionTool>;
} {
  const allowedHosts = opts?.allowedHosts;

  const httpFetch = functionTool(
    {
      name: "fetch",
      namespace: "http",
      description: "HTTP GET a URL and return the response body.",
      parameters: z.object({
        url: z.string().url(),
        headers: z.record(z.string()).optional(),
      }),
      risk: "read",
    },
    async ({ url, headers }) => {
      checkSSRF(url, allowedHosts);
      const resp = await fetch(url, { headers });
      const body = await resp.text();
      return { status: resp.status, body };
    },
  );

  const httpPost = functionTool(
    {
      name: "post",
      namespace: "http",
      description: "HTTP POST JSON to a URL.",
      parameters: z.object({
        url: z.string().url(),
        body: z.unknown(),
        headers: z.record(z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, body, headers }) => {
      checkSSRF(url, allowedHosts);
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body),
      });
      const text = await resp.text();
      return { status: resp.status, body: text };
    },
  );

  const httpPut = functionTool(
    {
      name: "put",
      namespace: "http",
      description: "HTTP PUT JSON to a URL.",
      parameters: z.object({
        url: z.string().url(),
        body: z.unknown(),
        headers: z.record(z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, body, headers }) => {
      checkSSRF(url, allowedHosts);
      const resp = await fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body),
      });
      const text = await resp.text();
      return { status: resp.status, body: text };
    },
  );

  const httpDelete = functionTool(
    {
      name: "delete",
      namespace: "http",
      description: "HTTP DELETE a URL.",
      parameters: z.object({
        url: z.string().url(),
        headers: z.record(z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, headers }) => {
      checkSSRF(url, allowedHosts);
      const resp = await fetch(url, { method: "DELETE", headers });
      const body = await resp.text();
      return { status: resp.status, body };
    },
  );

  return { fetch: httpFetch, post: httpPost, put: httpPut, delete: httpDelete };
}

export const {
  fetch: httpFetch,
  post: httpPost,
  put: httpPut,
  delete: httpDelete,
} = createHttpIntegration();
