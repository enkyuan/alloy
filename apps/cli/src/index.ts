#!/usr/bin/env node
import { Command } from "commander";
import "dotenv/config";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { init } from "./commands/init.js";
import { gen } from "./commands/gen.js";
import { info } from "./commands/info.js";
import { secret } from "./commands/secret.js";
import { upgrade } from "./commands/upgrade.js";
import { doctor } from "./commands/doctor.js";
import { mcp } from "./commands/mcp.js";
import { readNearestPackageJson } from "./utils/package-info.js";

process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));

export function buildProgram(): Command {
  const program = new Command("kaji");
  const pkg = readNearestPackageJson(fileURLToPath(new URL("..", import.meta.url)));
  const version = (pkg?.version as string | undefined) ?? "0.1.0";

  program
    .description("kaji CLI")
    .version(version)
    .addCommand(init)
    .addCommand(gen)
    .addCommand(info)
    .addCommand(secret)
    .addCommand(upgrade)
    .addCommand(doctor)
    .addCommand(mcp)
    .action(() => program.help());

  return program;
}

export async function main(argv = process.argv) {
  await buildProgram().parseAsync(argv);
}

export function isEntrypoint(path: string): boolean {
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(path);
  } catch {
    return false;
  }
}

if (process.argv[1] && isEntrypoint(process.argv[1])) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
