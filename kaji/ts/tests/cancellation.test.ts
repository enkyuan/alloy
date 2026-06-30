import { describe, expect, it, vi } from "vitest";

import { CancellationToken } from "@/runtime/cancellation";
import { OpenAIProvider } from "@/providers/openai";
import { AnthropicProvider } from "@/providers/anthropic";

describe("CancellationToken", () => {
  it("starts not cancelled with a non-aborted signal", () => {
    const t = new CancellationToken();
    expect(t.isCancelled).toBe(false);
    expect(t.signal.aborted).toBe(false);
  });

  it("cancel() flips both isCancelled and signal.aborted", () => {
    const t = new CancellationToken();
    t.cancel();
    expect(t.isCancelled).toBe(true);
    expect(t.signal.aborted).toBe(true);
  });

  it("cancel() is idempotent", () => {
    const t = new CancellationToken();
    t.cancel();
    t.cancel();
    expect(t.isCancelled).toBe(true);
  });

  it("throwIfCancelled raises after cancel", () => {
    const t = new CancellationToken();
    expect(() => t.throwIfCancelled()).not.toThrow();
    t.cancel();
    expect(() => t.throwIfCancelled()).toThrow(/cancelled/i);
  });

  it("notifies AbortSignal listeners synchronously on cancel", () => {
    const t = new CancellationToken();
    const fired = vi.fn();
    t.signal.addEventListener("abort", fired);
    t.cancel();
    expect(fired).toHaveBeenCalledOnce();
  });
});

describe("OpenAIProvider AbortSignal plumbing", () => {
  it("passes cancellationToken.signal to the OpenAI client on generate()", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok", tool_calls: null } }],
    });
    (provider as unknown as { client: unknown }).client = {
      chat: { completions: { create } },
    };

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });

  it("passes signal on generateStream() too", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const token = new CancellationToken();
    async function* empty() {} // eslint-disable-line @typescript-eslint/no-empty-function
    const create = vi.fn().mockResolvedValue(empty());
    (provider as unknown as { client: unknown }).client = {
      chat: { completions: { create } },
    };

    const iter = provider.generateStream([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });
    // Drain so the inner create() actually runs.
    for await (const _ of iter) {
      void _;
    }

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });
});

describe("AnthropicProvider AbortSignal plumbing", () => {
  it("passes cancellationToken.signal to the Anthropic client on generate()", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({ content: [{ type: "text", text: "ok" }] });
    (provider as unknown as { client: unknown }).client = {
      messages: { create },
    };

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });
});
