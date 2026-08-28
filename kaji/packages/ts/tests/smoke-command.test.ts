import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import process from "node:process";
import { describe, expect, it } from "vitest";

import {
  classifyCommandFailure,
  CommandCaptureError,
  CommandError,
  CommandExitError,
  CommandCleanupError,
  CommandOutputLimitError,
  CommandShuttingDownError,
  CommandStartError,
  CommandTimeoutError,
  runCommand,
  UnsupportedReleaseHostError,
} from "../scripts/command";

const packageRoot = resolve(import.meta.dirname, "..");

async function waitForFile(path: string): Promise<void> {
  const deadline = performance.now() + 1_000;
  while (performance.now() < deadline) {
    if (existsSync(path)) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`timed out waiting for ${path}`);
}

function findBun(): string | undefined {
  for (const directory of (process.env.PATH ?? "").split(":")) {
    const candidate = join(directory, "bun");
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}

describe("installed-package command runner", () => {
  it.each([
    [new UnsupportedReleaseHostError(), "unsupported_host"],
    [new CommandStartError(), "start"],
    [new CommandExitError(9), "exit"],
    [new CommandTimeoutError(1_000), "timeout"],
    [new CommandOutputLimitError("stdout", 64), "output_limit"],
    [new CommandCleanupError(), "cleanup"],
    [new CommandCaptureError("stderr"), "capture"],
    [new CommandShuttingDownError(), "shutting_down"],
    [new CommandError("opaque"), "unknown"],
    [new Error("opaque"), "unknown"],
  ] as const)("classifies %s by concrete error identity", (error, expected) => {
    expect(classifyCommandFailure(error)).toBe(expected);
  });

  it("captures bytes and returns intentional nonzero statuses", async () => {
    const result = await runCommand({
      command: process.execPath,
      args: ["-e", "process.stdout.write('ok'); process.stderr.write('err'); process.exit(7)"],
      cwd: packageRoot,
      timeoutMs: 1_000,
      maxOutputBytes: 64,
      check: false,
    });
    expect(result).toEqual({ status: 7, stdout: "ok", stderr: "err" });
  });

  it("redacts argv from nonzero failures", async () => {
    const secret = "sk-package-secret";
    let error: unknown;
    try {
      await runCommand({
        command: process.execPath,
        args: ["-e", "process.exit(9)", secret],
        cwd: packageRoot,
        timeoutMs: 1_000,
        maxOutputBytes: 64,
      });
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(CommandExitError);
    expect(String(error)).not.toContain(secret);
    expect(error).not.toHaveProperty("command");
  });

  it.each(["stdout", "stderr"] as const)("caps %s bytes", async (stream) => {
    const target = stream === "stdout" ? "stdout" : "stderr";
    await expect(
      runCommand({
        command: process.execPath,
        args: ["-e", `process.${target}.write(Buffer.alloc(8192))`],
        cwd: packageRoot,
        timeoutMs: 1_000,
        maxOutputBytes: 64,
        terminateGraceMs: 50,
      }),
    ).rejects.toMatchObject({ name: "CommandOutputLimitError", stream });
  });

  it("classifies cap-plus-one before a later timeout", async () => {
    await expect(
      runCommand({
        command: process.execPath,
        args: ["-e", "process.stdout.write(Buffer.alloc(65)); setInterval(()=>{},1000)"],
        cwd: packageRoot,
        timeoutMs: 500,
        maxOutputBytes: 64,
        terminateGraceMs: 50,
      }),
    ).rejects.toBeInstanceOf(CommandOutputLimitError);
  });

  it("returns exactly the configured output cap", async () => {
    const completed = await runCommand({
      command: process.execPath,
      args: ["-e", "process.stdout.write(Buffer.alloc(64, 120))"],
      cwd: packageRoot,
      timeoutMs: 1_000,
      maxOutputBytes: 64,
    });
    expect(Buffer.byteLength(completed.stdout)).toBe(64);
  });

  it("normalizes NUL arguments without retaining secrets", async () => {
    const secret = "sk-secret\0argument";
    let error: unknown;
    try {
      await runCommand({
        command: process.execPath,
        args: [secret],
        cwd: packageRoot,
        timeoutMs: 1_000,
        maxOutputBytes: 64,
      });
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(CommandStartError);
    expect(String(error)).not.toContain("sk-secret");
  });

  it.runIf(process.platform !== "win32")(
    "kills a detached descendant that ignores SIGTERM",
    async () => {
      const workdir = mkdtempSync(join(tmpdir(), "kaji-command-test-"));
      const pidFile = join(workdir, "child.pid");
      const program = `
        const {spawn} = require('node:child_process');
        process.on('SIGTERM', () => {});
        const child = spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], {stdio:'ignore'});
        require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));
        setInterval(()=>{},1000);
      `;
      try {
        await expect(
          runCommand({
            command: process.execPath,
            args: ["-e", program],
            cwd: workdir,
            timeoutMs: 200,
            maxOutputBytes: 64,
            terminateGraceMs: 50,
          }),
        ).rejects.toBeInstanceOf(CommandTimeoutError);
        expect(existsSync(pidFile)).toBe(true);
        const pid = Number(readFileSync(pidFile, "utf8"));
        expect(() => process.kill(pid, 0)).toThrow();
      } finally {
        rmSync(workdir, { recursive: true, force: true });
      }
    },
  );

  it.runIf(process.platform !== "win32").each([0, 7])(
    "cleans residual descendants after leader status %i",
    async (status) => {
      const workdir = mkdtempSync(join(tmpdir(), "kaji-command-residual-test-"));
      const pidFile = join(workdir, "child.pid");
      const program = `
        const {spawn} = require('node:child_process');
        const child = spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], {stdio:'ignore'});
        require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));
        process.exit(${status});
      `;
      try {
        const completed = await runCommand({
          command: process.execPath,
          args: ["-e", program],
          cwd: workdir,
          timeoutMs: 1_000,
          maxOutputBytes: 64,
          terminateGraceMs: 50,
          check: false,
        });
        expect(completed.status).toBe(status);
        const pid = Number(readFileSync(pidFile, "utf8"));
        expect(() => process.kill(pid, 0)).toThrow();
      } finally {
        rmSync(workdir, { recursive: true, force: true });
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "bounds pipe EOF when a descendant escapes the original group",
    async () => {
      const workdir = mkdtempSync(join(tmpdir(), "kaji-command-escaped-test-"));
      const pidFile = join(workdir, "escaped.pid");
      const program = `
        const {spawn} = require('node:child_process');
        const child = spawn(process.execPath, ['-e', "setInterval(()=>{},1000)"], {detached:true, stdio:'inherit'});
        require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));
        process.exit(0);
      `;
      try {
        await expect(
          runCommand({
            command: process.execPath,
            args: ["-e", program],
            cwd: workdir,
            timeoutMs: 1_000,
            maxOutputBytes: 64,
            terminateGraceMs: 50,
            check: false,
          }),
        ).rejects.toBeInstanceOf(CommandCleanupError);
      } finally {
        if (existsSync(pidFile)) {
          const pid = Number(readFileSync(pidFile, "utf8"));
          try {
            if (Number.isSafeInteger(pid) && pid > 0) process.kill(pid, "SIGKILL");
          } catch {
            // The escaped fixture may already have exited.
          }
        }
        rmSync(workdir, { recursive: true, force: true });
      }
    },
  );

  it.runIf(process.platform !== "win32").each([0, 7])(
    "preserves leader status %i when a descendant holds the pipes",
    async (status) => {
      const program = `
        const {spawn} = require('node:child_process');
        spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], {stdio:'inherit'});
        process.exit(${status});
      `;
      const completed = await runCommand({
        command: process.execPath,
        args: ["-e", program],
        cwd: packageRoot,
        timeoutMs: 1_000,
        maxOutputBytes: 64,
        terminateGraceMs: 50,
        check: false,
      });
      expect(completed.status).toBe(status);
    },
  );

  const bun = findBun();
  it.runIf(process.platform !== "win32" && bun !== undefined)(
    "reaps the direct child and its descendant before parent signal exit",
    async () => {
      const workdir = mkdtempSync(join(tmpdir(), "kaji-command-signal-test-"));
      const leafPid = join(workdir, "leaf.pid");
      const shutdown = join(workdir, "shutdown.txt");
      const runner = join(workdir, "runner.ts");
      const commandModule = resolve(packageRoot, "scripts/command.ts");
      const directProgram = `
        const {spawn} = require('node:child_process');
        const child = spawn('node', ['-e', "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], {stdio:'ignore'});
        require('node:fs').writeFileSync(${JSON.stringify(leafPid)}, String(child.pid));
        setInterval(()=>{},1000);
      `;
      await import("node:fs/promises").then(({ writeFile }) =>
        writeFile(
          runner,
          `
            import { writeFileSync } from "node:fs";
            import { runCommand } from ${JSON.stringify(commandModule)};
            const active = runCommand({ command: "node", args: ["-e", ${JSON.stringify(directProgram)}], cwd: ${JSON.stringify(workdir)}, timeoutMs: 60000, maxOutputBytes: 64, terminateGraceMs: 50 });
            process.on("SIGTERM", () => {
              void runCommand({ command: "node", args: ["-e", ""], cwd: ${JSON.stringify(workdir)}, timeoutMs: 1000, maxOutputBytes: 64 })
                .catch((error) => writeFileSync(${JSON.stringify(shutdown)}, error.name));
            });
            await active;
          `,
        ),
      );
      const parent = spawn(bun!, [runner], {
        cwd: workdir,
        stdio: ["ignore", "ignore", "pipe"],
      });
      let diagnostics = "";
      parent.stderr.on("data", (chunk: Buffer) => {
        diagnostics += chunk.toString("utf8");
      });
      try {
        await waitForFile(leafPid);
        parent.kill("SIGTERM");
        const status = await new Promise<number | null>((resolve) =>
          parent.once("close", (code) => resolve(code)),
        );
        expect(status, diagnostics).toBe(143);
        expect(readFileSync(shutdown, "utf8")).toBe("CommandShuttingDownError");
        const pid = Number(readFileSync(leafPid, "utf8"));
        expect(() => process.kill(pid, 0)).toThrow();
      } finally {
        if (parent.exitCode === null) parent.kill("SIGKILL");
        rmSync(workdir, { recursive: true, force: true });
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "finishes group cleanup when the leader exits on SIGTERM",
    async () => {
      const workdir = mkdtempSync(join(tmpdir(), "kaji-command-leader-test-"));
      const pidFile = join(workdir, "child.pid");
      const program = `
        const {spawn} = require('node:child_process');
        process.on('SIGTERM', () => process.exit(0));
        const child = spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], {stdio:'ignore'});
        require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));
        setInterval(()=>{},1000);
      `;
      try {
        await expect(
          runCommand({
            command: process.execPath,
            args: ["-e", program],
            cwd: workdir,
            timeoutMs: 200,
            maxOutputBytes: 64,
            terminateGraceMs: 50,
          }),
        ).rejects.toBeInstanceOf(CommandTimeoutError);
        const pid = Number(readFileSync(pidFile, "utf8"));
        expect(() => process.kill(pid, 0)).toThrow();
      } finally {
        rmSync(workdir, { recursive: true, force: true });
      }
    },
  );

  it("rejects unsupported hosts before spawning", async () => {
    await expect(
      runCommand({
        command: process.execPath,
        args: ["-e", "process.exit(0)"],
        cwd: packageRoot,
        timeoutMs: 1_000,
        maxOutputBytes: 64,
        platform: "win32",
      }),
    ).rejects.toBeInstanceOf(UnsupportedReleaseHostError);
  });
});
