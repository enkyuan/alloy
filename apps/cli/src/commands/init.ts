import { resolve } from "node:path";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { Command } from "commander";
import { isProvider, PROVIDERS, type Provider } from "../providers.js";
import {
  typescriptAgentTemplate,
  typescriptConfigTemplate,
  typescriptEnvTemplate,
  typescriptPackageTemplate,
} from "../templates/typescript-agent.js";
import {
  pythonAgentTemplate,
  pythonEnvTemplate,
  pythonRequirementsTemplate,
} from "../templates/python-agent.js";
import { writeScaffoldFiles, type ScaffoldFile } from "../utils/scaffold.js";

type Lang = "ts" | "python";

const LANGS = ["ts", "python"] as const;

function isLang(value: string | undefined): value is Lang {
  return LANGS.includes(value as Lang);
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
            { value: "mock", label: "Mock (no key required)" },
            { value: "openai", label: "OpenAI" },
            { value: "anthropic", label: "Anthropic" },
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
  .option("--provider <provider>", "mock|openai|anthropic")
  .option("--force", "overwrite existing files", false)
  .option("--yes", "non-interactive (requires --lang; provider defaults to mock)", false)
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
      if (opts.yes) provider ??= "mock";
      if (!opts.yes && (!lang || !provider)) {
        const r = await interactive();
        lang ??= r.lang;
        provider ??= r.provider;
      }
      if (!lang || !provider) {
        printArgError("--lang is required in --yes mode.");
        return;
      }
      const cwd = resolve(opts.cwd);
      let files: ScaffoldFile[];
      if (lang === "ts") {
        files = [
          { name: "package.json", contents: typescriptPackageTemplate(provider) },
          { name: "tsconfig.json", contents: typescriptConfigTemplate() },
          { name: "agent.ts", contents: typescriptAgentTemplate(provider) },
          { name: ".env.example", contents: typescriptEnvTemplate(provider) },
        ];
      } else {
        files = [
          { name: "agent.py", contents: pythonAgentTemplate(provider) },
          { name: ".env.example", contents: pythonEnvTemplate(provider) },
          { name: "requirements.txt", contents: pythonRequirementsTemplate(provider) },
        ];
      }
      let written: string[];
      try {
        written = writeScaffoldFiles(cwd, files, opts.force);
      } catch (error) {
        console.error(error instanceof Error ? error.message : "Failed to write scaffold.");
        process.exitCode = 1;
        return;
      }
      if (written.length === 0) {
        console.log(chalk.yellow("Nothing written -- pass --force to overwrite."));
        process.exitCode = 1;
        return;
      }
      if (opts.yes) {
        for (const f of written) console.log(f);
        if (lang === "ts") {
          console.log(`Next: cd ${cwd} && bun install && bun start`);
        } else {
          console.log(
            `Next: cd ${cwd} && python -m pip install -r requirements.txt && python agent.py`,
          );
        }
        return;
      }
      p.outro(`${chalk.green("✓")} Created ${written.join(", ")} (${lang}, ${provider})`);
    },
  );
