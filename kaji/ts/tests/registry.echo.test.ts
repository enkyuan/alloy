/**
 * Regression test for the echo registry template.
 *
 * functionTool falls back to `handler.name || "tool"` when `meta.name` is
 * omitted — anonymous arrow handlers have empty .name, so two such tools
 * collide on registration. The shipped echo template MUST set explicit
 * names so a consumer running `kaji add echo` doesn't hit
 * "Tool already registered: fn.tool" on the second `.tool()` call.
 *
 * Echo.ts itself is a consumer template (imports `@kaji/sdk` which only
 * resolves once installed), so we reconstruct its config here and exercise
 * the same code path against the local source tree.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { AgentBuilder, EventBus, InMemoryEventStore, functionTool } from "@/index";
import { MockProvider } from "@/providers/mock";

const __dirname = dirname(fileURLToPath(import.meta.url));
// Read from the TS-native registry (kaji/ts/registry/echo/index.ts)
const ECHO_TS_SOURCE = readFileSync(join(__dirname, "..", "registry", "echo", "index.ts"), "utf8");

describe("echo registry template", () => {
  it("the shipped echo.ts sets explicit names so tools don't collide", () => {
    // Lock the contract: omitting these in the template is a known footgun
    // because anonymous arrow handlers have an empty .name and functionTool
    // falls back to "tool", colliding on registration.
    expect(ECHO_TS_SOURCE).toContain('name: "say"');
    expect(ECHO_TS_SOURCE).toContain('name: "shout"');
    expect(ECHO_TS_SOURCE).toContain('namespace: "echo"');
  });

  it("registers both tools without colliding when wired the echo way", () => {
    const say = functionTool(
      {
        name: "say",
        namespace: "echo",
        description: "say",
        parameters: z.object({ message: z.string() }),
      },
      async ({ message }) => ({ message }),
    );
    const shout = functionTool(
      {
        name: "shout",
        namespace: "echo",
        description: "shout",
        parameters: z.object({ message: z.string() }),
      },
      async ({ message }) => ({ message: message.toUpperCase() }),
    );
    expect(() => {
      new AgentBuilder()
        .provider(new MockProvider({ reply: "ok" }))
        .tool(say)
        .tool(shout)
        .build({ bus: new EventBus(), store: new InMemoryEventStore() });
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
      },
      async ({ message }) => ({ message }),
    );
    const b = functionTool(
      {
        description: "b",
        parameters: z.object({ message: z.string() }),
      },
      async ({ message }) => ({ message }),
    );
    expect(() => {
      new AgentBuilder()
        .provider(new MockProvider({ reply: "ok" }))
        .tool(a)
        .tool(b)
        .build({ bus: new EventBus(), store: new InMemoryEventStore() });
    }).toThrow(/already registered/i);
  });
});
