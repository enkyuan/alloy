import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export function readNearestPackageJson(cwd: string): Record<string, unknown> | null {
  let dir = resolve(cwd);
  while (true) {
    const candidate = join(dir, "package.json");
    if (existsSync(candidate)) {
      try {
        return JSON.parse(readFileSync(candidate, "utf-8"));
      } catch {
        return null;
      }
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}
