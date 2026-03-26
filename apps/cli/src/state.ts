import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type {
  CliState,
  PersistedScriptRun,
  ScriptExecutionResult,
  ScriptFile,
} from "./types";

const CONFIG_DIRECTORY = join(homedir(), ".modal-cli");
const STATE_FILE_NAME = "state.json";

const DEFAULT_STATE: CliState = {
  recentScriptIds: [],
  executionCounts: {},
  lastRunByScript: {},
  executionHistory: [],
};

const MAX_HISTORY_ENTRIES = 100;
const MAX_RECENT_SCRIPTS = 20;

/**
 * Resolve the absolute path to the CLI state file.
 */
export function getStatePath(customBaseDir?: string): string {
  if (customBaseDir) {
    return resolve(customBaseDir, STATE_FILE_NAME);
  }
  return join(CONFIG_DIRECTORY, STATE_FILE_NAME);
}

/**
 * Load CLI state from disk. Falls back to an empty/default structure when the file
 * has not been created yet or cannot be parsed.
 */
export function loadCliState(path: string = getStatePath()): CliState {
  if (!existsSync(path)) {
    return { ...DEFAULT_STATE };
  }

  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Partial<CliState>;

    return {
      recentScriptIds: parsed.recentScriptIds ?? [],
      executionCounts: parsed.executionCounts ?? {},
      lastRunByScript: parsed.lastRunByScript ?? {},
      executionHistory: parsed.executionHistory ?? [],
      lastScriptsDir: parsed.lastScriptsDir,
    };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

/**
 * Persist CLI state to disk using an atomic write pattern.
 */
export function saveCliState(
  state: CliState,
  path: string = getStatePath(),
): void {
  const dir = dirname(path);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }

  const tempPath = `${path}.${process.pid}.tmp`;
  const payload = JSON.stringify(state, null, 2);

  writeFileSync(tempPath, `${payload}\n`, "utf-8");
  renameSync(tempPath, path);
}

/**
 * Record the outcome of a script execution in the persisted state.
 */
export function recordExecution(
  state: CliState,
  result: ScriptExecutionResult,
): CliState {
  const scriptId = result.script.id;
  const persistedRun: PersistedScriptRun = {
    scriptId,
    mode: result.mode,
    executedAt: result.finishedAt.toISOString(),
    durationMs: result.durationMs,
    exitCode: result.exitCode,
    errorMessage: result.errorMessage,
  };

  const executionCounts = {
    ...state.executionCounts,
    [scriptId]: (state.executionCounts?.[scriptId] ?? 0) + 1,
  };

  const recentScriptIds = [
    scriptId,
    ...(state.recentScriptIds ?? []).filter((id) => id !== scriptId),
  ].slice(0, MAX_RECENT_SCRIPTS);

  const existingHistory = state.executionHistory ?? [];
  const executionHistory = [persistedRun, ...existingHistory].slice(
    0,
    MAX_HISTORY_ENTRIES,
  );

  const lastRunByScript = {
    ...(state.lastRunByScript ?? {}),
    [scriptId]: persistedRun,
  };

  return {
    ...state,
    executionCounts,
    recentScriptIds,
    executionHistory,
    lastRunByScript,
  };
}

/**
 * Remember the last scripts directory the user browsed.
 */
export function rememberScriptsDir(
  state: CliState,
  dir: string | undefined,
): CliState {
  if (!dir) {
    return state;
  }
  if (state.lastScriptsDir === dir) {
    return state;
  }
  return { ...state, lastScriptsDir: dir };
}

/**
 * Merge persisted metadata back into the discovered script list.
 */
export function hydrateScriptsWithState(
  scripts: ScriptFile[],
  state: CliState,
): ScriptFile[] {
  const lastRuns = state.lastRunByScript ?? {};

  return scripts.map((script) => {
    const lastRun = lastRuns[script.id];
    if (!lastRun) {
      return script;
    }

    return {
      ...script,
      lastRunAt: new Date(lastRun.executedAt),
      lastExitCode: lastRun.exitCode ?? undefined,
    };
  });
}
