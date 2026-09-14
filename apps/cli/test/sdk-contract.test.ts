import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  TYPESCRIPT_SDK_PACKAGE,
  TYPESCRIPT_PROVIDER_RANGES,
  TYPESCRIPT_SDK_RANGE,
  ZOD_RANGE,
} from "../src/templates/typescript-agent.js";

interface PackageMetadata {
  name: string;
  version: string;
  peerDependencies: Record<string, string>;
}

const typescriptPackage = JSON.parse(
  readFileSync(new URL("../../../kaji/packages/ts/package.json", import.meta.url), "utf8"),
) as PackageMetadata;
const cliDocs = readFileSync(new URL("../../docs/content/cli.mdx", import.meta.url), "utf8");

describe("SDK scaffold contract", () => {
  it("tracks the TypeScript alpha package, version, and peer ranges", () => {
    expect(TYPESCRIPT_SDK_PACKAGE).toBe(typescriptPackage.name);
    expect(TYPESCRIPT_SDK_RANGE).toBe(typescriptPackage.version);
    expect(cliDocs).toContain(`${TYPESCRIPT_SDK_PACKAGE}@${TYPESCRIPT_SDK_RANGE}`);
    expect(ZOD_RANGE).toBe(typescriptPackage.peerDependencies.zod);
    // The TypeScript capability cut removed the OpenAI and Anthropic provider
    // adapters and their package peers from @irogane/kaji; assert absence
    // rather than a range so the scaffold contract stays in step with the
    // package's actual peer surface.
    expect(TYPESCRIPT_PROVIDER_RANGES.openai).toEqual({ openai: ">=4 <8" });
    expect(TYPESCRIPT_PROVIDER_RANGES.anthropic["@anthropic-ai/sdk"]).toEqual(">=0.30 <2");
    expect(typescriptPackage.peerDependencies).not.toHaveProperty("openai");
    expect(typescriptPackage.peerDependencies).not.toHaveProperty("@anthropic-ai/sdk");
  });
});
