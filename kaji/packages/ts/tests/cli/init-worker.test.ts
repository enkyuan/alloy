import { existsSync, lstatSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { runInitWorkerRequest } from "@/cli/init";

const previousCwd = process.cwd();
const directories: string[] = [];

function scratch(): string {
  const dir = mkdtempSync(join(tmpdir(), "kaji-init-worker-"));
  directories.push(dir);
  return dir;
}

function handshakeRequest(dir: string, overrides: Record<string, unknown> = {}) {
  const stat = lstatSync(dir, { bigint: true });
  return {
    version: 1,
    expectedDev: String(stat.dev),
    expectedIno: String(stat.ino),
    targetAbsolute: resolve(dir),
    files: { "hello.txt": "hi" },
    force: false,
    ...overrides,
  };
}

afterEach(() => {
  process.chdir(previousCwd);
});

describe("init scaffold worker request (in-process)", () => {
  it("writes the scaffold when the pinned directory identity matches", async () => {
    const dir = scratch();
    process.chdir(dir);

    await runInitWorkerRequest(handshakeRequest(dir));

    expect(readFileSync(join(dir, "hello.txt"), "utf8")).toBe("hi");
  });

  it("rejects malformed requests before touching the filesystem", async () => {
    const dir = scratch();
    process.chdir(dir);

    await expect(runInitWorkerRequest({ ...handshakeRequest(dir), version: 2 })).rejects.toThrow(
      "invalid scaffold worker request",
    );
    await expect(
      runInitWorkerRequest({ ...handshakeRequest(dir), expectedDev: "12x" }),
    ).rejects.toThrow("invalid scaffold worker request");
    await expect(runInitWorkerRequest(null)).rejects.toThrow("invalid scaffold worker request");
    expect(existsSync(join(dir, "hello.txt"))).toBe(false);
  });

  it("rejects a pinned directory identity mismatch", async () => {
    const dir = scratch();
    process.chdir(dir);

    await expect(
      runInitWorkerRequest(handshakeRequest(dir, { expectedDev: "999999" })),
    ).rejects.toThrow("pinned scaffold directory identity mismatch");
  });

  it("forwards an abort signal and stops before writing", async () => {
    const dir = scratch();
    process.chdir(dir);
    const controller = new AbortController();
    controller.abort();

    await expect(
      runInitWorkerRequest(handshakeRequest(dir), { signal: controller.signal }),
    ).rejects.toThrow();
    expect(existsSync(join(dir, "hello.txt"))).toBe(false);
  });
});
