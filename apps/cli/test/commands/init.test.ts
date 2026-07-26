import { existsSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
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
    expect(agent).toMatch(/kaji-sdk/);
    expect(agent).toMatch(/new OpenAIProvider\(\{ apiKey \}\)/);
    expect(agent).toMatch(/\.provider\(provider\)/);
    expect(agent).toMatch(/\.turn\("Say hello\."\)/);
    expect(agent).toContain("text=${result.text}");
    expect(agent).toContain("turn_id=${result.turnId}");
    expect(agent).toContain("final_sequence=${finalSequence}");
    expect(agent).not.toMatch(
      /EventBus|InMemoryEventStore|KajiEvent|SESSION_CREATED|runtime\.send/,
    );
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.engines.node).toBe("22.x || 24.x");
    expect(pkg.scripts.start).toBe("dotenvx run --ignore=MISSING_ENV_FILE -- tsx agent.ts");
    expect(pkg.scripts.typecheck).toBe("tsc --noEmit");
    expect(pkg.devDependencies["@dotenvx/dotenvx"]).toBe("2.9.0");
    expect(pkg.dependencies["kaji-sdk"]).toBe("^0.2.0-beta.3");
    expect(pkg.dependencies.zod).toBe(">=4.3 <5");
    expect(pkg.dependencies.openai).toBe(">=4 <8");
    expect(readFileSync(join(dir, ".env.example"), "utf-8")).toContain("OPENAI_API_KEY=\n");
  });

  it("ts --yes defaults to a deterministic mock provider", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    await init.parseAsync(["node", "kaji", "--cwd", dir, "--lang", "ts", "--yes"]);
    const agent = readFileSync(join(dir, "agent.ts"), "utf-8");
    expect(agent).toContain('import { MockProvider } from "kaji-sdk/testing"');
    expect(agent).toContain("const provider = new MockProvider()");
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
    expect(pkg.dependencies.openai).toBeUndefined();
    expect(pkg.dependencies["@anthropic-ai/sdk"]).toBeUndefined();
    expect(readFileSync(join(dir, ".env.example"), "utf-8")).toContain("KAJI_MODEL_PROVIDER=mock");
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
    expect(pkg.dependencies["@anthropic-ai/sdk"]).toBe(">=0.30 <2");
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
    expect(agent).toContain('kaji.get_provider("openai")');
    expect(agent).toContain('print(f"turn_id={result.turn_id}")');
    expect(agent).toContain('print(f"final_sequence={final_sequence}")');
    expect(agent).not.toMatch(/InMemoryEventBus|InMemoryEventStore|store\.append|run_turn/);
    const requirements = readFileSync(join(dir, "requirements.txt"), "utf-8");
    expect(requirements).toContain("kaji-sdk[openai]>=0.2.0b1,<0.3");
    expect(readFileSync(join(dir, ".env.example"), "utf-8")).toContain("OPENAI_API_KEY=\n");
  });

  it("refuses to overwrite without --force", async () => {
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
    expect(process.exitCode).toBe(1);
    process.exitCode = previousExitCode;
  });

  it("does not partially scaffold when one destination already exists", async () => {
    const previousExitCode = process.exitCode;
    process.exitCode = undefined;
    const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
    writeFileSync(join(dir, "agent.ts"), "keep me\n");

    await init.parseAsync([
      "node",
      "kaji",
      "--cwd",
      dir,
      "--lang",
      "ts",
      "--provider",
      "mock",
      "--yes",
    ]);

    expect(readFileSync(join(dir, "agent.ts"), "utf-8")).toBe("keep me\n");
    expect(existsSync(join(dir, "package.json"))).toBe(false);
    expect(existsSync(join(dir, "tsconfig.json"))).toBe(false);
    expect(existsSync(join(dir, ".env.example"))).toBe(false);
    expect(process.exitCode).toBe(1);
    process.exitCode = previousExitCode;
  });

  it.runIf(process.platform !== "win32")(
    "refuses to follow scaffold symlinks with --force",
    async () => {
      const previousExitCode = process.exitCode;
      process.exitCode = undefined;
      const dir = mkdtempSync(join(tmpdir(), "kaji-init-"));
      const outside = join(dir, "outside.txt");
      writeFileSync(outside, "do not replace\n");
      symlinkSync(outside, join(dir, "agent.ts"));

      await init.parseAsync([
        "node",
        "kaji",
        "--cwd",
        dir,
        "--lang",
        "ts",
        "--provider",
        "mock",
        "--yes",
        "--force",
      ]);

      expect(readFileSync(outside, "utf-8")).toBe("do not replace\n");
      expect(process.exitCode).toBe(1);
      process.exitCode = previousExitCode;
    },
  );

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
