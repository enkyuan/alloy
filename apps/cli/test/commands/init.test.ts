import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { init } from "../../src/commands/init.js";

describe("init command", () => {
  it("ts non-interactive scaffolds agent.ts and .env.example", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "openai",
      "--yes",
    ]);
    expect(existsSync(join(dir, "package.json"))).toBe(true);
    expect(existsSync(join(dir, "tsconfig.json"))).toBe(true);
    expect(existsSync(join(dir, "agent.ts"))).toBe(true);
    expect(existsSync(join(dir, ".env.example"))).toBe(true);
    const agent = readFileSync(join(dir, "agent.ts"), "utf-8");
    expect(agent).toMatch(/@kaji\/sdk/);
    // Provider is wired at scaffold time via a factory call, not a runtime env switch.
    expect(agent).toMatch(/\.provider\(openai\(\)\)/);
    expect(agent).toMatch(/\.turn\("Say hello\."\)/);
    expect(agent).not.toMatch(/EventBus|InMemoryEventStore|KajiEvent|SESSION_CREATED|runtime\.send/);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.dependencies["@kaji/sdk"]).toBe("^0.1.0");
    expect(pkg.dependencies.openai).toBe("^6.42.0");
  });

  it("ts --provider kimi wires the kimi() factory", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "kimi",
      "--yes",
    ]);
    const agent = readFileSync(join(dir, "agent.ts"), "utf-8");
    expect(agent).toMatch(/\bkimi\b/);
    expect(agent).toMatch(/\.provider\(kimi\(\)\)/);
    expect(agent).not.toMatch(/\.provider\(openai\(\)\)/);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.dependencies.openai).toBe("^6.42.0");
  });

  it("ts --provider gemini wires the gemini() factory", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "gemini",
      "--yes",
    ]);
    const agent = readFileSync(join(dir, "agent.ts"), "utf-8");
    expect(agent).toMatch(/\.provider\(gemini\(\)\)/);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.dependencies.openai).toBe("^6.42.0");
  });

  it("ts --provider anthropic adds the anthropic peer dependency", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "anthropic",
      "--yes",
    ]);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.dependencies["@anthropic-ai/sdk"]).toBe("^0.104.1");
    expect(pkg.dependencies.openai).toBeUndefined();
  });

  it("python non-interactive scaffolds agent.py and .env.example", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "python",
      "--provider",
      "openai",
      "--yes",
    ]);
    expect(existsSync(join(dir, "agent.py"))).toBe(true);
    expect(existsSync(join(dir, ".env.example"))).toBe(true);
    expect(existsSync(join(dir, "requirements.txt"))).toBe(true);
    const agent = readFileSync(join(dir, "agent.py"), "utf-8");
    expect(agent).toMatch(/runtime\.turn\("Say hello\."\)/);
    expect(agent).not.toMatch(/InMemoryEventBus|InMemoryEventStore|store\.append|run_turn/);
    const requirements = readFileSync(join(dir, "requirements.txt"), "utf-8");
    expect(requirements).toContain("kaji[openai]>=0.1.0");
  });

  it("refuses to overwrite without --force", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "openai",
      "--yes",
    ]);
    const first = readFileSync(join(dir, "agent.ts"), "utf-8");
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "anthropic",
      "--yes",
    ]);
    expect(readFileSync(join(dir, "agent.ts"), "utf-8")).toBe(first);
  });

  it("rejects invalid --lang in --yes mode", async () => {
    const previousExitCode = process.exitCode;
    process.exitCode = undefined;
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ruby",
      "--provider",
      "openai",
      "--yes",
    ]);
    expect(process.exitCode).toBe(2);
    process.exitCode = previousExitCode;
  });

  it("rejects invalid --provider in --yes mode", async () => {
    const previousExitCode = process.exitCode;
    process.exitCode = undefined;
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "bedrock",
      "--yes",
    ]);
    expect(process.exitCode).toBe(2);
    process.exitCode = previousExitCode;
  });
});
