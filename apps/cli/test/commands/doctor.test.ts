import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { doctor, runChecks } from "../../src/commands/doctor.js";

describe("doctor.runChecks", () => {
  it("flags missing provider env", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({
        dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6", openai: "6.42.0" },
      }),
    );
    const out = runChecks({
      cwd: dir,
      env: { KAJI_MODEL_PROVIDER: "openai" },
      nodeVersion: "v22.0.0",
    });
    expect(out.failed).toBe(true);
    expect(out.checks.find((c) => c.name === "provider key")?.ok).toBe(false);
    expect(out.checks.find((c) => c.name === "provider key")?.hint).toContain("OPENAI_API_KEY");
  });

  it("passes when sdk and provider key are present", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({
        dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6", openai: "6.42.0" },
      }),
    );
    const out = runChecks({
      cwd: dir,
      env: { KAJI_MODEL_PROVIDER: "openai", OPENAI_API_KEY: "sk" },
      nodeVersion: "v22.0.0",
    });
    expect(out.failed).toBe(false);
  });

  it("passes a no-key mock scaffold with the required TypeScript peers", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=mock\n");
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6" } }),
    );

    const out = runChecks({ cwd: dir, env: {}, nodeVersion: "v24.0.0" });

    expect(out.failed).toBe(false);
    expect(out.checks.some((check) => check.name === "provider key")).toBe(false);
  });

  it("flags a missing required Zod peer", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=mock\n");
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "kaji-sdk": "0.2.0-beta.7" } }),
    );

    const out = runChecks({ cwd: dir, env: {}, nodeVersion: "v22.0.0" });

    expect(out.failed).toBe(true);
    expect(out.checks.find((check) => check.name === "zod installed")?.ok).toBe(false);
  });

  it("flags missing TypeScript provider package for anthropic", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=anthropic\n");
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6" } }),
    );
    const out = runChecks({
      cwd: dir,
      env: { ANTHROPIC_API_KEY: "sk-ant" },
      nodeVersion: "v22.0.0",
      lang: "ts",
    });
    const check = out.checks.find((c) => c.name === "@anthropic-ai/sdk installed");
    expect(out.failed).toBe(true);
    expect(check?.ok).toBe(false);
    expect(check?.hint).toContain("bun add @anthropic-ai/sdk");
  });

  it("checks Python scaffolds without requiring package.json", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, "agent.py"), "print('hello')\n");
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=openai\n");
    writeFileSync(join(dir, "requirements.txt"), "kaji-sdk[openai]>=0.2.0b1,<0.3\n");
    const out = runChecks({
      cwd: dir,
      env: { OPENAI_API_KEY: "sk" },
      nodeVersion: "v22.0.0",
      lang: "python",
      runCommand: () => ({ ok: true, stdout: "Python 3.11.9\n", stderr: "" }),
    });
    expect(out.failed).toBe(false);
    expect(out.checks.find((c) => c.name === "python >= 3.11")?.ok).toBe(true);
    expect(out.checks.find((c) => c.name === "kaji-sdk Python distribution declared")?.ok).toBe(
      true,
    );
    expect(out.checks.some((c) => c.name === "kaji-sdk installed")).toBe(false);
  });

  it("auto-detects package.json as a TypeScript signal in mixed scaffolds", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=openai\n");
    writeFileSync(join(dir, "requirements.txt"), "kaji-sdk[openai]>=0.2.0b1,<0.3\n");
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({
        dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6", openai: "6.42.0" },
      }),
    );
    const out = runChecks({
      cwd: dir,
      env: { OPENAI_API_KEY: "sk" },
      nodeVersion: "v22.0.0",
      runCommand: () => ({ ok: true, stdout: "Python 3.11.9\n", stderr: "" }),
    });
    expect(out.failed).toBe(false);
    expect(out.checks.find((c) => c.name === "kaji-sdk installed")?.ok).toBe(true);
    expect(out.checks.find((c) => c.name === "python >= 3.11")?.ok).toBe(true);
  });

  it("flags old Python versions", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=openai\n");
    writeFileSync(join(dir, "requirements.txt"), "kaji-sdk[openai]>=0.2.0b1,<0.3\n");
    const out = runChecks({
      cwd: dir,
      env: { OPENAI_API_KEY: "sk" },
      nodeVersion: "v22.0.0",
      lang: "python",
      runCommand: () => ({ ok: true, stdout: "Python 3.10.13\n", stderr: "" }),
    });
    expect(out.failed).toBe(true);
    expect(out.checks.find((c) => c.name === "python >= 3.11")?.ok).toBe(false);
  });

  it("fails closed for a provider outside the beta scaffold contract", () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-doc-"));
    writeFileSync(join(dir, ".env.example"), "KAJI_MODEL_PROVIDER=gemini\n");
    writeFileSync(
      join(dir, "package.json"),
      JSON.stringify({ dependencies: { "kaji-sdk": "0.2.0-beta.7", zod: "4.3.6" } }),
    );

    const out = runChecks({ cwd: dir, env: {}, nodeVersion: "v22.0.0" });

    expect(out.failed).toBe(true);
    expect(out.checks.find((check) => check.name === "supported provider")?.ok).toBe(false);
  });

  it("rejects an unsupported language as a usage error", async () => {
    const previousExitCode = process.exitCode;
    process.exitCode = undefined;

    await doctor.parseAsync(["node", "kaji", "--lang", "ruby", "--json"]);

    expect(process.exitCode).toBe(2);
    process.exitCode = previousExitCode;
  });
});
