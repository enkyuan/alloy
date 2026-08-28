type BunRuntime = typeof Bun;

function bunRuntime(): BunRuntime | undefined {
  return (globalThis as { Bun?: BunRuntime }).Bun;
}

export async function readTextFile(path: string): Promise<string> {
  const bun = bunRuntime();
  if (bun) {
    return bun.file(path).text();
  }
  const { readFile } = await import("node:fs/promises");
  return readFile(path, "utf8");
}

export async function writeTextFile(path: string, content: string): Promise<void> {
  const bun = bunRuntime();
  if (bun) {
    await bun.write(path, content);
    return;
  }
  const { writeFile } = await import("node:fs/promises");
  await writeFile(path, content, "utf8");
}

export async function copyFileBunFirst(src: string, dest: string): Promise<void> {
  const bun = bunRuntime();
  if (bun) {
    await bun.write(dest, bun.file(src));
    return;
  }
  const { copyFile } = await import("node:fs/promises");
  await copyFile(src, dest);
}
