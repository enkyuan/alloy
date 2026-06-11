import { Command } from "commander";
import * as p from "@clack/prompts";
import chalk from "chalk";

export const init = new Command("init")
  .description("initialize agentkit in your project")
  .action(async () => {
    console.log();
    p.intro(chalk.bold("agentkit init"));

    const opts = await p.group(
      {
        language: () =>
          p.select({
            message: "Language",
            options: [
              { value: "typescript", label: "TypeScript" },
              { value: "python", label: "Python" },
            ],
          }),
        provider: () =>
          p.select({
            message: "Default LLM provider",
            options: [
              { value: "openai", label: "OpenAI" },
              { value: "kimi", label: "Kimi" },
              { value: "gemini", label: "Gemini" },
            ],
          }),
      },
      {
        onCancel: () => {
          p.cancel("Cancelled.");
          process.exit(0);
        },
      },
    );

    const s = p.spinner();
    s.start("Setting up agentkit");
    await new Promise((r) => setTimeout(r, 600));
    s.stop("Done");

    p.outro(
      `${chalk.green("✓")} agentkit initialized — language: ${opts.language}, provider: ${opts.provider}`,
    );
  });
