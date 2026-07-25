import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type OpenAI from "openai";

import {
  AgentRuntime,
  DEFAULT_PROVIDER_RESPONSE_LIMITS,
  EventType,
  InMemoryEventCommitter,
  InMemoryEventStore,
  InMemorySessionTurnCoordinator,
  KajiEvent,
  SessionProjector,
  StoredKajiEvent,
  ToolExecutionController,
  applyEvent,
  replaySession,
  type Clock,
  type IdFactory,
  type ModelProvider,
  type ModelProviderOptions,
  type ModelResponse,
  type ModelResponseChunk,
  type ProviderMessage,
  ProviderOutputLimitError,
  type TimerHandle,
  type TimerScheduler,
  type ToolExecutionContext,
  type ToolSpec,
} from "kaji-sdk";
import { OpenAIProvider } from "kaji-sdk/openai";
import {
  createSessionState,
  type ProviderResponseDiagnostics,
  withProviderResponseDiagnostics,
} from "kaji-sdk/testing";

const RESOLVED_PACKAGE = realpathSync(
  join(dirname(fileURLToPath(import.meta.resolve("kaji-sdk"))), ".."),
);

const CASES = [
  "replay10k",
  "crossSession100",
  "sameSession25",
  "toolBatch100",
  "context10kIterations5",
  "crossSessionCommit100",
  "streamDeltas10k",
  "toolArgDeltas10k",
] as const;
type CaseName = (typeof CASES)[number];
type RssProbeMode = "baseline" | "indexed";

interface Options {
  readonly caseName: CaseName | undefined;
  readonly samples: number;
  readonly warmups: number;
  readonly workerWarmups: number;
  readonly seed: number;
  readonly worker: boolean;
  readonly rssProbe: RssProbeMode | undefined;
}

interface WorkerSample {
  readonly case: CaseName;
  readonly durationMs: number;
  readonly peakMiB: number;
  readonly warmupRuns: number;
  readonly completed: number;
  readonly maxActive?: number;
  readonly eventsApplied?: number;
  readonly cursor?: number;
  readonly coordinatorEntries?: number;
  readonly coordinatorWaiters?: number;
  readonly batchRepetitions?: number;
  readonly calls?: number;
  readonly turns?: number;
  readonly stuckCalls?: number;
  readonly historyEvents?: number;
  readonly fullHistoryScans?: number;
  readonly providerIterations?: number;
  readonly coldEvents?: number;
  readonly incrementalEvents?: number;
  readonly suffixCalls?: number;
  readonly copiedPayloadBytes?: number;
  readonly retainedTurns?: number;
  readonly turnIndexEntries?: number;
  readonly sentinelEntries?: number;
  readonly totalIndexEntries?: number;
  readonly maxVisitedTurnEntries?: number;
  readonly incrementalRssBytes?: number;
  readonly timerLeaks?: number;
  readonly providerTaskLeaks?: number;
  readonly sessions?: number;
  readonly commits?: number;
  readonly overlappingSessions?: number;
  readonly contiguousSessions?: number;
  readonly laneEntriesAfter?: number;
  readonly reservationEntriesAfter?: number;
  readonly characters?: number;
  readonly deltaEvents?: number;
  readonly inputFragments?: number;
  readonly deltaJoinOperations?: number;
  readonly responseJoinOperations?: number;
  readonly providerTextMaxBytes?: number;
  readonly providerResponseMaxBytes?: number;
  readonly completionEvents?: number;
  readonly completionEventsAfterFailure?: number;
  readonly argumentBytes?: number;
  readonly responseMaxBytes?: number;
  readonly argumentFragments?: number;
  readonly rawFragments?: number;
  readonly fragmentJoins?: number;
  readonly overLimitBytes?: number;
  readonly overLimitRejectedBeforeParse?: boolean;
  readonly iteratorLeaks?: number;
  readonly parserLeaks?: number;
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

class TrackingTimerScheduler implements TimerScheduler {
  private readonly pending = new Set<ReturnType<typeof setTimeout>>();

  get pendingCount(): number {
    return this.pending.size;
  }

  schedule(delayMs: number, callback: () => void): TimerHandle {
    const timer = setTimeout(() => {
      this.pending.delete(timer);
      callback();
    }, delayMs);
    (timer as unknown as { unref?: () => void }).unref?.();
    this.pending.add(timer);
    return {
      cancel: () => {
        if (!this.pending.delete(timer)) return;
        clearTimeout(timer);
      },
    };
  }
}

class ToolLoopProvider implements ModelProvider {
  calls = 0;
  active = 0;

  async generate(): Promise<ModelResponse> {
    throw new Error("ToolLoopProvider only supports streaming");
  }

  async *generateStream(): AsyncGenerator<ModelResponseChunk> {
    this.calls++;
    this.active++;
    try {
      yield {
        delta: "",
        toolCalls: [
          {
            id: `runtime-call-${this.calls}`,
            name: "noop",
            args: {},
          },
        ],
      };
    } finally {
      this.active--;
    }
  }
}

class TextStreamProvider implements ModelProvider {
  active = 0;

  constructor(
    private readonly fragments: number,
    private readonly failure: Error | undefined = undefined,
  ) {}

  async generate(): Promise<ModelResponse> {
    throw new Error("TextStreamProvider only supports streaming");
  }

  async *generateStream(): AsyncGenerator<ModelResponseChunk> {
    this.active++;
    try {
      for (let index = 0; index < this.fragments; index++) {
        yield { delta: "x", toolCalls: [] };
      }
      if (this.failure !== undefined) throw this.failure;
    } finally {
      this.active--;
    }
  }
}

interface IteratorTracker {
  active: number;
}

class OpenAIToolArgumentStream implements AsyncIterableIterator<unknown> {
  private index = 0;
  private closed = false;

  constructor(
    private readonly fragments: readonly string[],
    private readonly tracker: IteratorTracker,
  ) {
    tracker.active++;
  }

  async next(): Promise<IteratorResult<unknown>> {
    if (this.index < this.fragments.length) {
      const index = this.index++;
      return {
        done: false,
        value: {
          choices: [
            {
              delta: {
                tool_calls: [
                  {
                    index: 0,
                    ...(index === 0 ? { id: "call" } : {}),
                    function: {
                      ...(index === 0 ? { name: "lookup" } : {}),
                      arguments: this.fragments[index],
                    },
                  },
                ],
              },
              finish_reason: null,
            },
          ],
        },
      };
    }
    if (this.index++ === this.fragments.length) {
      return {
        done: false,
        value: { choices: [{ delta: {}, finish_reason: "tool_calls" }] },
      };
    }
    this.close();
    return { done: true, value: undefined };
  }

  async return(): Promise<IteratorResult<unknown>> {
    this.close();
    return { done: true, value: undefined };
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<unknown> {
    return this;
  }

  private close(): void {
    if (this.closed) return;
    this.closed = true;
    this.tracker.active--;
  }
}

class BenchmarkOpenAIProvider extends OpenAIProvider {
  constructor(private readonly fakeClient: OpenAI) {
    super({ apiKey: "benchmark" });
  }

  protected override async createClient(): Promise<OpenAI> {
    return this.fakeClient;
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
  let rssProbe: RssProbeMode | undefined;
  let samples = 5;
  let warmups = 2;
  let workerWarmups = 0;
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
      case "--rss-probe":
        if (value !== "baseline" && value !== "indexed") {
          throw new Error("--rss-probe must be baseline or indexed");
        }
        rssProbe = value;
        break;
      case "--samples":
        samples = integer(value, flag);
        break;
      case "--warmups":
        warmups = integer(value, flag, true);
        break;
      case "--worker-warmups":
        workerWarmups = integer(value, flag, true);
        break;
      case "--seed":
        seed = integer(value, flag, true);
        break;
      default:
        throw new Error(`Unknown argument ${flag ?? "<missing>"}`);
    }
  }
  const selected = workerCase ?? caseName;
  if (selected === undefined && rssProbe === undefined) throw new Error("--case is required");
  if (selected !== undefined && rssProbe !== undefined) {
    throw new Error("--rss-probe cannot be combined with a benchmark case");
  }
  return {
    caseName: selected,
    samples,
    warmups,
    workerWarmups,
    seed,
    worker: workerCase !== undefined,
    rssProbe,
  };
}

function nowNs(): bigint {
  return process.hrtime.bigint();
}

function elapsedMs(started: bigint): number {
  return Number(nowNs() - started) / 1_000_000;
}

function peakMiB(): number {
  return peakRssBytes() / 1_048_576;
}

function peakRssBytes(): number {
  const rawMaxRss = process.resourceUsage().maxRSS;
  const currentRssBytes = process.memoryUsage().rss;
  return rawMaxRss >= currentRssBytes / 8 ? rawMaxRss : rawMaxRss * 1_024;
}

function* contextHistoryInputs(seed: number): Generator<Record<string, unknown>> {
  let event = 0;
  for (let batch = 0; batch < 2_000; batch++) {
    const callId = `call-${batch}`;
    const common = () => ({
      id: `context-${seed}-${++event}`,
      version: "1.0",
      timestamp: event,
      session_id: "context10k",
    });
    yield { ...common(), type: EventType.USER_MESSAGE, content: String(batch) };
    yield { ...common(), type: EventType.AGENT_REASONING_STARTED };
    yield {
      ...common(),
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: `seed-turn-${batch}`,
      tool_name: "lookup",
      tool_call_id: callId,
      tool_args: { batch },
    };
    yield {
      ...common(),
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: `seed-turn-${batch}`,
      tool_name: "lookup",
      tool_call_id: callId,
      result: { ok: true },
    };
    yield { ...common(), type: EventType.AGENT_MESSAGE_COMPLETED, content: `done-${batch}` };
  }
}

function splitNonempty(value: string, count: number): string[] {
  if (count < 1 || count > value.length) throw new RangeError("invalid fragment count");
  const base = Math.floor(value.length / count);
  const remainder = value.length % count;
  const fragments: string[] = [];
  let offset = 0;
  for (let index = 0; index < count; index++) {
    const width = base + (index < remainder ? 1 : 0);
    fragments.push(value.slice(offset, offset + width));
    offset += width;
  }
  return fragments;
}

function runRssProbe(mode: RssProbeMode, seed: number): { rss: number; messages: number } {
  const projector = mode === "indexed" ? new SessionProjector("context10k") : undefined;
  const state = projector === undefined ? createSessionState("context10k") : undefined;
  let sequence = 0;
  for (const input of contextHistoryInputs(seed)) {
    const event = StoredKajiEvent.parse({ ...input, sequence: ++sequence });
    if (projector === undefined) applyEvent(state!, event);
    else projector.apply(event);
  }
  if (typeof Bun !== "undefined") Bun.gc(true);
  const messages = projector?.state.messages.length ?? state!.messages.length;
  return { rss: peakRssBytes(), messages };
}

async function childRssProbe(
  mode: RssProbeMode,
  seed: number,
): Promise<{ rss: number; messages: number }> {
  const child = Bun.spawn({
    cmd: [
      process.execPath,
      fileURLToPath(import.meta.url),
      "--rss-probe",
      mode,
      "--seed",
      String(seed),
    ],
    stdout: "pipe",
    stderr: "pipe",
    env: process.env,
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  if (exitCode !== 0) throw new Error(`RSS child failed (${exitCode}): ${stderr.trim()}`);
  return JSON.parse(stdout) as { rss: number; messages: number };
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
    turns: turns.length,
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
    turns: turns.length,
    maxActive: provider.maxActive,
    calls: turns.length,
    coordinatorEntries: coordinator.entryCount,
    coordinatorWaiters: coordinator.waitingCount,
  };
}

interface ToolBatchResult {
  readonly completed: number;
  readonly maxActive: number;
  readonly calls: number;
  readonly stuckCalls: number;
}

async function toolBatch100(): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const batchRepetitions = 64;
  let completed = 0;
  let maxActive = 0;
  let calls = 0;
  let stuckCalls = 0;
  const started = nowNs();
  for (let repetition = 0; repetition < batchRepetitions; repetition++) {
    const result = await toolBatch100Once();
    completed += result.completed;
    maxActive = Math.max(maxActive, result.maxActive);
    calls += result.calls;
    stuckCalls += result.stuckCalls;
  }
  return {
    durationMs: elapsedMs(started),
    batchRepetitions,
    completed,
    maxActive,
    calls,
    stuckCalls,
  };
}

async function toolBatch100Once(): Promise<ToolBatchResult> {
  const controller = new ToolExecutionController({
    limits: { maxParallel: 4, timeoutMs: null },
  });
  const firstFour = new Deferred();
  const gate = new Deferred();
  let active = 0;
  let maxActive = 0;
  let startedCount = 0;
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
    completed,
    maxActive,
    calls: executions.length,
    stuckCalls,
  };
}

async function context10kIterations5(
  seed: number,
): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const baselineRss = await childRssProbe("baseline", seed);
  const indexedRss = await childRssProbe("indexed", seed);
  if (baselineRss.messages !== indexedRss.messages || baselineRss.messages === 0) {
    throw new Error("paired context RSS probes did not project identical histories");
  }

  const store = new InMemoryEventStore({ maxSessions: 2, maxEventsPerSession: 10_050 });
  const committer = new InMemoryEventCommitter(store);
  for (const input of contextHistoryInputs(seed)) {
    await committer.commit(KajiEvent.parse(input));
  }

  const provider = new ToolLoopProvider();
  const scheduler = new TrackingTimerScheduler();
  const noop: ToolSpec = {
    name: "noop",
    description: "deterministic benchmark no-op",
    parameters: { type: "object", additionalProperties: false },
    risk: "read",
  };
  const agent = new AgentRuntime({
    provider,
    store,
    committer,
    strategy: { maxToolIterations: 5 },
    tools: [noop],
    toolExecutor: async () => ({ ok: true }),
    defaultContext: { principalId: "benchmark" },
    idFactory: new DeterministicIds(seed),
    clock: MONOTONIC_CLOCK,
    timerScheduler: scheduler,
  });

  const started = nowNs();
  await agent.runTurn("context10k");
  const durationMs = elapsedMs(started);
  const stats = agent.contextIndexStats("context10k");
  if (stats === undefined) throw new Error("context benchmark did not retain index diagnostics");
  if (provider.calls !== 5) throw new Error("context benchmark did not execute five iterations");
  if (
    stats.fullColdBuilds !== 1 ||
    stats.coldEvents !== 10_000 ||
    stats.incrementalEvents !== 21 ||
    stats.suffixCalls !== 5 ||
    stats.persistentCopiedPayloadBytes !== 0 ||
    stats.retainedTurns === 0 ||
    stats.turnEntries / stats.retainedTurns > 1.01 ||
    stats.sentinelEntries > 1 ||
    stats.totalEntries !== stats.turnEntries + stats.sentinelEntries ||
    stats.maxVisitedTurnEntries > stats.retainedTurns
  ) {
    throw new Error("context index counters violated the benchmark invariant");
  }
  if (scheduler.pendingCount !== 0 || provider.active !== 0) {
    throw new Error("context benchmark leaked provider work");
  }

  return {
    durationMs,
    completed: provider.calls,
    historyEvents: 10_000,
    fullHistoryScans: stats.fullColdBuilds,
    providerIterations: provider.calls,
    coldEvents: stats.coldEvents,
    incrementalEvents: stats.incrementalEvents,
    suffixCalls: stats.suffixCalls,
    copiedPayloadBytes: stats.persistentCopiedPayloadBytes,
    retainedTurns: stats.retainedTurns,
    turnIndexEntries: stats.turnEntries,
    sentinelEntries: stats.sentinelEntries,
    totalIndexEntries: stats.totalEntries,
    maxVisitedTurnEntries: stats.maxVisitedTurnEntries,
    incrementalRssBytes: Math.max(0, indexedRss.rss - baselineRss.rss),
    timerLeaks: scheduler.pendingCount,
    providerTaskLeaks: provider.active,
  };
}

async function crossSessionCommit100(
  seed: number,
): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const store = new InMemoryEventStore({ maxSessions: 100, maxEventsPerSession: 2 });
  const committer = new InMemoryEventCommitter(store);
  const sessionIds = Array.from({ length: 100 }, (_, index) => `commit-${index}`);
  for (const [index, sessionId] of sessionIds.entries()) {
    await committer.commit(
      KajiEvent.parse({
        id: `commit-${seed}-${index}-1`,
        timestamp: 1,
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "first",
      }),
    );
  }

  const held = new Deferred();
  const release = new Deferred();
  const holder = store.sessionTransaction(sessionIds[0]!, async () => {
    held.resolve();
    await release.promise;
  });
  await held.promise;

  const completedBeforeRelease = new Set<string>();
  let blockedSessionCompleted = false;
  const started = nowNs();
  const commits = sessionIds.map((sessionId, index) =>
    committer
      .commit(
        KajiEvent.parse({
          id: `commit-${seed}-${index}-2`,
          timestamp: 2,
          type: EventType.AGENT_MESSAGE_COMPLETED,
          session_id: sessionId,
          content: "second",
        }),
      )
      .then((event) => {
        if (index === 0) blockedSessionCompleted = true;
        else completedBeforeRelease.add(sessionId);
        return event;
      }),
  );
  try {
    await Promise.all(commits.slice(1));
    if (blockedSessionCompleted) throw new Error("blocked session committed before lane release");
  } finally {
    release.resolve();
  }
  await holder;
  await Promise.all(commits);
  const durationMs = elapsedMs(started);

  let contiguousSessions = 0;
  for (const sessionId of sessionIds) {
    const sequences = (await store.getEvents(sessionId)).map((event) => event.sequence);
    if (sequences.length === 2 && sequences[0] === 1 && sequences[1] === 2) {
      contiguousSessions++;
    }
  }
  if (
    completedBeforeRelease.size < 2 ||
    contiguousSessions !== 100 ||
    store.activeSessionLaneCount !== 0 ||
    store.activeIdReservationCount !== 0
  ) {
    throw new Error("cross-session commits violated ordering or cleanup invariants");
  }
  return {
    durationMs,
    completed: commits.length,
    sessions: sessionIds.length,
    commits: commits.length,
    overlappingSessions: completedBeforeRelease.size,
    contiguousSessions,
    laneEntriesAfter: store.activeSessionLaneCount,
    reservationEntriesAfter: store.activeIdReservationCount,
  };
}

function streamingRuntime(
  provider: ModelProvider,
  seed: number,
  scheduler: TrackingTimerScheduler,
): { runtime: AgentRuntime; store: InMemoryEventStore } {
  const store = new InMemoryEventStore();
  return {
    store,
    runtime: new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      tools: [],
      idFactory: new DeterministicIds(seed),
      clock: MONOTONIC_CLOCK,
      timerScheduler: scheduler,
    }),
  };
}

async function streamDeltas10k(seed: number): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const provider = new TextStreamProvider(10_000);
  const scheduler = new TrackingTimerScheduler();
  const success = streamingRuntime(provider, seed, scheduler);
  const failureProvider = new TextStreamProvider(1, new Error("benchmark provider failure"));
  const failureScheduler = new TrackingTimerScheduler();
  const failure = streamingRuntime(failureProvider, seed + 1, failureScheduler);

  const started = nowNs();
  const result = await success.runtime.turn("stream", { sessionId: "stream-success" });
  let failed = false;
  try {
    await failure.runtime.turn("stream", { sessionId: "stream-failure" });
  } catch {
    failed = true;
  }
  const durationMs = elapsedMs(started);
  if (!failed) throw new Error("stream failure probe unexpectedly completed");
  if (result.text !== "x".repeat(10_000)) throw new Error("stream text was not exact");

  const diagnostics = success.runtime.streamDiagnostics("stream-success");
  if (diagnostics === undefined) throw new Error("stream diagnostics were not retained");
  const completionEvents = result.events.filter(
    (event) => event.type === EventType.AGENT_MESSAGE_COMPLETED,
  ).length;
  const completionEventsAfterFailure = (await failure.store.getEvents("stream-failure")).filter(
    (event) => event.type === EventType.AGENT_MESSAGE_COMPLETED,
  ).length;
  const limits = success.runtime.effectiveLimits();
  if (
    diagnostics.durableDeltaEvents > 16 ||
    diagnostics.inputFragments !== 10_000 ||
    diagnostics.deltaJoinOperations !== diagnostics.durableDeltaEvents ||
    diagnostics.responseJoinOperations !== 1 ||
    completionEvents !== 1 ||
    completionEventsAfterFailure !== 0 ||
    limits.providerTextMaxBytes !== 262_144 ||
    limits.providerResponseMaxBytes !== 524_288 ||
    scheduler.pendingCount !== 0 ||
    failureScheduler.pendingCount !== 0 ||
    provider.active !== 0 ||
    failureProvider.active !== 0
  ) {
    throw new Error("stream benchmark violated coalescing or cleanup invariants");
  }
  return {
    durationMs,
    completed: completionEvents,
    characters: result.text.length,
    deltaEvents: diagnostics.durableDeltaEvents,
    inputFragments: diagnostics.inputFragments,
    deltaJoinOperations: diagnostics.deltaJoinOperations,
    responseJoinOperations: diagnostics.responseJoinOperations,
    providerTextMaxBytes: limits.providerTextMaxBytes,
    providerResponseMaxBytes: limits.providerResponseMaxBytes,
    completionEvents,
    completionEventsAfterFailure,
    timerLeaks: scheduler.pendingCount + failureScheduler.pendingCount,
    providerTaskLeaks: provider.active + failureProvider.active,
  };
}

function openAIProviderFor(
  fragments: readonly string[],
  tracker: IteratorTracker,
): BenchmarkOpenAIProvider {
  const client = {
    chat: {
      completions: {
        create: async () => new OpenAIToolArgumentStream(fragments, tracker),
      },
    },
  } as unknown as OpenAI;
  return new BenchmarkOpenAIProvider(client);
}

async function toolArgDeltas10k(): Promise<Omit<WorkerSample, "case" | "peakMiB">> {
  const encoder = new TextEncoder();
  const overhead = encoder.encode('{"value":""}').byteLength;
  const value = "x".repeat(65_536 - overhead);
  const exactArguments = `{"value":"${value}"}`;
  const fragments = splitNonempty(exactArguments, 10_000);
  const exactTracker = { active: 0 };
  let diagnostics: Readonly<ProviderResponseDiagnostics> | undefined;

  const started = nowNs();
  const exactCalls = [];
  const exactProvider = openAIProviderFor(fragments, exactTracker);
  for await (const chunk of exactProvider.generateStream(
    [{ role: "user", content: "go" }],
    [],
    withProviderResponseDiagnostics(
      { responseLimits: DEFAULT_PROVIDER_RESPONSE_LIMITS },
      {
        record(value) {
          diagnostics = Object.freeze({ ...value });
        },
      },
    ),
  )) {
    exactCalls.push(...chunk.toolCalls);
  }
  if (exactCalls.length !== 1 || exactCalls[0]?.args.value !== value) {
    throw new Error("tool argument adapter did not parse the exact limit payload");
  }

  const overArguments = `${exactArguments.slice(0, -2)}a"}`;
  const overTracker = { active: 0 };
  const overProvider = openAIProviderFor([overArguments], overTracker);
  const originalParse = JSON.parse;
  let parseCalls = 0;
  let limitError: unknown;
  JSON.parse = ((...args: Parameters<typeof JSON.parse>) => {
    parseCalls++;
    return originalParse(...args);
  }) as typeof JSON.parse;
  try {
    for await (const _chunk of overProvider.generateStream([{ role: "user", content: "go" }], [], {
      responseLimits: DEFAULT_PROVIDER_RESPONSE_LIMITS,
    })) {
      // The first raw fragment must fail before the adapter yields or parses it.
    }
  } catch (error) {
    limitError = error;
  } finally {
    JSON.parse = originalParse;
  }
  const durationMs = elapsedMs(started);
  const rejectedBeforeParse =
    limitError instanceof ProviderOutputLimitError &&
    limitError.dimension === "tool_arguments" &&
    parseCalls === 0;
  if (!rejectedBeforeParse) throw new Error("one-byte-over tool arguments were not preflighted");
  if (diagnostics === undefined) throw new Error("adapter diagnostics were not captured");
  if (
    encoder.encode(exactArguments).byteLength !== 65_536 ||
    encoder.encode(overArguments).byteLength !== 65_537 ||
    fragments.length !== 10_000 ||
    diagnostics.rawFragments !== 10_002 ||
    diagnostics.toolArgumentJoinOperations !== 1 ||
    exactTracker.active !== 0 ||
    overTracker.active !== 0
  ) {
    throw new Error("tool argument benchmark violated assembly or cleanup invariants");
  }

  return {
    durationMs,
    completed: exactCalls.length,
    argumentBytes: encoder.encode(exactArguments).byteLength,
    responseMaxBytes: DEFAULT_PROVIDER_RESPONSE_LIMITS.responseMaxBytes,
    argumentFragments: fragments.length,
    rawFragments: diagnostics.rawFragments,
    fragmentJoins: diagnostics.toolArgumentJoinOperations,
    overLimitBytes: encoder.encode(overArguments).byteLength,
    overLimitRejectedBeforeParse: rejectedBeforeParse,
    iteratorLeaks: exactTracker.active + overTracker.active,
    parserLeaks: parseCalls,
    providerTaskLeaks: exactTracker.active + overTracker.active,
  };
}

async function runWorkload(
  caseName: CaseName,
  seed: number,
): Promise<Omit<WorkerSample, "case" | "peakMiB" | "warmupRuns">> {
  return caseName === "replay10k"
    ? await replay10k(seed)
    : caseName === "crossSession100"
      ? await crossSession100(seed)
      : caseName === "sameSession25"
        ? await sameSession25(seed)
        : caseName === "toolBatch100"
          ? await toolBatch100()
          : caseName === "context10kIterations5"
            ? await context10kIterations5(seed)
            : caseName === "crossSessionCommit100"
              ? await crossSessionCommit100(seed)
              : caseName === "streamDeltas10k"
                ? await streamDeltas10k(seed)
                : await toolArgDeltas10k();
}

async function runWorker(caseName: CaseName, seed: number, warmups: number): Promise<WorkerSample> {
  for (let index = 0; index < warmups; index++) {
    await runWorkload(caseName, seed + index);
  }
  const workload = await runWorkload(caseName, seed + warmups);
  return { case: caseName, ...workload, peakMiB: peakMiB(), warmupRuns: warmups };
}

async function childSample(
  caseName: CaseName,
  seed: number,
  warmups: number,
): Promise<WorkerSample> {
  const script = fileURLToPath(import.meta.url);
  const child = Bun.spawn({
    cmd: [
      process.execPath,
      script,
      "--worker-case",
      caseName,
      "--seed",
      String(seed),
      "--worker-warmups",
      String(warmups),
    ],
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
  if (options.rssProbe !== undefined) {
    process.stdout.write(`${JSON.stringify(runRssProbe(options.rssProbe, options.seed))}\n`);
    return;
  }
  if (options.caseName === undefined) throw new Error("--case is required");
  if (options.worker) {
    process.stdout.write(
      `${JSON.stringify(await runWorker(options.caseName, options.seed, options.workerWarmups))}\n`,
    );
    return;
  }

  const rawSamples: WorkerSample[] = [];
  for (let index = 0; index < options.samples; index++) {
    rawSamples.push(await childSample(options.caseName, options.seed + index, options.warmups));
  }
  const durations = rawSamples.map(({ durationMs }) => durationMs);
  const active = rawSamples.flatMap(({ maxActive }) =>
    maxActive === undefined ? [] : [maxActive],
  );
  const result = {
    schemaVersion: 1,
    runtime: "typescript",
    resolvedPackage: RESOLVED_PACKAGE,
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
