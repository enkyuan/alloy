import { describe, expect, it } from "vitest";
import { streamText } from "../src/runtime/oneshot";
import type { ModelProvider, ModelResponseChunk, ProviderMessage } from "../src/providers/base";

function makeFlakyProvider(): ModelProvider {
  return {
    async generate() {
      throw new Error("unused");
    },
    async *generateStream(_messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
      yield { delta: "hi", toolCalls: [] };
      throw new Error("upstream blew up");
    },
  };
}

function makeCleanProvider(deltas: string[]): ModelProvider {
  return {
    async generate() {
      throw new Error("unused");
    },
    async *generateStream(_messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
      for (const d of deltas) yield { delta: d, toolCalls: [] };
    },
  };
}

describe("streamText rejection observability", () => {
  it("rejects toolCalls when the source stream errors, even if textStream is not iterated", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    await expect(result.toolCalls).rejects.toThrow("upstream blew up");
  });

  it("rejects text when the source stream errors, even if toolCalls is not awaited", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    await expect(result.text).rejects.toThrow("upstream blew up");
  });

  it("iterating textStream yields the delta then throws", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    const seen: string[] = [];
    await expect(async () => {
      for await (const chunk of result.textStream) seen.push(chunk);
    }).rejects.toThrow("upstream blew up");
    expect(seen).toEqual(["hi"]);
  });
});

describe("streamText happy path", () => {
  it("resolves text and toolCalls without requiring textStream iteration", async () => {
    const result = streamText({
      provider: makeCleanProvider(["a", "b", "c"]),
      messages: [{ role: "user", content: "go" }],
    });
    expect(await result.text).toBe("abc");
    expect(await result.toolCalls).toEqual([]);
  });

  it("iterating textStream yields each delta in order", async () => {
    const result = streamText({
      provider: makeCleanProvider(["a", "b", "c"]),
      messages: [{ role: "user", content: "go" }],
    });
    const seen: string[] = [];
    for await (const chunk of result.textStream) seen.push(chunk);
    expect(seen).toEqual(["a", "b", "c"]);
    expect(await result.text).toBe("abc");
  });

  it("never double-yields when drain races ahead of the iterator", async () => {
    // Regression: an earlier implementation kept a separate `queue` alongside
    // `collected`, and the await-branch unconditionally shifted from the
    // queue even after the fast `collected[cursor]` path had already
    // returned those entries. Result: chunks emitted twice.
    const result = streamText({
      provider: makeCleanProvider(["a", "b"]),
      messages: [{ role: "user", content: "go" }],
    });
    // Let drain finish before we touch the iterator.
    await result.text;
    const seen: string[] = [];
    for await (const chunk of result.textStream) seen.push(chunk);
    expect(seen).toEqual(["a", "b"]);
  });

  it("supports two independent iterators that each replay the full stream", async () => {
    // Regression: the iterator state lived in the outer closure, so two
    // concurrent iterators clobbered each other. The contract is that
    // each `for await` over textStream starts a fresh replay.
    const result = streamText({
      provider: makeCleanProvider(["a", "b", "c"]),
      messages: [{ role: "user", content: "go" }],
    });
    await result.text;
    const first: string[] = [];
    for await (const c of result.textStream) first.push(c);
    const second: string[] = [];
    for await (const c of result.textStream) second.push(c);
    expect(first).toEqual(["a", "b", "c"]);
    expect(second).toEqual(["a", "b", "c"]);
  });

  it("supports awaiting text and iterating textStream in either order", async () => {
    const result = streamText({
      provider: makeCleanProvider(["x", "y"]),
      messages: [{ role: "user", content: "go" }],
    });
    // Await text first; the eager drain should let this resolve without iteration.
    const textValue = await result.text;
    expect(textValue).toBe("xy");
    // textStream is still consumable after drain completes; buffered chunks emit.
    const seen: string[] = [];
    for await (const chunk of result.textStream) seen.push(chunk);
    expect(seen).toEqual(["x", "y"]);
  });
});
