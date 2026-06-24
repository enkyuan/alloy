import Crypto from "node:crypto";
import chalk from "chalk";
import { Command } from "commander";

export const secret = new Command("secret")
  .description("generate a random 32-byte hex secret")
  .option("--name <name>", "env var name", "KAJI_SECRET")
  .option("--json", "print as JSON")
  .action((opts: { name: string; json?: boolean }) => {
    const value = Crypto.randomBytes(32).toString("hex");
    if (opts.json) {
      console.log(JSON.stringify({ name: opts.name, value }));
      return;
    }
    console.log(`\nAdd the following to your .env file:`);
    console.log(`${chalk.gray("# kaji secret")}\n${chalk.green(`${opts.name}=${value}`)}\n`);
  });
