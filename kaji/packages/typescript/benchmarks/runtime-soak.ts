import { realpathSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  AgentRuntime,
  CancellationError,
  CancellationToken,
  EventType,
  InMemoryEventCommitter,
  InMemoryEventStore,
  InMemoryToolIdempotencyLedger,
  InMemorySessionTurnCoordinator,
  KajiEvent,
  ToolExecutionController,
  ToolPlanner,
  ToolPolicy,
  type Clock,
  type IdFactory,
  type MetricMeasurement,
  type MetricsSink,
  type ModelProvider,
  type ModelProviderOptions,
  type ModelResponse,
  type ModelResponseChunk,
  type ProviderMessage,
  type ToolClaimResult,
  type ToolExecutionError,
  type ToolIdempotencyClaim,
  type ToolIdempotencyLedger,
  type ToolSpec,
  type TurnResult,
} from "kaji-sdk";

const RESOLVED_PACKAGE = realpathSync(
  join(dirname(fileURLToPath(import.meta.resolve("kaji-sdk"))), ".."),
);

interface Options {
  readonly minutes: number;
  readonly seed: number;
  readonly artifactPath?: string;
  readonly artifactDirectory?: string;
}

interface HeapSample {
  readonly minute: number;
  readonly elapsedMs: number;
  readonly heapUsedMiB: number;
  readonly heapTotalMiB: number;
  readonly rssMiB: number;
  readonly maxRssMiB: number;
  readonly attempted: number;
  readonly completed: number;
  readonly failed: number;
  readonly projectionCacheSize: number;
  readonly coordinatorEntries: number;
  readonly coordinatorWaiters: number;
  readonly maxToolActive: number;
  readonly maxSubscriberQueueDepth: number;
  readonly subscriberOverflows: number;
}

class Mulberry32 {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let value = this.state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  }

  integer(maxExclusive: number): number {
    return Math.floor(this.next() * maxExclusive);
  }
}

class DeterministicIds implements IdFactory {
  private index = 0;

  constructor(private readonly seed: number) {}

  next(scope: Parameters<IdFactory["next"]>[0]): string {
    return `${scope}-${this.seed}-${++this.index}`;
  }
}

class DeterministicClock implements Clock {
  private wall = 1;

  nowWallSeconds(): number {
    this.wall += 0.001;
    return this.wall;
  }

  nowMonotonic(): number {
    return Number(process.hrtime.bigint()) / 1_000_000;
  }
}

class DiagnosticsSink implements MetricsSink {
  maxToolActive = 0;
  maxSubscriberQueueDepth = 0;
  subscriberOverflows = 0;

  record(measurement: MetricMeasurement): void {
    if (measurement.name === "kaji.tool.active") {
      this.maxToolActive = Math.max(this.maxToolActive, measurement.value);
    } else if (measurement.name === "kaji.subscriber.lag_events") {
      this.maxSubscriberQueueDepth = Math.max(this.maxSubscriberQueueDepth, measurement.value);
    } else if (measurement.name === "kaji.subscriber.overflow") {
      this.subscriberOverflows++;
    }
  }
}

type LedgerState = "running" | "completed" | "unknown";

class ObservedLedger implements ToolIdempotencyLedger {
  private readonly backing: InMemoryToolIdempotencyLedger;
  private readonly states = new Map<string, LedgerState>();
  peakSize = 0;
  releasedEntries = 0;

  constructor(readonly capacity: number) {
    this.backing = new InMemoryToolIdempotencyLedger({ capacity });
  }

  get size(): number {
    return this.states.size;
  }

  get counts(): Readonly<Record<LedgerState, number>> {
    const counts: Record<LedgerState, number> = { running: 0, completed: 0, unknown: 0 };
    for (const state of this.states.values()) counts[state]++;
    return Object.freeze(counts);
  }

  private key(sessionId: string, toolCallId: string): string {
    return JSON.stringify([sessionId, toolCallId]);
  }

  private observe(claim: ToolIdempotencyClaim, state: LedgerState): void {
    this.states.set(this.key(claim.sessionId, claim.toolCallId), state);
    this.peakSize = Math.max(this.peakSize, this.states.size);
  }

  async claim(
    sessionId: string,
    toolCallId: string,
    fingerprint: string,
  ): Promise<ToolClaimResult> {
    const result = await this.backing.claim(sessionId, toolCallId, fingerprint);
    if (result.status === "owner") this.observe(result.claim, "running");
    return result;
  }

  async complete(claim: ToolIdempotencyClaim, result: unknown): Promise<void> {
    await this.backing.complete(claim, result);
    this.observe(claim, "completed");
  }

  async retryableFailure(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    await this.backing.retryableFailure(claim, error);
    this.states.delete(this.key(claim.sessionId, claim.toolCallId));
  }

  async unknownOutcome(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    await this.backing.unknownOutcome(claim, error);
    this.observe(claim, "unknown");
  }

  async releaseCompleted(sessionId: string): Promise<number> {
    const released = await this.backing.releaseCompleted(sessionId);
    let observed = 0;
    for (const [key, state] of this.states) {
      const [entrySessionId] = JSON.parse(key) as [string, string];
      if (entrySessionId === sessionId && state === "completed") {
        this.states.delete(key);
        observed++;
      }
    }
    if (observed !== released) throw new Error("ledger diagnostics diverged from release count");
    return released;
  }

  async releaseSettled(sessionId: string): Promise<number> {
    const released = await this.backing.releaseSettled(sessionId);
    let observed = 0;
    for (const [key, state] of this.states) {
      const [entrySessionId] = JSON.parse(key) as [string, string];
      if (entrySessionId === sessionId && state !== "running") {
        this.states.delete(key);
        observed++;
      }
    }
    if (observed !== released) throw new Error("ledger diagnostics diverged from release count");
    this.releasedEntries += released;
    return released;
  }
}

class OfflineProvider implements ModelProvider {
  private callIndex = 0;
  calls = 0;
  active = 0;
  maxActive = 0;

  async generate(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    throw new Error("OfflineProvider only supports streaming");
  }

  async *generateStream(
    messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    this.calls++;
    this.active++;
    this.maxActive = Math.max(this.maxActive, this.active);
    try {
      if (messages.at(-1)?.role === "tool") {
        yield { delta: "done", toolCalls: [] };
        return;
      }
      const prompt =
        [...messages].reverse().find(({ role }) => role === "user")?.content ?? "plain";
      if (prompt.startsWith("tools:")) {
        const count = Number(prompt.split(":", 2)[1]);
        yield {
          delta: "",
          toolCalls: Array.from({ length: count }, (_, index) => ({
            id: `provider-call-${++this.callIndex}`,
            name: "parallel",
            args: { index },
          })),
        };
        return;
      }
      if (prompt.startsWith("approval:")) {
        yield {
          delta: "",
          toolCalls: [
            {
              id: `provider-call-${++this.callIndex}`,
              name: "approval",
              args: { approved: true },
            },
          ],
        };
        return;
      }
      if (prompt.startsWith("timeout-cooperative:")) {
        yield {
          delta: "",
          toolCalls: [
            { id: `provider-call-${++this.callIndex}`, name: "cooperative-timeout", args: {} },
          ],
        };
        return;
      }
      if (prompt.startsWith("timeout-noncooperative:")) {
        yield {
          delta: "",
          toolCalls: [
            {
              id: `provider-call-${++this.callIndex}`,
              name: "noncooperative-timeout",
              args: {},
            },
          ],
        };
        return;
      }
      yield { delta: "ok", toolCalls: [] };
    } finally {
      this.active--;
    }
  }
}

const TOOL_SPECS: readonly ToolSpec[] = Object.freeze([
  {
    name: "parallel",
    description: "offline bounded tool",
    parameters: { type: "object", additionalProperties: true },
    risk: "read",
    parallel_safe: true,
  },
  {
    name: "approval",
    description: "offline approval tool",
    parameters: { type: "object", additionalProperties: true },
    risk: "external_effect",
  },
  {
    name: "cooperative-timeout",
    description: "offline cooperative timeout",
    parameters: { type: "object", additionalProperties: false },
    risk: "read",
    parallel_safe: true,
    timeout_ms: 1,
  },
  {
    name: "noncooperative-timeout",
    description: "offline non-cooperative timeout",
    parameters: { type: "object", additionalProperties: false },
    risk: "read",
    parallel_safe: true,
    timeout_ms: 1,
  },
]);

function parseNumber(value: string | undefined, flag: string, integer = false): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0 || (integer && !Number.isSafeInteger(parsed))) {
    throw new Error(`${flag} must be a positive ${integer ? "integer" : "number"}`);
  }
  return parsed;
}

function parseArgs(argv: readonly string[]): Options {
  let minutes = 30;
  let seed = 13_013;
  let artifactPath: string | undefined;
  let artifactDirectory: string | undefined;
  for (let index = 0; index < argv.length; index++) {
    const flag = argv[index];
    if (flag === "--json") continue;
    const value = argv[++index];
    switch (flag) {
      case "--minutes":
        minutes = parseNumber(value, flag);
        break;
      case "--seed":
        seed = parseNumber(value, flag, true);
        break;
      case "--artifact":
      case "--artifact-path":
        if (value === undefined || value.length === 0) throw new Error(`${flag} requires a path`);
        if (value.endsWith(".json")) artifactPath = value;
        else artifactDirectory = value;
        break;
      case "--artifact-dir":
        if (value === undefined || value.length === 0) throw new Error(`${flag} requires a path`);
        artifactDirectory = value;
        break;
      default:
        throw new Error(`Unknown argument ${flag ?? "<missing>"}`);
    }
  }
  return {
    minutes,
    seed,
    ...(artifactPath === undefined ? {} : { artifactPath }),
    ...(artifactDirectory === undefined ? {} : { artifactDirectory }),
  };
}

function nowNs(): bigint {
  return process.hrtime.bigint();
}

function elapsedMs(started: bigint): number {
  return Number(nowNs() - started) / 1_000_000;
}

function toMiB(bytes: number): number {
  return bytes / 1_048_576;
}

function maxRssMiB(): number {
  const rawMaxRss = process.resourceUsage().maxRSS;
  const currentRssBytes = process.memoryUsage().rss;
  const maxRssBytes = rawMaxRss >= currentRssBytes / 8 ? rawMaxRss : rawMaxRss * 1_024;
  return toMiB(maxRssBytes);
}

export function countObservedCancellation(outcome: PromiseSettledResult<unknown>): number {
  if (outcome.status !== "rejected" || !(outcome.reason instanceof CancellationError)) {
    throw new Error("unexpected cancellation outcome");
  }
  return 1;
}

export function countObservedTimeout(
  outcome: PromiseSettledResult<unknown>,
  expectedToolName: string,
): number {
  if (
    outcome.status !== "fulfilled" ||
    typeof outcome.value !== "object" ||
    outcome.value === null ||
    !("events" in outcome.value) ||
    !Array.isArray(outcome.value.events)
  ) {
    throw new Error("unexpected timeout outcome");
  }
  const terminalEvents = outcome.value.events.filter(
    (event): event is Record<string, unknown> =>
      typeof event === "object" &&
      event !== null &&
      event.tool_name === expectedToolName &&
      (event.type === EventType.TOOL_CALL_COMPLETED || event.type === EventType.TOOL_CALL_FAILED),
  );
  const terminal = terminalEvents[0];
  if (
    terminalEvents.length !== 1 ||
    terminal?.type !== EventType.TOOL_CALL_FAILED ||
    terminal.error_code !== "TOOL_TIMEOUT" ||
    terminal.outcome !== "unknown"
  ) {
    throw new Error("unexpected timeout outcome");
  }
  return 1;
}

async function main(): Promise<void> {
  const { fullGC, heapStats } = await import("bun:jsc");
  const options = parseArgs(process.argv.slice(2));
  const rng = new Mulberry32(options.seed);
  const diagnostics = new DiagnosticsSink();
  const coordinator = new InMemorySessionTurnCoordinator();
  const store = new InMemoryEventStore({ maxSessions: 256, maxEventsPerSession: 10_000 });
  const committer = new InMemoryEventCommitter(store, {
    subscriberCapacity: 1_024,
    metricsSink: diagnostics,
  });
  const ledger = new ObservedLedger(10_000);
  const executionController = new ToolExecutionController({
    limits: { maxParallel: 4, timeoutMs: null },
    ledger,
    metricsSink: diagnostics,
  });
  const clock = new DeterministicClock();
  const ids = new DeterministicIds(options.seed);
  const provider = new OfflineProvider();
  const planner = new ToolPlanner({
    executor: async (name, args, context) => {
      if (name === "cooperative-timeout") {
        return new Promise((_resolve, reject) => {
          const fail = () => reject(new DOMException("aborted", "AbortError"));
          if (context.signal.aborted) fail();
          else context.signal.addEventListener("abort", fail, { once: true });
        });
      }
      if (name === "noncooperative-timeout") {
        return new Promise((resolve) => setTimeout(() => resolve({ settled: true }), 5));
      }
      return { name, args };
    },
    policy: new ToolPolicy({ requireApprovalFor: new Set(["external_effect"]) }),
    approvalHandler: {
      async request() {
        return { granted: true, code: "approved" as const };
      },
    },
    specs: new Map(TOOL_SPECS.map((spec) => [spec.name, spec])),
    idFactory: ids,
    clock,
    executionController,
    approvalCommitter: committer,
    metricsSink: diagnostics,
  });
  const runtime = new AgentRuntime({
    provider,
    store,
    committer,
    tools: [...TOOL_SPECS],
    planner,
    defaultContext: { principalId: "soak" },
    turnCoordinator: coordinator,
    metricsSink: diagnostics,
    idFactory: ids,
    clock,
  });

  let attempted = 0;
  let completed = 0;
  let failed = 0;
  let cancelled = 0;
  let batch = 0;
  let sharedGeneration = 0;
  let sharedSession = `shared-${sharedGeneration}`;
  let slowSubscriber = committer.subscribe(sharedSession);
  const scenarios = {
    sameSessionTurns: 0,
    crossSessionTurns: 0,
    toolCallsRequested: 0,
    approvals: 0,
    cancellations: 0,
    cooperativeTimeouts: 0,
    nonCooperativeTimeouts: 0,
    sessionClosures: 0,
  };

  const closeSession = async (sessionId: string): Promise<void> => {
    if ((await store.lastSequence(sessionId)) !== 0) {
      await runtime.appendEvent(
        KajiEvent.parse({
          id: ids.next("event"),
          timestamp: clock.nowWallSeconds(),
          type: EventType.SESSION_CLOSED,
          session_id: sessionId,
          reason: "soak rotation",
        }),
      );
      scenarios.sessionClosures++;
    }
    await runtime.purgeSession(sessionId);
  };

  const closedTurn = async (
    prompt: string,
    sessionId: string,
    waitForToolSettlement = false,
  ): Promise<TurnResult> => {
    try {
      return await runtime.turn(prompt, { sessionId });
    } finally {
      if (waitForToolSettlement) await runtime.drainTools(100);
      await closeSession(sessionId);
    }
  };

  const started = nowNs();
  const requestedMs = options.minutes * 60_000;
  let lastSampleBucket = 0;
  const heapSamples: HeapSample[] = [];
  const sample = (observedElapsedMs: number): void => {
    fullGC();
    const heap = heapStats();
    const memory = process.memoryUsage();
    heapSamples.push({
      minute: observedElapsedMs / 60_000,
      elapsedMs: observedElapsedMs,
      heapUsedMiB: toMiB(heap.heapSize),
      heapTotalMiB: toMiB(heap.heapCapacity),
      rssMiB: toMiB(memory.rss),
      maxRssMiB: maxRssMiB(),
      attempted,
      completed,
      failed,
      projectionCacheSize: runtime.projectionCacheSize,
      coordinatorEntries: coordinator.entryCount,
      coordinatorWaiters: coordinator.waitingCount,
      maxToolActive: diagnostics.maxToolActive,
      maxSubscriberQueueDepth: diagnostics.maxSubscriberQueueDepth,
      subscriberOverflows: diagnostics.subscriberOverflows,
    });
  };

  while (elapsedMs(started) < requestedMs) {
    const toolCount = 2 + rng.integer(5);
    const crossPlain = `cross-${batch}-plain`;
    const crossApproval = `cross-${batch}-approval`;
    const cancelledSession = `cross-${batch}-cancelled`;
    const cancellation = new CancellationToken();
    cancellation.cancel();
    const jobs: Promise<unknown>[] = [
      runtime.turn(`plain:${rng.integer(1_000_000)}`, { sessionId: sharedSession }),
      runtime.turn(`tools:${toolCount}:${rng.integer(1_000_000)}`, {
        sessionId: sharedSession,
      }),
      closedTurn(`plain:${rng.integer(1_000_000)}`, crossPlain),
      closedTurn(`approval:${rng.integer(1_000_000)}`, crossApproval),
      runtime.turn("cancelled", { sessionId: cancelledSession, cancellationToken: cancellation }),
    ];
    const cancellationJobIndex = jobs.length - 1;
    let cooperativeTimeoutJobIndex: number | undefined;
    let nonCooperativeTimeoutJobIndex: number | undefined;
    scenarios.sameSessionTurns += 2;
    scenarios.crossSessionTurns += 3;
    scenarios.toolCallsRequested += toolCount;
    scenarios.approvals++;
    scenarios.cancellations++;

    if (batch % 200 === 0) {
      const sessionId = `cross-${batch}-cooperative-timeout`;
      cooperativeTimeoutJobIndex = jobs.length;
      jobs.push(closedTurn(`timeout-cooperative:${batch}`, sessionId));
      scenarios.crossSessionTurns++;
      scenarios.toolCallsRequested++;
    }
    if (batch % 1_000 === 0) {
      const sessionId = `cross-${batch}-noncooperative-timeout`;
      nonCooperativeTimeoutJobIndex = jobs.length;
      jobs.push(closedTurn(`timeout-noncooperative:${batch}`, sessionId, true));
      scenarios.crossSessionTurns++;
      scenarios.toolCallsRequested++;
    }

    attempted += jobs.length;
    const outcomes = await Promise.allSettled(jobs);
    completed += outcomes.filter(({ status }) => status === "fulfilled").length;
    failed += outcomes.filter(({ status }) => status === "rejected").length;
    cancelled += countObservedCancellation(outcomes[cancellationJobIndex]!);
    if (cooperativeTimeoutJobIndex !== undefined) {
      scenarios.cooperativeTimeouts += countObservedTimeout(
        outcomes[cooperativeTimeoutJobIndex]!,
        "cooperative-timeout",
      );
    }
    if (nonCooperativeTimeoutJobIndex !== undefined) {
      scenarios.nonCooperativeTimeouts += countObservedTimeout(
        outcomes[nonCooperativeTimeoutJobIndex]!,
        "noncooperative-timeout",
      );
    }
    await closeSession(cancelledSession);
    batch++;

    if (batch % 100 === 0) {
      await slowSubscriber.return?.();
      await closeSession(sharedSession);
      const observedElapsedMs = elapsedMs(started);
      const observedSampleBucket = Math.floor(observedElapsedMs / 60_000);
      if (observedSampleBucket > lastSampleBucket) {
        sample(observedElapsedMs);
        lastSampleBucket = observedSampleBucket;
      }
      sharedSession = `shared-${++sharedGeneration}`;
      slowSubscriber = committer.subscribe(sharedSession);
    }
  }

  await slowSubscriber.return?.();
  await closeSession(sharedSession);
  const stuckToolCallIds = await runtime.drainTools(100);
  const elapsed = elapsedMs(started);
  const finalSampleBucket = Math.floor(elapsed / 60_000);
  if (heapSamples.length === 0 || finalSampleBucket > lastSampleBucket) sample(elapsed);

  const elapsedSeconds = elapsed / 1_000;
  const result = {
    schemaVersion: 2,
    runtime: "typescript",
    resolvedPackage: RESOLVED_PACKAGE,
    engine: typeof Bun === "undefined" ? `node-${process.version}` : `bun-${Bun.version}`,
    seed: options.seed,
    offline: true,
    requestedMinutes: options.minutes,
    elapsedSeconds,
    attemptedTurns: attempted,
    completedTurns: completed,
    failedTurns: failed,
    throughputTurnsPerSecond: elapsedSeconds === 0 ? 0 : completed / elapsedSeconds,
    terminalOutcomes: {
      completed,
      failed: failed - cancelled,
      cancelled,
    },
    memorySamples: heapSamples,
    provider: {
      kind: "offline-fixture",
      calls: provider.calls,
      active: provider.active,
      maxActive: provider.maxActive,
    },
    internal: {
      maxToolActive: diagnostics.maxToolActive,
      maxSubscriberQueueDepth: diagnostics.maxSubscriberQueueDepth,
      subscriberOverflows: diagnostics.subscriberOverflows,
      projectionCacheSize: runtime.projectionCacheSize,
      projectionCacheLimit: store.maxSessions,
      ledgerSize: ledger.size,
      ledgerPeakSize: ledger.peakSize,
      ledgerLimit: ledger.capacity,
      ledgerCounts: ledger.counts,
      coordinatorEntries: coordinator.entryCount,
      coordinatorWaiters: coordinator.waitingCount,
      stuckToolCallIds,
      stuckToolCalls: stuckToolCallIds.length,
      releasedLedgerEntries: ledger.releasedEntries,
      gcAvailable: true,
      scenarios,
    },
  };

  const json = `${JSON.stringify(result)}\n`;
  const artifactTargets = new Set<string>();
  if (options.artifactPath !== undefined) artifactTargets.add(options.artifactPath);
  if (options.artifactDirectory !== undefined) {
    artifactTargets.add(join(options.artifactDirectory, "typescript-heap-samples.json"));
  }
  const artifactJson = `${JSON.stringify({
    schemaVersion: 1,
    runtime: "typescript",
    seed: options.seed,
    memorySamples: heapSamples,
  })}\n`;
  for (const target of artifactTargets) {
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, artifactJson, "utf8");
  }
  process.stdout.write(json);
}

if (import.meta.main) await main();
