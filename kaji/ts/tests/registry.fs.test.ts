/**
 * Tests for the fs registry integration pattern.
 *
 * Validates sandbox path checking, list/read/write operations using a
 * real tmpdir. Reconstructs key logic inline (like registry.echo.test.ts)
 * so tests run against the local source tree without the registry files
 * needing to be in tsconfig.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { z } from "zod";
import { functionTool, type ToolContext } from "../src/index";

const ctx: ToolContext = { userId: "_" };

function sandboxResolve(root: string, unsafePath: string): string {
  const resolved = resolve(root, unsafePath);
  const rel = relative(root, resolved);
  if (rel.startsWith("..") || resolve(root, rel) !== resolved) {
    throw new Error(`Path escapes sandbox root: ${JSON.stringify(unsafePath)}`);
  }
  return resolved;
}

function createFsList(root: string) {
  return functionTool(
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
}

function createFsRead(root: string) {
  return functionTool(
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
}

function createFsWrite(root: string) {
  return functionTool(
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
}

describe("fs integration: sandboxResolve", () => {
  it("allows paths within root", () => {
    const root = "/tmp/sandbox";
    expect(() => sandboxResolve(root, "subdir/file.txt")).not.toThrow();
    expect(() => sandboxResolve(root, ".")).not.toThrow();
    expect(() => sandboxResolve(root, "a/b/c")).not.toThrow();
  });

  it("blocks paths that escape the root", () => {
    const root = "/tmp/sandbox";
    expect(() => sandboxResolve(root, "../../etc/passwd")).toThrow(/escape.*sandbox/i);
    expect(() => sandboxResolve(root, "../other")).toThrow(/escape.*sandbox/i);
  });
});

describe("fs integration: list", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
    await writeFile(join(tmpRoot, "hello.txt"), "hello");
    await writeFile(join(tmpRoot, "world.txt"), "world");
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("lists files in the temp directory", async () => {
    const tool = createFsList(tmpRoot);
    const result = await tool.handler(ctx, { path: "." });

    expect(result).toHaveProperty("entries");
    const entries = result["entries"] as { name: string; isDir: boolean }[];
    const names = entries.map((e) => e.name).sort();
    expect(names).toContain("hello.txt");
    expect(names).toContain("world.txt");
  });
});

describe("fs integration: read", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
    await writeFile(join(tmpRoot, "greeting.txt"), "Hello from test!");
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("reads a file that was written in setup", async () => {
    const tool = createFsRead(tmpRoot);
    const result = await tool.handler(ctx, { path: "greeting.txt" });

    expect(result).toEqual({ content: "Hello from test!" });
  });

  it("path escape blocked: ../../etc/passwd throws", async () => {
    const tool = createFsRead(tmpRoot);
    await expect(tool.handler(ctx, { path: "../../etc/passwd" })).rejects.toThrow(
      /escape.*sandbox/i,
    );
  });
});

describe("fs integration: write", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("creates a file and returns byte count", async () => {
    const tool = createFsWrite(tmpRoot);
    const content = "Written by test";
    const result = await tool.handler(ctx, { path: "output.txt", content });

    expect(result).toEqual({ written: content.length });

    const actual = await readFile(join(tmpRoot, "output.txt"), "utf8");
    expect(actual).toBe(content);
  });

  it("path escape blocked on write: ../../tmp/evil throws", async () => {
    const tool = createFsWrite(tmpRoot);
    await expect(tool.handler(ctx, { path: "../../tmp/evil", content: "bad" })).rejects.toThrow(
      /escape.*sandbox/i,
    );
  });
});
