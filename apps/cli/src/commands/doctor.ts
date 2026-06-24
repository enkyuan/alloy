import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import chalk from "chalk";
import { Command } from "commander";
import { readNearestPackageJson } from "../utils/package-info.js";

interface Check {
  name: string;
  ok: boolean;
  detail?: string;
}
interface RunOptions {
  cwd: string;
  env: Record<string, string | undefined>;
  nodeVersion: string;
}

export function runChecks(o: RunOptions): { checks: Check[]; failed: boolean } {
  const checks: Check[] = [];
  const major = parseInt(o.nodeVersion.replace(/^v/, "").split(".")[0] ?? "0", 10);
  checks.push({ name: "node >= 22", ok: major >= 22, detail: o.nodeVersion });
  const pkg = readNearestPackageJson(o.cwd);
  const all = {
    ...(pkg?.dependencies as Record<string, string> | undefined),
    ...(pkg?.devDependencies as Record<string, string> | undefined),
  };
  const hasAgentkit = Object.keys(all ?? {}).some((k) => k.startsWith("@kaji/"));
  checks.push({ name: "@kaji/* installed", ok: hasAgentkit });
  const providerKeys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "KIMI_API_KEY"];
  const hasProvider = providerKeys.some((k) => (o.env[k] ?? "").length > 0);
  checks.push({ name: "provider key", ok: hasProvider, detail: providerKeys.join(" | ") });
  checks.push({ name: ".env.example present", ok: existsSync(join(o.cwd, ".env.example")) });
  // .env.example is a soft check — never fails the run
  const failed = checks.slice(0, 3).some((c) => !c.ok);
  return { checks, failed };
}

export const doctor = new Command("doctor")
  .description("check the environment for common kaji issues")
  .option("--cwd <cwd>", "working directory", process.cwd())
  .option("--json", "output as JSON")
  .action((opts: { cwd: string; json?: boolean }) => {
    const out = runChecks({
      cwd: resolve(opts.cwd),
      env: process.env,
      nodeVersion: process.version,
    });
    if (opts.json) {
      console.log(JSON.stringify(out, null, 2));
    } else {
      for (const c of out.checks) {
        const mark = c.ok ? chalk.green("✓") : chalk.red("✗");
        console.log(`${mark} ${c.name}${c.detail ? chalk.gray(` (${c.detail})`) : ""}`);
      }
    }
    if (out.failed) process.exit(1);
  });
