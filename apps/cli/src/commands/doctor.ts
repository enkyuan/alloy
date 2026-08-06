import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import chalk from "chalk";
import { Command } from "commander";
import {
  isProvider,
  PROVIDER_ENV_KEYS,
  TYPESCRIPT_PROVIDER_PACKAGES,
  type Provider,
} from "../providers.js";
import { readNearestPackageJson } from "../utils/package-info.js";

type DoctorLang = "auto" | "ts" | "python";
const DOCTOR_LANGS = ["auto", "ts", "python"] as const;

interface Check {
  name: string;
  ok: boolean;
  detail?: string;
  hint?: string;
  severity: "hard" | "soft";
}
interface RunOptions {
  cwd: string;
  env: Record<string, string | undefined>;
  nodeVersion: string;
  lang?: DoctorLang;
  runCommand?: (cmd: string, args: string[]) => { ok: boolean; stdout: string; stderr: string };
}

function defaultRunCommand(cmd: string, args: string[]) {
  try {
    const stdout = execFileSync(cmd, args, {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { ok: true, stdout, stderr: "" };
  } catch (error) {
    const e = error as { stdout?: Buffer | string; stderr?: Buffer | string };
    return {
      ok: false,
      stdout: e.stdout?.toString() ?? "",
      stderr: e.stderr?.toString() ?? "",
    };
  }
}

function readIfExists(path: string): string {
  return existsSync(path) ? readFileSync(path, "utf-8") : "";
}

function isDoctorLang(value: string | undefined): value is DoctorLang {
  return value === undefined || DOCTOR_LANGS.includes(value as DoctorLang);
}

function configuredProvider(cwd: string, env: Record<string, string | undefined>): string {
  return (
    env.KAJI_MODEL_PROVIDER ??
    readIfExists(join(cwd, ".env.example")).match(/^KAJI_MODEL_PROVIDER=(.+)$/m)?.[1] ??
    "mock"
  ).trim();
}

function hasDependency(all: Record<string, string>, name: string): boolean {
  return Object.prototype.hasOwnProperty.call(all, name);
}

function detectLangs(cwd: string, lang: DoctorLang): Array<"ts" | "python"> {
  if (lang === "ts" || lang === "python") return [lang];
  const hasTs =
    existsSync(join(cwd, "agent.ts")) ||
    existsSync(join(cwd, "tsconfig.json")) ||
    existsSync(join(cwd, "package.json"));
  const hasPython =
    existsSync(join(cwd, "agent.py")) ||
    existsSync(join(cwd, "requirements.txt")) ||
    existsSync(join(cwd, "pyproject.toml"));
  if (hasTs && hasPython) return ["ts", "python"];
  if (hasPython) return ["python"];
  return ["ts"];
}

export function runChecks(o: RunOptions): { checks: Check[]; failed: boolean } {
  const checks: Check[] = [];
  const lang = o.lang ?? "auto";
  const langs = detectLangs(o.cwd, lang);
  const configured = configuredProvider(o.cwd, o.env);
  const provider: Provider = isProvider(configured) ? configured : "mock";
  const pkg = readNearestPackageJson(o.cwd);
  const all = {
    ...(pkg?.dependencies as Record<string, string> | undefined),
    ...(pkg?.devDependencies as Record<string, string> | undefined),
  };

  checks.push({
    name: "supported provider",
    ok: isProvider(configured),
    detail: configured,
    hint: "Use mock, openai, or anthropic for the beta scaffold.",
    severity: "hard",
  });

  if (langs.includes("ts")) {
    const major = parseInt(o.nodeVersion.replace(/^v/, "").split(".")[0] ?? "0", 10);
    checks.push({
      name: "node >= 22",
      ok: major >= 22,
      detail: o.nodeVersion,
      hint: "Install Node 22 or newer for TypeScript kaji projects.",
      severity: "hard",
    });
    checks.push({
      name: "kaji-sdk installed",
      ok: hasDependency(all, "kaji-sdk"),
      hint: "Run `bun add kaji-sdk@0.2.0-beta.11` or regenerate with `kaji init --lang ts`.",
      severity: "hard",
    });
    checks.push({
      name: "zod installed",
      ok: hasDependency(all, "zod"),
      hint: 'Run `bun add "zod@>=4.3 <5"`; Zod is a required kaji-sdk peer.',
      severity: "hard",
    });
    const providerPackage = TYPESCRIPT_PROVIDER_PACKAGES[provider];
    if (providerPackage) {
      checks.push({
        name: `${providerPackage} installed`,
        ok: hasDependency(all, providerPackage),
        detail: provider,
        hint: `Run \`bun add ${providerPackage}\` for the selected ${provider} provider.`,
        severity: pkg ? "hard" : "soft",
      });
    }
  }

  if (langs.includes("python")) {
    const runCommand = o.runCommand ?? defaultRunCommand;
    const result = runCommand("python3", ["--version"]);
    const versionText = `${result.stdout} ${result.stderr}`.trim();
    const match = versionText.match(/Python\s+(\d+)\.(\d+)/);
    const major = match ? Number(match[1]) : 0;
    const minor = match ? Number(match[2]) : 0;
    checks.push({
      name: "python >= 3.11",
      ok: result.ok && (major > 3 || (major === 3 && minor >= 11)),
      detail: versionText || "python3 not found",
      hint: "Install Python 3.11 or newer for Python kaji projects.",
      severity: "hard",
    });
    const requirements = readIfExists(join(o.cwd, "requirements.txt"));
    const pyproject = readIfExists(join(o.cwd, "pyproject.toml"));
    const hasPythonManifest = requirements.length > 0 || pyproject.length > 0;
    const hasKajiPython =
      /(^|\n)\s*kaji-sdk(\[|[<>=~! ]|$)/.test(requirements) ||
      /["']kaji-sdk(\[|["'<>=~! ])/.test(pyproject);
    checks.push({
      name: "kaji-sdk Python distribution declared",
      ok: hasKajiPython,
      hint: "Add `kaji-sdk>=0.2.0b1,<0.3` or the provider extra generated by `kaji init`.",
      severity: hasPythonManifest ? "hard" : "soft",
    });
  }

  const providerKey = PROVIDER_ENV_KEYS[provider];
  if (providerKey) {
    checks.push({
      name: "provider key",
      ok: (o.env[providerKey] ?? "").length > 0,
      detail: providerKey,
      hint: `Set ${providerKey} for the selected ${provider} provider.`,
      severity: "hard",
    });
  }
  checks.push({
    name: ".env.example present",
    ok: existsSync(join(o.cwd, ".env.example")),
    hint: "Regenerate the scaffold or add .env.example so setup is discoverable.",
    severity: "soft",
  });
  const failed = checks.some((c) => c.severity === "hard" && !c.ok);
  return { checks, failed };
}

export const doctor = new Command("doctor")
  .description("check the environment for common kaji issues")
  .option("--cwd <cwd>", "working directory", process.cwd())
  .option("--lang <lang>", "auto|ts|python", "auto")
  .option("--json", "output as JSON")
  .action((opts: { cwd: string; lang?: string; json?: boolean }) => {
    if (!isDoctorLang(opts.lang)) {
      console.error(`--lang must be one of: ${DOCTOR_LANGS.join(", ")}`);
      process.exitCode = 2;
      return;
    }
    const out = runChecks({
      cwd: resolve(opts.cwd),
      env: process.env,
      nodeVersion: process.version,
      lang: opts.lang ?? "auto",
    });
    if (opts.json) {
      console.log(JSON.stringify(out, null, 2));
    } else {
      for (const c of out.checks) {
        const mark = c.ok ? chalk.green("✓") : chalk.red("✗");
        const suffix = c.detail ? chalk.gray(` (${c.detail})`) : "";
        const hint = !c.ok && c.hint ? chalk.gray(`\n  ${c.hint}`) : "";
        console.log(`${mark} ${c.name}${suffix}${hint}`);
      }
    }
    if (out.failed) process.exitCode = 1;
  });
