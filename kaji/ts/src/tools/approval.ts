/**
 * Default approval handler for dev / REPL use. Prints the tool name, risk,
 * and arguments to `output` (stdout by default), then reads a single line
 * from `input` (stdin by default). Approves only `"y"` (case-insensitive).
 * Anything else, including empty input or EOF, returns a rejected decision.
 *
 * Concurrency: prompts against the same input stream are serialized through
 * a per-stream mutex so concurrent approval gates from `Promise.all`-style
 * batch execution does not interleave reads — a single 'y' cannot satisfy two
 * pending prompts. Use distinct streams or distinct handler factories if
 * you want parallelism.
 */
import { createInterface } from "node:readline";
import type { TypedApprovalHandler } from "@/runtime/approval/types";

export interface CliApprovalInput {
  readonly readableEnded?: boolean;
  readonly destroyed?: boolean;
  on(event: string | symbol, listener: (...args: unknown[]) => void): this;
  once(event: string | symbol, listener: (...args: unknown[]) => void): this;
  removeListener(event: string | symbol, listener: (...args: unknown[]) => void): this;
  pause(): this;
  resume(): this;
}

export interface CliApprovalOutput {
  write(chunk: string): boolean;
}

export interface CliApprovalOptions {
  /** Defaults to process.stdin. Override in tests with a readable input. */
  input?: CliApprovalInput;
  /** Defaults to process.stdout. Override in tests with a writable output. */
  output?: CliApprovalOutput;
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
const streamLocks = new WeakMap<CliApprovalInput, Promise<void>>();

export function cliApprovalHandler(opts: CliApprovalOptions = {}): TypedApprovalHandler {
  return {
    async request(call, context) {
      const name = call.name;
      const args = context.arguments;
      const risk = context.risk;
      const input = opts.input ?? process.stdin;
      const output = opts.output ?? process.stdout;
      const readlineInput = input as unknown as NodeJS.ReadableStream;
      const readlineOutput = output as unknown as NodeJS.WritableStream;
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
        output.write(`  risk: ${risk}\n`);
        output.write(`  arguments: ${JSON.stringify(args)}\n`);
        output.write("  approve? [y/N]: (input ended) -> N\n");
        release();
        return { granted: false, code: "rejected", reason: "Approval input ended" };
      }

      const rl = createInterface({ input: readlineInput, output: readlineOutput });
      try {
        output.write(`\nApproval requested${labelSuffix}: ${name}\n`);
        output.write(`  risk: ${risk}\n`);
        output.write(`  arguments: ${JSON.stringify(args)}\n`);
        const answer = await new Promise<string | undefined>((resolve) => {
          // Resolve on either a line or stream close (EOF). EOF without a
          // line is distinguished from an explicit blank response.
          const onLine = (line: string) => {
            rl.off("close", onClose);
            resolve(line);
          };
          const onClose = () => {
            rl.off("line", onLine);
            resolve(undefined);
          };
          rl.once("line", onLine);
          rl.once("close", onClose);
          output.write("  approve? [y/N]: ");
        });
        if (answer === undefined) {
          return { granted: false, code: "rejected", reason: "Approval input ended" };
        }
        return answer.trim().toLowerCase() === "y"
          ? { granted: true, code: "approved" }
          : { granted: false, code: "rejected", reason: "Rejected by operator" };
      } finally {
        rl.close();
        release();
      }
    },
  };
}
