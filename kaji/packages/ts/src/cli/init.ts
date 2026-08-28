/** `kaji init`: scaffold a no-key TypeScript Kaji project. */
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { constants, existsSync, lstatSync, mkdirSync, readFileSync } from "node:fs";
import { link, lstat as lstatAsync, mkdtemp, open, rename, rm, writeFile } from "node:fs/promises";
import { basename, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { RunOptions } from "@/cli/index";

const PROVIDERS = ["mock", "openai", "anthropic"] as const;
type Provider = (typeof PROVIDERS)[number];

interface Args {
  out: string;
  provider: Provider;
  force: boolean;
}

interface PackageMetadata {
  version: string;
  peerDependencies: Record<string, string>;
  devDependencies: Record<string, string>;
}

class CliArgError extends Error {}

export interface InitWorkerRequest {
  readonly version: 1;
  readonly expectedDev: string;
  readonly expectedIno: string;
  readonly targetAbsolute: string;
  readonly files: Readonly<Record<string, string>>;
  readonly force: boolean;
}

interface InitWorkerRequestOptions {
  readonly afterHandshake?: () => void | Promise<void>;
  readonly beforePublish?: () => void | Promise<void>;
  readonly publish?: (temporary: string, destination: string) => Promise<void>;
  readonly signal?: AbortSignal;
}

interface PinnedWorkerOptions {
  readonly invokeWorker?: (request: InitWorkerRequest) => Promise<void>;
}

interface WorkerProcessOptions {
  readonly beforeCommit?: () => void | Promise<void>;
  readonly command?: readonly [executable: string, ...args: string[]];
  readonly startupTimeoutMs?: number;
  readonly transactionTimeoutMs?: number;
}

const WORKER_INPUT_LIMIT_BYTES = 256 * 1024;
const WORKER_OUTPUT_LIMIT_BYTES = 8 * 1024;
const WORKER_TIMEOUT_MS = 15_000;
const WORKER_COMMIT = "commit";
const WORKER_CANCEL = "cancel";
const WORKER_PREPARED = '{"prepared":true}';
const WORKER_SUCCESS = '{"ok":true}';
const RECOVERY_DIRECTORY = /^\.kaji-scaffold-backup-[A-Za-z0-9]{6}$/;

function safeRecoveryDirectory(value: unknown): string | undefined {
  return typeof value === "string" && RECOVERY_DIRECTORY.test(value) ? value : undefined;
}

export class ScaffoldRollbackError extends Error {
  readonly recoveryDirectory: string;

  constructor(recoveryDirectory: string, cause?: unknown) {
    const safeDirectory = safeRecoveryDirectory(recoveryDirectory);
    if (safeDirectory === undefined) throw new Error("invalid scaffold recovery directory");
    super("scaffold publication rollback failed", { cause });
    this.name = "ScaffoldRollbackError";
    this.recoveryDirectory = safeDirectory;
  }
}

export function scaffoldRecoveryDirectory(error: unknown): string | undefined {
  return error instanceof ScaffoldRollbackError ? error.recoveryDirectory : undefined;
}

function throwIfCancelled(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw new Error("scaffold worker cancelled");
}

function parseArgs(rest: string[]): Args {
  let positionalPath: string | undefined;
  let provider: Provider = "mock";
  let force = false;

  for (let index = 0; index < rest.length; index++) {
    const arg = rest[index]!;
    if (arg === "--provider") {
      const next = rest[index + 1];
      if (next === undefined || next.startsWith("--")) {
        throw new CliArgError("--provider requires a value");
      }
      if (!PROVIDERS.includes(next as Provider)) {
        throw new CliArgError("--provider must be mock, openai, or anthropic");
      }
      provider = next as Provider;
      index++;
    } else if (arg === "--force") {
      force = true;
    } else if (arg === "--yes") {
      // Reserved for prompt-free parity with the Python CLI.
    } else if (arg.startsWith("--")) {
      throw new CliArgError(`unknown argument: ${arg}`);
    } else if (positionalPath === undefined) {
      positionalPath = arg;
    } else {
      throw new CliArgError(`unexpected path argument: ${arg}`);
    }
  }

  return {
    out: resolve(positionalPath ?? "."),
    provider,
    force,
  };
}

function installedMetadata(): PackageMetadata {
  const path = new URL("../../package.json", import.meta.url);
  const value = JSON.parse(readFileSync(path, "utf8")) as Partial<PackageMetadata>;
  if (
    typeof value.version !== "string" ||
    value.version.length === 0 ||
    value.peerDependencies === undefined ||
    value.devDependencies === undefined
  ) {
    throw new Error("installed kaji package metadata is incomplete");
  }
  return value as PackageMetadata;
}

function agentSource(provider: Provider): string {
  const providerImports = {
    mock: 'import { MockProvider } from "@irogane/kaji/testing";',
    openai: 'import { OpenAIProvider } from "@irogane/kaji/openai";',
    anthropic: 'import { AnthropicProvider } from "@irogane/kaji/anthropic";',
  } as const;
  const providerSetup = {
    mock: "const provider = new MockProvider();",
    openai: `const environment = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
const apiKey = environment.OPENAI_API_KEY;
if (!apiKey) throw new Error("OPENAI_API_KEY is required for the openai scaffold");
const provider = new OpenAIProvider({ apiKey });`,
    anthropic: `const environment = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
const apiKey = environment.ANTHROPIC_API_KEY;
if (!apiKey) throw new Error("ANTHROPIC_API_KEY is required for the anthropic scaffold");
const provider = new AnthropicProvider({ apiKey });`,
  } as const;

  return `import { AgentBuilder } from "@irogane/kaji";
${providerImports[provider]}

${providerSetup[provider]}
const runtime = new AgentBuilder().provider(provider).build();
const result = await runtime.turn("Say hello.");
const finalSequence = Math.max(...result.events.map((event) => event.sequence));
console.log(\`text=\${result.text}\`);
console.log(\`turn_id=\${result.turnId}\`);
console.log(\`final_sequence=\${finalSequence}\`);
`;
}

function scaffoldFiles(provider: Provider): Record<string, string> {
  const metadata = installedMetadata();
  const zodRange = metadata.peerDependencies.zod;
  if (zodRange === undefined) throw new Error("installed kaji has no Zod peer range");
  const nodeTypesRange = metadata.devDependencies["@types/node"];
  if (nodeTypesRange === undefined) {
    throw new Error("installed kaji has no supported @types/node range");
  }
  const dotenvxVersion = metadata.devDependencies["@dotenvx/dotenvx"];
  if (dotenvxVersion === undefined) {
    throw new Error("installed kaji has no supported dotenvx version");
  }

  const dependencies: Record<string, string> = {
    "@irogane/kaji": metadata.version,
    zod: zodRange,
  };
  if (provider === "openai") {
    const range = metadata.peerDependencies.openai;
    if (range === undefined) throw new Error("installed kaji has no OpenAI peer range");
    dependencies.openai = range;
  } else if (provider === "anthropic") {
    const range = metadata.peerDependencies["@anthropic-ai/sdk"];
    if (range === undefined) throw new Error("installed kaji has no Anthropic peer range");
    dependencies["@anthropic-ai/sdk"] = range;
  }

  return {
    "package.json": JSON.stringify(
      {
        name: "my-kaji-agent",
        version: "0.1.0",
        private: true,
        type: "module",
        scripts: {
          start: "dotenvx run --ignore=MISSING_ENV_FILE -- tsx agent.ts",
          typecheck: "tsc --noEmit",
        },
        dependencies,
        devDependencies: {
          "@dotenvx/dotenvx": dotenvxVersion,
          "@types/node": nodeTypesRange,
          tsx: "^4.0.0",
          typescript57: metadata.devDependencies.typescript57 ?? "npm:typescript@5.7.3",
          typescript: metadata.devDependencies.typescript ?? "^6.0.0",
        },
      },
      null,
      2,
    ),
    "tsconfig.json": JSON.stringify(
      {
        compilerOptions: {
          target: "ES2022",
          module: "ESNext",
          moduleResolution: "Bundler",
          strict: true,
          esModuleInterop: true,
          skipLibCheck: false,
          types: ["node"],
        },
        include: ["*.ts"],
      },
      null,
      2,
    ),
    "agent.ts": agentSource(provider),
    ".env.example":
      provider === "mock"
        ? "# No provider credentials required.\n"
        : provider === "openai"
          ? "OPENAI_API_KEY=\n"
          : "ANTHROPIC_API_KEY=\n",
  };
}

function destinationKind(path: string): "missing" | "symlink" | "file" | "other" {
  try {
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) return "symlink";
    return stat.isFile() ? "file" : "other";
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return "missing";
    throw error;
  }
}

function validateWorkerRequest(value: unknown): InitWorkerRequest {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid scaffold worker request");
  }
  const request = value as Partial<InitWorkerRequest>;
  if (
    request.version !== 1 ||
    typeof request.expectedDev !== "string" ||
    !/^\d+$/.test(request.expectedDev) ||
    typeof request.expectedIno !== "string" ||
    !/^\d+$/.test(request.expectedIno) ||
    typeof request.targetAbsolute !== "string" ||
    !isAbsolute(request.targetAbsolute) ||
    typeof request.files !== "object" ||
    request.files === null ||
    Array.isArray(request.files) ||
    typeof request.force !== "boolean"
  ) {
    throw new Error("invalid scaffold worker request");
  }
  const entries = Object.entries(request.files);
  if (
    entries.length === 0 ||
    entries.length > 32 ||
    entries.some(
      ([name, body]) =>
        name.length === 0 ||
        name === "." ||
        name === ".." ||
        basename(name) !== name ||
        name.includes("\0") ||
        typeof body !== "string",
    )
  ) {
    throw new Error("invalid scaffold worker request");
  }
  return request as InitWorkerRequest;
}

async function assertTargetIdentity(
  targetAbsolute: string,
  expectedDev: bigint,
  expectedIno: bigint,
): Promise<void> {
  let targetStat;
  try {
    targetStat = await lstatAsync(targetAbsolute, { bigint: true });
  } catch {
    throw new Error("target directory changed during scaffold publication");
  }
  if (
    !targetStat.isDirectory() ||
    targetStat.isSymbolicLink() ||
    targetStat.dev !== expectedDev ||
    targetStat.ino !== expectedIno
  ) {
    throw new Error("target directory changed during scaffold publication");
  }
}

export async function runInitWorkerRequest(
  requestValue: unknown,
  options: InitWorkerRequestOptions = {},
): Promise<void> {
  const request = validateWorkerRequest(requestValue);
  const expectedDev = BigInt(request.expectedDev);
  const expectedIno = BigInt(request.expectedIno);

  throwIfCancelled(options.signal);
  // This must remain the worker's first filesystem operation. The parent
  // passes the identity obtained from an O_NOFOLLOW directory handle.
  const cwdStat = await lstatAsync(".", { bigint: true });
  throwIfCancelled(options.signal);
  if (!cwdStat.isDirectory() || cwdStat.dev !== expectedDev || cwdStat.ino !== expectedIno) {
    throw new Error("pinned scaffold directory identity mismatch");
  }

  await options.afterHandshake?.();
  throwIfCancelled(options.signal);
  await writeScaffoldFiles(".", request.files, request.force, {
    beforePublish: options.beforePublish,
    publish: options.publish,
    signal: options.signal,
    verifyTarget: () => assertTargetIdentity(request.targetAbsolute, expectedDev, expectedIno),
  });
}

class WorkerInput {
  private buffer = Buffer.alloc(0);
  private bytes = 0;

  async readLine(signal: AbortSignal): Promise<string> {
    for (;;) {
      const newline = this.buffer.indexOf(0x0a);
      if (newline >= 0) {
        const line = this.buffer.subarray(0, newline);
        this.buffer = this.buffer.subarray(newline + 1);
        return line.at(-1) === 0x0d
          ? line.subarray(0, line.byteLength - 1).toString("utf8")
          : line.toString("utf8");
      }

      const value = process.stdin.read() as Buffer | string | null;
      if (value !== null) {
        const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
        this.bytes += chunk.byteLength;
        if (this.bytes > WORKER_INPUT_LIMIT_BYTES) {
          throw new Error("scaffold worker input exceeded limit");
        }
        this.buffer = Buffer.concat([this.buffer, chunk]);
        continue;
      }
      if (process.stdin.readableEnded) {
        if (this.buffer.byteLength === 0) throw new Error("scaffold worker input ended early");
        const line = this.buffer.toString("utf8");
        this.buffer = Buffer.alloc(0);
        return line;
      }
      await once(process.stdin, "readable", { signal });
    }
  }
}

export async function runInitWorkerMain(): Promise<void> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  let timeout = setTimeout(cancel, WORKER_TIMEOUT_MS);
  process.once("SIGTERM", cancel);
  const input = new WorkerInput();
  try {
    const request = JSON.parse(await input.readLine(controller.signal)) as unknown;
    await runInitWorkerRequest(request, {
      signal: controller.signal,
      beforePublish: async () => {
        throwIfCancelled(controller.signal);
        clearTimeout(timeout);
        timeout = setTimeout(cancel, WORKER_TIMEOUT_MS);
        process.stdout.write(`${WORKER_PREPARED}\n`);
        const command = await input.readLine(controller.signal);
        if (command !== WORKER_COMMIT) throw new Error("scaffold worker cancelled");
        throwIfCancelled(controller.signal);
        // Past this barrier the validated, bounded transaction must run to completion or rollback.
        clearTimeout(timeout);
      },
    });
  } finally {
    clearTimeout(timeout);
    process.removeListener("SIGTERM", cancel);
  }
}

function workerRecoveryLine(line: string): string | undefined {
  try {
    const value = JSON.parse(line) as unknown;
    if (typeof value !== "object" || value === null) return undefined;
    const record = value as Record<string, unknown>;
    if (record.ok !== false || Object.keys(record).sort().join(",") !== "ok,recovery") {
      return undefined;
    }
    return safeRecoveryDirectory(record.recovery);
  } catch {
    return undefined;
  }
}

function safeTimeout(value: number | undefined): number {
  return value !== undefined && Number.isSafeInteger(value) && value > 0
    ? value
    : WORKER_TIMEOUT_MS;
}

/** @internal Spawn the pinned scaffold worker using its bounded commit protocol. */
export async function invokeInitWorkerProcess(
  request: InitWorkerRequest,
  options: WorkerProcessOptions = {},
): Promise<void> {
  const payload = JSON.stringify(request);
  if (Buffer.byteLength(`${payload}\n${WORKER_COMMIT}\n`) > WORKER_INPUT_LIMIT_BYTES) {
    throw new Error("pinned scaffold worker failed");
  }
  const workerPath = fileURLToPath(new URL("./init-worker.js", import.meta.url));
  const workerExecutable =
    typeof process.versions.bun === "string"
      ? (process.env.NODE_BINARY ?? "node")
      : process.execPath;
  const workerEnvironment = { ...process.env };
  delete workerEnvironment.NODE_OPTIONS;
  delete workerEnvironment.NODE_PATH;
  const command = options.command ?? [workerExecutable, workerPath];
  const startupTimeoutMs = safeTimeout(options.startupTimeoutMs);
  const transactionTimeoutMs = safeTimeout(options.transactionTimeoutMs);

  await new Promise<void>((resolveWorker, rejectWorker) => {
    const child = spawn(command[0], command.slice(1), {
      cwd: request.targetAbsolute,
      env: workerEnvironment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdoutBuffer = "";
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let failed = false;
    let settled = false;
    let prepared = false;
    let succeeded = false;
    let recoveryDirectory: string | undefined;
    let timer: NodeJS.Timeout | undefined;

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error === undefined) resolveWorker();
      else rejectWorker(error);
    };
    const cancelWorker = () => {
      if (settled) return;
      failed = true;
      if (!child.stdin.destroyed && child.stdin.writable) child.stdin.end(`${WORKER_CANCEL}\n`);
      child.kill("SIGTERM");
    };
    const armTimeout = (durationMs: number) => {
      clearTimeout(timer);
      timer = setTimeout(cancelWorker, durationMs);
    };
    const authorizeCommit = async () => {
      try {
        await options.beforeCommit?.();
      } catch {
        cancelWorker();
        return;
      }
      if (!failed && !settled && !child.stdin.destroyed && child.stdin.writable) {
        // Never reintroduce a hard cutoff after backups have been authorized for publication.
        clearTimeout(timer);
        child.stdin.end(`${WORKER_COMMIT}\n`);
      }
    };
    const consumeLine = (line: string) => {
      if (!prepared && line === WORKER_PREPARED) {
        prepared = true;
        armTimeout(transactionTimeoutMs);
        void authorizeCommit();
        return;
      }
      if (prepared && !succeeded && line === WORKER_SUCCESS) {
        succeeded = true;
        return;
      }
      const recovery = workerRecoveryLine(line);
      if (recovery !== undefined && recoveryDirectory === undefined) {
        recoveryDirectory = recovery;
        return;
      }
      cancelWorker();
    };
    const consume = (chunk: Buffer, stream: "stdout" | "stderr") => {
      if (stream === "stdout") {
        stdoutBytes += chunk.byteLength;
        if (stdoutBytes <= WORKER_OUTPUT_LIMIT_BYTES) {
          stdoutBuffer += chunk.toString("utf8");
          for (;;) {
            const newline = stdoutBuffer.indexOf("\n");
            if (newline < 0) break;
            const line = stdoutBuffer.slice(0, newline);
            stdoutBuffer = stdoutBuffer.slice(newline + 1);
            consumeLine(line);
          }
        }
      } else {
        stderrBytes += chunk.byteLength;
      }
      if (stdoutBytes > WORKER_OUTPUT_LIMIT_BYTES || stderrBytes > WORKER_OUTPUT_LIMIT_BYTES) {
        cancelWorker();
      }
    };

    armTimeout(startupTimeoutMs);
    child.stdout.on("data", (chunk: Buffer) => consume(chunk, "stdout"));
    child.stderr.on("data", (chunk: Buffer) => consume(chunk, "stderr"));
    child.stdin.on("error", cancelWorker);
    child.on("error", () => finish(new Error("pinned scaffold worker failed")));
    child.on("close", (code) => {
      if (recoveryDirectory !== undefined) {
        finish(new ScaffoldRollbackError(recoveryDirectory));
      } else if (!failed && code === 0 && prepared && succeeded && stdoutBuffer.length === 0) {
        finish();
      } else {
        finish(new Error("pinned scaffold worker failed"));
      }
    });
    child.stdin.write(`${payload}\n`);
  });
}

export async function runPinnedInitWorker(
  out: string,
  files: Readonly<Record<string, string>>,
  force: boolean,
  options: PinnedWorkerOptions = {},
): Promise<void> {
  const targetAbsolute = resolve(out);
  let directory;
  try {
    directory = await open(
      targetAbsolute,
      constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW,
    );
  } catch (error) {
    if (["ELOOP", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) {
      throw new Error("unsafe scaffold destination: symbolic links are not allowed");
    }
    throw error;
  }
  try {
    const targetStat = await directory.stat({ bigint: true });
    if (!targetStat.isDirectory()) {
      throw new Error("unsafe scaffold destination: target is not a directory");
    }
    const request: InitWorkerRequest = {
      version: 1,
      expectedDev: targetStat.dev.toString(),
      expectedIno: targetStat.ino.toString(),
      targetAbsolute,
      files,
      force,
    };
    try {
      await (options.invokeWorker ?? invokeInitWorkerProcess)(request);
    } catch (error) {
      if (error instanceof ScaffoldRollbackError) throw error;
      throw new Error("pinned scaffold worker failed");
    }
  } finally {
    await directory.close();
  }
}

export async function writeScaffoldFiles(
  out: string,
  files: Readonly<Record<string, string>>,
  force: boolean,
  options: {
    readonly beforePublish?: () => void | Promise<void>;
    readonly publish?: (temporary: string, destination: string) => Promise<void>;
    readonly signal?: AbortSignal;
    readonly verifyTarget?: () => Promise<void>;
  } = {},
): Promise<void> {
  const entries = Object.entries(files).map(([name, body]) => ({
    body,
    destination: join(out, name),
    temporary: join(out, `.${name}.kaji-${randomUUID()}.tmp`),
  }));
  const committed: Array<{ destination: string; dev: bigint; ino: bigint }> = [];
  const backups: Array<{ destination: string; backup: string }> = [];
  const published: Array<{ destination: string; dev: bigint; ino: bigint }> = [];
  let backupDirectory: string | undefined;
  try {
    throwIfCancelled(options.signal);
    for (const entry of entries) {
      await writeFile(entry.temporary, entry.body, { encoding: "utf8", flag: "wx" });
      throwIfCancelled(options.signal);
    }
    if (entries.some(({ destination }) => destinationKind(destination) === "symlink")) {
      throw new Error("unsafe scaffold destination: symbolic links are not allowed");
    }
    if (!force && entries.some(({ destination }) => destinationKind(destination) !== "missing")) {
      throw Object.assign(new Error("scaffold destination appeared during write"), {
        code: "EEXIST",
      });
    }

    if (force) {
      const kinds = entries.map((entry) => [entry, destinationKind(entry.destination)] as const);
      if (kinds.some(([, kind]) => kind === "symlink")) {
        throw new Error("unsafe scaffold destination: symbolic links are not allowed");
      }
      if (kinds.some(([, kind]) => kind === "other")) {
        throw new Error("unsafe scaffold destination: generated paths must be regular files");
      }

      backupDirectory = await mkdtemp(join(out, ".kaji-scaffold-backup-"));
      for (const [entry] of kinds) {
        const currentKind = destinationKind(entry.destination);
        if (currentKind === "symlink" || currentKind === "other") {
          throw new Error("unsafe scaffold destination: generated paths must be regular files");
        }
        if (currentKind === "missing") continue;
        const sourceStat = await lstatAsync(entry.destination, { bigint: true });
        if (!sourceStat.isFile() || sourceStat.isSymbolicLink()) {
          throw new Error("unsafe scaffold destination: generated paths must be regular files");
        }
        const backup = join(backupDirectory, basename(entry.destination));
        await rename(entry.destination, backup);
        backups.push({ destination: entry.destination, backup });
        throwIfCancelled(options.signal);
        const backupStat = await lstatAsync(backup, { bigint: true });
        throwIfCancelled(options.signal);
        if (
          !backupStat.isFile() ||
          backupStat.isSymbolicLink() ||
          backupStat.dev !== sourceStat.dev ||
          backupStat.ino !== sourceStat.ino
        ) {
          throw new Error("unsafe scaffold destination: destination changed during backup");
        }
      }
      await options.beforePublish?.();
      throwIfCancelled(options.signal);
      const publish = options.publish ?? rename;
      for (const entry of entries) {
        const temporaryStat = await lstatAsync(entry.temporary, { bigint: true });
        throwIfCancelled(options.signal);
        published.push({
          destination: entry.destination,
          dev: temporaryStat.dev,
          ino: temporaryStat.ino,
        });
        await publish(entry.temporary, entry.destination);
        throwIfCancelled(options.signal);
        const destinationStat = await lstatAsync(entry.destination, { bigint: true });
        throwIfCancelled(options.signal);
        if (
          !destinationStat.isFile() ||
          destinationStat.isSymbolicLink() ||
          destinationStat.dev !== temporaryStat.dev ||
          destinationStat.ino !== temporaryStat.ino
        ) {
          throw new Error("unsafe scaffold destination: destination changed during publication");
        }
      }
      await options.verifyTarget?.();
      throwIfCancelled(options.signal);
      await rm(backupDirectory, { recursive: true, force: true });
      backupDirectory = undefined;
    } else {
      await options.beforePublish?.();
      throwIfCancelled(options.signal);
      for (const entry of entries) {
        const sourceStat = await lstatAsync(entry.temporary, { bigint: true });
        throwIfCancelled(options.signal);
        await link(entry.temporary, entry.destination);
        committed.push({
          destination: entry.destination,
          dev: sourceStat.dev,
          ino: sourceStat.ino,
        });
        throwIfCancelled(options.signal);
      }
      await options.verifyTarget?.();
      throwIfCancelled(options.signal);
    }
  } catch (error) {
    const rollbackErrors: unknown[] = [];
    if (force) {
      for (const item of published.reverse()) {
        try {
          if (destinationKind(item.destination) === "missing") continue;
          const destinationStat = await lstatAsync(item.destination, { bigint: true });
          if (
            !destinationStat.isFile() ||
            destinationStat.isSymbolicLink() ||
            destinationStat.dev !== item.dev ||
            destinationStat.ino !== item.ino
          ) {
            throw new Error("scaffold destination changed during rollback");
          }
          await rm(item.destination, { force: true });
        } catch (rollbackError) {
          rollbackErrors.push(rollbackError);
        }
      }
      for (const item of backups.reverse()) {
        try {
          if (destinationKind(item.destination) !== "missing") {
            throw new Error("scaffold destination changed before backup restore");
          }
          await rename(item.backup, item.destination);
        } catch (rollbackError) {
          rollbackErrors.push(rollbackError);
        }
      }
      if (rollbackErrors.length === 0 && backupDirectory !== undefined) {
        try {
          await rm(backupDirectory, { recursive: true, force: true });
          backupDirectory = undefined;
        } catch (rollbackError) {
          rollbackErrors.push(rollbackError);
        }
      }
    } else {
      for (const item of committed) {
        try {
          const destinationStat = await lstatAsync(item.destination, { bigint: true });
          if (
            destinationStat.isFile() &&
            !destinationStat.isSymbolicLink() &&
            destinationStat.dev === item.dev &&
            destinationStat.ino === item.ino
          ) {
            await rm(item.destination, { force: true });
          }
        } catch (cleanupError) {
          if ((cleanupError as NodeJS.ErrnoException).code !== "ENOENT") {
            rollbackErrors.push(cleanupError);
          }
        }
      }
    }
    if (rollbackErrors.length > 0) {
      if (backupDirectory !== undefined) {
        throw new ScaffoldRollbackError(
          basename(backupDirectory),
          new AggregateError([error, ...rollbackErrors]),
        );
      }
      throw new AggregateError([error, ...rollbackErrors], "scaffold publication rollback failed");
    }
    throw error;
  } finally {
    for (const entry of entries) await rm(entry.temporary, { force: true }).catch(() => undefined);
  }
}

export async function init(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((message: string) => console.log(message));
  const err = opts.err ?? ((message: string) => console.error(message));
  let args: Args;
  try {
    args = parseArgs(rest);
  } catch (error) {
    if (error instanceof CliArgError) {
      err(`Error: ${error.message}`);
      err("usage: kaji init [path] [--provider mock|openai|anthropic] [--yes] [--force]");
      return 2;
    }
    throw error;
  }

  let files: Record<string, string>;
  try {
    files = scaffoldFiles(args.provider);
  } catch {
    err("kaji init could not read installed package metadata");
    return 1;
  }
  const destinations = Object.keys(files).map((name) => join(args.out, name));
  const targetKind = destinationKind(args.out);
  const kinds = destinations.map((path) => [path, destinationKind(path)] as const);
  if (targetKind === "symlink" || kinds.some(([, kind]) => kind === "symlink")) {
    err("unsafe scaffold destination: symbolic links are not allowed");
    return 1;
  }
  const conflicts = kinds.filter(([, kind]) => kind !== "missing").map(([path]) => path);
  if (conflicts.length > 0 && !args.force) {
    err(
      `refusing to overwrite without --force: ${conflicts.map((path) => path.split("/").at(-1)).join(", ")}`,
    );
    return 1;
  }

  try {
    if (!existsSync(args.out)) mkdirSync(args.out, { recursive: true });
    await (opts.initWorkerRunner ?? runPinnedInitWorker)(args.out, files, args.force);
    for (const name of Object.keys(files)) log(`wrote ${join(args.out, name)}`);
  } catch (error) {
    if (error instanceof ScaffoldRollbackError) {
      err(
        "kaji init failed while writing the scaffold; " +
          `original preserved in target directory as ${error.recoveryDirectory}`,
      );
    } else if (error instanceof Error && error.message.includes("unsafe scaffold destination")) {
      err(error.message);
    } else if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      err("refusing to overwrite without --force: destination changed during write");
    } else {
      err("kaji init failed while writing the scaffold");
    }
    return 1;
  }
  log("");
  log(`Next: cd ${args.out} && npm install && npm start (or bun install && bun start)`);
  return 0;
}
