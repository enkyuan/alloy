import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const bin = join(root, "dist", "index.js");
const workspace = mkdtempSync(join(tmpdir(), "kaji-cli-smoke-"));
const tsOut = join(workspace, "typescript");
const pyOut = join(workspace, "python");

if (!existsSync(join(root, "dist", "LICENSE"))) {
  throw new Error("built CLI package is missing its distributable license");
}

const help = execFileSync("node", [bin, "--help"], { encoding: "utf-8" });
if (!help.includes("init") || !help.includes("doctor")) {
  throw new Error("built CLI help is missing expected commands");
}

execFileSync("node", [bin, "init", "--cwd", tsOut, "--lang", "ts", "--yes"], { encoding: "utf-8" });

const tsAgent = readFileSync(join(tsOut, "agent.ts"), "utf-8");
const tsPackage = JSON.parse(readFileSync(join(tsOut, "package.json"), "utf-8"));
if (!tsAgent.includes('turn("Say hello.")') || !tsAgent.includes("final_sequence=")) {
  throw new Error("generated TypeScript scaffold does not use the turn() API");
}
if (!tsAgent.includes("MockProvider") || tsPackage.dependencies.zod !== ">=4.3 <5") {
  throw new Error("generated TypeScript scaffold is missing the no-key provider or required peers");
}
execFileSync("node", ["--check", join(tsOut, "agent.ts")], { stdio: "ignore" });

execFileSync("node", [bin, "init", "--cwd", pyOut, "--lang", "python", "--yes"], {
  encoding: "utf-8",
});

const pyAgent = readFileSync(join(pyOut, "agent.py"), "utf-8");
const pyRequirements = readFileSync(join(pyOut, "requirements.txt"), "utf-8");
if (!pyAgent.includes('turn("Say hello.")') || !pyAgent.includes("final_sequence=")) {
  throw new Error("generated Python scaffold does not use the turn() API");
}
if (!pyAgent.includes('get_provider("mock")') || !pyRequirements.includes(">=0.2.0b1,<0.3")) {
  throw new Error("generated Python scaffold is not bound to the beta no-key contract");
}

console.log(`smoke ok: ${workspace}`);
