/**
 * Tests for the fs registry integration pattern.
 *
 * Validates sandbox path checking and list/read/write/glob operations using a
 * real tmpdir against the shipped registry template.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createFsIntegration } from "../registry/fs/index";
import type { ToolExecutionContext } from "@/index";

const ctx: ToolExecutionContext = {
  principalId: "_",
  sessionId: "test-session",
  turnId: "test-turn",
  requestId: "test-request",
  traceId: "test-trace",
  toolCallId: "test-call",
  idempotencyKey: "test-session:test-call",
  signal: new AbortController().signal,
  metadata: {},
};

describe("fs integration: sandbox path handling", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
    await writeFile(join(tmpRoot, "inside.txt"), "inside");
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("allows ordinary paths within root", async () => {
    const { read } = createFsIntegration({ root: tmpRoot });
    await expect(read.handler({ path: "inside.txt" }, ctx)).resolves.toEqual({ content: "inside" });
  });

  it("blocks lexical paths that escape the root", async () => {
    const { read } = createFsIntegration({ root: tmpRoot });
    await expect(read.handler({ path: "../../etc/passwd" }, ctx)).rejects.toThrow(
      /escape.*sandbox/i,
    );
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
    const { list } = createFsIntegration({ root: tmpRoot });
    const result = await list.handler({ path: "." }, ctx);

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
    const { read } = createFsIntegration({ root: tmpRoot });
    const result = await read.handler({ path: "greeting.txt" }, ctx);

    expect(result).toEqual({ content: "Hello from test!" });
  });

  it("rejects reads through a symlink that points outside the root", async () => {
    const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
    try {
      await writeFile(join(outside, "secret.txt"), "secret");
      await symlink(join(outside, "secret.txt"), join(tmpRoot, "secret-link.txt"));
      const { read } = createFsIntegration({ root: tmpRoot });

      await expect(read.handler({ path: "secret-link.txt" }, ctx)).rejects.toThrow(
        /escape.*sandbox/i,
      );
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
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
    const { write } = createFsIntegration({ root: tmpRoot });
    const content = "Written by test";
    const result = await write.handler({ path: "output.txt", content }, ctx);

    expect(result).toEqual({ written: content.length });

    const actual = await readFile(join(tmpRoot, "output.txt"), "utf8");
    expect(actual).toBe(content);
  });

  it("blocks lexical paths that escape the root on write", async () => {
    const { write } = createFsIntegration({ root: tmpRoot });
    await expect(write.handler({ path: "../../tmp/evil", content: "bad" }, ctx)).rejects.toThrow(
      /escape.*sandbox/i,
    );
  });

  it("rejects writes through a symlinked parent directory", async () => {
    const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
    try {
      await symlink(outside, join(tmpRoot, "linkdir"));
      const { write } = createFsIntegration({ root: tmpRoot });

      await expect(
        write.handler({ path: "linkdir/evil.txt", content: "bad" }, ctx),
      ).rejects.toThrow(/escape.*sandbox/i);
      await expect(readFile(join(outside, "evil.txt"), "utf8")).rejects.toThrow();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("rejects writes through a symlinked file with a missing target", async () => {
    const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
    try {
      await symlink(join(outside, "missing.txt"), join(tmpRoot, "missing-link.txt"));
      const { write } = createFsIntegration({ root: tmpRoot });

      await expect(
        write.handler({ path: "missing-link.txt", content: "bad" }, ctx),
      ).rejects.toThrow(/escape.*sandbox/i);
      await expect(readFile(join(outside, "missing.txt"), "utf8")).rejects.toThrow();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });
});

describe("fs integration: glob", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
    await writeFile(join(tmpRoot, "visible.txt"), "visible");
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("returns files matching a pattern", async () => {
    const { glob } = createFsIntegration({ root: tmpRoot });
    const result = await glob.handler({ pattern: "**/*.txt" }, ctx);

    expect(result).toEqual({ matches: ["visible.txt"] });
  });

  it("does not return symlinked outside-root paths from glob", async () => {
    const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
    try {
      await writeFile(join(outside, "secret.txt"), "secret");
      await symlink(join(outside, "secret.txt"), join(tmpRoot, "secret-link.txt"));
      const { glob } = createFsIntegration({ root: tmpRoot });

      const result = await glob.handler({ pattern: "**/*" }, ctx);
      const matches = result["matches"] as string[];
      expect(matches).not.toContain("secret-link.txt");
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });
});
