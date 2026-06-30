/**
 * Default approval handler for dev / REPL use. Prints the tool name, risk,
 * and arguments to `output` (stdout by default), then reads a single line
 * from `input` (stdin by default). Returns `true` only on `"y"` (case-
 * insensitive). Anything else, including empty input or EOF, returns `false`.
 *
 * Production hosts should implement their own ApprovalHandler that talks
 * to a web modal, Slack, etc. This handler exists so the approval flow is
 * wireable end-to-end without writing a custom prompt.
 *
 * Concurrency: prompts against the same input stream are serialized through
 * a per-stream mutex so concurrent approval gates from `Promise.all`-style
 * scatter-gather do not interleave reads — a single 'y' cannot satisfy two
 * pending prompts. Use distinct streams or distinct handler factories if
 * you want parallelism.
 */
import { createInterface } from "node:readline";
import type { ApprovalHandler } from "@/tools/planner";

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

/**
 * Per-stream FIFO of pending acquires. Async chaining: each acquire awaits
 * the previous one's release. WeakMap so streams are garbage collected when
 * the host drops them.
 */
const streamLocks = new WeakMap<NodeJS.ReadableStream, Promise<void>>();

export function cliApprovalHandler(opts: CliApprovalOptions = {}): ApprovalHandler {
  return async (name, args, risk) => {
    const input = opts.input ?? process.stdin;
    const output = opts.output ?? process.stdout;
    const labelSuffix = opts.label ? ` [${opts.label}]` : "";

    // Reserve our slot in the per-stream queue synchronously — read+write of
    // streamLocks happens with no intervening await so concurrent callers
    // serialize on the most recent registered promise.
    const prior = streamLocks.get(input) ?? Promise.resolve();
    let release!: () => void;
    const turn = new Promise<void>((resolve) => {
      release = resolve;
    });
    streamLocks.set(
      input,
      prior.then(() => turn),
    );
    await prior;

    // Short-circuit if a prior prompt drained and ended the stream while we
    // were queued: createInterface against an already-ended readable may
    // never emit 'line' OR 'close', which would hang this approval forever.
    // Treat that as EOF (reject the call) so the agent loop stays live.
    const ended =
      (input as { readableEnded?: boolean }).readableEnded === true ||
      (input as { destroyed?: boolean }).destroyed === true;
    if (ended) {
      output.write(`\nApproval requested${labelSuffix}: ${name}\n`);
      output.write(`  risk: ${risk ?? "unknown"}\n`);
      output.write(`  arguments: ${JSON.stringify(args)}\n`);
      output.write("  approve? [y/N]: (input ended) -> N\n");
      release();
      return false;
    }

    const rl = createInterface({ input, output });
    try {
      output.write(`\nApproval requested${labelSuffix}: ${name}\n`);
      output.write(`  risk: ${risk ?? "unknown"}\n`);
      output.write(`  arguments: ${JSON.stringify(args)}\n`);
      const answer = await new Promise<string>((resolve) => {
        // Resolve on either a line or stream close (EOF). EOF without a
        // line defaults to "" so the handler returns false — never hang.
        const onLine = (line: string) => {
          rl.off("close", onClose);
          resolve(line);
        };
        const onClose = () => {
          rl.off("line", onLine);
          resolve("");
        };
        rl.once("line", onLine);
        rl.once("close", onClose);
        output.write("  approve? [y/N]: ");
      });
      return answer.trim().toLowerCase() === "y";
    } finally {
      rl.close();
      release();
    }
  };
}
