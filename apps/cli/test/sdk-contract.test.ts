import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PYTHON_SDK_RANGE } from "../src/templates/python-agent.js";
import {
  TYPESCRIPT_PROVIDER_RANGES,
  TYPESCRIPT_SDK_RANGE,
  ZOD_RANGE,
} from "../src/templates/typescript-agent.js";

interface PackageMetadata {
  version: string;
  peerDependencies: Record<string, string>;
}

const typescriptPackage = JSON.parse(
  readFileSync(new URL("../../../kaji/packages/typescript/package.json", import.meta.url), "utf8"),
) as PackageMetadata;
const pythonProject = readFileSync(
  new URL("../../../kaji/packages/python/pyproject.toml", import.meta.url),
  "utf8",
);

describe("SDK scaffold contract", () => {
  it("tracks the TypeScript beta version and peer ranges", () => {
    expect(TYPESCRIPT_SDK_RANGE).toBe(`^${typescriptPackage.version}`);
    expect(ZOD_RANGE).toBe(typescriptPackage.peerDependencies.zod);
    expect(TYPESCRIPT_PROVIDER_RANGES.openai.openai).toBe(
      typescriptPackage.peerDependencies.openai,
    );
    expect(TYPESCRIPT_PROVIDER_RANGES.anthropic["@anthropic-ai/sdk"]).toBe(
      typescriptPackage.peerDependencies["@anthropic-ai/sdk"],
    );
  });

  it("tracks the Python beta version", () => {
    const version = pythonProject.match(/^version = "([^"]+)"$/m)?.[1];

    expect(version).toBeDefined();
    expect(PYTHON_SDK_RANGE).toContain(`>=${version}`);
  });
});
