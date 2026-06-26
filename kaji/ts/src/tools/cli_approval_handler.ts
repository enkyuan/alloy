/**
 * Default approval handler for dev / REPL use. Prints the tool name, risk,
 * and arguments to `output` (stdout by default), then reads a single line
 * from `input` (stdin by default). Returns `true` only on `"y"` (case-
 * insensitive). Anything else, including empty input, returns `false`.
 *
 * Production hosts should implement their own ApprovalHandler that talks
 * to a web modal, Slack, etc. This handler exists so the approval flow is
 * wireable end-to-end without writing a custom prompt.
 */
import { createInterface } from "node:readline";
import type { ApprovalHandler } from "./planner";

export interface CliApprovalOptions {
  /** Defaults to process.stdin. Override in tests with a Readable stream. */
  input?: NodeJS.ReadableStream;
  /** Defaults to process.stdout. Override in tests with a Writable stream. */
  output?: NodeJS.WritableStream;
  /**
   * Optional label printed in the prompt header to disambiguate concurrent
   * agents (e.g. `"agent-a"`, `"session-c1"`). Defaults to empty.
   */
  label?: string;
}

export function cliApprovalHandler(opts: CliApprovalOptions = {}): ApprovalHandler {
  return async (name, args, risk) => {
    const input = opts.input ?? process.stdin;
    const output = opts.output ?? process.stdout;
    const labelSuffix = opts.label ? ` [${opts.label}]` : "";
    const rl = createInterface({ input, output });
    try {
      output.write(`\nApproval requested${labelSuffix}: ${name}\n`);
      output.write(`  risk: ${risk ?? "unknown"}\n`);
      output.write(`  arguments: ${JSON.stringify(args)}\n`);
      const answer = await new Promise<string>((resolve) => {
        rl.question("  approve? [y/N]: ", (a) => resolve(a));
      });
      return answer.trim().toLowerCase() === "y";
    } finally {
      rl.close();
    }
  };
}
