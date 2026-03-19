import {
  createCliRenderer,
  SelectRenderable,
  SelectRenderableEvents,
  TextRenderable,
  type KeyEvent,
} from "@opentui/core";
import { spawn } from "child_process";
import type { CliOptions } from "../types";
import { colors, formatDuration, getTerminalSize } from "../utils";
import { loadScriptsFromDirectory } from "../scripts";
import {
  loadCliState,
  saveCliState,
  recordExecution,
  rememberScriptsDir,
  getStatePath,
} from "../state";
import { DEFAULT_SCRIPTS_DIR, LOGO_LINES, MENU_FOOTER } from "../constants";
import type { ScriptFile, MenuResult, ScriptExecutionResult } from "../types";
import { setupCommand } from "./setup";
import { startupCommand } from "./startup";
import { basename } from "node:path";

interface RunOptions extends CliOptions {
  dir?: string;
  debug?: boolean | string;
}

/**
 * Present the interactive script picker menu.
 */
async function presentMenu(
  scripts: ScriptFile[],
  options: { debug: boolean },
): Promise<MenuResult> {
  const renderer = await createCliRenderer({
    consoleOptions: {
      startInDebugMode: options.debug,
    },
  });

  const { width: terminalWidth, height: terminalHeight } = getTerminalSize();
  const selectorWidth = Math.max(60, Math.min(terminalWidth - 8, 100));
  const selectorHeight = Math.max(
    4,
    Math.min(terminalHeight - 8, Math.max(scripts.length * 2, 4)),
  );

  // Calculate positions - leave room for logo at top
  const logoHeight = LOGO_LINES.length;
  const logoTop = 1;
  const subtitleTop = logoTop + logoHeight + 1;
  const selectorTop = subtitleTop + 2;
  const footerTop = selectorTop + selectorHeight + 1;

  const left = Math.max(2, Math.floor((terminalWidth - selectorWidth) / 2));
  const logoLeft = 2; // Left-align the logo

  // Render ASCII logo - each line as a separate TextRenderable
  LOGO_LINES.forEach((line, index) => {
    const logoLine = new TextRenderable(renderer, {
      id: `logo-line-${index}`,
      content: line,
      fg: colors.primary,
      position: "absolute",
      left: logoLeft,
      top: logoTop + index,
    });
    renderer.root.add(logoLine);
  });

  const subtitle = new TextRenderable(renderer, {
    id: "subtitle",
    content: `${scripts.length} script${scripts.length === 1 ? "" : "s"} available`,
    fg: colors.secondary,
    position: "absolute",
    left,
    top: subtitleTop,
  });

  const selector = new SelectRenderable(renderer, {
    id: "script-selector",
    width: selectorWidth,
    height: selectorHeight,
    options: scripts.map((script) => ({
      name:
        script.name.length > 0
          ? script.name[0].toUpperCase() + script.name.slice(1)
          : script.name,
      description: script.description,
    })),
    position: "absolute",
    left,
    top: selectorTop,
  });

  const footer = new TextRenderable(renderer, {
    id: "footer",
    content: `  ${MENU_FOOTER}`,
    fg: colors.muted,
    position: "absolute",
    left,
    top: footerTop,
  });

  renderer.root.add(subtitle);
  renderer.root.add(selector);
  renderer.root.add(footer);

  selector.focus();

  return new Promise<MenuResult>((resolve) => {
    let finished = false;

    const finalize = (result: MenuResult) => {
      if (finished) {
        return;
      }
      finished = true;
      try {
        renderer.stop();
      } catch {
        // Ignore stop errors, renderer might already be stopped.
      }
      try {
        renderer.destroy();
      } catch {
        // Ignore destruction errors, renderer might already be destroyed.
      }
      resolve(result);
    };

    selector.on(SelectRenderableEvents.ITEM_SELECTED, (index: number) => {
      const script = scripts[index];
      finalize({ type: "script", script });
    });

    renderer.keyInput.on("keypress", (key: KeyEvent) => {
      if (key.name === "q" || (key.ctrl && key.name === "c")) {
        finalize({ type: "exit" });
        return;
      }

      if (key.name === "?" || key.name === "h") {
        console.log("\nKeyboard Shortcuts:");
        console.log("  ↑/k      - Navigate up");
        console.log("  ↓/j      - Navigate down");
        console.log("  enter    - Execute script");
        console.log("  q        - Quit");
        console.log("  ?/h      - Toggle help");
        console.log("  ctrl+c   - Quit immediately\n");
      }
    });

    try {
      renderer.start();
    } catch (error) {
      console.error("Renderer error:", error);
      finalize({ type: "exit" });
    }
  });
}

/**
 * Execute the selected script.
 */
async function runScript(
  script: ScriptFile,
  statePath: string,
): Promise<ScriptExecutionResult> {
  const startedAt = new Date();
  const scriptBase = basename(script.path);

  if (scriptBase === "setup.sh") {
    return runInternalCommand(script, statePath, setupCommand);
  }
  if (scriptBase === "startup.sh") {
    return runInternalCommand(script, statePath, startupCommand);
  }

  return new Promise((resolve, reject) => {
    const child = spawn(script.path, [], {
      stdio: ["inherit", "pipe", "pipe"],
      shell: true,
    });

    // Capture stdout
    child.stdout?.on("data", (data: Buffer) => {
      process.stdout.write(data);
    });

    // Capture stderr
    child.stderr?.on("data", (data: Buffer) => {
      process.stderr.write(data);
    });

    child.on("close", async (code) => {
      const finishedAt = new Date();
      const durationMs = finishedAt.getTime() - startedAt.getTime();

      console.log("\n  " + "─".repeat(60));
      if (code === 0) {
        console.log(`\n  ✓ Completed in ${formatDuration(durationMs)}`);
      } else {
        console.log(
          `\n  ✗ Exited with code ${code ?? "unknown"} after ${formatDuration(durationMs)}`,
        );
      }

      const result: ScriptExecutionResult = {
        script,
        mode: "execute",
        startedAt,
        finishedAt,
        durationMs,
        exitCode: code,
        succeeded: code === 0,
      };

      // Update state
      const state = loadCliState(statePath);
      const updatedState = recordExecution(state, result);
      saveCliState(updatedState, statePath);

      await waitForKeyPress("\n  Press any key to return to the menu...");
      resolve(result);
    });

    child.on("error", async (error) => {
      const finishedAt = new Date();
      const durationMs = finishedAt.getTime() - startedAt.getTime();

      console.log("\n  " + "─".repeat(60));
      console.error(`\n  ✗ Failed to execute script: ${error.message}`);
      console.log(`  Duration before failure: ${formatDuration(durationMs)}`);

      const result: ScriptExecutionResult = {
        script,
        mode: "execute",
        startedAt,
        finishedAt,
        durationMs,
        exitCode: null,
        succeeded: false,
        errorMessage: error.message,
      };

      // Update state
      const state = loadCliState(statePath);
      const updatedState = recordExecution(state, result);
      saveCliState(updatedState, statePath);

      await waitForKeyPress("\n  Press any key to return to the menu...");
      reject(error);
    });
  });
}

async function runInternalCommand(
  script: ScriptFile,
  statePath: string,
  handler: () => Promise<void>,
): Promise<ScriptExecutionResult> {
  const startedAt = new Date();

  try {
    await handler();
    const finishedAt = new Date();
    const durationMs = finishedAt.getTime() - startedAt.getTime();

    const result: ScriptExecutionResult = {
      script,
      mode: "execute",
      startedAt,
      finishedAt,
      durationMs,
      exitCode: 0,
      succeeded: true,
    };

    const state = loadCliState(statePath);
    const updatedState = recordExecution(state, result);
    saveCliState(updatedState, statePath);

    await waitForKeyPress("\n  Press any key to return to the menu...");
    return result;
  } catch (error) {
    const finishedAt = new Date();
    const durationMs = finishedAt.getTime() - startedAt.getTime();

    const result: ScriptExecutionResult = {
      script,
      mode: "execute",
      startedAt,
      finishedAt,
      durationMs,
      exitCode: null,
      succeeded: false,
      errorMessage: error instanceof Error ? error.message : "Unknown error",
    };

    const state = loadCliState(statePath);
    const updatedState = recordExecution(state, result);
    saveCliState(updatedState, statePath);

    await waitForKeyPress("\n  Press any key to return to the menu...");
    return result;
  }
}

/**
 * Utility for pausing until the user presses any key.
 */
async function waitForKeyPress(message: string): Promise<void> {
  process.stdout.write(`${message}\n`);

  if (!process.stdin.isTTY) {
    console.clear();
    return;
  }

  return new Promise((resolve) => {
    const stdin = process.stdin;
    const handleData = () => {
      if (stdin.isTTY) {
        stdin.setRawMode(false);
      }
      stdin.pause();
      stdin.removeListener("data", handleData);
      console.clear();
      resolve();
    };

    stdin.resume();
    if (stdin.isTTY) {
      stdin.setRawMode(true);
    }
    stdin.once("data", handleData);
  });
}

function parseBooleanFlag(value: string | boolean | undefined): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (
      normalized === "false" ||
      normalized === "0" ||
      normalized === "no" ||
      normalized === "off"
    ) {
      return false;
    }
    if (
      normalized === "true" ||
      normalized === "1" ||
      normalized === "yes" ||
      normalized === "on"
    ) {
      return true;
    }
  }
  return false;
}

/**
 * Run command - interactive script launcher.
 */
export async function runCommand(options: RunOptions): Promise<void> {
  const scriptsDir =
    options.dir || process.env.MODAL_SCRIPTS_DIR || DEFAULT_SCRIPTS_DIR;

  const statePath = getStatePath();
  let state = loadCliState(statePath);
  state = rememberScriptsDir(state, scriptsDir);
  saveCliState(state, statePath);

  while (true) {
    const scripts = await loadScriptsFromDirectory(scriptsDir, state);

    if (scripts.length === 0) {
      console.error(`\n  ✗ No scripts found in: ${scriptsDir}\n`);
      console.error(
        "  Set MODAL_SCRIPTS_DIR environment variable or use --dir flag\n",
      );
      console.error(
        "  Example: MODAL_SCRIPTS_DIR=/path/to/scripts modal-cli run\n",
      );
      process.exit(1);
    }

    const result = await presentMenu(scripts, {
      debug: parseBooleanFlag(options.debug),
    });

    if (result.type === "exit") {
      break;
    }

    if (result.type === "script") {
      try {
        await runScript(result.script, statePath);
        // Reload state after execution
        state = loadCliState(statePath);
      } catch (error) {
        console.error("Script execution failed:", error);
        await waitForKeyPress("\n  Press any key to continue...");
      }
    }
  }

  console.clear();
  console.log("\n  👋 Goodbye!\n");
}
