import * as os from "node:os";
import * as path from "node:path";

export function getMcpConfigPath(tool: string, scope: "project" | "global"): string | null {
  const home = os.homedir();
  switch (tool) {
    case "cursor":
      return scope === "global"
        ? path.join(home, ".cursor", "mcp.json")
        : path.join(process.cwd(), ".cursor", "mcp.json");
    case "claude-desktop":
      if (process.platform === "win32")
        return path.join(process.env.APPDATA || home, "Claude", "claude_desktop_config.json");
      if (process.platform === "darwin")
        return path.join(
          home,
          "Library",
          "Application Support",
          "Claude",
          "claude_desktop_config.json",
        );
      return path.join(home, ".config", "Claude", "claude_desktop_config.json");
    case "windsurf":
      return path.join(home, ".codeium", "windsurf", "mcp_config.json");
    case "vscode":
      return scope === "global" ? null : path.join(process.cwd(), ".vscode", "mcp.json");
    default:
      return null;
  }
}
