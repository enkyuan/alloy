/**
 * CLI entry for `kaji`. Resolves the registry shipped inside the npm package
 * and dispatches `add` to ./add.
 *
 * Built by tsup with a `#!/usr/bin/env node` banner so it works as a bin.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { add } from "./add";

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === undefined || cmd === "-h" || cmd === "--help") {
    console.log("usage: kaji add <name> [--out <dir>] [--force]");
    return cmd === undefined ? 1 : 0;
  }
  if (cmd !== "add") {
    console.error(`Unknown command: ${cmd}`);
    console.error("usage: kaji add <name> [--out <dir>] [--force]");
    return 1;
  }
  // dist/cli/index.js -> dist/cli -> dist -> <pkg>/registry
  const here = dirname(fileURLToPath(import.meta.url));
  const registryRoot = join(here, "..", "..", "registry");
  return add(rest, { registryRoot });
}

main().then((code) => process.exit(code));
