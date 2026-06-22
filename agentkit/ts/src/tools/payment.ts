/**
 * requestPayment: a thin agentkit -> agentpay bridge.
 *
 * Posts to `${baseUrl}/v1/sessions` and returns the JSON payload. Pass a
 * custom fetchImpl in tests; in production it uses the global fetch.
 */
import type { ToolSpec, ToolHandler, ToolContext } from "./registry";

export interface RequestPaymentOptions {
  baseUrl: string;
  apiKey?: string;
  fetchImpl?: typeof fetch;
}

export interface RequestPaymentTool {
  spec: ToolSpec;
  handler: ToolHandler;
}

export function requestPayment(opts: RequestPaymentOptions): RequestPaymentTool {
  const spec: ToolSpec = {
    name: "request_payment",
    description: "Request a payment via agentpay. Returns the checkout URL.",
    parameters: {
      type: "object",
      properties: {
        amount: { type: "integer", description: "Amount in the smallest currency unit (cents)." },
        description: { type: "string", description: "Short reason shown to the payer." },
      },
      required: ["amount", "description"],
    },
    risk: "write",
  };

  const fetchImpl = opts.fetchImpl ?? globalThis.fetch;

  const handler: ToolHandler = async (_ctx: ToolContext, args: Record<string, unknown>) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (opts.apiKey) headers.Authorization = `Bearer ${opts.apiKey}`;
    const url = `${opts.baseUrl.replace(/\/$/, "")}/v1/sessions`;
    const r = await fetchImpl(url, { method: "POST", headers, body: JSON.stringify(args) });
    if (!r.ok) {
      throw new Error(`agentpay POST /v1/sessions failed: ${r.status} ${r.statusText}`);
    }
    return (await r.json()) as Record<string, unknown>;
  };

  return { spec, handler };
}
