import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const packageRoot = resolve(import.meta.dir, "..");
const workdir = mkdtempSync(join(tmpdir(), "kaji-installed-smoke-"));
const npmCache = join(workdir, "npm-cache");
const installRoot = join(workdir, "project");
const nodeBinary = process.env.NODE_BINARY ?? "node";
const npmEnv = {
  ...process.env,
  npm_config_audit: "false",
  npm_config_cache: npmCache,
  npm_config_fund: "false",
  npm_config_update_notifier: "false",
};

function run(
  command: string,
  args: string[],
  cwd = installRoot,
  env: NodeJS.ProcessEnv = npmEnv,
): string {
  return execFileSync(command, args, {
    cwd,
    encoding: "utf8",
    env,
    stdio: ["ignore", "pipe", "inherit"],
  });
}

try {
  mkdirSync(installRoot, { recursive: true });
  const requestedTarball = process.argv[2];
  let tarball: string;
  if (requestedTarball === undefined) {
    const packed = JSON.parse(
      run(
        "npm",
        ["pack", "--json", "--ignore-scripts", "--pack-destination", workdir],
        packageRoot,
      ),
    ) as Array<{ filename: string }>;
    const filename = packed[0]?.filename;
    if (!filename) throw new Error("npm pack did not report a tarball");
    tarball = join(workdir, filename);
  } else {
    tarball = resolve(requestedTarball);
    if (!existsSync(tarball)) throw new Error(`supplied npm tarball does not exist: ${tarball}`);
  }

  run("npm", ["init", "-y"]);
  run("npm", [
    "install",
    "--ignore-scripts",
    tarball,
    "zod@4.3.6",
    "openai@6.42.0",
    "@anthropic-ai/sdk@0.104.1",
  ]);
  run("npm", ["audit", "--omit=dev", "--audit-level=high"], installRoot, {
    ...npmEnv,
    npm_config_audit: "true",
  });

  const esm = `
import * as sdk from "@kaji/sdk";
import * as testing from "@kaji/sdk/testing";
import * as openai from "@kaji/sdk/openai";
import * as anthropic from "@kaji/sdk/anthropic";
if (sdk.VERSION !== "0.2.0-beta.1" || !sdk.AgentRuntime || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
`;
  const cjs = `
const sdk = require("@kaji/sdk");
const testing = require("@kaji/sdk/testing");
const openai = require("@kaji/sdk/openai");
const anthropic = require("@kaji/sdk/anthropic");
if (sdk.VERSION !== "0.2.0-beta.1" || !sdk.AgentRuntime || !testing.MockProvider || !openai.OpenAIProvider || !anthropic.AnthropicProvider) process.exit(1);
`;
  writeFileSync(join(installRoot, "smoke.mjs"), esm);
  writeFileSync(join(installRoot, "smoke.cjs"), cjs);

  const version = run(nodeBinary, ["--version"]).trim();
  const major = Number(/^v(\d+)/.exec(version)?.[1]);
  if (!Number.isInteger(major) || major < 22) {
    throw new Error(`package smoke requires Node >=22, received ${version}`);
  }
  run(nodeBinary, ["smoke.mjs"]);
  run(nodeBinary, ["smoke.cjs"]);
  run(nodeBinary, [join(installRoot, "node_modules/.bin/kaji"), "--help"]);
  console.log("PASS: exact npm tarball resolves ESM, CJS, subpaths, and CLI");
} finally {
  rmSync(workdir, { recursive: true, force: true });
}
