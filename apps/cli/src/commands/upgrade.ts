import { spawn } from "node:child_process";
import { resolve } from "node:path";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { Command } from "commander";
import * as semver from "semver";
import yoctoSpinner from "yocto-spinner";
import { fetchLatestVersion } from "../utils/latest-version.js";
import { readNearestPackageJson } from "../utils/package-info.js";
import { detectPackageManager, type PackageManager } from "../utils/package-manager.js";

export interface OutdatedEntry {
  name: string;
  current: string;
  latest: string;
  depType: "prod" | "dev";
}

const PREFIX = "@kaji/";

export async function findOutdated(
  cwd: string,
  fetcher: (name: string) => Promise<string | null> = fetchLatestVersion,
): Promise<OutdatedEntry[]> {
  const pkg = readNearestPackageJson(cwd);
  if (!pkg) return [];
  const collect = (obj: Record<string, string> | undefined, depType: "prod" | "dev") =>
    Object.entries(obj ?? {})
      .filter(([name, v]) => name.startsWith(PREFIX) && !v.startsWith("workspace:"))
      .map(([name, current]) => ({ name, current, depType }));
  const candidates = [
    ...collect(pkg.dependencies as Record<string, string>, "prod"),
    ...collect(pkg.devDependencies as Record<string, string>, "dev"),
  ];
  const results = await Promise.all(
    candidates.map(async (c) => ({ ...c, latest: await fetcher(c.name) })),
  );
  const out: OutdatedEntry[] = [];
  for (const r of results) {
    if (!r.latest) continue;
    const coerced = semver.coerce(r.current);
    if (coerced && semver.lt(coerced, r.latest)) {
      out.push({ name: r.name, current: r.current, latest: r.latest, depType: r.depType });
    }
  }
  return out;
}

function installCmd(pm: PackageManager, prod: string[], dev: string[]): string[][] {
  const cmds: string[][] = [];
  const add = pm === "npm" ? "install" : "add";
  if (prod.length) cmds.push([pm, add, ...prod]);
  if (dev.length) cmds.push([pm, add, "-D", ...dev]);
  return cmds;
}

async function run(cmd: string[], cwd: string): Promise<void> {
  return new Promise((res, rej) => {
    const [head, ...rest] = cmd;
    const child = spawn(head, rest, { cwd, stdio: "inherit" });
    child.on("close", (code) =>
      code === 0 ? res() : rej(new Error(`${cmd.join(" ")} exited with ${code}`)),
    );
  });
}

export const upgrade = new Command("upgrade")
  .description("upgrade @kaji/* packages to latest")
  .option("-c, --cwd <cwd>", "working directory", process.cwd())
  .option("-y, --yes", "skip confirmation", false)
  .action(async (opts: { cwd: string; yes: boolean }) => {
    const cwd = resolve(opts.cwd);
    const sp = yoctoSpinner({ text: "checking for updates..." }).start();
    const outdated = await findOutdated(cwd);
    sp.stop();
    if (outdated.length === 0) {
      console.log("All kaji packages are up to date.");
      return;
    }
    console.log(`\nThe following packages can be upgraded:\n`);
    for (const u of outdated) {
      console.log(
        `  ${chalk.cyan(u.name)} ${chalk.gray(u.current)} ${chalk.white("→")} ${chalk.green(u.latest)}`,
      );
    }
    let go = opts.yes;
    if (!go) {
      const r = await p.confirm({ message: "Upgrade these packages?", initialValue: true });
      if (p.isCancel(r) || !r) {
        console.log("Cancelled.");
        return;
      }
      go = true;
    }
    const pm = detectPackageManager(cwd);
    const prod = outdated.filter((u) => u.depType === "prod").map((u) => `${u.name}@${u.latest}`);
    const dev = outdated.filter((u) => u.depType === "dev").map((u) => `${u.name}@${u.latest}`);
    for (const c of installCmd(pm, prod, dev)) await run(c, cwd);
    console.log(chalk.green("\n✓ Upgrade complete."));
  });
