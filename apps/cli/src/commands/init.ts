import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { Command } from "commander";
import {
  tsAgentTemplate,
  tsConfigTemplate,
  tsEnvTemplate,
  tsPackageTemplate,
} from "../templates/ts-agent.js";
import { pyAgentTemplate, pyEnvTemplate, pyRequirementsTemplate } from "../templates/py-agent.js";

type Lang = "ts" | "python";
type Provider = "openai" | "anthropic" | "kimi" | "gemini";

const LANGS = ["ts", "python"] as const;
const PROVIDERS = ["openai", "anthropic", "kimi", "gemini"] as const;

function writeFile(target: string, body: string, force: boolean): boolean {
  if (existsSync(target) && !force) return false;
  mkdirSync(resolve(target, ".."), { recursive: true });
  writeFileSync(target, body);
  return true;
}

function isLang(value: string | undefined): value is Lang {
  return LANGS.includes(value as Lang);
}

function isProvider(value: string | undefined): value is Provider {
  return PROVIDERS.includes(value as Provider);
}

function printArgError(message: string): void {
  console.error(message);
  process.exitCode = 2;
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
      if (lang !== undefined && !isLang(lang)) {
        printArgError(`--lang must be one of: ${LANGS.join(", ")}`);
        return;
      }
      if (provider !== undefined && !isProvider(provider)) {
        printArgError(`--provider must be one of: ${PROVIDERS.join(", ")}`);
        return;
      }
      if (!opts.yes && (!lang || !provider)) {
        const r = await interactive();
        lang ??= r.lang;
        provider ??= r.provider;
      }
      if (!lang || !provider) {
        printArgError("--lang and --provider are required in --yes mode.");
        return;
      }
      const cwd = resolve(opts.cwd);
      const written: string[] = [];
      if (lang === "ts") {
        if (writeFile(join(cwd, "package.json"), tsPackageTemplate(provider), opts.force))
          written.push("package.json");
        if (writeFile(join(cwd, "tsconfig.json"), tsConfigTemplate(), opts.force))
          written.push("tsconfig.json");
        if (writeFile(join(cwd, "agent.ts"), tsAgentTemplate(provider), opts.force))
          written.push("agent.ts");
        if (writeFile(join(cwd, ".env.example"), tsEnvTemplate(provider), opts.force))
          written.push(".env.example");
      } else {
        if (writeFile(join(cwd, "agent.py"), pyAgentTemplate(provider), opts.force))
          written.push("agent.py");
        if (writeFile(join(cwd, ".env.example"), pyEnvTemplate(provider), opts.force))
          written.push(".env.example");
        if (writeFile(join(cwd, "requirements.txt"), pyRequirementsTemplate(provider), opts.force))
          written.push("requirements.txt");
      }
      if (written.length === 0) {
        console.log(chalk.yellow("Nothing written -- pass --force to overwrite."));
        return;
      }
      if (opts.yes) {
        for (const f of written) console.log(f);
        if (lang === "ts") {
          console.log(`Next: cd ${cwd} && bun install && bun start`);
        } else {
          console.log(`Next: cd ${cwd} && python -m pip install -r requirements.txt && python agent.py`);
        }
        return;
      }
      p.outro(`${chalk.green("✓")} Created ${written.join(", ")} (${lang}, ${provider})`);
    },
  );
