// This is YOUR fs integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Expand sandbox root to multiple allowed paths if needed
//   4. Add helper tools your agent wants (e.g. move, copy, delete)
// Updates: re-run `kaji add fs` to diff against the latest version we ship.

import { functionTool } from "@kaji/sdk";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { z } from "zod";

function sandboxResolve(root: string, unsafePath: string): string {
  const resolved = resolve(root, unsafePath);
  const rel = relative(root, resolved);
  if (rel.startsWith("..") || resolve(root, rel) !== resolved) {
    throw new Error(`Path escapes sandbox root: ${JSON.stringify(unsafePath)}`);
  }
  return resolved;
}

async function walkDir(dir: string): Promise<string[]> {
  const files: string[] = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return files;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walkDir(full)));
    } else {
      files.push(full);
    }
  }
  return files;
}

function globToRegex(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*\//g, "(?:.+/)?")
    .replace(/\*\*/g, ".*")
    .replace(/\*/g, "[^/]*")
    .replace(/\?/g, "[^/]");
  return new RegExp(`^${escaped}$`);
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
      const safe = sandboxResolve(root, path);
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
      const safe = sandboxResolve(root, path);
      const content = await readFile(safe, "utf8");
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
      const safe = sandboxResolve(root, path);
      await mkdir(dirname(safe), { recursive: true });
      await writeFile(safe, content, "utf8");
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
      const allFiles = await walkDir(root);
      const regex = globToRegex(pattern);
      const matches = allFiles.map((f) => relative(root, f)).filter((rel) => regex.test(rel));
      return { matches };
    },
  );

  return { list: fsList, read: fsRead, write: fsWrite, glob: fsGlob };
}
