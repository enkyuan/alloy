// This is YOUR fs integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Expand sandbox root to multiple allowed paths if needed
//   4. Add helper tools your agent wants (e.g. move, copy, delete)
// Updates: re-run `kaji add fs` to diff against the latest version we ship.

import { functionTool } from "@kaji/sdk";
import { lstat, mkdir, readdir, realpath } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { z } from "zod";

type BunRuntime = typeof Bun;

function bunRuntime(): BunRuntime | undefined {
  return (globalThis as { Bun?: BunRuntime }).Bun;
}

async function readTextFile(path: string): Promise<string> {
  const bun = bunRuntime();
  if (bun) {
    return bun.file(path).text();
  }
  const { readFile } = await import("node:fs/promises");
  return readFile(path, "utf8");
}

async function writeTextFile(path: string, content: string): Promise<void> {
  const bun = bunRuntime();
  if (bun) {
    await bun.write(path, content);
    return;
  }
  const { writeFile } = await import("node:fs/promises");
  await writeFile(path, content, "utf8");
}

async function deepestExisting(path: string): Promise<string> {
  let probe = path;
  while (probe !== dirname(probe)) {
    try {
      await realpath(probe);
      return probe;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
      probe = dirname(probe);
    }
  }
  return probe;
}

function isInside(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && resolve(root, rel) === candidate);
}

function sandboxEscapeError(path: string): Error {
  return new Error(`Path escapes sandbox root: ${JSON.stringify(path)}`);
}

function assertInsideSandbox(root: string, candidate: string, unsafePath: string): void {
  if (!isInside(root, candidate)) {
    throw sandboxEscapeError(unsafePath);
  }
}

async function sandboxResolve(
  root: string,
  unsafePath: string,
  mode: "read" | "write",
): Promise<string> {
  const rootPath = resolve(root);
  const rootReal = await realpath(rootPath);
  const resolved = resolve(rootPath, unsafePath);
  const rel = relative(rootPath, resolved);
  if (rel.startsWith("..") || resolve(rootPath, rel) !== resolved) {
    throw sandboxEscapeError(unsafePath);
  }

  try {
    const targetReal = await realpath(resolved);
    assertInsideSandbox(rootReal, targetReal, unsafePath);
    return targetReal;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT" || mode === "read") {
      throw error;
    }
  }

  try {
    if ((await lstat(resolved)).isSymbolicLink()) {
      throw sandboxEscapeError(unsafePath);
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }

  const parent = await deepestExisting(dirname(resolved));
  const parentReal = await realpath(parent);
  assertInsideSandbox(rootReal, parentReal, unsafePath);
  return resolved;
}

async function walkDir(dir: string, rootReal: string): Promise<string[]> {
  const dirReal = await realpath(dir);
  assertInsideSandbox(rootReal, dirReal, dir);

  const files: string[] = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return files;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      continue;
    }
    if (entry.isDirectory()) {
      files.push(...(await walkDir(full, rootReal)));
    } else {
      files.push(full);
    }
  }
  return files;
}

function globToRegex(pattern: string): RegExp {
  let regex = "";
  for (let i = 0; i < pattern.length; i++) {
    const char = pattern.charAt(i);
    const next = pattern.charAt(i + 1);
    const afterNext = pattern.charAt(i + 2);
    if (char === "*" && next === "*" && afterNext === "/") {
      regex += "(?:.*/)?";
      i += 2;
    } else if (char === "*" && next === "*") {
      regex += ".*";
      i++;
    } else if (char === "*") {
      regex += "[^/]*";
    } else if (char === "?") {
      regex += "[^/]";
    } else {
      regex += char.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${regex}$`);
}

export function createFsIntegration(opts: { root: string }): {
  list: ReturnType<typeof functionTool>;
  read: ReturnType<typeof functionTool>;
  write: ReturnType<typeof functionTool>;
  glob: ReturnType<typeof functionTool>;
} {
  const root = resolve(opts.root);

  const fsList = functionTool(
    {
      name: "list",
      namespace: "fs",
      description: "List files in a directory.",
      parameters: z.object({ path: z.string().default(".") }),
      risk: "read",
    },
    async ({ path }) => {
      const safe = await sandboxResolve(root, path, "read");
      const entries = await readdir(safe, { withFileTypes: true });
      return {
        entries: entries.map((e) => ({ name: e.name, isDir: e.isDirectory() })),
      };
    },
  );

  const fsRead = functionTool(
    {
      name: "read",
      namespace: "fs",
      description: "Read a file's contents.",
      parameters: z.object({ path: z.string() }),
      risk: "read",
    },
    async ({ path }) => {
      const safe = await sandboxResolve(root, path, "read");
      const content = await readTextFile(safe);
      return { content };
    },
  );

  const fsWrite = functionTool(
    {
      name: "write",
      namespace: "fs",
      description: "Write content to a file.",
      parameters: z.object({ path: z.string(), content: z.string() }),
      risk: "write",
    },
    async ({ path, content }) => {
      const safe = await sandboxResolve(root, path, "write");
      await mkdir(dirname(safe), { recursive: true });
      await writeTextFile(safe, content);
      return { written: content.length };
    },
  );

  const fsGlob = functionTool(
    {
      name: "glob",
      namespace: "fs",
      description: "Glob for files matching a pattern.",
      parameters: z.object({ pattern: z.string() }),
      risk: "read",
    },
    async ({ pattern }) => {
      const rootReal = await realpath(root);
      const allFiles = await walkDir(root, rootReal);
      const regex = globToRegex(pattern);
      const matches = allFiles.map((f) => relative(root, f)).filter((rel) => regex.test(rel));
      return { matches };
    },
  );

  return { list: fsList, read: fsRead, write: fsWrite, glob: fsGlob };
}
