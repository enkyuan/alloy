/** Descriptor-pinned worker for initially absent integration destinations. */
import { constants } from "node:fs";
import { copyFile, lstat, mkdir } from "node:fs/promises";
import { dirname, isAbsolute, join } from "node:path";

const MAX_COMMAND_BYTES = 32;

function safeRelativePath(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    isAbsolute(value) ||
    value.includes("\0")
  ) {
    return false;
  }
  const parts = value.split("/");
  return parts.every(
    (part) => part.length > 0 && part !== "." && part !== ".." && !part.includes("\\"),
  );
}

async function readCommand() {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.byteLength;
    if (bytes > MAX_COMMAND_BYTES) throw new Error("invalid integration copy command");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main() {
  const [expectedDev, expectedIno, staging, ...relativePaths] = process.argv.slice(2);
  if (
    expectedDev === undefined ||
    !/^\d+$/.test(expectedDev) ||
    expectedIno === undefined ||
    !/^\d+$/.test(expectedIno) ||
    staging === undefined ||
    !isAbsolute(staging) ||
    relativePaths.length === 0 ||
    relativePaths.length > 64 ||
    new Set(relativePaths).size !== relativePaths.length ||
    !relativePaths.every(safeRelativePath)
  ) {
    throw new Error("invalid integration copy request");
  }

  // This must remain the worker's first filesystem operation. The process cwd
  // is bound by the kernel during spawn, so every relative write below targets
  // this inode even if the destination pathname is concurrently replaced.
  const cwd = await lstat(".", { bigint: true });
  if (!cwd.isDirectory() || cwd.dev !== BigInt(expectedDev) || cwd.ino !== BigInt(expectedIno)) {
    throw new Error("pinned integration destination identity mismatch");
  }
  process.stdout.write("prepared\n");
  if ((await readCommand()) !== "commit\n") throw new Error("integration copy cancelled");

  for (const relativePath of relativePaths) {
    const target = join(".", ...relativePath.split("/"));
    await mkdir(dirname(target), { recursive: true });
    await copyFile(join(staging, ...relativePath.split("/")), target, constants.COPYFILE_EXCL);
  }
  process.stdout.write("ok\n");
}

main().catch(() => {
  process.exitCode = 1;
});
