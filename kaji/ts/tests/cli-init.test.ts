/**
 * Tests for `kaji init`. Scaffolds into an ephemeral tmpdir and checks file
 * contents + overwrite semantics.
 */
import { describe, expect, it } from "vitest";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { rename } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import {
  init,
  invokeInitWorkerProcess,
  runInitWorkerRequest,
  runPinnedInitWorker,
  ScaffoldRollbackError,
  writeScaffoldFiles,
} from "@/cli/init";

interface InitCase {
  readonly name: string;
  readonly args: string[];
  readonly exitCode: number;
  readonly setup?: "existing-file";
  readonly pythonOnly?: boolean;
}

const CLI_CASES = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../../contracts/cli/init-cases-v1.json"), "utf8"),
) as { readonly cases: InitCase[] };
const TYPESCRIPT_CASES = CLI_CASES.cases.filter(({ pythonOnly }) => pythonOnly !== true);

const sourceInit = (args: string[], options: Parameters<typeof init>[1]) =>
  init(args, {
    ...options,
    initWorkerRunner: (out, files, force) => writeScaffoldFiles(out, files, force),
  });

describe("kaji init", () => {
  it("includes the shared existing-file refusal case", () => {
    expect(TYPESCRIPT_CASES.map(({ name }) => name)).toContain("existing-file-refusal");
  });

  it.each(TYPESCRIPT_CASES)("executes shared init case: $name", async (testCase) => {
    const root = mkdtempSync(join(tmpdir(), `kaji-init-corpus-${testCase.name}-`));
    const previousCwd = process.cwd();
    const stdout: string[] = [];
    const stderr: string[] = [];
    try {
      process.chdir(root);
      if (testCase.setup === "existing-file" || testCase.name === "force") {
        writeFileSync(join(root, "agent.ts"), "// existing\n");
      }

      const code = await sourceInit(testCase.args, {
        registryRoot: "",
        log: (message) => stdout.push(message),
        err: (message) => stderr.push(message),
      });
      expect(code, testCase.name).toBe(testCase.exitCode);

      const project = testCase.name === "explicit-path" ? join(root, "project") : root;
      switch (testCase.name) {
        case "defaults":
        case "mock-provider":
        case "yes":
          expect(readFileSync(join(project, "agent.ts"), "utf8")).toContain("new MockProvider");
          expect(stdout.join("\n")).toContain("Next:");
          break;
        case "explicit-path":
          expect(existsSync(join(project, "package.json"))).toBe(true);
          expect(existsSync(join(root, "package.json"))).toBe(false);
          break;
        case "openai-provider":
          expect(readFileSync(join(project, "agent.ts"), "utf8")).toContain(
            'from "kaji-sdk/openai"',
          );
          break;
        case "anthropic-provider":
          expect(readFileSync(join(project, "agent.ts"), "utf8")).toContain(
            'from "kaji-sdk/anthropic"',
          );
          break;
        case "force":
          expect(readFileSync(join(project, "agent.ts"), "utf8")).not.toBe("// existing\n");
          break;
        case "unknown-provider":
          expect(stderr.join("\n")).toContain("--provider must be mock, openai, or anthropic");
          expect(existsSync(join(project, "package.json"))).toBe(false);
          break;
        case "missing-provider-value":
          expect(stderr.join("\n")).toContain("--provider requires a value");
          expect(existsSync(join(project, "package.json"))).toBe(false);
          break;
        case "unknown-option":
          expect(stderr.join("\n")).toContain("unknown argument");
          expect(existsSync(join(project, "package.json"))).toBe(false);
          break;
        case "existing-file-refusal":
          expect(testCase.setup).toBe("existing-file");
          expect(readFileSync(join(root, "agent.ts"), "utf8")).toBe("// existing\n");
          expect(existsSync(join(root, "package.json"))).toBe(false);
          expect(stderr.join("\n")).toContain("refusing to overwrite without --force");
          break;
        default:
          throw new Error(`unhandled shared init case: ${testCase.name}`);
      }
    } finally {
      process.chdir(previousCwd);
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("scaffolds package.json, tsconfig.json, agent.ts, .env.example", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-"));
    const lines: string[] = [];
    const code = await sourceInit([out, "--provider", "mock", "--yes"], {
      registryRoot: "",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(0);
    for (const f of ["package.json", "tsconfig.json", "agent.ts", ".env.example"]) {
      expect(existsSync(join(out, f))).toBe(true);
    }
    const pkg = JSON.parse(readFileSync(join(out, "package.json"), "utf8"));
    const installed = JSON.parse(
      readFileSync(join(import.meta.dirname, "../package.json"), "utf8"),
    );
    expect(pkg.dependencies).toEqual({
      "kaji-sdk": "0.2.0-beta.4",
      zod: ">=4.3 <5",
    });
    expect(pkg.devDependencies["@types/node"]).toBe(installed.devDependencies["@types/node"]);
    expect(pkg.devDependencies["@dotenvx/dotenvx"]).toBe(
      installed.devDependencies["@dotenvx/dotenvx"],
    );
    expect(pkg.scripts.start).toBe("dotenvx run --ignore=MISSING_ENV_FILE -- tsx agent.ts");
    const tsconfig = JSON.parse(readFileSync(join(out, "tsconfig.json"), "utf8"));
    expect(tsconfig.compilerOptions.types).toEqual(["node"]);
    expect(tsconfig.compilerOptions.skipLibCheck).toBe(false);
    const agent = readFileSync(join(out, "agent.ts"), "utf8");
    expect(agent).toContain('from "kaji-sdk/testing"');
    expect(agent).toContain('import { AgentBuilder } from "kaji-sdk"');
    expect(agent).toContain("new AgentBuilder().provider(provider).build()");
    expect(agent).not.toContain("InMemoryEventStore");
    expect(agent).not.toContain("purgeSession");
    expect(agent).toContain("result.turnId");
    expect(agent).toContain("event.sequence");
    expect(lines.join("\n")).toMatch(/Next: cd .* && (npm|bun) install/);
  });

  it("refuses to overwrite an existing file without --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-conflict-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const stderr: string[] = [];
    const code = await sourceInit([out], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(1);
    expect(stderr.join("\n")).toMatch(/refusing to overwrite without --force/);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toBe("// existing");
    expect(existsSync(join(out, "package.json"))).toBe(false);
  });

  it("overwrites with --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const code = await sourceInit([out, "--force"], { registryRoot: "", log: () => {} });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).not.toBe("// existing");
  });

  it("does not replace a generated-path directory with --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-directory-"));
    mkdirSync(join(out, "agent.ts"));
    const stderr: string[] = [];

    const code = await sourceInit([out, "--force"], {
      registryRoot: "",
      log: () => {},
      err: (message) => stderr.push(message),
    });

    expect(code).toBe(1);
    expect(stderr.join("\n")).toContain("unsafe scaffold destination");
    expect(existsSync(join(out, "agent.ts"))).toBe(true);
    expect(existsSync(join(out, "package.json"))).toBe(false);
    expect(readdirSync(out)).toEqual(["agent.ts"]);
    rmSync(out, { recursive: true, force: true });
  });

  it("rolls back a failed forced publication and removes temporary artifacts", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-rollback-"));
    writeFileSync(join(out, "package.json"), "original package\n");
    writeFileSync(join(out, "agent.ts"), "original agent\n");
    const victim = join(out, "victim.txt");
    writeFileSync(victim, "untouched victim\n");
    let publications = 0;

    await expect(
      writeScaffoldFiles(
        out,
        {
          "package.json": "replacement package\n",
          "tsconfig.json": "new config\n",
          "agent.ts": "replacement agent\n",
          ".env.example": "new environment\n",
        },
        true,
        {
          publish: async (temporary, destination) => {
            publications++;
            if (publications === 3) throw new Error("injected publication failure");
            if (publications === 1) symlinkSync(victim, destination);
            await rename(temporary, destination);
          },
        },
      ),
    ).rejects.toThrow("injected publication failure");

    expect(readFileSync(join(out, "package.json"), "utf8")).toBe("original package\n");
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toBe("original agent\n");
    expect(readFileSync(victim, "utf8")).toBe("untouched victim\n");
    expect(existsSync(join(out, "tsconfig.json"))).toBe(false);
    expect(existsSync(join(out, ".env.example"))).toBe(false);
    expect(readdirSync(out).sort()).toEqual(["agent.ts", "package.json", "victim.txt"]);
    rmSync(out, { recursive: true, force: true });
  });

  it("preserves the original backup instead of clobbering a raced-in symlink", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-race-"));
    const packagePath = join(out, "package.json");
    const victim = join(out, "victim.txt");
    writeFileSync(packagePath, "original package\n");
    writeFileSync(victim, "untouched victim\n");
    let publications = 0;
    let rollbackError: unknown;

    try {
      await writeScaffoldFiles(
        out,
        {
          "package.json": "replacement package\n",
          "tsconfig.json": "new config\n",
          "agent.ts": "replacement agent\n",
        },
        true,
        {
          publish: async (temporary, destination) => {
            publications++;
            if (publications === 3) throw new Error("injected publication failure");
            await rename(temporary, destination);
            if (publications === 2) {
              rmSync(packagePath);
              symlinkSync(victim, packagePath);
            }
          },
        },
      );
    } catch (error) {
      rollbackError = error;
    }

    expect(rollbackError).toBeInstanceOf(ScaffoldRollbackError);
    expect(lstatSync(packagePath).isSymbolicLink()).toBe(true);
    expect(readFileSync(victim, "utf8")).toBe("untouched victim\n");
    expect(existsSync(join(out, "tsconfig.json"))).toBe(false);
    expect(existsSync(join(out, "agent.ts"))).toBe(false);
    const backupDirectories = readdirSync(out).filter((name) =>
      name.startsWith(".kaji-scaffold-backup-"),
    );
    expect(backupDirectories).toHaveLength(1);
    expect((rollbackError as ScaffoldRollbackError).recoveryDirectory).toBe(backupDirectories[0]);
    expect(readFileSync(join(out, backupDirectories[0]!, "package.json"), "utf8")).toBe(
      "original package\n",
    );
    rmSync(out, { recursive: true, force: true });
  });

  it("preserves a raced-in symlink during non-forced cleanup", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-race-"));
    const packagePath = join(out, "package.json");
    const victim = join(out, "victim.txt");
    writeFileSync(victim, "untouched victim\n");

    await expect(
      writeScaffoldFiles(
        out,
        {
          "package.json": "generated package\n",
        },
        false,
        {
          verifyTarget: async () => {
            rmSync(packagePath);
            symlinkSync(victim, packagePath);
            throw new Error("injected verification failure");
          },
        },
      ),
    ).rejects.toThrow("injected verification failure");

    expect(lstatSync(packagePath).isSymbolicLink()).toBe(true);
    expect(readFileSync(victim, "utf8")).toBe("untouched victim\n");
    rmSync(out, { recursive: true, force: true });
  });

  it("reports only the generated recovery directory after rollback failure", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-recovery-message-"));
    const recoveryDirectory = basename(mkdtempSync(join(out, ".kaji-scaffold-backup-")));
    const secret = "/private/operator/customer-secret/original.ts";
    const stderr: string[] = [];

    const code = await init([out, "--force"], {
      registryRoot: "",
      log: () => {},
      err: (message) => stderr.push(message),
      initWorkerRunner: async () => {
        throw new ScaffoldRollbackError(recoveryDirectory, new Error(secret));
      },
    });

    expect(code).toBe(1);
    expect(stderr).toEqual([
      "kaji init failed while writing the scaffold; " +
        `original preserved in target directory as ${recoveryDirectory}`,
    ]);
    expect(stderr.join("\n")).not.toContain(secret);
    expect(stderr.join("\n")).not.toContain(out);
    rmSync(out, { recursive: true, force: true });
  });

  it("creates the out directory if it does not exist", async () => {
    const parent = mkdtempSync(join(tmpdir(), "kaji-init-parent-"));
    const out = join(parent, "nested", "dir");
    const code = await sourceInit([out], { registryRoot: "", log: () => {} });
    expect(code).toBe(0);
    expect(existsSync(join(out, "package.json"))).toBe(true);
  });

  it("rejects the removed --out alias", async () => {
    const stderr: string[] = [];
    const code = await sourceInit(["--out"], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(2);
    expect(stderr.join("\n")).toMatch(/unknown argument: --out/);
  });

  it("errors on unknown arguments", async () => {
    const stderr: string[] = [];
    const code = await sourceInit(["one", "two"], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });
    expect(code).toBe(2);
    expect(stderr.join("\n")).toMatch(/unexpected path argument: two/);
  });

  it.each([
    ["openai", "openai", ">=4 <8"],
    ["anthropic", "@anthropic-ai/sdk", ">=0.30 <2"],
  ] as const)("adds only the selected %s provider peer", async (provider, peer, range) => {
    const out = mkdtempSync(join(tmpdir(), `kaji-init-${provider}-`));
    const code = await sourceInit([out, "--provider", provider], {
      registryRoot: "",
      log: () => {},
    });
    const pkg = JSON.parse(readFileSync(join(out, "package.json"), "utf8"));

    expect(code).toBe(0);
    expect(pkg.dependencies).toEqual({
      "kaji-sdk": "0.2.0-beta.4",
      zod: ">=4.3 <5",
      [peer]: range,
    });
    const key = provider === "openai" ? "OPENAI_API_KEY" : "ANTHROPIC_API_KEY";
    expect(readFileSync(join(out, ".env.example"), "utf8")).toContain(`${key}=\n`);
    const installed = JSON.parse(
      readFileSync(join(import.meta.dirname, "../package.json"), "utf8"),
    );
    expect(pkg.devDependencies["@types/node"]).toBe(installed.devDependencies["@types/node"]);
  });

  it("defaults to mock and never prompts with --yes", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-default-"));
    const code = await sourceInit([out, "--yes"], { registryRoot: "", log: () => {} });

    expect(code).toBe(0);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toContain("new MockProvider");
  });

  it.each(["unknown", "kimi", "gemini"])("rejects unsupported provider %s", async (provider) => {
    const stderr: string[] = [];
    const code = await sourceInit(["--provider", provider], {
      registryRoot: "",
      log: () => {},
      err: (m) => stderr.push(m),
    });

    expect(code).toBe(2);
    expect(stderr.join("\n")).toContain("--provider must be mock, openai, or anthropic");
  });

  it("never follows a generated destination symlink with --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-symlink-"));
    const outside = join(out, "outside.ts");
    writeFileSync(outside, "keep-me");
    symlinkSync(outside, join(out, "agent.ts"));
    const stderr: string[] = [];

    const code = await sourceInit([out, "--force"], {
      registryRoot: "",
      log: () => {},
      err: (message) => stderr.push(message),
    });

    expect(code).toBe(1);
    expect(stderr.join("\n")).toContain("unsafe scaffold destination");
    expect(readFileSync(outside, "utf8")).toBe("keep-me");
    expect(existsSync(join(out, "package.json"))).toBe(false);
  });

  it("rejects a target symlink swapped in before the pinned worker starts", async () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-init-target-pre-spawn-"));
    const out = join(root, "out");
    const held = join(root, "held");
    const victim = join(root, "victim");
    mkdirSync(out);
    mkdirSync(victim);
    writeFileSync(join(victim, "outside.txt"), "untouched\n");

    try {
      await expect(
        runPinnedInitWorker(out, { "agent.ts": "generated\n" }, false, {
          invokeWorker: async (request) => {
            renameSync(out, held);
            symlinkSync(victim, out, "dir");
            const previousCwd = process.cwd();
            try {
              process.chdir(out);
              await runInitWorkerRequest(request);
            } finally {
              process.chdir(previousCwd);
            }
          },
        }),
      ).rejects.toThrow("pinned scaffold worker failed");

      expect(readdirSync(victim)).toEqual(["outside.txt"]);
      expect(readdirSync(held)).toEqual([]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it.each([false, true])(
    "rolls back inside the pinned directory when the target is swapped after handshake (force=%s)",
    async (force) => {
      const root = mkdtempSync(join(tmpdir(), "kaji-init-target-post-handshake-"));
      const out = join(root, "out");
      const held = join(root, "held");
      const victim = join(root, "victim");
      mkdirSync(out);
      mkdirSync(victim);
      writeFileSync(join(victim, "outside.txt"), "untouched\n");
      if (force) writeFileSync(join(out, "agent.ts"), "original\n");
      const targetStat = statSync(out, { bigint: true });
      const previousCwd = process.cwd();

      try {
        process.chdir(out);
        await expect(
          runInitWorkerRequest(
            {
              version: 1,
              expectedDev: targetStat.dev.toString(),
              expectedIno: targetStat.ino.toString(),
              targetAbsolute: out,
              files: { "agent.ts": "generated\n", "package.json": "{}\n" },
              force,
            },
            {
              afterHandshake: () => {
                renameSync(out, held);
                symlinkSync(victim, out, "dir");
              },
            },
          ),
        ).rejects.toThrow("target directory changed during scaffold publication");
      } finally {
        process.chdir(previousCwd);
      }

      expect(readdirSync(victim)).toEqual(["outside.txt"]);
      expect(readdirSync(held)).toEqual(force ? ["agent.ts"] : []);
      if (force) expect(readFileSync(join(held, "agent.ts"), "utf8")).toBe("original\n");
      expect(readdirSync(held).some((name) => name.includes(".kaji-"))).toBe(false);
      rmSync(root, { recursive: true, force: true });
    },
  );

  it("rejects non-basename worker entries before creating files", async () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-init-worker-basename-"));
    const out = join(root, "out");
    mkdirSync(out);
    const targetStat = statSync(out, { bigint: true });
    const previousCwd = process.cwd();
    try {
      process.chdir(out);
      await expect(
        runInitWorkerRequest({
          version: 1,
          expectedDev: targetStat.dev.toString(),
          expectedIno: targetStat.ino.toString(),
          targetAbsolute: out,
          files: { "../outside.ts": "escape\n" },
          force: false,
        }),
      ).rejects.toThrow("invalid scaffold worker request");
    } finally {
      process.chdir(previousCwd);
    }
    expect(existsSync(join(root, "outside.ts"))).toBe(false);
    expect(readdirSync(out)).toEqual([]);
    rmSync(root, { recursive: true, force: true });
  });

  it("cooperatively rolls back a real child timeout after backup staging", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-worker-timeout-"));
    writeFileSync(join(out, "agent.ts"), "original agent\n");
    writeFileSync(join(out, "package.json"), "original package\n");
    const workerSource = resolve(import.meta.dirname, "../src/cli/init-worker.ts");
    let prepared = false;

    await expect(
      runPinnedInitWorker(
        out,
        {
          "agent.ts": "generated agent\n",
          "package.json": "generated package\n",
        },
        true,
        {
          invokeWorker: (request) =>
            invokeInitWorkerProcess(request, {
              command: ["bun", workerSource],
              startupTimeoutMs: 5_000,
              transactionTimeoutMs: 25,
              beforeCommit: async () => {
                prepared = true;
                await delay(500);
              },
            }),
        },
      ),
    ).rejects.toThrow("pinned scaffold worker failed");

    expect(prepared).toBe(true);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toBe("original agent\n");
    expect(readFileSync(join(out, "package.json"), "utf8")).toBe("original package\n");
    expect(readdirSync(out).some((name) => name.includes(".kaji-"))).toBe(false);
    rmSync(out, { recursive: true, force: true });
  });

  it("fails generically before spawning when the worker payload exceeds its bound", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-worker-input-bound-"));
    await expect(
      runPinnedInitWorker(out, { "agent.ts": "x".repeat(300 * 1024) }, false),
    ).rejects.toThrow("pinned scaffold worker failed");
    expect(readdirSync(out)).toEqual([]);
    rmSync(out, { recursive: true, force: true });
  });
});
