// This is YOUR http integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Map API errors to retry vs surrender for your ToolPlanner policy
//   4. Add helper tools your agent wants but the API doesn't have natively
// Updates: re-run `kaji add http` to diff against the latest version we ship.

import {
  functionTool,
  safeRequest,
  type BoundNetworkTransport,
  type SafeFetchPolicy,
  type ToolExecutionContext,
} from "@kaji/sdk";
import * as z from "zod";

export interface HttpIntegrationOptions {
  readonly policy: SafeFetchPolicy;
  readonly transport: BoundNetworkTransport;
  /** @internal Deterministic resolver seam for tests and pinned egress adapters. */
  readonly resolver?: (hostname: string) => Promise<readonly string[]>;
}

export function createHttpIntegration(opts: HttpIntegrationOptions): {
  fetch: ReturnType<typeof functionTool>;
  post: ReturnType<typeof functionTool>;
  put: ReturnType<typeof functionTool>;
  delete: ReturnType<typeof functionTool>;
} {
  if (typeof opts?.policy !== "object") throw new TypeError("HTTP safe fetch policy is required");
  if (typeof opts.transport?.request !== "function") {
    throw new TypeError("HTTP bound network transport is required");
  }

  const request = async (
    url: string,
    init: RequestInit,
    context: ToolExecutionContext,
  ): Promise<{ status: number; body: string }> => {
    const response = await safeRequest(
      new URL(url),
      init,
      context,
      opts.policy,
      opts.transport,
      opts.resolver,
    );
    return { status: response.status, body: new TextDecoder().decode(response.bytes) };
  };

  const httpFetch = functionTool(
    {
      name: "fetch",
      namespace: "http",
      description: "HTTP GET a URL and return the response body.",
      parameters: z.object({
        url: z.string().url(),
        headers: z.record(z.string(), z.string()).optional(),
      }),
      risk: "read",
    },
    async ({ url, headers }, context) => request(url, { headers }, context),
  );

  const httpPost = functionTool(
    {
      name: "post",
      namespace: "http",
      description: "HTTP POST JSON to a URL.",
      parameters: z.object({
        url: z.string().url(),
        body: z.unknown(),
        headers: z.record(z.string(), z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, body, headers }, context) =>
      request(
        url,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify(body),
        },
        context,
      ),
  );

  const httpPut = functionTool(
    {
      name: "put",
      namespace: "http",
      description: "HTTP PUT JSON to a URL.",
      parameters: z.object({
        url: z.string().url(),
        body: z.unknown(),
        headers: z.record(z.string(), z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, body, headers }, context) =>
      request(
        url,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify(body),
        },
        context,
      ),
  );

  const httpDelete = functionTool(
    {
      name: "delete",
      namespace: "http",
      description: "HTTP DELETE a URL.",
      parameters: z.object({
        url: z.string().url(),
        headers: z.record(z.string(), z.string()).optional(),
      }),
      risk: "write",
    },
    async ({ url, headers }, context) => request(url, { method: "DELETE", headers }, context),
  );

  return { fetch: httpFetch, post: httpPost, put: httpPut, delete: httpDelete };
}
