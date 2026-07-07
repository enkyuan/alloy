/**
 * `kaji init`: scaffold a minimal TypeScript Kaji project under --out.
 *
 * Drops package.json, tsconfig.json, agent.ts, .env.example and prints a
 * 'Next: bun install && bun start' hint so the scaffold is not a dead end.
 * Refuses to overwrite any existing file unless --force is passed.
 */
import { existsSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { writeTextFile } from "@/cli/bun-io";
import type { RunOptions } from "@/cli/index";

interface Args {
  out: string;
  force: boolean;
}

class CliArgError extends Error {}

function parseArgs(rest: string[]): Args {
  let out = ".";
  let force = false;
  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i];
    if (arg === "--out") {
      const next = rest[i + 1];
      if (next === undefined || next.startsWith("--")) {
        throw new CliArgError("--out requires a directory argument");
      }
      out = next;
      i++;
    } else if (arg === "--force") {
      force = true;
    } else {
      throw new CliArgError(`unknown argument: ${arg}`);
    }
  }
  return { out: resolve(out), force };
}

const FILES: Record<string, string> = {
  "package.json": JSON.stringify(
    {
      name: "my-kaji-agent",
      version: "0.1.0",
      private: true,
      type: "module",
      scripts: { start: "tsx agent.ts" },
      // `openai` is an optional peer dep of @kaji/sdk that OpenAIProvider
      // imports dynamically. The scaffold defaults to the OpenAI provider,
      // so include it here so `bun install && bun start` runs end-to-end.
      // Swap to `@anthropic-ai/sdk` (or remove) if you wire a different
      // provider in agent.ts.
      dependencies: { "@kaji/sdk": "^0.1.0", openai: "^6.42.0" },
      devDependencies: { tsx: "^4.0.0", typescript: "^5.4.0" },
    },
    null,
    2,
  ),
  "tsconfig.json": JSON.stringify(
    {
      compilerOptions: {
        target: "ES2022",
        module: "ESNext",
        moduleResolution: "Bundler",
        strict: true,
        esModuleInterop: true,
        skipLibCheck: true,
      },
      include: ["*.ts"],
    },
    null,
    2,
  ),
  "agent.ts": `import { AgentBuilder, openai } from "@kaji/sdk";

const agent = new AgentBuilder()
  .provider(openai())
  .build();

const result = await agent.turn("Say hello.");
console.log(result.text);
`,
  ".env.example": "OPENAI_API_KEY=sk-...\n",
};

export async function init(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  let args: Args;
  try {
    args = parseArgs(rest);
  } catch (e) {
    if (e instanceof CliArgError) {
      err(`Error: ${e.message}`);
      err("usage: kaji init [--out <dir>] [--force]");
      return 1;
    }
    throw e;
  }
  if (!existsSync(args.out)) {
    mkdirSync(args.out, { recursive: true });
  }
  const conflicts: string[] = [];
  for (const name of Object.keys(FILES)) {
    if (existsSync(join(args.out, name)) && !args.force) {
      conflicts.push(name);
    }
  }
  if (conflicts.length > 0) {
    err(`refusing to overwrite without --force: ${conflicts.join(", ")}`);
    return 1;
  }
  for (const [name, body] of Object.entries(FILES)) {
    await writeTextFile(join(args.out, name), body);
    log(`wrote ${join(args.out, name)}`);
  }
  log("");
  log(`Next: cd ${args.out} && bun install && bun start`);
  return 0;
}
