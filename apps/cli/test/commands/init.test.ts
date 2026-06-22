import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { init } from "../../src/commands/init.js";

describe("init command", () => {
  it("ts non-interactive scaffolds agent.ts and .env.example", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-init-"));
    await init.parseAsync([
      "node",
      "agentkit",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "openai",
      "--yes",
    ]);
    expect(existsSync(join(dir, "agent.ts"))).toBe(true);
    expect(existsSync(join(dir, ".env.example"))).toBe(true);
    const agent = readFileSync(join(dir, "agent.ts"), "utf-8");
    expect(agent).toMatch(/@agentkit\/sdk/);
    // Provider is wired at scaffold time via a factory call, not a runtime env switch.
    expect(agent).toMatch(/\.provider\(openai\(\)\)/);
  });

  it("ts --provider kimi wires the kimi() factory", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-init-"));
    await init.parseAsync([
      "node",
      "agentkit",
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
  });

  it("ts --provider gemini wires the gemini() factory", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-init-"));
    await init.parseAsync([
      "node",
      "agentkit",
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
  });

  it("python non-interactive scaffolds agent.py and .env.example", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-init-"));
    await init.parseAsync([
      "node",
      "agentkit",
      "--cwd",
      dir,
      "--lang",
      "python",
      "--provider",
      "openai",
      "--yes",
    ]);
    expect(existsSync(join(dir, "agent.py"))).toBe(true);
  });

  it("refuses to overwrite without --force", async () => {
    const dir = mkdtempSync(join(tmpdir(), "agentkit-init-"));
    await init.parseAsync([
      "node",
      "agentkit",
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
      "agentkit",
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
});
