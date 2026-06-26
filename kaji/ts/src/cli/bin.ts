/**
 * Binary entry point for `kaji`. Built by tsup with a `#!/usr/bin/env node`
 * banner; `package.json` `bin` points at `./dist/cli/bin.js`.
 *
 * Keep this file as thin as possible — all command logic lives in `./index.ts`
 * and the per-command modules so tests can drive `runCli` without firing
 * `process.exit`.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runCli } from "./index";

const here = dirname(fileURLToPath(import.meta.url));
// dist/cli/bin.js -> dist/cli -> dist -> <pkg>/registry
const registryRoot = join(here, "..", "..", "registry");

runCli(process.argv.slice(2), { registryRoot }).then((code) => process.exit(code));
