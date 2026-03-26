import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  constants,
} from "node:fs";
import { access } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname } from "node:path";
import { RGBA } from "@opentui/core";
import {
  ACCENT_COLOR,
  ERROR_COLOR,
  MUTED_COLOR,
  PRIMARY_COLOR,
  SECONDARY_COLOR,
  SUCCESS_COLOR,
} from "./constants";

/**
 * Color palette for the CLI, aligned with the shared branding constants.
 */
export const palette = {
  primary: PRIMARY_COLOR,
  secondary: SECONDARY_COLOR,
  accent: ACCENT_COLOR,
  muted: MUTED_COLOR,
  success: SUCCESS_COLOR,
  error: ERROR_COLOR,
  warning: "#FACC15",
  info: "#60A5FA",
  background: "#0F172A",
  backgroundElevated: "#111827",
  backgroundFocused: "#1E293B",
  border: "#1E293B",
};

export const colors = palette;

/**
 * Convert hex color to RGBA
 */
export function hexToRGBA(hex: string): RGBA {
  return RGBA.fromHex(hex);
}

/**
 * Get color from environment or use default
 */
export function getColor(envKey: string, defaultColor: string): string {
  return process.env[envKey] || defaultColor;
}

/**
 * Format script name for display
 */
export function formatScriptName(filename: string): string {
  return filename.replace(/\.(m?js|cjs|ts|bash|zsh|sh|py)$/i, "");
}

/**
 * Get script icon based on file extension
 */
export function getScriptIcon(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase();
  const icons: Record<string, string> = {
    sh: "⚡",
    bash: "🛠",
    zsh: "✨",
    py: "🐍",
    js: "📜",
    mjs: "📜",
    cjs: "📜",
    ts: "📘",
    tsx: "🧩",
  };
  return icons[ext ?? ""] ?? "📄";
}

/**
 * Truncate text to fit width
 */
export function truncateText(text: string, maxWidth: number): string {
  if (text.length <= maxWidth) return text;
  if (maxWidth <= 1) return text.slice(0, maxWidth);
  const ellipsis = "…";
  const sliceWidth = Math.max(0, maxWidth - ellipsis.length);
  return text.slice(0, sliceWidth).trimEnd() + ellipsis;
}

/**
 * Center text within a given width
 */
export function centerText(text: string, width: number): string {
  const padding = Math.max(0, Math.floor((width - text.length) / 2));
  return " ".repeat(padding) + text;
}

export function clamp(value: number, min: number, max: number): number {
  const lower = Math.min(min, max);
  const upper = Math.max(min, max);
  const candidate = Number.isNaN(value) ? lower : value;
  return Math.min(Math.max(candidate, lower), upper);
}

/**
 * Parse command line arguments
 */
export function parseArgs(): Record<string, string | boolean> {
  const args = process.argv.slice(2);
  const parsed: Record<string, string | boolean> = {};

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (!arg.startsWith("-")) {
      continue;
    }

    const stripped = arg.replace(/^-+/, "");
    if (!stripped) {
      continue;
    }

    if (stripped.includes("=")) {
      const [key, value] = stripped.split("=", 2);
      parsed[key] = value ?? true;
      continue;
    }

    const nextArg = args[i + 1];
    if (nextArg && !nextArg.startsWith("-")) {
      parsed[stripped] = nextArg;
      i++;
      continue;
    }

    if (!arg.startsWith("--") && stripped.length > 1) {
      for (const flag of stripped) {
        parsed[flag] = true;
      }
      continue;
    }

    parsed[stripped] = true;
  }

  return parsed;
}

export function parseBooleanFlag(value: string | boolean | undefined): boolean {
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
 * Format duration in milliseconds to human-readable string
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/**
 * Check if script is executable
 */
export async function isExecutable(path: string): Promise<boolean> {
  try {
    await access(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Get terminal size
 */
export function getTerminalSize(): { width: number; height: number } {
  return {
    width: process.stdout.columns || 80,
    height: process.stdout.rows || 24,
  };
}

export function shortenPath(fullPath: string): string {
  const home = homedir();
  const cwd = process.cwd();

  if (fullPath.startsWith(cwd)) {
    return "." + fullPath.slice(cwd.length);
  }

  if (fullPath.startsWith(home)) {
    return fullPath.replace(home, "~");
  }

  return fullPath;
}

export function readJsonFile<T = unknown>(path: string, fallback: T): T {
  try {
    if (existsSync(path)) {
      return JSON.parse(readFileSync(path, "utf-8")) as T;
    }
  } catch {
    // Ignore invalid JSON and fall back
  }

  return fallback;
}

export function writeJsonFile(path: string, data: unknown): void {
  const dir = dirname(path);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }

  writeFileSync(path, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

export function formatTimestamp(value?: Date | string): string {
  if (!value) {
    return "";
  }
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelativeTime(value?: Date | string): string {
  if (!value) {
    return "";
  }
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const diffSeconds = (date.getTime() - Date.now()) / 1000;
  const divisions: ReadonlyArray<{
    amount: number;
    unit: Intl.RelativeTimeFormatUnit;
  }> = [
    { amount: 60, unit: "second" },
    { amount: 60, unit: "minute" },
    { amount: 24, unit: "hour" },
    { amount: 7, unit: "day" },
    { amount: 4.34524, unit: "week" },
    { amount: 12, unit: "month" },
    { amount: Number.POSITIVE_INFINITY, unit: "year" },
  ];

  let duration = diffSeconds;
  for (const division of divisions) {
    if (Math.abs(duration) < division.amount) {
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
        Math.round(duration),
        division.unit,
      );
    }
    duration /= division.amount;
  }

  return "";
}
