#!/usr/bin/env node

import { Command } from "commander";
import { init } from "./commands/init.js";
import { gen } from "./commands/gen.js";

import "dotenv/config";

process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));

async function main() {
  const program = new Command("agentkit");

  program
    .addCommand(init)
    .addCommand(gen)
    .version("0.0.1")
    .description("agentkit CLI")
    .action(() => program.help());

  program.parse();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
