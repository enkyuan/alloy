import { readFileSync } from "node:fs";

interface PackageIdentity {
  readonly name: string;
  readonly version: string;
}

export const TYPESCRIPT_SDK_CLI = `bun --no-install -e 'import("@kaji/sdk/cli")' --`;

export function packageIdentity(): PackageIdentity {
  const value = JSON.parse(
    readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
  ) as Partial<PackageIdentity>;
  if (
    value.name !== "@kaji/sdk" ||
    typeof value.version !== "string" ||
    value.version.length === 0
  ) {
    throw new Error("installed @kaji/sdk package metadata is incomplete");
  }
  return { name: value.name, version: value.version };
}
