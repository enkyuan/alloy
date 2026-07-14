/**
 * Regression test for the echo registry template.
 *
 * functionTool falls back to `handler.name || "tool"` when `meta.name` is
 * omitted — anonymous arrow handlers have empty .name, so two such tools
 * collide on registration. The shipped echo template MUST set explicit
 * names so a consumer running `kaji add echo` doesn't hit
 * "Tool already registered: fn.tool" on the second `.tool()` call.
 *
 * Import the shipped module directly so tests and registry typechecking cover
 * the implementation consumers receive.
 */
import { describe, it, expect } from "vitest";
import * as z from "zod";
import { AgentBuilder, InMemoryEventStore, functionTool } from "@/index";
import { MockProvider } from "@/providers/mock";
import { say, shout } from "../registry/echo/index";

describe("echo registry template", () => {
  it("the shipped echo tools set explicit names and namespaces", () => {
    // Lock the contract: omitting these in the template is a known footgun
    // because anonymous arrow handlers have an empty .name and functionTool
    // falls back to "tool", colliding on registration.
    expect(say.spec.name).toBe("say");
    expect(shout.spec.name).toBe("shout");
    expect(say.namespace).toBe("echo");
    expect(shout.namespace).toBe("echo");
  });

  it("registers both tools without colliding when wired the echo way", () => {
    expect(() => {
      new AgentBuilder()
        .provider(new MockProvider({ reply: "ok" }))
        .tool(say)
        .tool(shout)
        .build({ store: new InMemoryEventStore() });
    }).not.toThrow();
  });

  it("anonymous handlers without explicit names collide (regression baseline)", () => {
    // Demonstrate why explicit names matter: omitting `name` makes both
    // tools register as the same fallback name. The first .tool() succeeds;
    // the second throws.
    const a = functionTool(
      {
        description: "a",
        parameters: z.object({ message: z.string() }),
        risk: "read",
      },
      async ({ message }) => ({ message }),
    );
    const b = functionTool(
      {
        description: "b",
        parameters: z.object({ message: z.string() }),
        risk: "read",
      },
      async ({ message }) => ({ message }),
    );
    expect(() => {
      new AgentBuilder()
        .provider(new MockProvider({ reply: "ok" }))
        .tool(a)
        .tool(b)
        .build({ store: new InMemoryEventStore() });
    }).toThrow(/already registered/i);
  });
});
