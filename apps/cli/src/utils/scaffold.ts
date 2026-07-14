import {
  constants,
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  writeFileSync,
} from "node:fs";
import { basename, join } from "node:path";

export interface ScaffoldFile {
  name: string;
  contents: string;
}

function assertSafeFileName(name: string): void {
  if (!name || name === "." || name === ".." || basename(name) !== name || name.includes("\0")) {
    throw new Error(`unsafe scaffold file name: ${JSON.stringify(name)}`);
  }
}

function assertSafeTarget(target: string): void {
  const stat = lstatSync(target);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error("unsafe scaffold destination: target must be a real directory");
  }
}

function inspectDestination(path: string): "missing" | "file" {
  if (!existsSync(path)) return "missing";
  const stat = lstatSync(path);
  if (stat.isSymbolicLink()) {
    throw new Error("unsafe scaffold destination: symbolic links are not allowed");
  }
  if (!stat.isFile()) {
    throw new Error("unsafe scaffold destination: expected a regular file");
  }
  return "file";
}

function writeRegularFile(path: string, contents: string, overwrite: boolean): void {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const flags =
    constants.O_WRONLY |
    constants.O_CREAT |
    noFollow |
    (overwrite ? constants.O_TRUNC : constants.O_EXCL);
  const descriptor = openSync(path, flags, 0o644);
  try {
    writeFileSync(descriptor, contents, { encoding: "utf8" });
  } finally {
    closeSync(descriptor);
  }
}

/**
 * Publish a scaffold only after every destination passes the same preflight.
 * Existing files make the non-force operation a no-op, and symlinks are never
 * followed, including when `--force` is set.
 */
export function writeScaffoldFiles(
  target: string,
  files: readonly ScaffoldFile[],
  force: boolean,
): string[] {
  mkdirSync(target, { recursive: true });
  assertSafeTarget(target);

  const destinations = files.map((file) => {
    assertSafeFileName(file.name);
    const path = join(target, file.name);
    return { ...file, path, state: inspectDestination(path) };
  });

  if (!force && destinations.some((destination) => destination.state === "file")) return [];

  for (const destination of destinations) {
    assertSafeTarget(target);
    writeRegularFile(destination.path, destination.contents, force);
  }
  return destinations.map((destination) => destination.name);
}
