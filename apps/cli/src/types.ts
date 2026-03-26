/**
 * Shared domain types for the Modal CLI.
 *
 * These types mirror the “describe everything up front” style used in the
 * better-icons project so that functions can compose richer return values
 * without guessing at shape downstream.
 */

/**
 * Metadata about a runnable script discovered on disk.
 */
export interface ScriptFile {
  /** Unique identifier for UI state (defaults to absolute path if not provided). */
  id: string;
  /** File name as it appears in the scripts directory. */
  name: string;
  /** Absolute file system path. */
  path: string;
  /** Path relative to the scripts root, used for grouping and display. */
  relativePath: string;
  /** Short human friendly summary surfaced in the picker. */
  description: string;
  /** Optional excerpt or inline comment shown in previews. */
  snippet?: string;
  /** Emoji or glyph shown alongside the name. */
  icon: string;
  /** Optional logical grouping (derived from subdirectories). */
  category?: string;
  /** Arbitrary tags extracted from front-matter or comments. */
  tags?: string[];
  /** When the script was last executed via the CLI. */
  lastRunAt?: Date;
  /** Exit code from the last run (undefined when never executed). */
  lastExitCode?: number;
  /** Indicates whether the script is currently executable by the OS. */
  executable: boolean;
}

/**
 * Shape returned when parsing inline metadata from the script source.
 */
export interface ScriptMetadata {
  description?: string;
  category?: string;
  tags?: string[];
  icon?: string;
  snippet?: string;
  heading?: string;
}

/**
 * Summary information shown in the footer/header of the TUI.
 */
export interface MenuNarrative {
  title: string;
  subtitle?: string;
  footerHint?: string;
}

/**
 * Domain-specific theme tokens used by the renderer.
 */
export interface Palette {
  primary: string;
  secondary: string;
  accent: string;
  muted: string;
  success: string;
  error: string;
}

/**
 * Result emitted when the interactive menu resolves.
 */
export type MenuResult =
  | { type: "script"; script: ScriptFile }
  | { type: "exit" }
  | { type: "refresh" };

/**
 * Execution mode (straight run or dry preview).
 */
export type ScriptRunMode = "execute" | "preview";

/**
 * Data captured for each script invocation.
 */
export interface ScriptExecutionResult {
  script: ScriptFile;
  mode: ScriptRunMode;
  startedAt: Date;
  finishedAt: Date;
  durationMs: number;
  exitCode: number | null;
  succeeded: boolean;
  errorMessage?: string;
  stdoutFile?: string;
  stderrFile?: string;
}

/**
 * Persisted script execution metadata saved to disk.
 */
export interface PersistedScriptRun {
  scriptId: string;
  mode: ScriptRunMode;
  executedAt: string;
  durationMs?: number;
  exitCode?: number | null;
  errorMessage?: string;
}

/**
 * Persisted CLI state (mirrors better-icons config style).
 */
export interface CliState {
  /** Directory the user last browsed. */
  lastScriptsDir?: string;
  /** Script IDs sorted by most recent usage. */
  recentScriptIds?: string[];
  /** Aggregate run counts keyed by script ID. */
  executionCounts?: Record<string, number>;
  /** Last execution summary keyed by script ID. */
  lastRunByScript?: Record<string, PersistedScriptRun>;
  /** Chronological execution log (most recent first). */
  executionHistory?: PersistedScriptRun[];
}

/**
 * Commonly accessed command-line flags (Commander passes these to actions).
 */
export interface CliOptions {
  /** Custom scripts directory (falls back to DEFAULT_SCRIPTS_DIR). */
  dir?: string;
  /** Launch the renderer with debugging overlays enabled. */
  debug?: boolean | string;
  /** When true, prints metadata as JSON instead of starting the TUI. */
  json?: boolean | string;
  /** Skip confirmation prompts where applicable. */
  yes?: boolean | string;
}

/**
 * Context object shared between discovery, rendering, and execution stages.
 */
export interface CliContext {
  options: CliOptions;
  palette: Palette;
  state: CliState;
  scriptsDir: string;
  scripts: ScriptFile[];
}
