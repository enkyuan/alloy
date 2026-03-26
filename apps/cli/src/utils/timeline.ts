import * as p from "@clack/prompts";
import chalk from "chalk";
import type { ScriptFile } from "../types";

export interface TimelineStep {
  id: string;
  label: string;
  status: "pending" | "running" | "success" | "error" | "skipped";
  message?: string;
  duration?: number;
}

export class Timeline {
  private steps: TimelineStep[] = [];
  private currentStepIndex: number = -1;
  private startTime: number = Date.now();

  constructor(steps: TimelineStep[]) {
    this.steps = steps;
  }

  /**
   * Create a timeline from a script file.
   */
  static async fromScript(script: ScriptFile): Promise<Timeline> {
    const steps: TimelineStep[] = [
      {
        id: "prepare",
        label: "Preparing script execution",
        status: "pending",
      },
    ];

    try {
      const { readFile } = await import("node:fs/promises");
      const content = await readFile(script.path, "utf-8");
      const lines = content.split("\n");
      const seenSteps = new Set<string>();

      // Look for step indicators in the script
      // Only match actual section headers, not function definitions
      // Pattern: echo -e "${COLOR}=== Step Name ===${NC}" or "# === Step Name ==="
      const stepPatterns = [
        /echo.*=== (.+?) ===/i, // "echo === Step Name ===" (most common in bash scripts)
        /^#\s*=== (.+?) ===/i, // "# === Step Name ==="
        /^## (.+)$/i, // "## Step Name"
        /^#\s*Step\s*[0-9]+[:\-]\s*(.+)$/i, // "# Step 1: Name"
      ];

      for (const line of lines) {
        for (const pattern of stepPatterns) {
          const match = line.match(pattern);
          if (match && match[1]) {
            const stepName = match[1].trim();
            // Skip if it's a common non-step pattern, function-like names, or already seen
            // Filter out function names (usually lowercase with underscores)
            const isFunctionName =
              /^[a-z_]+$/.test(stepName) && stepName.includes("_");
            if (
              !stepName.match(
                /^(set|if|then|else|fi|done|do|while|for|case|nc)$/i,
              ) &&
              !isFunctionName &&
              !seenSteps.has(stepName.toLowerCase()) &&
              stepName.length > 3 // Skip very short matches
            ) {
              seenSteps.add(stepName.toLowerCase());
              steps.push({
                id: stepName
                  .toLowerCase()
                  .replace(/\s+/g, "-")
                  .replace(/[^a-z0-9-]/g, ""),
                label: stepName,
                status: "pending",
              });
              break;
            }
          }
        }
      }
    } catch {
      // If we can't read the file, use default steps
    }

    // Always add execute and complete steps
    if (steps.length === 1) {
      steps.push({
        id: "execute",
        label: `Executing ${script.name}`,
        status: "pending",
      });
    }

    steps.push({
      id: "complete",
      label: "Completing execution",
      status: "pending",
    });

    return new Timeline(steps);
  }

  /**
   * Start the timeline display.
   */
  start(title?: string): void {
    if (title) {
      p.intro(chalk.bgBlue.black(` ${title} `));
    }
    this.render(true);
  }

  /**
   * Mark a step as running.
   */
  startStep(stepId: string, message?: string): void {
    const step = this.steps.find((s) => s.id === stepId);
    if (!step) return;

    step.status = "running";
    step.message = message;
    this.currentStepIndex = this.steps.indexOf(step);

    // Show all steps up to current (don't clear console during script execution)
    this.render(false);
  }

  /**
   * Mark a step as successful.
   */
  completeStep(stepId: string, message?: string, duration?: number): void {
    const step = this.steps.find((s) => s.id === stepId);
    if (!step) return;

    step.status = "success";
    step.message = message;
    step.duration = duration;
    // Only clear console when completing final steps
    this.render(stepId === "complete");
  }

  /**
   * Mark a step as failed.
   */
  failStep(stepId: string, message?: string): void {
    const step = this.steps.find((s) => s.id === stepId);
    if (!step) return;

    step.status = "error";
    step.message = message;
    this.render(false);
  }

  /**
   * Skip a step.
   */
  skipStep(stepId: string, reason?: string): void {
    const step = this.steps.find((s) => s.id === stepId);
    if (!step) return;

    step.status = "skipped";
    step.message = reason;
    this.render(false);
  }

  /**
   * Render the current timeline state.
   */
  render(clearConsole: boolean = false): void {
    if (clearConsole) {
      console.clear();
    }

    // Render each step
    for (let i = 0; i < this.steps.length; i++) {
      const step = this.steps[i];
      const isLast = i === this.steps.length - 1;
      const connector = isLast ? " " : "│";

      let symbol: string;
      let color: (text: string) => string;

      switch (step.status) {
        case "pending":
          symbol = "○";
          color = chalk.dim;
          break;
        case "running":
          symbol = "◐";
          color = chalk.cyan;
          break;
        case "success":
          symbol = "✓";
          color = chalk.green;
          break;
        case "error":
          symbol = "✗";
          color = chalk.red;
          break;
        case "skipped":
          symbol = "⊘";
          color = chalk.yellow;
          break;
      }

      const statusText = color(symbol);
      const labelText =
        step.status === "running"
          ? chalk.cyan(step.label)
          : step.status === "success"
            ? chalk.green(step.label)
            : step.status === "error"
              ? chalk.red(step.label)
              : step.status === "skipped"
                ? chalk.dim(step.label)
                : chalk.dim(step.label);

      const durationText = step.duration
        ? chalk.dim(` (${this.formatDuration(step.duration)})`)
        : "";
      const messageText = step.message ? chalk.dim(` - ${step.message}`) : "";

      console.log(
        `  ${color(connector)} ${statusText} ${labelText}${durationText}${messageText}`,
      );
    }
  }

  /**
   * Format duration in milliseconds.
   */
  private formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}m ${seconds}s`;
  }

  /**
   * Complete the timeline with a summary.
   */
  complete(success: boolean, totalDuration?: number): void {
    const durationText = totalDuration
      ? chalk.dim(` in ${this.formatDuration(totalDuration)}`)
      : "";

    if (success) {
      p.outro(chalk.green(`✓ Script completed successfully${durationText}`));
    } else {
      p.outro(chalk.red(`✗ Script execution failed${durationText}`));
    }
  }
}

/**
 * Parse script output to detect steps (looks for common patterns).
 */
export function parseScriptStepsFromOutput(
  output: string,
  scriptName: string,
): TimelineStep[] {
  const steps: TimelineStep[] = [];
  const lines = output.split("\n");

  // Look for common step indicators
  const stepPatterns = [
    /^=== (.+) ===$/i, // "=== Step Name ==="
    /^## (.+)$/i, // "## Step Name"
    /^# (.+)$/i, // "# Step Name"
    /^\[(.+)\]/i, // "[Step Name]"
  ];

  for (const line of lines) {
    for (const pattern of stepPatterns) {
      const match = line.match(pattern);
      if (match) {
        steps.push({
          id: match[1].toLowerCase().replace(/\s+/g, "-"),
          label: match[1].trim(),
          status: "pending",
        });
        break;
      }
    }
  }

  // If no steps found, create a default step
  if (steps.length === 0) {
    steps.push({
      id: "execute",
      label: `Executing ${scriptName}`,
      status: "pending",
    });
  }

  return steps;
}
