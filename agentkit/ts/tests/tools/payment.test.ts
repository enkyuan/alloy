import { describe, expect, it, vi } from "vitest";
import { requestPayment } from "../../src/tools/payment";

describe("requestPayment", () => {
  it("builds a ToolSpec with name and required params", () => {
    const { spec } = requestPayment({ baseUrl: "https://api.example.com" });
    expect(spec.name).toBe("request_payment");
    const params = spec.parameters as Record<string, unknown>;
    expect(params.required).toEqual(["amount", "description"]);
    const props = params.properties as Record<string, { type: string }>;
    expect(props.amount.type).toBe("integer");
    expect(props.description.type).toBe("string");
  });

  it("posts to <baseUrl>/v1/sessions with the args as JSON", async () => {
    const fakeFetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("https://api.example.com/v1/sessions");
      expect(init?.method).toBe("POST");
      expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
      expect(JSON.parse(init?.body as string)).toEqual({ amount: 1500, description: "Coffee" });
      return new Response(JSON.stringify({ checkoutUrl: "https://pay/abc" }), { status: 200 });
    }) as unknown as typeof fetch;

    const { handler } = requestPayment({
      baseUrl: "https://api.example.com",
      fetchImpl: fakeFetch,
    });
    const ctx = { userId: "u1", db: null } as never;
    const result = await handler(ctx, { amount: 1500, description: "Coffee" });
    expect(result).toEqual({ checkoutUrl: "https://pay/abc" });
    expect(fakeFetch).toHaveBeenCalledOnce();
  });

  it("includes Authorization header when apiKey provided", async () => {
    const fakeFetch = vi.fn(async (_url: string, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer sk-test");
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;

    const { handler } = requestPayment({
      baseUrl: "https://x",
      apiKey: "sk-test",
      fetchImpl: fakeFetch,
    });
    await handler({} as never, { amount: 1, description: "x" });
  });

  it("throws on non-2xx response with the status code in the message", async () => {
    const fakeFetch = vi.fn(
      async () => new Response("nope", { status: 502, statusText: "Bad Gateway" }),
    ) as unknown as typeof fetch;

    const { handler } = requestPayment({ baseUrl: "https://x", fetchImpl: fakeFetch });
    await expect(handler({} as never, { amount: 1, description: "x" })).rejects.toThrow(/502/);
  });
});
