/**
 * Tests for bun-io helpers, exercising both the Bun-native branch and the
 * node:fs/promises fallback (forced by stubbing out globalThis.Bun).
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { readTextFile, writeTextFile, copyFileBunFirst } from "@/cli/bun-io";

const realBun = globalThis.Bun;

describe.each([
  ["Bun runtime", false],
  ["node:fs/promises fallback", true],
])("bun-io (%s)", (_label, forceFallback) => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(join(tmpdir(), "kaji-bun-io-"));
    if (forceFallback) {
      delete (globalThis as { Bun?: typeof Bun }).Bun;
    }
  });

  afterEach(() => {
    globalThis.Bun = realBun;
    rmSync(tmp, { recursive: true, force: true });
  });

  it("writes then reads back matching text content", async () => {
    const path = join(tmp, "hello.txt");
    await writeTextFile(path, "hello world");

    const content = await readTextFile(path);

    expect(content).toBe("hello world");
  });

  it("copies a file byte-identical to the source", async () => {
    const src = join(tmp, "src.txt");
    const dest = join(tmp, "dest.txt");
    await writeTextFile(src, "copy me please");

    await copyFileBunFirst(src, dest);

    expect(readFileSync(dest)).toEqual(readFileSync(src));
  });
});
