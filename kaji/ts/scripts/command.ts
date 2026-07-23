import { spawn, type ChildProcessByStdio } from "node:child_process";
import { constants as osConstants } from "node:os";
import { performance } from "node:perf_hooks";
import process from "node:process";
import type { Readable } from "node:stream";

type OwnedChild = ChildProcessByStdio<null, Readable, Readable>;
const CLEANUP_SETTLE_MS = 1_000;

export interface CommandOptions {
  readonly command: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeoutMs: number;
  readonly maxOutputBytes: number;
  readonly terminateGraceMs?: number;
  readonly check?: boolean;
  readonly platform?: NodeJS.Platform;
}

export interface CompletedCommand {
  readonly status: number;
  readonly stdout: string;
  readonly stderr: string;
}

export class CommandError extends Error {}

export class UnsupportedReleaseHostError extends CommandError {
  constructor() {
    super("release process cleanup requires macOS or Linux");
    this.name = "UnsupportedReleaseHostError";
  }
}

export class CommandStartError extends CommandError {
  constructor() {
    super("release command could not be started");
    this.name = "CommandStartError";
  }
}

export class CommandExitError extends CommandError {
  constructor(readonly status: number) {
    super(`release command exited with status ${status}`);
    this.name = "CommandExitError";
  }
}

export class CommandTimeoutError extends CommandError {
  constructor(readonly timeoutMs: number) {
    super("release command exceeded its time budget");
    this.name = "CommandTimeoutError";
  }
}

export class CommandOutputLimitError extends CommandError {
  constructor(
    readonly stream: "stdout" | "stderr",
    readonly capturedBytes: number,
  ) {
    super(`release command exceeded its ${stream} capture budget`);
    this.name = "CommandOutputLimitError";
  }
}

export class CommandCleanupError extends CommandError {
  constructor() {
    super("release command process-group cleanup did not settle");
    this.name = "CommandCleanupError";
  }
}

export class CommandCaptureError extends CommandError {
  constructor(readonly stream: "stdout" | "stderr") {
    super(`release command ${stream} capture failed`);
    this.name = "CommandCaptureError";
  }
}

export class CommandShuttingDownError extends CommandError {
  constructor() {
    super("release command runner is shutting down");
    this.name = "CommandShuttingDownError";
  }
}

export type CommandFailureKind =
  | "unsupported_host"
  | "start"
  | "exit"
  | "timeout"
  | "output_limit"
  | "cleanup"
  | "capture"
  | "shutting_down"
  | "unknown";

export function classifyCommandFailure(error: unknown): CommandFailureKind {
  if (error instanceof UnsupportedReleaseHostError) return "unsupported_host";
  if (error instanceof CommandStartError) return "start";
  if (error instanceof CommandExitError) return "exit";
  if (error instanceof CommandTimeoutError) return "timeout";
  if (error instanceof CommandOutputLimitError) return "output_limit";
  if (error instanceof CommandCleanupError) return "cleanup";
  if (error instanceof CommandCaptureError) return "capture";
  if (error instanceof CommandShuttingDownError) return "shutting_down";
  return "unknown";
}

interface ActiveGroup {
  readonly settle: (bounded: boolean) => Promise<CommandError | undefined>;
}

const activeGroups = new Map<number, ActiveGroup>();
let handlersInstalled = false;
let parentSignalActive = false;

const delay = async (milliseconds: number): Promise<void> =>
  await new Promise((resolve) => setTimeout(resolve, milliseconds));

async function signalGroup(pid: number, signal: NodeJS.Signals): Promise<boolean> {
  const permissionDeadline = performance.now() + 50;
  while (true) {
    try {
      process.kill(-pid, signal);
      return true;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "ESRCH") return false;
      if (code !== "EPERM" || performance.now() >= permissionDeadline) {
        throw new CommandCleanupError();
      }
      await delay(1);
    }
  }
}

async function groupExists(pid: number): Promise<boolean> {
  const permissionDeadline = performance.now() + 50;
  while (true) {
    try {
      process.kill(-pid, 0);
      return true;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "ESRCH") return false;
      if (code !== "EPERM" || performance.now() >= permissionDeadline) {
        throw new CommandCleanupError();
      }
      await delay(1);
    }
  }
}

async function terminateGroup(pid: number, graceMs: number): Promise<void> {
  if (!(await groupExists(pid))) return;
  await signalGroup(pid, "SIGTERM");
  const deadline = performance.now() + graceMs;
  while ((await groupExists(pid)) && performance.now() < deadline) {
    await delay(Math.min(10, Math.max(1, deadline - performance.now())));
  }
  if (!(await groupExists(pid))) return;
  await signalGroup(pid, "SIGKILL");
  const killDeadline = performance.now() + CLEANUP_SETTLE_MS;
  while ((await groupExists(pid)) && performance.now() < killDeadline) await delay(5);
  if (await groupExists(pid)) throw new CommandCleanupError();
}

async function closesWithin(closed: Promise<void>, timeoutMs: number): Promise<boolean> {
  return await new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(false), timeoutMs);
    void closed.then(() => {
      clearTimeout(timeout);
      resolve(true);
    });
  });
}

async function closesBeforeBoundedOrDeadline(
  closed: Promise<void>,
  boundedWake: Promise<void>,
  absoluteDeadline: number,
): Promise<boolean> {
  return await new Promise((resolve) => {
    let settled = false;
    const finish = (closedFirst: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(closedFirst);
    };
    const timeout = setTimeout(
      () => finish(false),
      Math.max(0, absoluteDeadline - performance.now()),
    );
    void closed.then(() => finish(true));
    void boundedWake.then(() => finish(false));
  });
}

async function settleChild(
  child: OwnedChild,
  closed: Promise<void>,
  graceMs: number,
  absoluteDeadline: number,
  bounded: () => boolean,
  boundedWake: Promise<void>,
): Promise<CommandError | undefined> {
  let cleanupError: CommandError | undefined;
  if (child.pid !== undefined) {
    try {
      await terminateGroup(child.pid, graceMs);
    } catch (error) {
      cleanupError = error instanceof CommandError ? error : new CommandCleanupError();
      try {
        child.kill("SIGKILL");
      } catch {
        // The typed cleanup failure below remains authoritative.
      }
    }
  }
  if (!bounded() && cleanupError === undefined) {
    const natural = await closesBeforeBoundedOrDeadline(closed, boundedWake, absoluteDeadline);
    if (natural) return undefined;
  }
  if (await closesWithin(closed, CLEANUP_SETTLE_MS)) return cleanupError;
  child.stdout.destroy();
  child.stderr.destroy();
  if (!(await closesWithin(closed, CLEANUP_SETTLE_MS))) {
    return new CommandCleanupError();
  }
  return cleanupError ?? new CommandCleanupError();
}

function handleParentSignal(signum: number): void {
  if (parentSignalActive) return;
  parentSignalActive = true;
  const groups = [...activeGroups.values()];
  void Promise.allSettled(
    groups.map(async (group) => {
      await group.settle(true);
    }),
  ).then(() => process.exit(128 + signum));
}

const handleSigterm = () => handleParentSignal(15);
const handleSigint = () => handleParentSignal(2);

function installSignalCleanup(): void {
  if (handlersInstalled) return;
  handlersInstalled = true;
  process.on("SIGTERM", handleSigterm);
  process.on("SIGINT", handleSigint);
}

function removeSignalCleanupIfIdle(): void {
  if (!handlersInstalled || activeGroups.size !== 0) return;
  process.off("SIGTERM", handleSigterm);
  process.off("SIGINT", handleSigint);
  handlersInstalled = false;
}

function validateOptions(options: CommandOptions): number {
  const platform = options.platform ?? process.platform;
  if (platform !== "darwin" && platform !== "linux") {
    throw new UnsupportedReleaseHostError();
  }
  if (
    typeof options.command !== "string" ||
    !options.command ||
    !Array.isArray(options.args) ||
    options.args.some((arg) => typeof arg !== "string")
  ) {
    throw new TypeError("command and arguments must be strings");
  }
  if (options.command.includes("\0") || options.args.some((arg) => arg.includes("\0"))) {
    throw new CommandStartError();
  }
  if (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0) {
    throw new RangeError("timeoutMs must be positive and finite");
  }
  if (!Number.isSafeInteger(options.maxOutputBytes) || options.maxOutputBytes <= 0) {
    throw new RangeError("maxOutputBytes must be a positive safe integer");
  }
  const graceMs = options.terminateGraceMs ?? 1_000;
  if (!Number.isFinite(graceMs) || graceMs < 0) {
    throw new RangeError("terminateGraceMs must be finite and non-negative");
  }
  return graceMs;
}

export async function collectBoundedChild(
  child: OwnedChild,
  options: CommandOptions,
  absoluteDeadline: number,
  settle: (bounded: boolean) => Promise<CommandError | undefined>,
): Promise<CompletedCommand> {
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  let stdoutBytes = 0;
  let stderrBytes = 0;
  let retainedStdoutBytes = 0;
  let retainedStderrBytes = 0;
  let failure: CommandError | undefined;
  let cleanup: Promise<CommandError | undefined> | undefined;
  let startCleanupSignal: (() => void) | undefined;
  const cleanupStarted = new Promise<void>((resolve) => {
    startCleanupSignal = resolve;
  });

  const startCleanup = (bounded: boolean) => {
    const requested = settle(bounded);
    if (cleanup === undefined) {
      cleanup = requested;
      startCleanupSignal!();
    }
  };

  const beginFailure = (error: CommandError) => {
    if (failure !== undefined) return;
    failure = error;
    startCleanup(true);
  };

  child.stdout.on("data", (value: Buffer) => {
    stdoutBytes += value.byteLength;
    const remaining = options.maxOutputBytes - retainedStdoutBytes;
    if (remaining > 0) {
      const retained = value.subarray(0, remaining);
      stdout.push(retained);
      retainedStdoutBytes += retained.byteLength;
    }
    if (stdoutBytes > options.maxOutputBytes) {
      beginFailure(
        new CommandOutputLimitError("stdout", Math.min(stdoutBytes, options.maxOutputBytes)),
      );
    }
  });
  child.stderr.on("data", (value: Buffer) => {
    stderrBytes += value.byteLength;
    const remaining = options.maxOutputBytes - retainedStderrBytes;
    if (remaining > 0) {
      const retained = value.subarray(0, remaining);
      stderr.push(retained);
      retainedStderrBytes += retained.byteLength;
    }
    if (stderrBytes > options.maxOutputBytes) {
      beginFailure(
        new CommandOutputLimitError("stderr", Math.min(stderrBytes, options.maxOutputBytes)),
      );
    }
  });
  child.stdout.once("error", () => beginFailure(new CommandCaptureError("stdout")));
  child.stderr.once("error", () => beginFailure(new CommandCaptureError("stderr")));

  child.once("error", () => beginFailure(new CommandStartError()));
  child.once("exit", (status, signal) => {
    if (failure === undefined && options.check !== false && (status ?? 1) !== 0) {
      const signalNumber = signal === null ? 0 : (osConstants.signals[signal] ?? 0);
      beginFailure(new CommandExitError(status ?? 128 + signalNumber));
    }
    startCleanup(failure !== undefined);
  });

  const timeout = setTimeout(
    () => beginFailure(new CommandTimeoutError(options.timeoutMs)),
    Math.max(0, absoluteDeadline - performance.now()),
  );
  await cleanupStarted;
  const cleanupError = await cleanup!;
  clearTimeout(timeout);
  if (cleanupError !== undefined) throw cleanupError;

  if (failure !== undefined) throw failure;
  return {
    status:
      child.exitCode ??
      128 + (child.signalCode === null ? 0 : (osConstants.signals[child.signalCode] ?? 0)),
    stdout: Buffer.concat(stdout).toString("utf8"),
    stderr: Buffer.concat(stderr).toString("utf8"),
  };
}

export async function runCommand(options: CommandOptions): Promise<CompletedCommand> {
  if (parentSignalActive) throw new CommandShuttingDownError();
  const graceMs = validateOptions(options);
  const absoluteDeadline = performance.now() + options.timeoutMs;
  installSignalCleanup();
  let child: OwnedChild;
  try {
    child = spawn(options.command, [...options.args], {
      cwd: options.cwd,
      env: options.env,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    removeSignalCleanupIfIdle();
    throw new CommandStartError();
  }
  const closed = new Promise<void>((resolve) => child.once("close", () => resolve()));
  let settlement: Promise<CommandError | undefined> | undefined;
  let bounded = false;
  let wakeBounded: (() => void) | undefined;
  const boundedWake = new Promise<void>((resolve) => {
    wakeBounded = resolve;
  });
  const settle = (forceBounded: boolean): Promise<CommandError | undefined> => {
    if (forceBounded && !bounded) {
      bounded = true;
      wakeBounded!();
    }
    settlement ??= settleChild(
      child,
      closed,
      graceMs,
      absoluteDeadline,
      () => bounded,
      boundedWake,
    );
    return settlement;
  };
  if (child.pid !== undefined) {
    activeGroups.set(child.pid, { settle });
  }
  try {
    return await collectBoundedChild(child, options, absoluteDeadline, settle);
  } catch (error) {
    if (parentSignalActive) {
      return await new Promise<CompletedCommand>(() => undefined);
    }
    throw error;
  } finally {
    if (child.pid !== undefined) activeGroups.delete(child.pid);
    removeSignalCleanupIfIdle();
  }
}
