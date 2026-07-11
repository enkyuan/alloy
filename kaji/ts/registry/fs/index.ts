// This is YOUR fs integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Adjust resource limits for your workload
//   4. Add helper tools your agent wants (e.g. move, copy, delete)
// Updates: re-run `kaji add fs` to diff against the latest version we ship.

import { functionTool, type ToolExecutionContext } from "@kaji/sdk";
import { constants, realpathSync, statSync, type Dirent } from "node:fs";
import { lstat, mkdir, open, opendir, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import * as z from "zod";

const DEFAULT_MAX_DEPTH = 32;
const DEFAULT_MAX_VISITED_ENTRIES = 10_000;
const DEFAULT_MAX_FILE_BYTES = 1_048_576;
const DEFAULT_MAX_TOTAL_BYTES = 10_485_760;
const DEFAULT_MAX_WRITE_BYTES = 1_048_576;

export interface FsIntegrationPolicy {
  readonly root: string;
  readonly maxDepth?: number;
  readonly maxVisitedEntries?: number;
  readonly maxFileBytes?: number;
  readonly maxTotalBytes?: number;
  readonly maxWriteBytes?: number;
}

interface FsLimits {
  readonly maxDepth: number;
  readonly maxVisitedEntries: number;
  readonly maxFileBytes: number;
  readonly maxTotalBytes: number;
  readonly maxWriteBytes: number;
}

function positiveLimit(value: number | undefined, fallback: number, name: string): number {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < 1) {
    throw new RangeError(`${name} must be a positive safe integer`);
  }
  return result;
}

function policyLimits(policy: FsIntegrationPolicy): FsLimits {
  if (typeof policy?.root !== "string" || policy.root.trim().length === 0) {
    throw new TypeError("filesystem root is required");
  }
  return {
    maxDepth: positiveLimit(policy.maxDepth, DEFAULT_MAX_DEPTH, "maxDepth"),
    maxVisitedEntries: positiveLimit(
      policy.maxVisitedEntries,
      DEFAULT_MAX_VISITED_ENTRIES,
      "maxVisitedEntries",
    ),
    maxFileBytes: positiveLimit(policy.maxFileBytes, DEFAULT_MAX_FILE_BYTES, "maxFileBytes"),
    maxTotalBytes: positiveLimit(policy.maxTotalBytes, DEFAULT_MAX_TOTAL_BYTES, "maxTotalBytes"),
    maxWriteBytes: positiveLimit(policy.maxWriteBytes, DEFAULT_MAX_WRITE_BYTES, "maxWriteBytes"),
  };
}

function isInside(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`));
}

function sandboxEscapeError(path: string): Error {
  return new Error(`Path escapes sandbox root: ${JSON.stringify(path)}`);
}

function assertInsideSandbox(root: string, candidate: string, unsafePath: string): void {
  if (!isInside(root, candidate)) throw sandboxEscapeError(unsafePath);
}

function errorCode(error: unknown): string | undefined {
  return error instanceof Error && "code" in error
    ? (error as NodeJS.ErrnoException).code
    : undefined;
}

function operationError(operation: string, path: string, cause: unknown): Error {
  const detail = cause instanceof Error ? `: ${cause.message}` : "";
  return new Error(`${operation} failed for ${JSON.stringify(path)}${detail}`, { cause });
}

interface RootIdentity {
  readonly requested: string;
  readonly real: string;
  readonly device: bigint;
  readonly inode: bigint;
}

function pinRoot(root: string): RootIdentity {
  const requested = resolve(root);
  const real = realpathSync(requested);
  const info = statSync(real, { bigint: true });
  if (!info.isDirectory()) throw new TypeError("filesystem root must be a directory");
  return { requested, real, device: info.dev, inode: info.ino };
}

async function assertRootStable(root: RootIdentity): Promise<void> {
  try {
    const currentReal = await realpath(root.requested);
    const info = await stat(currentReal, { bigint: true });
    if (currentReal !== root.real || info.dev !== root.device || info.ino !== root.inode) {
      throw new Error("identity changed");
    }
  } catch (error) {
    throw new Error(`Filesystem sandbox root changed: ${JSON.stringify(root.requested)}`, {
      cause: error,
    });
  }
}

async function deepestExisting(path: string): Promise<string> {
  let probe = path;
  while (probe !== dirname(probe)) {
    try {
      await realpath(probe);
      return probe;
    } catch (error) {
      if (errorCode(error) !== "ENOENT") throw error;
      probe = dirname(probe);
    }
  }
  return probe;
}

async function sandboxResolve(
  root: string,
  unsafePath: string,
  mode: "read" | "write",
): Promise<string> {
  const resolved = resolve(root, unsafePath);
  if (!isInside(root, resolved)) throw sandboxEscapeError(unsafePath);

  try {
    const targetReal = await realpath(resolved);
    assertInsideSandbox(root, targetReal, unsafePath);
    return targetReal;
  } catch (error) {
    if (errorCode(error) !== "ENOENT" || mode === "read") throw error;
  }

  try {
    if ((await lstat(resolved)).isSymbolicLink()) throw sandboxEscapeError(unsafePath);
  } catch (error) {
    if (errorCode(error) !== "ENOENT") throw error;
  }

  const parent = await deepestExisting(dirname(resolved));
  const parentReal = await realpath(parent);
  assertInsideSandbox(root, parentReal, unsafePath);
  return resolved;
}

function throwIfCancelled(context: ToolExecutionContext): void {
  if (!context.signal.aborted) return;
  if (context.signal.reason instanceof Error) throw context.signal.reason;
  throw new DOMException("Filesystem operation cancelled", "AbortError");
}

function addVisited(current: number, limits: FsLimits): number {
  const next = current + 1;
  if (next > limits.maxVisitedEntries) {
    throw new RangeError(
      `Filesystem operation exceeds maxVisitedEntries (${limits.maxVisitedEntries})`,
    );
  }
  return next;
}

function addBytes(current: number, size: number, limits: FsLimits): number {
  const next = current + size;
  if (size > limits.maxFileBytes) {
    throw new RangeError(`File exceeds maxFileBytes (${limits.maxFileBytes})`);
  }
  if (next > limits.maxTotalBytes) {
    throw new RangeError(`Filesystem operation exceeds maxTotalBytes (${limits.maxTotalBytes})`);
  }
  return next;
}

async function boundedDirectoryEntries(
  directory: string,
  remaining: number,
  operation: "list" | "glob",
  context: ToolExecutionContext,
): Promise<Dirent[]> {
  let handle;
  try {
    handle = await opendir(directory);
    const entries: Dirent[] = [];
    while (true) {
      throwIfCancelled(context);
      const entry = await handle.read();
      if (entry === null) break;
      if (entries.length >= remaining) {
        throw new RangeError(
          `Filesystem operation exceeds maxVisitedEntries (${remaining + entries.length})`,
        );
      }
      entries.push(entry);
    }
    return entries.sort((left, right) => left.name.localeCompare(right.name));
  } catch (error) {
    if (error instanceof RangeError || error instanceof DOMException) throw error;
    throw operationError(operation, directory, error);
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function boundedRead(
  path: string,
  limits: FsLimits,
  context: ToolExecutionContext,
): Promise<string> {
  throwIfCancelled(context);
  let handle;
  try {
    const before = await lstat(path);
    if (!before.isFile()) throw new Error("target is not a regular file");
    handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const info = await handle.stat();
    if (!info.isFile()) throw new Error("target is not a regular file");
    if (info.size > limits.maxFileBytes || info.size > limits.maxTotalBytes) {
      throw new RangeError(
        `File exceeds read byte limit (${Math.min(limits.maxFileBytes, limits.maxTotalBytes)})`,
      );
    }
    const cap = Math.min(limits.maxFileBytes, limits.maxTotalBytes);
    const chunks: Buffer[] = [];
    let total = 0;
    while (total <= cap) {
      throwIfCancelled(context);
      const chunk = Buffer.allocUnsafe(Math.min(64 * 1024, cap + 1 - total));
      const { bytesRead } = await handle.read(chunk, 0, chunk.byteLength, null);
      if (bytesRead === 0) break;
      total += bytesRead;
      if (total > cap) throw new RangeError(`File exceeds read byte limit (${cap})`);
      chunks.push(chunk.subarray(0, bytesRead));
    }
    return Buffer.concat(chunks, total).toString("utf8");
  } catch (error) {
    if (error instanceof RangeError || error instanceof DOMException) throw error;
    throw operationError("read", path, error);
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function boundedWrite(
  path: string,
  content: string,
  limits: FsLimits,
  context: ToolExecutionContext,
): Promise<number> {
  const bytes = Buffer.byteLength(content, "utf8");
  if (bytes > limits.maxWriteBytes) {
    throw new RangeError(`Write exceeds maxWriteBytes (${limits.maxWriteBytes})`);
  }
  throwIfCancelled(context);
  let handle;
  try {
    try {
      const before = await lstat(path);
      if (!before.isFile()) throw new Error("target is not a regular file");
    } catch (error) {
      if (errorCode(error) !== "ENOENT") throw error;
    }
    handle = await open(
      path,
      constants.O_WRONLY | constants.O_CREAT | constants.O_NOFOLLOW | constants.O_NONBLOCK,
      0o666,
    );
    const info = await handle.stat();
    if (!info.isFile()) throw new Error("target is not a regular file");
    throwIfCancelled(context);
    await handle.truncate(0);
    await handle.writeFile(content, "utf8");
    return bytes;
  } catch (error) {
    if (error instanceof RangeError || error instanceof DOMException) throw error;
    throw operationError("write", path, error);
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

interface ListedEntry {
  readonly name: string;
  readonly isDir: boolean;
}

async function boundedList(
  directory: string,
  rootReal: string,
  limits: FsLimits,
  context: ToolExecutionContext,
  verifyRoot: () => Promise<void>,
): Promise<ListedEntry[]> {
  await verifyRoot();
  const entries = await boundedDirectoryEntries(
    directory,
    limits.maxVisitedEntries,
    "list",
    context,
  );
  const result: ListedEntry[] = [];
  let visited = 0;
  let bytes = 0;
  for (const entry of entries) {
    throwIfCancelled(context);
    await verifyRoot();
    visited = addVisited(visited, limits);
    const path = join(directory, entry.name);
    try {
      const targetReal = await realpath(path);
      assertInsideSandbox(rootReal, targetReal, path);
      const info = await stat(targetReal);
      if (info.isFile()) bytes = addBytes(bytes, info.size, limits);
      result.push({ name: entry.name, isDir: info.isDirectory() });
    } catch (error) {
      if (
        error instanceof RangeError ||
        (error instanceof Error && error.message.startsWith("Path escapes"))
      ) {
        throw error;
      }
      throw operationError("list", path, error);
    }
  }
  return result;
}

async function walkDir(
  root: string,
  rootReal: string,
  limits: FsLimits,
  context: ToolExecutionContext,
  verifyRoot: () => Promise<void>,
): Promise<string[]> {
  const queue: Array<{ directory: string; depth: number }> = [{ directory: root, depth: 0 }];
  const visitedDirectories = new Set<string>();
  const files: string[] = [];
  let queueIndex = 0;
  let visited = 0;
  let bytes = 0;

  while (queueIndex < queue.length) {
    throwIfCancelled(context);
    await verifyRoot();
    const { directory, depth } = queue[queueIndex++]!;
    let directoryReal: string;
    let directoryInfo;
    try {
      directoryReal = await realpath(directory);
      assertInsideSandbox(rootReal, directoryReal, directory);
      directoryInfo = await stat(directoryReal);
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("Path escapes")) throw error;
      throw operationError("glob", directory, error);
    }
    const identity = `${directoryInfo.dev}:${directoryInfo.ino}`;
    if (visitedDirectories.has(identity)) continue;
    visitedDirectories.add(identity);

    const entries = await boundedDirectoryEntries(
      directoryReal,
      limits.maxVisitedEntries - visited,
      "glob",
      context,
    );
    for (const entry of entries) {
      throwIfCancelled(context);
      await verifyRoot();
      visited = addVisited(visited, limits);
      const path = join(directoryReal, entry.name);
      try {
        const entryInfo = await lstat(path);
        const targetReal = await realpath(path);
        assertInsideSandbox(rootReal, targetReal, path);
        const targetInfo = await stat(targetReal);
        if (entryInfo.isSymbolicLink() && targetInfo.isDirectory()) continue;
        if (targetInfo.isDirectory()) {
          const nextDepth = depth + 1;
          if (nextDepth > limits.maxDepth) {
            throw new RangeError(`Filesystem operation exceeds maxDepth (${limits.maxDepth})`);
          }
          queue.push({ directory: targetReal, depth: nextDepth });
        } else if (targetInfo.isFile()) {
          bytes = addBytes(bytes, targetInfo.size, limits);
          files.push(path);
        }
      } catch (error) {
        if (
          error instanceof RangeError ||
          (error instanceof Error && error.message.startsWith("Path escapes"))
        ) {
          throw error;
        }
        throw operationError("glob", path, error);
      }
    }
  }
  return files.sort((left, right) => left.localeCompare(right));
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

export function createFsIntegration(policy: FsIntegrationPolicy): {
  list: ReturnType<typeof functionTool>;
  read: ReturnType<typeof functionTool>;
  write: ReturnType<typeof functionTool>;
  glob: ReturnType<typeof functionTool>;
} {
  const limits = policyLimits(policy);
  const root = pinRoot(policy.root);
  const verifyRoot = () => assertRootStable(root);

  const fsList = functionTool(
    {
      name: "list",
      namespace: "fs",
      description: "List files in a sandboxed directory within configured resource limits.",
      parameters: z.object({ path: z.string().default(".") }),
      risk: "read",
    },
    async ({ path }, context) => {
      const unsafePath = path ?? ".";
      await verifyRoot();
      const safe = await sandboxResolve(root.real, unsafePath, "read");
      await verifyRoot();
      const rechecked = await sandboxResolve(root.real, unsafePath, "read");
      if (safe !== rechecked) throw new Error("Filesystem target changed during validation");
      return {
        entries: await boundedList(rechecked, root.real, limits, context, verifyRoot),
      };
    },
  );

  const fsRead = functionTool(
    {
      name: "read",
      namespace: "fs",
      description: "Read a bounded file within the configured sandbox root.",
      parameters: z.object({ path: z.string() }),
      risk: "read",
    },
    async ({ path }, context) => {
      await verifyRoot();
      await sandboxResolve(root.real, path, "read");
      await verifyRoot();
      const safe = await sandboxResolve(root.real, path, "read");
      await verifyRoot();
      return { content: await boundedRead(safe, limits, context) };
    },
  );

  const fsWrite = functionTool(
    {
      name: "write",
      namespace: "fs",
      description: "Write bounded UTF-8 content within the configured sandbox root.",
      parameters: z.object({ path: z.string(), content: z.string() }),
      risk: "write",
    },
    async ({ path, content }, context) => {
      if (Buffer.byteLength(content, "utf8") > limits.maxWriteBytes) {
        throw new RangeError(`Write exceeds maxWriteBytes (${limits.maxWriteBytes})`);
      }
      await verifyRoot();
      const safe = await sandboxResolve(root.real, path, "write");
      await mkdir(dirname(safe), { recursive: true });
      await verifyRoot();
      const rechecked = await sandboxResolve(root.real, path, "write");
      await verifyRoot();
      return { written: await boundedWrite(rechecked, content, limits, context) };
    },
  );

  const fsGlob = functionTool(
    {
      name: "glob",
      namespace: "fs",
      description: "Glob deterministically within configured depth, entry, and byte limits.",
      parameters: z.object({ pattern: z.string() }),
      risk: "read",
    },
    async ({ pattern }, context) => {
      await verifyRoot();
      const allFiles = await walkDir(root.real, root.real, limits, context, verifyRoot);
      const regex = globToRegex(pattern);
      const matches = allFiles
        .map((file) => relative(root.real, file).split(sep).join("/"))
        .filter((path) => regex.test(path));
      return { matches };
    },
  );

  return { list: fsList, read: fsRead, write: fsWrite, glob: fsGlob };
}
