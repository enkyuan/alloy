#!/usr/bin/env bun
import { program } from "commander";
import { VERSION, APP_NAME, APP_DESCRIPTION } from "./constants";
import { runCommand, startupCommand, setupCommand } from "./commands/index";

program.name(APP_NAME).description(APP_DESCRIPTION).version(VERSION);

program
  .command("run")
  .description("Launch interactive script picker (default command)")
  .option("-d, --dir <path>", "Directory containing scripts to list")
  .option("--debug", "Start the OpenTUI console in debug mode")
  .action(async (options) => {
    await runCommand(options);
  });

program
  .command("startup")
  .description("Startup and manage Modal application services")
  .action(async () => {
    await startupCommand();
  });

program
  .command("setup")
  .description("Setup Modal environment configuration")
  .action(async () => {
    await setupCommand();
  });

// Default action: run command (when no command specified)
program.action(async () => {
  await runCommand({});
});

program.parse();
