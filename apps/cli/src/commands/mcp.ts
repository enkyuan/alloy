import { Command } from "commander";

export const MCP_UNAVAILABLE_MESSAGE =
  "Kaji MCP setup is not shipped in @kaji/cli yet.\n" +
  "Use `kaji gen` to generate tools today. MCP server support is planned separately.";

export function runMcp(log: (message: string) => void = console.error): number {
  log(MCP_UNAVAILABLE_MESSAGE);
  process.exitCode = 1;
  return 1;
}

export const mcp = new Command("mcp").description("explain MCP setup availability").action(() => {
  runMcp();
});
