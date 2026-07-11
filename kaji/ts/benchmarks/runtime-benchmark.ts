import { fileURLToPath } from "node:url";

import { InMemoryEventCommitter } from "@/events/committer";
import { StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import type { Clock, IdFactory } from "@/internal/uuid";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "@/providers/base";
import type { ToolExecutionContext } from "@/runtime/context";
import { AgentRuntime } from "@/runtime/runtime";
import { InMemorySessionTurnCoordinator } from "@/runtime/session-turn-coordinator";
import { replaySession } from "@/sessions/replay";
import { ToolExecutionController } from "@/tools/execution";
import type { ToolSpec } from "@/tools/registry";

const CASES = ["replay10k", "crossSession100", "sameSession25", "toolBatch100"] as const;
type CaseName = (typeof CASES)[number];

interface Options {
  readonly caseName: CaseName;
  readonly samples: number;
  readonly warmups: number;
  readonly seed: number;
  readonly worker: boolean;
}

interface WorkerSample {
  readonly case: CaseName;
  readonly durationMs: number;
  readonly peakMiB: number;
  readonly completed: number;
  readonly maxActive?: number;
  readonly eventsApplied?: number;
  readonly cursor?: number;
  readonly coordinatorEntries?: number;
  readonly coordinatorWaiters?: number;
  readonly calls?: number;
  readonly stuckCalls?: number;
}

class Deferred<T = void> {
  readonly promise: Promise<T>;
  private settle!: (value: T | PromiseLike<T>) => void;

  constructor() {
    this.promise = new Promise((resolve) => {
      this.settle = resolve;
    });
  }

  resolve(value: T extends void ? never : T): void;
  resolve(): void;
  resolve(value?: T): void {
    this.settle(value as T);
  }
}

class DeterministicIds implements IdFactory {
  private index = 0;

  constructor(private readonly seed: number) {}

  next(scope: Parameters<IdFactory["next"]>[0]): string {
    return `${scope}-${this.seed}-${++this.index}`;
  }
}

class ReleaseProvider implements ModelProvider {
  private readonly enteredTarget = new Deferred();
  private readonly gate = new Deferred();
  private entered = 0;
  active = 0;
  maxActive = 0;

  constructor(private readonly target: number) {}

  waitUntilTarget(): Promise<void> {
    return this.enteredTarget.promise;
  }

  release(): void {
    this.gate.resolve();
  }

  async generate(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    throw new Error("ReleaseProvider only supports streaming");
  }

  async *generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    this.entered++;
    this.active++;
    this.maxActive = Math.max(this.maxActive, this.active);
    if (this.entered === this.target) this.enteredTarget.resolve();
    try {
      await this.gate.promise;
      yield { delta: "ok", toolCalls: [] };
    } finally {
      this.active--;
    }
  }
}

const MONOTONIC_CLOCK: Clock = Object.freeze({
  nowWallSeconds: () => 1,
  nowMonotonic: () => Number(process.hrtime.bigint()) / 1_000_000,
});

function parseCase(value: string | undefined, flag: string): CaseName {
  if (!CASES.includes(value as CaseName)) {
    throw new Error(`${flag} must be one of ${CASES.join(", ")}`);
  }
  return value as CaseName;
}

function integer(value: string | undefined, flag: string, allowZero = false): number {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < (allowZero ? 0 : 1)) {
    throw new Error(`${flag} must be ${allowZero ? "a non-negative" : "a positive"} integer`);
  }
  return parsed;
}

function parseArgs(argv: readonly string[]): Options {
  let caseName: CaseName | undefined;
  let workerCase: CaseName | undefined;
  let samples = 5;
  let warmups = 2;
  let seed = 13_013;
  for (let index = 0; index < argv.length; index++) {
    const flag = argv[index];
    if (flag === "--json") continue;
    const value = argv[++index];
    switch (flag) {
      case "--case":
        caseName = parseCase(value, flag);
        break;
      case "--worker-case":
        workerCase = parseCase(value, flag);
        break;
      case "--samples":
        samples = integer(value, flag);
        break;
      case "--warmups":
        warmups = integer(value, flag, true);
        break;
      case "--seed":
        seed = integer(value, flag, true);
        break;
      default:
        throw new Error(`Unknown argument ${flag ?? "<missing>"}`);
    }
  }
  const selected = workerCase ?? caseName;
  if (selected === undefined) throw new Error("--case is required");
  return { caseName: selected, samples, warmups, seed, worker: workerCase !== undefined };
}

function nowNs(): bigint {
  return process.hrtime.bigint();
}

function elapsedMs(started: bigint): number {
  return Number(nowNs() - started) / 1_000_000;
}

function peakMiB(): number {
  const rawMaxRss = process.resourceUsage().maxRSS;
  const currentRssBytes = process.memoryUsage().rss;
  const maxRssBytes = rawMaxRss >= currentRssBytes / 8 ? rawMaxRss : rawMaxRss * 1_024;
  return maxRssBytes / 1_048_576;
}

function runtime(
  provider: ModelProvider,
  seed: number,
  coordinator: InMemorySessionTurnCoordinator,
): AgentRuntime {
  const store = new InMemoryEventStore();
  return new AgentRuntime({
    provider,
    store,
    committer: new InMemoryEventCommitter(store),
    turnCoordinator: coordinator,
    tools: [],
    idFactory: new DeterministicIds(seed),
    clock: MONOTONIC_CLOCK,
  });
}

function executionContext(index: number): ToolExecutionContext {
  const sessionId = "tool-batch";
  const callId = `call-${index}`;
  return {
    principalId: "benchmark",
    sessionId,
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: callId,
    idempotencyKey: `${sessionId}:${callId}`,
    signal: new AbortController().signal,
    metadata: {},
  };
}

async function replay10k(seed: number): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const events = Array.from({ length: 10_000 }, (_, index) =>
    StoredKajiEvent.parse({
      id: `replay-${seed}-${index}`,
      version: "1.0",
      timestamp: index,
      type: EventType.USER_MESSAGE,
      session_id: "replay10k",
      content: `event-${index}`,
      metadata: {},
      sequence: index + 1,
    }),
  );
  const started = nowNs();
  const state = replaySession(events);
  const durationMs = elapsedMs(started);
  if (state.messages.length !== events.length) throw new Error("replay dropped events");
  return {
    durationMs,
    completed: state.messages.length,
    eventsApplied: state.messages.length,
    cursor: events.at(-1)?.sequence ?? 0,
  };
}

async function crossSession100(seed: number): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const provider = new ReleaseProvider(100);
  const coordinator = new InMemorySessionTurnCoordinator();
  const agent = runtime(provider, seed, coordinator);
  const started = nowNs();
  const turns = Array.from({ length: 100 }, (_, index) =>
    agent.turn(`cross-${index}`, { sessionId: `session-${index}` }),
  );
  await provider.waitUntilTarget();
  provider.release();
  await Promise.all(turns);
  return {
    durationMs: elapsedMs(started),
    completed: turns.length,
    maxActive: provider.maxActive,
    calls: turns.length,
    coordinatorEntries: coordinator.entryCount,
    coordinatorWaiters: coordinator.waitingCount,
  };
}

async function sameSession25(seed: number): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const provider = new ReleaseProvider(1);
  const coordinator = new InMemorySessionTurnCoordinator();
  const agent = runtime(provider, seed, coordinator);
  const started = nowNs();
  const turns = Array.from({ length: 25 }, (_, index) =>
    agent.turn(`same-${index}`, { sessionId: "same-session" }),
  );
  await provider.waitUntilTarget();
  provider.release();
  await Promise.all(turns);
  return {
    durationMs: elapsedMs(started),
    completed: turns.length,
    maxActive: provider.maxActive,
    calls: turns.length,
    coordinatorEntries: coordinator.entryCount,
    coordinatorWaiters: coordinator.waitingCount,
  };
}

async function toolBatch100(): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const controller = new ToolExecutionController({
    limits: { maxParallel: 4, timeoutMs: null },
  });
  const firstFour = new Deferred();
  const gate = new Deferred();
  let active = 0;
  let maxActive = 0;
  let startedCount = 0;
  const started = nowNs();
  const executions = Array.from({ length: 100 }, (_, index) =>
    controller.execute({
      name: "parallel",
      args: { index },
      context: executionContext(index),
      exclusive: false,
      onStarted: async () => {},
      execute: async () => {
        active++;
        maxActive = Math.max(maxActive, active);
        startedCount++;
        if (startedCount === 4) firstFour.resolve();
        try {
          await gate.promise;
          return { index };
        } finally {
          active--;
        }
      },
    }),
  );
  await firstFour.promise;
  gate.resolve();
  const outcomes = await Promise.all(executions);
  const completed = outcomes.filter(({ status }) => status === "completed").length;
  const stuckCalls = (await controller.drain(0)).length;
  if (stuckCalls !== 0) throw new Error("tool handlers leaked");
  return {
    durationMs: elapsedMs(started),
    completed,
    maxActive,
    calls: executions.length,
    stuckCalls,
  };
}

async function runWorker(caseName: CaseName, seed: number): Promise<WorkerSample> {
  const workload =
    caseName === "replay10k"
      ? await replay10k(seed)
      : caseName === "crossSession100"
        ? await crossSession100(seed)
        : caseName === "sameSession25"
          ? await sameSession25(seed)
          : await toolBatch100();
  return { case: caseName, ...workload, peakMiB: peakMiB() };
}

async function childSample(caseName: CaseName, seed: number): Promise<WorkerSample> {
  const script = fileURLToPath(import.meta.url);
  const child = Bun.spawn({
    cmd: [process.execPath, script, "--worker-case", caseName, "--seed", String(seed)],
    stdout: "pipe",
    stderr: "pipe",
    env: process.env,
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  if (exitCode !== 0) {
    throw new Error(`Benchmark child failed (${exitCode}): ${stderr.trim()}`);
  }
  return JSON.parse(stdout) as WorkerSample;
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1]! + sorted[middle]!) / 2 : sorted[middle]!;
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  if (options.worker) {
    process.stdout.write(`${JSON.stringify(await runWorker(options.caseName, options.seed))}\n`);
    return;
  }

  for (let index = 0; index < options.warmups; index++) {
    await childSample(options.caseName, options.seed);
  }
  const rawSamples: WorkerSample[] = [];
  for (let index = 0; index < options.samples; index++) {
    rawSamples.push(await childSample(options.caseName, options.seed));
  }
  const durations = rawSamples.map(({ durationMs }) => durationMs);
  const active = rawSamples.flatMap(({ maxActive }) =>
    maxActive === undefined ? [] : [maxActive],
  );
  const result = {
    schemaVersion: 1,
    runtime: "typescript",
    engine: typeof Bun === "undefined" ? `node-${process.version}` : `bun-${Bun.version}`,
    case: options.caseName,
    seed: options.seed,
    warmups: options.warmups,
    samples: options.samples,
    medianMs: median(durations),
    maxPeakMiB: Math.max(...rawSamples.map((sample) => sample.peakMiB)),
    ...(active.length === 0 ? {} : { maxActive: Math.max(...active) }),
    sampleResults: rawSamples,
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

await main();
