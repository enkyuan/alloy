/** Package-qualified CLI entry for `bun --no-install -e 'import("@kaji/sdk/cli")' -- ...`. */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { runCli } from "@/cli/index";

const here = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(here, "..", "..", "registry");

process.exitCode = await runCli(process.argv.slice(1), { registryRoot });
