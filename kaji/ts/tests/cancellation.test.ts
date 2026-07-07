import { describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";
import type OpenAI from "openai";

import { CancellationToken } from "@/runtime/cancellation";
import { TestAnthropicProvider, TestOpenAIProvider } from "./helpers/provider-clients";

function openAIClient(create: ReturnType<typeof vi.fn>): OpenAI {
  return { chat: { completions: { create } } } as unknown as OpenAI;
}

function anthropicClient(create: ReturnType<typeof vi.fn>): Anthropic {
  return { messages: { create } } as unknown as Anthropic;
}

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
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok", tool_calls: null } }],
    });
    const provider = new TestOpenAIProvider({ apiKey: "test-key" }, openAIClient(create));

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });

  it("passes signal on generateStream() too", async () => {
    const token = new CancellationToken();
    async function* empty() {} // eslint-disable-line @typescript-eslint/no-empty-function
    const create = vi.fn().mockResolvedValue(empty());
    const provider = new TestOpenAIProvider({ apiKey: "test-key" }, openAIClient(create));

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
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({ content: [{ type: "text", text: "ok" }] });
    const provider = new TestAnthropicProvider(
      { apiKey: "test-key" },
      anthropicClient(create),
    );

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });
});
