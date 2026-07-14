import { execFileSync } from "node:child_process";
import { chmodSync, copyFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "dist");
const tsc = join(root, "node_modules", ".bin", process.platform === "win32" ? "tsc.cmd" : "tsc");

rmSync(output, { recursive: true, force: true });
execFileSync(tsc, ["-p", join(root, "tsconfig.build.json")], { stdio: "inherit" });
copyFileSync(join(root, "..", "..", "LICENSE"), join(output, "LICENSE"));
if (process.platform !== "win32") chmodSync(join(output, "index.js"), 0o755);
