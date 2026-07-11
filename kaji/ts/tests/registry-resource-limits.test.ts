import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { chmod, mkdir, mkdtemp, readFile, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { ToolExecutionContext } from "@/index";
import { createFsIntegration, type FsIntegrationPolicy } from "../registry/fs/index";

const ctx: ToolExecutionContext = {
  principalId: "tester",
  sessionId: "session",
  turnId: "turn",
  requestId: "request",
  traceId: "trace",
  toolCallId: "call",
  idempotencyKey: "session:call",
  signal: new AbortController().signal,
  metadata: {},
};

describe("filesystem registry resource limits", () => {
  let root: string;

  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), "kaji-fs-limits-"));
  });

  afterEach(async () => {
    await chmod(root, 0o700).catch(() => undefined);
    await rm(root, { recursive: true, force: true });
  });

  it.each([
    "maxDepth",
    "maxVisitedEntries",
    "maxFileBytes",
    "maxTotalBytes",
    "maxWriteBytes",
  ] as const)("requires %s to be a positive safe integer", (limit) => {
    expect(() => createFsIntegration({ root, [limit]: 0 })).toThrow(/positive safe integer/);
    expect(() => createFsIntegration({ root, [limit]: Number.MAX_SAFE_INTEGER + 1 })).toThrow(
      /positive safe integer/,
    );
  });

  it("allows exact single-file read boundaries and rejects one byte over", async () => {
    await writeFile(join(root, "exact.txt"), "four");
    const exact = createFsIntegration({ root, maxFileBytes: 4, maxTotalBytes: 4 });
    await expect(exact.read.handler({ path: "exact.txt" }, ctx)).resolves.toEqual({
      content: "four",
    });

    const capped = createFsIntegration({ root, maxFileBytes: 3 });
    await expect(capped.read.handler({ path: "exact.txt" }, ctx)).rejects.toThrow(/byte limit/i);
  });

  it("counts UTF-8 bytes for write boundaries before touching the destination", async () => {
    const exact = createFsIntegration({ root, maxWriteBytes: 2 });
    await expect(exact.write.handler({ path: "exact.txt", content: "é" }, ctx)).resolves.toEqual({
      written: 2,
    });
    expect(await readFile(join(root, "exact.txt"), "utf8")).toBe("é");

    const capped = createFsIntegration({ root, maxWriteBytes: 1 });
    await expect(
      capped.write.handler({ path: "missing/out.txt", content: "é" }, ctx),
    ).rejects.toThrow(/maxWriteBytes/);
    await expect(readFile(join(root, "missing/out.txt"), "utf8")).rejects.toThrow();
  });

  it("enforces exact visit and cumulative byte limits during glob", async () => {
    await writeFile(join(root, "a.txt"), "aa");
    await writeFile(join(root, "b.txt"), "bbb");
    const exact = createFsIntegration({
      root,
      maxVisitedEntries: 2,
      maxFileBytes: 3,
      maxTotalBytes: 5,
    });
    await expect(exact.glob.handler({ pattern: "**/*.txt" }, ctx)).resolves.toEqual({
      matches: ["a.txt", "b.txt"],
    });

    await expect(
      createFsIntegration({ root, maxVisitedEntries: 1 }).glob.handler({ pattern: "**/*" }, ctx),
    ).rejects.toThrow(/maxVisitedEntries/);
    await expect(
      createFsIntegration({ root, maxTotalBytes: 4 }).glob.handler({ pattern: "**/*" }, ctx),
    ).rejects.toThrow(/maxTotalBytes/);
  });

  it("enforces depth iteratively without recursive stack growth", async () => {
    await mkdir(join(root, "one"));
    await writeFile(join(root, "one", "inside.txt"), "x");
    const exact = createFsIntegration({ root, maxDepth: 1 });
    await expect(exact.glob.handler({ pattern: "**/*.txt" }, ctx)).resolves.toEqual({
      matches: ["one/inside.txt"],
    });

    await mkdir(join(root, "one", "two"));
    await writeFile(join(root, "one", "two", "too-deep.txt"), "x");
    await expect(exact.glob.handler({ pattern: "**/*" }, ctx)).rejects.toThrow(/maxDepth/);
  });

  it("handles an in-root directory symlink cycle without following it", async () => {
    await mkdir(join(root, "dir"));
    await writeFile(join(root, "dir", "file.txt"), "x");
    await symlink(root, join(root, "dir", "back"));

    const tools = createFsIntegration({ root });
    await expect(tools.glob.handler({ pattern: "**/*.txt" }, ctx)).resolves.toEqual({
      matches: ["dir/file.txt"],
    });
  });

  it("rejects an outside symlink rather than silently omitting it", async () => {
    const outside = await mkdtemp(join(tmpdir(), "kaji-fs-limits-outside-"));
    try {
      await writeFile(join(outside, "secret.txt"), "secret");
      await symlink(join(outside, "secret.txt"), join(root, "secret.txt"));
      const tools = createFsIntegration({ root });
      await expect(tools.glob.handler({ pattern: "**/*" }, ctx)).rejects.toThrow(
        /escape.*sandbox/i,
      );
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it.skipIf(process.getuid?.() === 0)(
    "surfaces unreadable directory failures with their path",
    async () => {
      const denied = join(root, "denied");
      await mkdir(denied);
      await chmod(denied, 0);
      const tools = createFsIntegration({ root });
      await expect(tools.list.handler({ path: "denied" }, ctx)).rejects.toThrow(denied);
      await chmod(denied, 0o700);
    },
  );

  it("applies the same limits to directory listings", async () => {
    await writeFile(join(root, "a.txt"), "aa");
    await writeFile(join(root, "b.txt"), "bbb");
    const policy: FsIntegrationPolicy = { root, maxVisitedEntries: 1 };
    await expect(createFsIntegration(policy).list.handler({ path: "." }, ctx)).rejects.toThrow(
      /maxVisitedEntries/,
    );
    await expect(
      createFsIntegration({ root, maxTotalBytes: 4 }).list.handler({ path: "." }, ctx),
    ).rejects.toThrow(/maxTotalBytes/);
  });

  it("pins root identity and rejects a replaced root symlink", async () => {
    const base = await mkdtemp(join(tmpdir(), "kaji-fs-root-swap-"));
    try {
      const first = join(base, "first");
      const second = join(base, "second");
      const rootLink = join(base, "root");
      await mkdir(first);
      await mkdir(second);
      await writeFile(join(first, "value.txt"), "first");
      await writeFile(join(second, "value.txt"), "second");
      await symlink(first, rootLink);
      const tools = createFsIntegration({ root: rootLink });

      await unlink(rootLink);
      await symlink(second, rootLink);
      await expect(tools.read.handler({ path: "value.txt" }, ctx)).rejects.toThrow(
        /sandbox root changed/i,
      );
    } finally {
      await rm(base, { recursive: true, force: true });
    }
  });

  it.skipIf(process.platform === "win32")(
    "rejects FIFOs for reads and writes without blocking",
    async () => {
      const fifo = join(root, "pipe");
      execFileSync("mkfifo", [fifo]);
      const tools = createFsIntegration({ root });
      await expect(tools.read.handler({ path: "pipe" }, ctx)).rejects.toThrow(/not a regular file/);
      await expect(tools.write.handler({ path: "pipe", content: "data" }, ctx)).rejects.toThrow(
        /not a regular file/,
      );
    },
  );

  it("rejects pre-cancelled reads before opening the file", async () => {
    await writeFile(join(root, "value.txt"), "value");
    const controller = new AbortController();
    controller.abort(new Error("cancel filesystem"));
    const tools = createFsIntegration({ root });
    await expect(
      tools.read.handler({ path: "value.txt" }, { ...ctx, signal: controller.signal }),
    ).rejects.toThrow("cancel filesystem");
  });
});
