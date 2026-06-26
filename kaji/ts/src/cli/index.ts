/**
 * CLI entry surface for `kaji`. Exports a testable `runCli` plus a dispatch
 * table; the script-mode binary lives in `./bin.ts` so importing this module
 * from tests does not trigger `process.exit`.
 */
import { add } from "./add";
import { init } from "./init";
import { listIntegrations } from "./list_integrations";

export interface RunOptions {
  registryRoot: string;
  log?: (msg: string) => void;
  err?: (msg: string) => void;
}

export interface Command {
  describe: string;
  usage: string;
  run(rest: string[], opts: RunOptions): Promise<number>;
}

export const COMMANDS: Record<string, Command> = {
  add: {
    describe: "Copy an integration's TypeScript source into your project.",
    usage: "kaji add <name> [--out <dir>] [--force]",
    run: (rest, opts) =>
      Promise.resolve(add(rest, { registryRoot: opts.registryRoot, log: opts.log })),
  },
  init: {
    describe: "Scaffold a new TypeScript Kaji project.",
    usage: "kaji init [--out <dir>] [--force]",
    run: (rest, opts) => init(rest, opts),
  },
  "list-integrations": {
    describe: "List integrations available via `kaji add`.",
    usage: "kaji list-integrations",
    run: (rest, opts) => listIntegrations(rest, opts),
  },
};

function printHelp(log: (m: string) => void): void {
  log("usage: kaji <command> [args]");
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
  const [cmd, ...rest] = argv;
  if (cmd === undefined) {
    printHelp(log);
    return 1;
  }
  if (cmd === "-h" || cmd === "--help") {
    printHelp(log);
    return 0;
  }
  const handler = COMMANDS[cmd];
  if (!handler) {
    err(`Unknown command: ${cmd}`);
    printHelp(err);
    return 1;
  }
  if (rest[0] === "-h" || rest[0] === "--help") {
    log(`usage: ${handler.usage}`);
    return 0;
  }
  return handler.run(rest, opts);
}
