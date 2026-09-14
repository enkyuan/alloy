import { describe, expect, it } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { init, writeScaffoldFiles } from "@/cli/init";

describe("kaji init capability template", () => {
  it("writes a capability scaffold without agent or provider imports", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-capability-"));
    try {
      const code = await init([out], {
        registryRoot: "",
        log: () => {},
        initWorkerRunner: (target, files, force) => writeScaffoldFiles(target, files, force),
      });
      expect(code).toBe(0);
      const source = readFileSync(join(out, "capability.ts"), "utf8");
      expect(source).toContain("Kaji.execute");
      expect(source).not.toContain("AgentBuilder");
      expect(source).not.toContain("@irogane/kaji/openai");
      expect(source).not.toContain("@irogane/kaji/anthropic");
      expect(existsSync(join(out, "agent.ts"))).toBe(false);
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });

  it("rejects provider and agent template options", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-options-"));
    try {
      const errors: string[] = [];
      expect(
        await init([out, "--provider", "openai"], {
          registryRoot: "",
          log: () => {},
          err: (message) => errors.push(message),
        }),
      ).toBe(2);
      expect(errors.join("\n")).toContain("unknown argument: --provider");
      errors.length = 0;
      expect(
        await init([out, "--template", "agent"], {
          registryRoot: "",
          log: () => {},
          err: (message) => errors.push(message),
        }),
      ).toBe(2);
      expect(errors.join("\n")).toContain("--template must be capability");
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });

  it("preserves existing files unless force is set", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-conflict-"));
    try {
      writeFileSync(join(out, "capability.ts"), "existing");
      const errors: string[] = [];
      expect(
        await init([out], {
          registryRoot: "",
          log: () => {},
          err: (message) => errors.push(message),
        }),
      ).toBe(1);
      expect(readFileSync(join(out, "capability.ts"), "utf8")).toBe("existing");
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });
});
