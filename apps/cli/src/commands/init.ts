import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { Command } from "commander";
import { tsAgentTemplate, tsEnvTemplate } from "../templates/ts-agent.js";
import { pyAgentTemplate, pyEnvTemplate } from "../templates/py-agent.js";

type Lang = "ts" | "python";
type Provider = "openai" | "anthropic" | "kimi" | "gemini";

function writeFile(target: string, body: string, force: boolean): boolean {
  if (existsSync(target) && !force) return false;
  mkdirSync(resolve(target, ".."), { recursive: true });
  writeFileSync(target, body);
  return true;
}

async function interactive(): Promise<{ lang: Lang; provider: Provider }> {
  p.intro(chalk.bold("kaji init"));
  const opts = await p.group(
    {
      lang: () =>
        p.select({
          message: "Language",
          options: [
            { value: "ts", label: "TypeScript" },
            { value: "python", label: "Python" },
          ],
        }) as Promise<Lang>,
      provider: () =>
        p.select({
          message: "Default LLM provider",
          options: [
            { value: "openai", label: "OpenAI" },
            { value: "anthropic", label: "Anthropic" },
            { value: "kimi", label: "Kimi" },
            { value: "gemini", label: "Gemini" },
          ],
        }) as Promise<Provider>,
    },
    {
      onCancel: () => {
        p.cancel("Cancelled.");
        process.exit(0);
      },
    },
  );
  return opts;
}

export const init = new Command("init")
  .description("scaffold a new kaji project")
  .option("--cwd <cwd>", "target directory", process.cwd())
  .option("--lang <lang>", "ts|python")
  .option("--provider <provider>", "openai|anthropic|kimi|gemini")
  .option("--force", "overwrite existing files", false)
  .option("--yes", "non-interactive (requires --lang and --provider)", false)
  .action(
    async (opts: {
      cwd: string;
      lang?: Lang;
      provider?: Provider;
      force: boolean;
      yes: boolean;
    }) => {
      let lang = opts.lang;
      let provider = opts.provider;
      if (!opts.yes && (!lang || !provider)) {
        const r = await interactive();
        lang ??= r.lang;
        provider ??= r.provider;
      }
      if (!lang || !provider) {
        console.error("--lang and --provider are required in --yes mode.");
        process.exit(2);
      }
      const cwd = resolve(opts.cwd);
      const written: string[] = [];
      if (lang === "ts") {
        if (writeFile(join(cwd, "agent.ts"), tsAgentTemplate(provider), opts.force))
          written.push("agent.ts");
        if (writeFile(join(cwd, ".env.example"), tsEnvTemplate(provider), opts.force))
          written.push(".env.example");
      } else {
        if (writeFile(join(cwd, "agent.py"), pyAgentTemplate(provider), opts.force))
          written.push("agent.py");
        if (writeFile(join(cwd, ".env.example"), pyEnvTemplate(provider), opts.force))
          written.push(".env.example");
      }
      if (written.length === 0) {
        console.log(chalk.yellow("Nothing written -- pass --force to overwrite."));
        return;
      }
      if (opts.yes) {
        for (const f of written) console.log(f);
        return;
      }
      p.outro(`${chalk.green("✓")} Created ${written.join(", ")} (${lang}, ${provider})`);
    },
  );
