/**
 * Tests for MockProvider's reply / toolCall options.
 */
import { describe, it, expect } from "vitest";
import { MockProvider } from "../src/providers/mock";

describe("MockProvider options", () => {
  it("reply returns literal text", async () => {
    const p = new MockProvider({ reply: "hello world" });
    const r = await p.generate([{ role: "user", content: "hi" }], []);
    expect(r.content).toBe("hello world");
    expect(r.toolCalls).toEqual([]);
  });

  it("toolCall returns a named call with no content", async () => {
    const p = new MockProvider({
      toolCall: { name: "ping", args: { x: 1 } },
    });
    const r = await p.generate([{ role: "user", content: "hi" }], []);
    expect(r.content).toBe("");
    expect(r.toolCalls).toHaveLength(1);
    expect(r.toolCalls[0]!.name).toBe("ping");
    expect(r.toolCalls[0]!.args).toEqual({ x: 1 });
  });

  it("toolCall falls through to terminal text after a tool result", async () => {
    const p = new MockProvider({
      toolCall: { name: "ping", args: { x: 1 } },
    });
    const r = await p.generate(
      [
        { role: "user", content: "hi" },
        { role: "tool", content: "{}", name: "ping" },
      ],
      [],
    );
    expect(r.content).toBeTruthy();
    expect(r.toolCalls).toEqual([]);
  });

  it("reply + toolCall throws", () => {
    expect(
      () =>
        new MockProvider({
          reply: "x",
          toolCall: { name: "y", args: {} },
        }),
    ).toThrow();
  });

  it("default behavior unchanged when no options", async () => {
    const p = new MockProvider();
    const r = await p.generate([{ role: "user", content: "hi" }], []);
    expect(r.content).toBeTruthy();
  });

  it("reply stream yields a single chunk", async () => {
    const p = new MockProvider({ reply: "hello world" });
    const chunks: { delta: string; toolCalls: { name: string }[] }[] = [];
    for await (const c of p.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(c);
    }
    expect(chunks).toHaveLength(1);
    expect(chunks[0]!.delta).toBe("hello world");
    expect(chunks[0]!.toolCalls).toEqual([]);
  });

  it("toolCall stream yields one call chunk then returns", async () => {
    const p = new MockProvider({
      toolCall: { name: "ping", args: { x: 1 } },
    });
    const chunks: { delta: string; toolCalls: { name: string }[] }[] = [];
    for await (const c of p.generateStream([{ role: "user", content: "hi" }], [])) {
      chunks.push(c);
    }
    expect(chunks).toHaveLength(1);
    expect(chunks[0]!.delta).toBe("");
    expect(chunks[0]!.toolCalls[0]!.name).toBe("ping");
  });
});
