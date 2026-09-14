/**
 * CLI entry surface for `kaji`. Exports a testable `runCli` plus a dispatch
 * table; the script-mode binary lives in `./bin.ts` so importing this module
 * from tests does not trigger `process.exit`.
 */
import { init } from "@/cli/init";
import { replay } from "@/cli/replay";
import { packageIdentity } from "@/cli/package-identity";

export interface RunOptions {
  registryRoot: string;
  /** Directory containing schema.json and index.schema.json. Defaults to registryRoot. */
  schemaRoot?: string;
  log?: (msg: string) => void;
  err?: (msg: string) => void;
  noColor?: boolean;
  verbose?: boolean;
  /** @internal Source-test seam; packaged CLI calls the pinned worker process. */
  initWorkerRunner?: (
    out: string,
    files: Readonly<Record<string, string>>,
    force: boolean,
  ) => Promise<void>;
  signal?: AbortSignal;
}

export interface Command {
  describe: string;
  usage: string;
  run(rest: string[], opts: RunOptions): Promise<number>;
}

export const COMMANDS: Record<string, Command> = {
  init: {
    describe: "Scaffold a new TypeScript Kaji project.",
    usage: "kaji init [path] [--template capability] [--yes] [--force]",
    run: (rest, opts) => init(rest, opts),
  },
  replay: {
    describe: "Pretty-print a kaji session replay log (JSONL).",
    usage:
      "kaji replay <session.jsonl> [--format tree|summary|json] [--filter <kind>] [--grep <pattern>] [--tail]",
    run: (rest, opts) => replay(rest, opts),
  },
};

function printHelp(log: (m: string) => void): void {
  const identity = packageIdentity();
  log(`kaji ${identity.version}`);
  log("usage: kaji [--no-color] [--verbose] <command> [args]");
  log("");
  log("commands:");
  for (const name of Object.keys(COMMANDS).sort()) {
    const cmd = COMMANDS[name]!;
    log(`  ${name.padEnd(20)} ${cmd.describe}`);
  }
}

export async function runCli(argv: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  let index = 0;
  let noColor = opts.noColor ?? false;
  let verbose = opts.verbose ?? false;
  while (index < argv.length) {
    if (argv[index] === "--no-color") {
      noColor = true;
      index++;
    } else if (argv[index] === "--verbose") {
      verbose = true;
      index++;
    } else {
      break;
    }
  }
  const [cmd, ...rest] = argv.slice(index);
  if (cmd === undefined) {
    printHelp(log);
    return 0;
  }
  if (cmd === "-h" || cmd === "--help") {
    printHelp(log);
    return 0;
  }
  const handler = COMMANDS[cmd];
  if (!handler) {
    err(`Unknown command: ${cmd}`);
    printHelp(err);
    return 2;
  }
  if (rest[0] === "-h" || rest[0] === "--help") {
    log(`usage: ${handler.usage}`);
    return 0;
  }
  return handler.run(rest, { ...opts, noColor, verbose });
}
