import os from "node:os";
import { resolve } from "node:path";
import chalk from "chalk";
import { Command } from "commander";
import { copyToClipboard } from "../utils/clipboard.js";
import { redact } from "../utils/redact.js";
import { readNearestPackageJson } from "../utils/package-info.js";
import { detectPackageManager } from "../utils/package-manager.js";

const FRAMEWORK_KEYS = [
  "next",
  "react",
  "vue",
  "nuxt",
  "svelte",
  "@sveltejs/kit",
  "astro",
  "hono",
  "express",
  "fastify",
  "solid-js",
];
const KAJI_PREFIX = "@kaji/";
const PROVIDER_KEYS = ["openai", "@anthropic-ai/sdk", "@google/genai", "google-genai"];

function pickDeps(pkg: Record<string, unknown> | null, keys: string[]) {
  if (!pkg) return [];
  const all = {
    ...(pkg.dependencies as Record<string, string> | undefined),
    ...(pkg.devDependencies as Record<string, string> | undefined),
  };
  return keys.flatMap((k) => (all[k] ? [{ name: k, version: all[k] }] : []));
}

function pickByPrefix(pkg: Record<string, unknown> | null, prefix: string) {
  if (!pkg) return [];
  const all = {
    ...(pkg.dependencies as Record<string, string> | undefined),
    ...(pkg.devDependencies as Record<string, string> | undefined),
  };
  return Object.entries(all)
    .filter(([k]) => k.startsWith(prefix))
    .map(([name, version]) => ({ name, version }));
}

export const info = new Command("info")
  .description("display environment and kaji configuration")
  .option("--cwd <cwd>", "working directory", process.cwd())
  .option("-j, --json", "output as JSON")
  .option("-c, --copy", "copy output to clipboard")
  .action(async (opts: { cwd: string; json?: boolean; copy?: boolean }) => {
    const cwd = resolve(opts.cwd);
    const pkg = readNearestPackageJson(cwd);
    const data = {
      system: { platform: os.platform(), arch: os.arch(), release: os.release() },
      node: { version: process.version, env: process.env.NODE_ENV ?? "development" },
      packageManager: detectPackageManager(cwd),
      frameworks: pickDeps(pkg, FRAMEWORK_KEYS),
      kaji: { packages: pickByPrefix(pkg, KAJI_PREFIX) },
      providers: pickDeps(pkg, PROVIDER_KEYS),
    };
    const safe = redact(data) as typeof data;
    const text = opts.json ? JSON.stringify(safe, null, 2) : formatText(safe);
    console.log(text);
    if (opts.copy) {
      const ok = await copyToClipboard(text);
      console.log(
        ok
          ? chalk.green("\n✓ Copied to clipboard")
          : chalk.yellow("\n⚠ Could not copy to clipboard"),
      );
    }
  });

function formatText(d: Record<string, unknown>): string {
  const lines: string[] = [];
  lines.push(chalk.bold("kaji info"));
  lines.push(chalk.gray("=".repeat(40)));
  lines.push(`${chalk.cyan("platform")}: ${(d.system as any).platform} ${(d.system as any).arch}`);
  lines.push(`${chalk.cyan("node")}: ${(d.node as any).version}`);
  lines.push(`${chalk.cyan("package manager")}: ${d.packageManager}`);
  const frameworks = d.frameworks as Array<{ name: string; version: string }>;
  if (frameworks.length)
    lines.push(
      `${chalk.cyan("frameworks")}: ${frameworks.map((f) => `${f.name}@${f.version}`).join(", ")}`,
    );
  const kaji = d.kaji as { packages: Array<{ name: string; version: string }> };
  if (kaji.packages.length)
    lines.push(
      `${chalk.cyan("kaji")}: ${kaji.packages.map((f) => `${f.name}@${f.version}`).join(", ")}`,
    );
  const providers = d.providers as Array<{ name: string; version: string }>;
  if (providers.length)
    lines.push(
      `${chalk.cyan("providers")}: ${providers.map((f) => `${f.name}@${f.version}`).join(", ")}`,
    );
  return lines.join("\n");
}
