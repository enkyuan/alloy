import { mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { MCP_UNAVAILABLE_MESSAGE, runMcp } from "../../src/commands/mcp.js";

describe("mcp command", () => {
  it("reports that MCP setup is deferred without writing config", () => {
    const previousExitCode = process.exitCode;
    process.exitCode = undefined;
    const dir = mkdtempSync(join(tmpdir(), "kaji-mcp-"));
    const messages: string[] = [];

    const rc = runMcp((message) => messages.push(message));

    expect(rc).toBe(1);
    expect(process.exitCode).toBe(1);
    expect(messages.join("\n")).toContain("not shipped");
    expect(messages.join("\n")).toContain("kaji gen");
    expect(readdirSync(dir)).toEqual([]);
    expect(MCP_UNAVAILABLE_MESSAGE).not.toContain("mcp-server");
    process.exitCode = previousExitCode;
  });
});
