import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const bin = join(root, "dist", "index.js");
const out = mkdtempSync(join(tmpdir(), "kaji-cli-smoke-"));

const help = execFileSync("node", [bin, "--help"], { encoding: "utf-8" });
if (!help.includes("init") || !help.includes("doctor")) {
  throw new Error("built CLI help is missing expected commands");
}

execFileSync(
  "node",
  [bin, "init", "--cwd", out, "--lang", "ts", "--provider", "openai", "--yes"],
  { encoding: "utf-8" },
);

const agent = readFileSync(join(out, "agent.ts"), "utf-8");
if (!agent.includes('turn("Say hello.")')) {
  throw new Error("generated TypeScript scaffold does not use the turn() API");
}

console.log(`smoke ok: ${out}`);
