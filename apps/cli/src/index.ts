#!/usr/bin/env node

import { Command } from "commander";
import { doctor } from "./commands/doctor.js";
import { gen } from "./commands/gen.js";
import { info } from "./commands/info.js";
import { init } from "./commands/init.js";
import { mcp } from "./commands/mcp.js";
import { secret } from "./commands/secret.js";
import { upgrade } from "./commands/upgrade.js";

import "dotenv/config";

process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));

async function main() {
  const program = new Command("agentkit");

  program
    .addCommand(init)
    .addCommand(secret)
    .addCommand(gen)
    .addCommand(info)
    .addCommand(upgrade)
    .addCommand(doctor)
    .addCommand(mcp)
    .version("0.0.1")
    .description("agentkit CLI")
    .action(() => program.help());

  program.parse();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
