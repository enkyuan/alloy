import { execSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { Command } from "commander";
import yoctoSpinner from "yocto-spinner";
import { getMcpConfigPath } from "../utils/mcp-paths.js";

type Tool = "cursor" | "claude-code" | "claude-desktop" | "windsurf" | "vscode" | "other";

interface McpEntry {
  command: string;
  args: string[];
}

const MCP_ARGS = ["-y", "@agentkit/cli", "mcp-server"];

function cancelled(): never {
  p.cancel("Setup cancelled.");
  process.exit(0);
}

function displayPath(filePath: string, scope: "project" | "global"): string {
  if (scope === "project") {
    return path.relative(process.cwd(), filePath) || filePath;
  }
  return filePath.replace(os.homedir(), "~");
}

function showJsonConfig(entry: McpEntry) {
  const json = JSON.stringify({ mcpServers: { agentkit: entry } }, null, 2);
  console.log(chalk.bold.white("\nAdd to your MCP configuration:\n"));
  console.log(
    json
      .split("\n")
      .map((line) => chalk.cyan(`  ${line}`))
      .join("\n"),
  );
  console.log();
}

function writeMcpConfig(configPath: string, entry: McpEntry) {
  let config: Record<string, unknown> = {};
  if (fs.existsSync(configPath)) {
    try {
      config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    } catch {
      /* start fresh */
    }
  }
  const servers = (config.mcpServers as Record<string, unknown> | undefined) ?? {};
  servers["agentkit"] = entry;
  config.mcpServers = servers;

  const dir = path.dirname(configPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
}

async function writeMcpConfigInteractive(
  tool: string,
  scope: "project" | "global",
  args: string[],
) {
  const entry: McpEntry = { command: "npx", args };
  const configPath = getMcpConfigPath(tool, scope);

  if (!configPath) {
    showJsonConfig(entry);
    return;
  }

  const display = displayPath(configPath, scope);
  const write = await p.confirm({
    message: `Write config to ${chalk.cyan(display)}?`,
    initialValue: true,
  });

  if (p.isCancel(write)) cancelled();

  if (write) {
    writeMcpConfig(configPath, entry);
    console.log(chalk.green(`\n✓ Written to ${display}`));
  } else {
    showJsonConfig(entry);
  }
}

async function setupClaudeCode(args: string[]) {
  const scope = await p.select({
    message: "Where should it be configured?",
    options: [
      {
        value: "project",
        label: "This project",
        hint: "--scope project",
      },
      {
        value: "user",
        label: "Global (all projects)",
        hint: "--scope user",
      },
    ],
  });

  if (p.isCancel(scope)) cancelled();

  const cmdParts = [
    "claude",
    "mcp",
    "add",
    "agentkit",
    "--scope",
    scope as string,
    "--",
    "npx",
    ...args,
  ];
  const cmd = cmdParts.join(" ");

  console.log(chalk.bold.white("\nRun this command:"));
  console.log(chalk.cyan(`  ${cmd}\n`));

  const run = await p.confirm({
    message: "Run it now?",
    initialValue: true,
  });

  if (p.isCancel(run)) cancelled();

  if (run) {
    const s = yoctoSpinner({
      text: "Adding MCP server to Claude Code…",
      color: "white",
    });
    s.start();
    try {
      execSync(cmd, { stdio: "pipe" });
      s.success("Added to Claude Code.");
    } catch {
      s.stop();
      console.log(chalk.yellow("⚠ Could not run the command automatically."));
      console.log(chalk.gray("  Run the command above manually."));
    }
  }
}

async function mcpAction() {
  p.intro(chalk.bold("agentkit mcp setup"));

  const tool = await p.select<Tool>({
    message: "Which AI tool?",
    options: [
      { value: "cursor", label: "Cursor" },
      { value: "claude-code", label: "Claude Code" },
      { value: "claude-desktop", label: "Claude Desktop" },
      { value: "windsurf", label: "Windsurf" },
      { value: "vscode", label: "VS Code / Copilot" },
      { value: "other", label: "Other" },
    ],
  });

  if (p.isCancel(tool)) cancelled();

  let scope: "project" | "global" = "global";

  if (
    (tool as string) === "cursor" ||
    (tool as string) === "vscode" ||
    (tool as string) === "claude-code"
  ) {
    const hintProject =
      (tool as string) === "cursor"
        ? ".cursor/mcp.json"
        : (tool as string) === "vscode"
          ? ".vscode/mcp.json"
          : "--scope project";
    const hintGlobal =
      (tool as string) === "cursor"
        ? "~/.cursor/mcp.json"
        : (tool as string) === "vscode"
          ? "user settings"
          : "--scope user";

    // For claude-code, scope selection is handled inside setupClaudeCode
    if ((tool as string) !== "claude-code") {
      const s = await p.select<"project" | "global">({
        message: "Where should it be configured?",
        options: [
          {
            value: "project",
            label: "This project",
            hint: hintProject,
          },
          {
            value: "global",
            label: "Global (all projects)",
            hint: hintGlobal,
          },
        ],
      });

      if (p.isCancel(s)) cancelled();
      scope = s as "project" | "global";
    }
  }

  if ((tool as string) === "claude-code") {
    await setupClaudeCode(MCP_ARGS);
  } else if ((tool as string) === "other") {
    const entry: McpEntry = { command: "npx", args: MCP_ARGS };
    showJsonConfig(entry);
  } else {
    await writeMcpConfigInteractive(tool as string, scope, MCP_ARGS);
  }

  console.log(chalk.gray("\nDone. Restart your AI tool to connect.\n"));
}

export const mcp = new Command("mcp")
  .description("register agentkit MCP server with your AI tool")
  .action(mcpAction);
