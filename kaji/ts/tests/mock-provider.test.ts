import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import type { ModelProvider, ModelResponseChunk, ProviderMessage } from "@/providers/base";
import { ProviderConfigError } from "@/providers/errors";
import { MockProvider } from "@/providers/mock";
import { clearProviders, getProvider, registerProvider } from "@/providers/registry";
import { CancellationError } from "@/runtime/cancellation";
import { toolSpecFromSchema } from "@/tools/registry";

afterEach(() => clearProviders());

describe("provider registry", () => {
  it("registers and retrieves by name", () => {
    const p = new MockProvider();
    registerProvider("mock", p);
    expect(getProvider("mock")).toBe(p);
  });

  it("throws on duplicate registration", () => {
    registerProvider("dup", new MockProvider());
    expect(() => registerProvider("dup", new MockProvider())).toThrow(/already registered/);
    expect(() => registerProvider("dup", new MockProvider())).toThrow(ProviderConfigError);
  });

  it("throws on unknown provider", () => {
    expect(() => getProvider("nope")).toThrow(/Unknown provider/);
    expect(() => getProvider("nope")).toThrow(ProviderConfigError);
  });
});

describe("MockProvider", () => {
  const weather = toolSpecFromSchema(
    "get_weather",
    "Look up weather",
    z.object({ city: z.string() }),
  );

  it("requests the first tool when no tool result is in history", async () => {
    const messages: ProviderMessage[] = [{ role: "user", content: "weather?" }];
    const r = await new MockProvider().generate(messages, [weather]);
    expect(r.toolCalls).toHaveLength(1);
    expect(r.toolCalls[0]?.name).toBe("get_weather");
    expect(r.content).toBe("");
  });

  it("returns text once a tool result is present", async () => {
    const messages: ProviderMessage[] = [
      { role: "user", content: "weather?" },
      {
        role: "tool",
        name: "get_weather",
        content: '{"tempF":68}',
        tool_call_id: "c1",
      },
    ];
    const r = await new MockProvider().generate(messages, [weather]);
    expect(r.toolCalls).toHaveLength(0);
    expect(r.content.length).toBeGreaterThan(0);
  });

  it("returns text immediately with no tools", async () => {
    const r = await new MockProvider().generate([{ role: "user", content: "hi" }], []);
    expect(r.toolCalls).toHaveLength(0);
  });

  it("generateStream yields one chunk equal to generate", async () => {
    const chunks: ModelResponseChunk[] = [];
    for await (const c of new MockProvider().generateStream(
      [{ role: "user", content: "hi" }],
      [],
    )) {
      chunks.push(c);
    }
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.toolCalls).toHaveLength(0);
  });

  it("satisfies the ModelProvider interface", () => {
    const p: ModelProvider = new MockProvider();
    expect(p).toBeDefined();
  });

  it("yields pre-baked deltas from streamChunks", async () => {
    const provider = new MockProvider({ streamChunks: ["hel", "lo", " wor", "ld"] });
    const seen: string[] = [];
    for await (const c of provider.generateStream([{ role: "user", content: "hi" }], [])) {
      seen.push(c.delta);
    }
    expect(seen).toEqual(["hel", "lo", " wor", "ld"]);
  });

  it("non-streaming generate returns the joined chunks as content", async () => {
    const provider = new MockProvider({ streamChunks: ["a", "b", "c"] });
    const r = await provider.generate([{ role: "user", content: "hi" }], []);
    expect(r.content).toBe("abc");
  });

  it("aborts mid-stream when the cancellation token is set", async () => {
    const provider = new MockProvider({ streamChunks: ["one", "two", "three"] });
    const token = { isCancelled: false };
    const iter = provider.generateStream([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });
    const first = await iter.next();
    expect(first.value?.delta).toBe("one");
    token.isCancelled = true;
    await expect(iter.next()).rejects.toThrow(CancellationError);
  });
});
