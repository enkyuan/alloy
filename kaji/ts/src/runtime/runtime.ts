/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `kaji.runtime.agents.runtime.AgentRuntime`.
 *
 * runTurn: replay state -> build messages -> stream from provider -> emit
 * events -> execute a bounded tool batch -> loop until the
 * provider returns no tool calls -> emit AgentMessageCompleted.
 */
import type { EventBusProtocol } from "@/events/protocols";
import type { EventCommitter } from "@/events/protocols";
import {
  KajiEvent,
  StoredKajiEvent,
  validateStoredEvent,
  type KajiEventInput,
  type NewKajiEvent,
} from "@/events/schemas";
import { EventType } from "@/events/types";
import type { EventStore } from "@/events/store";
import { SplitEventCommitter } from "@/events/committer";
import {
  resolveProviderResponseLimits,
  withProviderResponseDiagnostics,
  type ModelProvider,
  type ProviderResponseLimits,
  type TokenUsage,
} from "@/providers/base";
import { ProviderOutputLimitError } from "@/providers/errors";
import { SessionProjector } from "@/sessions/projector";
import type { ContextIndexStats } from "@/sessions/context-index";
import { executeTool, listToolSpecs, type ToolSpec } from "@/tools/registry";
import type { ToolPolicy } from "@/tools/policy";
import {
  ToolPlanner,
  bindEmitterToCommitter,
  type AnyApprovalHandler,
  type ToolExecutor,
} from "@/tools/planner";
import { ToolExecutionController, type ToolExecutionLimits } from "@/tools/execution";
import type { ToolIdempotencyLedger } from "@/tools/idempotency";
import {
  systemClock,
  systemIdFactory,
  systemTimerScheduler,
  type Clock,
  type IdFactory,
  type TimerHandle,
  type TimerScheduler,
} from "@/internal/uuid";
import {
  CancellationError,
  CancellationToken,
  createDeadlineCancellationScope,
} from "@/runtime/cancellation";
import {
  resolveTurnExecutionLimits,
  providerViolationSettlement,
  ProviderCancellationContractViolation,
  TurnTimeoutError,
  type TurnExecutionLimits,
} from "@/runtime/limits";
import {
  DEFAULT_CONTEXT_WINDOW,
  MissingToolIdentityError,
  assertNoLegacyDeadline,
  assertNonEmptyContextId,
  assertValidDeadline,
  normalizePrincipalId,
  snapshotContextMetadata,
  validateContextWindow,
  type ContextDiagnostics,
  type ContextWindow,
  type TurnContext,
} from "@/runtime/context";
import {
  InMemorySessionTurnCoordinator,
  type SessionTurnLease,
  type SessionTurnCoordinator,
} from "@/runtime/session-turn-coordinator";
import {
  NOOP_METRICS,
  NOOP_TRACE,
  providerFamily,
  recordMetric,
  startSpan,
  type MetricsSink,
  type ProviderStatus,
  type TraceSink,
  type TurnOutcome,
} from "@/observability";
import { RuntimeStreamAccumulator, type StreamDiagnostics } from "@/runtime/delta-accumulator";

const PUBLIC_TURN_FAILURE = "Agent turn failed";
const DEFAULT_TURN_COORDINATORS = new WeakMap<EventStore, SessionTurnCoordinator>();

function isCompatibleAbortError(error: unknown): boolean {
  return (
    typeof error === "object" && error !== null && "name" in error && error.name === "AbortError"
  );
}

function defaultTurnCoordinator(store: EventStore): SessionTurnCoordinator {
  const existing = DEFAULT_TURN_COORDINATORS.get(store);
  if (existing !== undefined) return existing;
  const coordinator = new InMemorySessionTurnCoordinator();
  DEFAULT_TURN_COORDINATORS.set(store, coordinator);
  return coordinator;
}

function cloneStoredEvent(event: StoredKajiEvent): StoredKajiEvent {
  return StoredKajiEvent.parse(structuredClone(event));
}

/** Tuning parameters for the ReAct loop, mirroring Python `AgentStrategy`. */
export interface AgentStrategy {
  /** Maximum tool-call iterations before the loop terminates. Default: 5. */
  maxToolIterations?: number;
  /**
   * When `false`, the loop breaks after the first provider response even if
   * it requested tool calls (the calls are never executed). Default: `true`.
   */
  allowToolCalls?: boolean;
}

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  /** Canonical append + subscription boundary. */
  committer?: EventCommitter;
  /** @deprecated Pass `committer`; a bus implies the experimental split adapter. */
  bus?: EventBusProtocol;
  systemPrompt?: string;
  strategy?: AgentStrategy;
  /**
   * Tool specs to surface to the provider each turn. When provided, only
   * these tools are offered (scoped registry). When omitted, falls back to
   * `listToolSpecs()` from the global registry.
   */
  tools?: ToolSpec[];
  /**
   * Optional tool policy. When provided, tool calls whose risk level is in
   * `policy.requireApprovalFor` require an `approvalHandler` before execution.
   */
  policy?: ToolPolicy;
  /**
   * Optional approval handler for tools that require explicit approval.
   * Wired into the default `ToolPlanner` when `planner` is not provided.
   */
  approvalHandler?: AnyApprovalHandler;
  /**
   * Tool execution planner. When omitted, a default planner is constructed from
   * `toolExecutor`, `policy`, `approvalHandler`, and `tools`.
   */
  planner?: ToolPlanner;
  /**
   * Scoped tool executor. Used by the default planner when `planner` is omitted.
   * Falls back to the global `executeTool` registry.
   */
  toolExecutor?: ToolExecutor;
  /** Runtime-lifetime tool execution bounds used by every dynamic planner. */
  toolExecutionLimits?: Partial<ToolExecutionLimits>;
  /** Replace the process-local tool idempotency ledger. */
  toolIdempotencyLedger?: ToolIdempotencyLedger;
  /** Whole-turn deadline and provider response bounds. */
  turnExecutionLimits?: Partial<TurnExecutionLimits>;
  /** Explicit defaults for a single-tenant application. */
  defaultContext?: TurnContext;
  /**
   * Defaults to one process-local coordinator per store object. Inject a
   * distributed implementation when runtimes span processes.
   */
  turnCoordinator?: SessionTurnCoordinator;
  /** Complete-turn provider-history bounds. Defaults to 32 turns / 100,000 characters. */
  contextWindow?: ContextWindow;
  /** Dependency-free recording sink; defaults to a no-op. */
  metricsSink?: MetricsSink;
  /** Privileged trace sink; defaults to a no-op. */
  traceSink?: TraceSink;
  /** Scoped identifier source used for every runtime and event identifier. */
  idFactory?: IdFactory;
  /** Wall and monotonic clock used by runtime events and timing. */
  clock?: Clock;
  /** Disposable one-shot timers used for deterministic deadline races. */
  timerScheduler?: TimerScheduler;
}

/** Immutable snapshot of the resolved limits used by one runtime instance. */
export interface EffectiveRuntimeLimits {
  readonly maxToolIterations: number;
  readonly contextWindowTurns: number | null;
  readonly contextWindowCharacters: number | null;
  readonly toolMaxParallel: number;
  readonly toolTimeoutMs: number | null;
  readonly approvalTimeoutMs: number;
  readonly turnTimeoutMs: number;
  readonly providerCancellationGraceMs: number;
  readonly providerTextMaxBytes: number;
  readonly providerToolArgumentsMaxBytes: number;
  readonly providerResponseMaxBytes: number;
  readonly providerToolCallsMax: number;
}

export interface RunTurnOptions {
  cancellationToken?: CancellationToken;
  context?: TurnContext;
}

export interface TurnOptions {
  /** Existing session to reuse; a fresh UUID is generated when omitted. */
  sessionId?: string;
  cancellationToken?: CancellationToken;
  context?: TurnContext;
}

interface ResolvedTurnContext {
  readonly principalId?: string;
  readonly requestId: string;
  readonly traceId: string;
  readonly deadlineMonotonicMs: number;
  readonly db?: unknown;
  readonly metadata: Readonly<Record<string, unknown>>;
}

interface ProviderQuarantineRecord {
  readonly sessionId: string;
  readonly lease: SessionTurnLease;
  readonly settlement: Promise<void>;
  settled: boolean;
  failed: boolean;
}

/**
 * Result of one `AgentRuntime.turn` call.
 *
 * - `text` is built from `AGENT_MESSAGE_COMPLETED` content joined across
 *   iterations, not delta accumulation. It may be empty when the provider keeps
 *   returning tool calls; inspect `events` for `AGENT_TURN_EXHAUSTED`.
 * - `toolCallEvents` are `KajiEvent`s of type `TOOL_CALL_REQUESTED`, not
 *   provider-neutral `ToolCall` payloads. The name reflects the type.
 * - `events` contains persisted events after this call's starting cursor.
 */
export interface TurnResult {
  text: string;
  sessionId: string;
  turnId: string;
  toolCallEvents: StoredKajiEvent[];
  events: StoredKajiEvent[];
}

/**
 * One member of the event-input union with `session_id` removed (the runtime
 * supplies it). Distributive so each member keeps its own fields; a plain
 * `Omit<Union, "session_id">` would collapse the union to shared keys and lose
 * per-variant fields like `content` or `delta`.
 */
type EventInputWithoutRuntimeContext<T = KajiEventInput> = T extends unknown
  ? Omit<T, "session_id" | "turn_id">
  : never;

export class AgentRuntime {
  private readonly provider: ModelProvider;
  private readonly store: EventStore;
  private readonly committer: EventCommitter;
  private readonly systemPrompt?: string;
  private readonly maxToolIterations: number;
  private readonly allowToolCalls: boolean;
  private readonly fixedTools: ToolSpec[] | undefined;
  private readonly toolExecutor: ToolExecutor;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: AnyApprovalHandler | undefined;
  private readonly defaultContext: TurnContext | undefined;
  private readonly turnCoordinator: SessionTurnCoordinator;
  private readonly contextWindow: Readonly<ContextWindow>;
  private readonly projectionCacheCapacity: number;
  private readonly projectors = new Map<string, SessionProjector>();
  private readonly projectionTails = new Map<string, Promise<void>>();
  private readonly activeProjectionSessions = new Map<string, number>();
  private readonly turnEventCollectors = new Map<string, StoredKajiEvent[]>();
  private readonly contextDiagnosticsBySession = new Map<string, Readonly<ContextDiagnostics>>();
  private readonly streamDiagnosticsBySession = new Map<string, Readonly<StreamDiagnostics>>();
  private readonly toolExecutionController: ToolExecutionController;
  private readonly metrics: MetricsSink;
  private readonly trace: TraceSink;
  private readonly idFactory: IdFactory;
  private readonly clock: Clock;
  private readonly turnLimits: Readonly<TurnExecutionLimits>;
  private readonly providerResponseLimits: Readonly<ProviderResponseLimits>;
  private readonly timerScheduler: TimerScheduler;
  private readonly providerQuarantine = new Map<string, ProviderQuarantineRecord>();
  private closed = false;
  /**
   * Resolved planner: explicit if caller provided one, cached when the tool
   * set is fixed at construction, `null` when the runtime must rebuild a
   * planner per turn from the dynamic global registry.
   */
  private readonly planner: ToolPlanner | null;

  constructor(options: AgentRuntimeOptions) {
    if (
      options.planner !== undefined &&
      (options.toolExecutionLimits !== undefined || options.toolIdempotencyLedger !== undefined)
    ) {
      throw new TypeError(
        "Explicit planner cannot be combined with tool execution limits or idempotency ledger",
      );
    }
    this.provider = options.provider;
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.trace = options.traceSink ?? NOOP_TRACE;
    this.idFactory = options.idFactory ?? systemIdFactory;
    this.clock = options.clock ?? systemClock;
    this.timerScheduler = options.timerScheduler ?? systemTimerScheduler;
    this.turnLimits = resolveTurnExecutionLimits(options.turnExecutionLimits);
    this.providerResponseLimits = resolveProviderResponseLimits({
      textMaxBytes: this.turnLimits.providerTextMaxBytes,
      toolArgumentsMaxBytes: this.turnLimits.providerToolArgumentsMaxBytes,
      responseMaxBytes: this.turnLimits.providerResponseMaxBytes,
      toolCallsMax: this.turnLimits.providerToolCallsMax,
    });
    this.store = options.store;
    if (options.committer !== undefined) {
      if (options.committer.store !== options.store) {
        throw new Error("AgentRuntime store must match the injected committer store");
      }
      this.committer = options.committer;
    } else if (options.bus !== undefined) {
      this.committer = new SplitEventCommitter(options.store, options.bus, {
        metricsSink: this.metrics,
      });
    } else {
      throw new Error("AgentRuntime requires an event committer or compatibility bus");
    }
    if (
      options.planner?.approvalCommitter !== undefined &&
      options.planner.approvalCommitter !== this.committer
    ) {
      throw new Error("Explicit planner approval committer must match the AgentRuntime committer");
    }
    this.systemPrompt = options.systemPrompt;
    const maxToolIterations = options.strategy?.maxToolIterations ?? 5;
    if (!(Number.isInteger(maxToolIterations) && maxToolIterations >= 1)) {
      throw new RangeError("maxToolIterations must be a positive integer");
    }
    this.maxToolIterations = maxToolIterations;
    this.allowToolCalls = options.strategy?.allowToolCalls ?? true;
    this.fixedTools = options.tools;
    if (options.defaultContext === undefined) {
      this.defaultContext = undefined;
    } else {
      const context = options.defaultContext;
      assertNoLegacyDeadline(context);
      if (context.requestId !== undefined) assertNonEmptyContextId(context.requestId, "requestId");
      if (context.traceId !== undefined) assertNonEmptyContextId(context.traceId, "traceId");
      assertValidDeadline(context.deadlineAtMs, "deadlineAtMs");
      this.defaultContext = Object.freeze({
        ...context,
        ...(context.principalId === undefined
          ? {}
          : { principalId: normalizePrincipalId(context.principalId) }),
        metadata: snapshotContextMetadata(context.metadata),
      });
    }
    this.turnCoordinator = options.turnCoordinator ?? defaultTurnCoordinator(options.store);
    this.projectionCacheCapacity = Math.max(1, options.store.maxSessions ?? 1_000);
    const contextWindow = options.contextWindow ?? DEFAULT_CONTEXT_WINDOW;
    validateContextWindow(contextWindow);
    this.contextWindow = Object.freeze({ ...contextWindow });
    this.policy = options.policy;
    this.approvalHandler = options.approvalHandler;
    this.toolExecutor =
      options.toolExecutor ?? ((name, args, context) => executeTool(name, args, context));
    this.toolExecutionController =
      options.planner?.executionController ??
      new ToolExecutionController({
        limits: options.toolExecutionLimits,
        ledger: options.toolIdempotencyLedger,
        metricsSink: this.metrics,
        traceSink: this.trace,
        monotonicNow: () => this.clock.nowMonotonic(),
        timerScheduler: this.timerScheduler,
      });
    // Planner resolution:
    //  1. Explicit planner wins.
    //  2. Otherwise, if tools are fixed at construction time, build once.
    //  3. Otherwise rebuild per turn so dynamic global-registry mutations
    //     remain visible (signalled by `null`).
    this.planner =
      options.planner ??
      (this.fixedTools !== undefined ? this.buildPlanner(this.fixedTools) : null);
  }

  private buildPlanner(tools: ToolSpec[]): ToolPlanner {
    return new ToolPlanner({
      executor: this.toolExecutor,
      policy: this.policy,
      approvalHandler: this.approvalHandler,
      approvalCommitter: this.committer,
      metricsSink: this.metrics,
      traceSink: this.trace,
      idFactory: this.idFactory,
      clock: this.clock,
      timerScheduler: this.timerScheduler,
      specs: new Map(tools.map((spec) => [spec.name, spec])),
      executionController: this.toolExecutionController,
    });
  }

  private resolvePlanner(tools: ToolSpec[]): ToolPlanner {
    return this.planner ?? this.buildPlanner(tools);
  }

  /** Drain actual tool handler settlement without claiming cancellation stopped work. */
  async drainTools(timeoutMs: number): Promise<readonly string[]> {
    return this.toolExecutionController.drain(timeoutMs);
  }

  async drainProviders(timeoutMs: number): Promise<readonly string[]> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
      throw new RangeError("timeoutMs must be a finite non-negative number");
    }
    const records = [...this.providerQuarantine.values()];
    if (records.length > 0) {
      let timer: TimerHandle | undefined;
      const timeout = new Promise<void>((resolve) => {
        timer = this.timerScheduler.schedule(timeoutMs, resolve);
      });
      try {
        await Promise.race([
          Promise.allSettled(records.map((record) => record.settlement)),
          timeout,
        ]);
      } finally {
        timer?.cancel();
      }
    }
    for (const record of records) {
      if (!record.settled || record.failed) continue;
      if (this.providerQuarantine.get(record.sessionId) !== record) continue;
      await record.lease.release();
      await this.turnCoordinator.clearQuarantine(record.sessionId);
      this.providerQuarantine.delete(record.sessionId);
    }
    return [...this.providerQuarantine.keys()].sort();
  }

  close(): void {
    this.closed = true;
  }

  private ensureOpen(): void {
    if (this.closed) throw new Error("Agent runtime is closed");
  }

  /** Return an immutable snapshot of the limits this runtime will use. */
  effectiveLimits(): Readonly<EffectiveRuntimeLimits> {
    const toolLimits = this.toolExecutionController.limits;
    return Object.freeze({
      maxToolIterations: this.maxToolIterations,
      contextWindowTurns: this.contextWindow.maxTurns,
      contextWindowCharacters: this.contextWindow.maxCharacters,
      toolMaxParallel: toolLimits.maxParallel,
      toolTimeoutMs: toolLimits.timeoutMs,
      approvalTimeoutMs: toolLimits.approvalTimeoutMs,
      turnTimeoutMs: this.turnLimits.turnTimeoutMs,
      providerCancellationGraceMs: this.turnLimits.providerCancellationGraceMs,
      providerTextMaxBytes: this.turnLimits.providerTextMaxBytes,
      providerToolArgumentsMaxBytes: this.turnLimits.providerToolArgumentsMaxBytes,
      providerResponseMaxBytes: this.turnLimits.providerResponseMaxBytes,
      providerToolCallsMax: this.turnLimits.providerToolCallsMax,
    });
  }

  private resolveTurnContext(context?: TurnContext): ResolvedTurnContext {
    const fallback = this.defaultContext;
    if (context !== undefined) assertNoLegacyDeadline(context);
    const metadata = {
      ...(fallback?.metadata ?? {}),
      ...(context?.metadata ?? {}),
    };
    const principalId = context?.principalId ?? fallback?.principalId;
    const requestId = context?.requestId ?? fallback?.requestId ?? this.idFactory.next("request");
    const traceId = context?.traceId ?? fallback?.traceId ?? this.idFactory.next("trace");
    assertValidDeadline(context?.deadlineAtMs, "deadlineAtMs");
    assertValidDeadline(fallback?.deadlineAtMs, "deadlineAtMs");
    const deadlineAtValues = [context?.deadlineAtMs, fallback?.deadlineAtMs].filter(
      (value): value is number => value !== undefined,
    );
    const deadlineAtMs = deadlineAtValues.length === 0 ? undefined : Math.min(...deadlineAtValues);
    const db = context?.db ?? fallback?.db;
    assertNonEmptyContextId(requestId, "requestId");
    assertNonEmptyContextId(traceId, "traceId");
    assertValidDeadline(deadlineAtMs, "deadlineAtMs");
    const nowMonotonic = this.clock.nowMonotonic();
    let deadlineMonotonicMs = nowMonotonic + this.turnLimits.turnTimeoutMs;
    if (deadlineAtMs !== undefined) {
      const converted = nowMonotonic + (deadlineAtMs - this.clock.nowWallSeconds() * 1_000);
      deadlineMonotonicMs = Math.min(deadlineMonotonicMs, converted);
    }
    if (!Number.isFinite(deadlineMonotonicMs)) {
      throw new TypeError("resolved deadlineMonotonicMs must be finite");
    }
    return Object.freeze({
      ...(principalId === undefined ? {} : { principalId: normalizePrincipalId(principalId) }),
      requestId,
      traceId,
      deadlineMonotonicMs,
      ...(db === undefined ? {} : { db }),
      metadata: snapshotContextMetadata(metadata),
    });
  }

  private event<T extends KajiEventInput>(input: T): KajiEvent {
    return KajiEvent.parse({
      ...input,
      id: this.idFactory.next("event"),
      timestamp: this.clock.nowWallSeconds(),
    });
  }

  /** Canonical application write path for event drafts. */
  async appendEvent(event: NewKajiEvent): Promise<StoredKajiEvent> {
    return this.withProjectionSession(event.session_id, () =>
      this.withProjectionLock(event.session_id, async () => {
        const projector = this.projectorFor(event.session_id);
        const collect = (applied: StoredKajiEvent) => {
          if (applied.turn_id === undefined) return;
          this.turnEventCollectors.get(applied.turn_id)?.push(cloneStoredEvent(applied));
        };
        if (!projector.initialized) await projector.sync(this.store, collect);
        const stored = await this.committer.commit(event);
        if (stored.sequence === projector.lastSequence + 1) {
          projector.apply(stored);
          collect(stored);
        } else if (stored.sequence > projector.lastSequence) {
          // A canonical writer committed during the active turn. Pull the gap
          // plus this event before the next provider iteration reads state.
          await projector.sync(this.store, collect);
        }
        return cloneStoredEvent(stored);
      }),
    );
  }

  private projectorFor(sessionId: string): SessionProjector {
    let projector = this.projectors.get(sessionId);
    if (projector === undefined) {
      projector = new SessionProjector(sessionId, this.metrics, this.contextWindow);
      this.projectors.set(sessionId, projector);
      this.trimProjectionCache();
    } else {
      this.projectors.delete(sessionId);
      this.projectors.set(sessionId, projector);
    }
    return projector;
  }

  private async withProjectionSession<T>(
    sessionId: string,
    operation: () => Promise<T>,
  ): Promise<T> {
    this.activeProjectionSessions.set(
      sessionId,
      (this.activeProjectionSessions.get(sessionId) ?? 0) + 1,
    );
    try {
      return await operation();
    } finally {
      const remaining = this.activeProjectionSessions.get(sessionId)! - 1;
      if (remaining === 0) this.activeProjectionSessions.delete(sessionId);
      else this.activeProjectionSessions.set(sessionId, remaining);
      this.trimProjectionCache();
    }
  }

  private trimProjectionCache(): void {
    while (this.projectors.size > this.projectionCacheCapacity) {
      let candidate: string | undefined;
      for (const sessionId of this.projectors.keys()) {
        if (!this.activeProjectionSessions.has(sessionId)) {
          candidate = sessionId;
          break;
        }
      }
      if (candidate === undefined) return;
      this.projectors.delete(candidate);
      this.contextDiagnosticsBySession.delete(candidate);
      this.streamDiagnosticsBySession.delete(candidate);
    }
  }

  get projectionCacheSize(): number {
    return this.projectors.size;
  }

  private async withProjectionLock<T>(sessionId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.projectionTails.get(sessionId) ?? Promise.resolve();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = previous.then(() => gate);
    this.projectionTails.set(sessionId, tail);
    await previous;
    try {
      return await operation();
    } finally {
      release();
      if (this.projectionTails.get(sessionId) === tail) {
        this.projectionTails.delete(sessionId);
      }
    }
  }

  private async syncProjection(sessionId: string): Promise<SessionProjector> {
    return this.withProjectionLock(sessionId, async () => {
      const projector = this.projectorFor(sessionId);
      await projector.sync(this.store);
      return projector;
    });
  }

  /** Diagnostics from the latest provider context built for a session. */
  contextDiagnostics(sessionId: string): ContextDiagnostics | undefined {
    const diagnostics = this.contextDiagnosticsBySession.get(sessionId);
    return diagnostics === undefined ? undefined : Object.freeze({ ...diagnostics });
  }

  /** Immutable counters from the latest provider call for a session. */
  streamDiagnostics(sessionId: string): StreamDiagnostics | undefined {
    const diagnostics = this.streamDiagnosticsBySession.get(sessionId);
    return diagnostics === undefined ? undefined : Object.freeze({ ...diagnostics });
  }

  /** Read index counters without creating a session projector. */
  contextIndexStats(sessionId: string): Readonly<ContextIndexStats> | undefined {
    return this.projectors.get(sessionId)?.contextIndexStats;
  }

  private async runCoordinated<T>(
    sessionId: string,
    turnId: string,
    token: CancellationToken,
    deadlineMonotonicMs: number,
    operation: () => Promise<T>,
  ): Promise<T> {
    const queuedAt = this.clock.nowMonotonic();
    let recorded = false;
    const recordWait = () => {
      if (recorded) return;
      recorded = true;
      recordMetric(
        this.metrics,
        "kaji.turn.queue_wait_ms",
        Math.max(0, this.clock.nowMonotonic() - queuedAt),
        {},
      );
    };
    let lease: SessionTurnLease;
    try {
      lease = await this.turnCoordinator.acquire(sessionId, token, {
        deadlineMonotonicMs,
        clock: this.clock,
        scheduler: this.timerScheduler,
      });
    } catch (error) {
      recordWait();
      if (error instanceof TurnTimeoutError && error.phase === "queue") {
        await this.recordTurnFailure(sessionId, turnId, error);
      } else if (error instanceof ProviderCancellationContractViolation) {
        await this.recordTurnFailure(sessionId, turnId, error);
      } else if (error instanceof CancellationError && token.isCancelled) {
        await this.appendEvent(
          this.event({
            type: EventType.CANCELLATION_COMPLETED,
            session_id: sessionId,
            turn_id: turnId,
          }),
        );
      }
      throw error;
    }
    let transferred = false;
    try {
      recordWait();
      return await operation();
    } catch (error) {
      if (error instanceof ProviderCancellationContractViolation) {
        const settlement = providerViolationSettlement(error);
        if (settlement === undefined) throw error;
        const transferredLease = lease.transfer();
        const record: ProviderQuarantineRecord = {
          sessionId,
          lease: transferredLease,
          settlement,
          settled: false,
          failed: false,
        };
        this.providerQuarantine.set(sessionId, record);
        void settlement.then(
          () => {
            record.settled = true;
          },
          () => {
            record.settled = true;
            record.failed = true;
          },
        );
        transferred = true;
        await this.turnCoordinator.quarantine(sessionId);
      }
      throw error;
    } finally {
      if (!transferred) await lease.release();
    }
  }

  /**
   * Run one full agent turn and return a structured result.
   *
   * Wraps the ceremony of bootstrapping a session, sending the prompt,
   * running the ReAct loop, and slicing the new events out of the store.
   * Errors from the underlying loop propagate unchanged.
   */
  async turn(prompt: string, options: TurnOptions = {}): Promise<TurnResult> {
    this.ensureOpen();
    const sessionId = options.sessionId ?? this.idFactory.next("session");
    const turnId = this.idFactory.next("turn");
    const token = options.cancellationToken ?? new CancellationToken();
    const context = this.resolveTurnContext(options.context);
    return this.runCoordinated(sessionId, turnId, token, context.deadlineMonotonicMs, () =>
      this.withProjectionSession(sessionId, async () => {
        const projector = await this.syncProjection(sessionId);
        const turnEvents: StoredKajiEvent[] = [];
        this.turnEventCollectors.set(turnId, turnEvents);
        try {
          if (projector.lastSequence === 0) {
            const created = this.event({
              type: EventType.SESSION_CREATED,
              session_id: sessionId,
              turn_id: turnId,
            });
            await this.appendEvent(created);
          }
          await this.sendUnlocked(sessionId, prompt, turnId, token, context);
          const resultEvents = turnEvents.map(cloneStoredEvent);
          const text = resultEvents
            .filter((event) => event.type === EventType.AGENT_MESSAGE_COMPLETED)
            .map((event) => ("content" in event ? (event.content as string) : ""))
            .join("");
          const toolCallEvents = resultEvents
            .filter((event) => event.type === EventType.TOOL_CALL_REQUESTED)
            .map(cloneStoredEvent);
          return { text, sessionId, turnId, toolCallEvents, events: resultEvents };
        } finally {
          this.turnEventCollectors.delete(turnId);
        }
      }),
    );
  }

  /**
   * Append a user message and immediately run the agent turn.
   *
   * This is the idiomatic one-shot call:
   *   await runtime.send("s1", "What time is it?");
   *
   * For more control (batch-append, replay, pre-seeding), call `appendEvent()`
   * and then `runTurn()` separately.
   */
  async send(sessionId: string, content: string, options: RunTurnOptions = {}): Promise<void> {
    this.ensureOpen();
    const turnId = this.idFactory.next("turn");
    const token = options.cancellationToken ?? new CancellationToken();
    const context = this.resolveTurnContext(options.context);
    await this.runCoordinated(sessionId, turnId, token, context.deadlineMonotonicMs, () =>
      this.withProjectionSession(sessionId, async () => {
        await this.syncProjection(sessionId);
        await this.sendUnlocked(sessionId, content, turnId, token, context);
      }),
    );
  }

  private async sendUnlocked(
    sessionId: string,
    content: string,
    turnId: string,
    token: CancellationToken,
    context: ResolvedTurnContext,
  ): Promise<void> {
    token.throwIfCancelled();
    const event = this.event({
      type: EventType.USER_MESSAGE,
      session_id: sessionId,
      turn_id: turnId,
      content,
    });
    await this.appendEvent(event);
    await this.runTurnUnlocked(sessionId, turnId, token, context);
  }

  /**
   * Return a cursor page of persisted events for `sessionId` in append order.
   */
  async history(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<StoredKajiEvent[]> {
    return (
      await this.store.getEvents(sessionId, { ...options, limit: options.limit ?? 1_024 })
    ).map(validateStoredEvent);
  }

  async runTurn(sessionId: string, options: RunTurnOptions = {}): Promise<void> {
    this.ensureOpen();
    const token = options.cancellationToken ?? new CancellationToken();
    const turnId = this.idFactory.next("turn");
    const context = this.resolveTurnContext(options.context);
    await this.runCoordinated(sessionId, turnId, token, context.deadlineMonotonicMs, () =>
      this.withProjectionSession(sessionId, async () => {
        await this.syncProjection(sessionId);
        await this.runTurnUnlocked(sessionId, turnId, token, context);
      }),
    );
  }

  private async runTurnUnlocked(
    sessionId: string,
    turnId: string,
    token: CancellationToken,
    turnContext: ResolvedTurnContext,
  ): Promise<void> {
    token.throwIfCancelled();
    const turnStarted = this.clock.nowMonotonic();
    let turnOutcome: TurnOutcome = "completed";
    let iterations = 0;
    const turnSpan = startSpan(this.trace, "kaji.turn", {
      "session.id": sessionId,
      "turn.id": turnId,
      "request.id": turnContext.requestId,
      "trace.id": turnContext.traceId,
    });

    const emit = async <T extends KajiEventInput>(
      input: EventInputWithoutRuntimeContext<T>,
    ): Promise<void> => {
      const event = this.event({ ...input, session_id: sessionId, turn_id: turnId });
      await this.appendEvent(event);
    };

    try {
      const tools = this.fixedTools ?? listToolSpecs();
      if (this.allowToolCalls && tools.length > 0 && turnContext.principalId === undefined) {
        throw new MissingToolIdentityError();
      }
      const providerTools = this.allowToolCalls ? tools : [];

      for (let i = 0; i < this.maxToolIterations; i++) {
        iterations = i + 1;
        token.throwIfCancelled();

        // Persist a provider-output/tool-batch boundary for deterministic
        // cold replay of consecutive tool-only iterations.
        await emit({ type: EventType.AGENT_REASONING_STARTED });

        const projector = this.projectorFor(sessionId);
        const providerContext = projector.buildProjectedContext(
          this.systemPrompt,
          this.contextWindow,
        );
        this.contextDiagnosticsBySession.set(
          sessionId,
          Object.freeze({ ...providerContext.diagnostics }),
        );
        const messages = providerContext.messages;

        const response = new RuntimeStreamAccumulator(this.providerResponseLimits);
        let usage: TokenUsage | undefined;
        let costUsd: number | undefined;

        const family = providerFamily(this.provider);
        const providerStarted = this.clock.nowMonotonic();
        let providerStatus: ProviderStatus = "success";
        const providerSpan = startSpan(this.trace, "kaji.provider", {
          "session.id": sessionId,
          "turn.id": turnId,
          "request.id": turnContext.requestId,
          "trace.id": turnContext.traceId,
          "provider.family": family,
        });
        try {
          const scope = createDeadlineCancellationScope(
            token,
            turnContext.deadlineMonotonicMs,
            this.turnLimits.providerCancellationGraceMs,
            this.clock,
            this.timerScheduler,
          );
          let providerCompleted = false;
          try {
            try {
              for await (const chunk of scope.consume(
                this.provider.generateStream(
                  messages,
                  providerTools,
                  withProviderResponseDiagnostics(
                    {
                      cancellationToken: scope.token,
                      metricsSink: this.metrics,
                      responseLimits: this.providerResponseLimits,
                    },
                    response.responseDiagnostics,
                  ),
                ),
              )) {
                const deltas = response.accept(chunk);
                if (chunk.usage) usage = Object.freeze({ ...chunk.usage });
                if (chunk.costUsd !== undefined) costUsd = chunk.costUsd;
                for (const delta of deltas) {
                  await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta });
                }
              }
              response.finish();
              providerCompleted = true;
            } finally {
              const residual = response.flush(!providerCompleted);
              if (residual !== undefined) {
                await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta: residual });
              }
            }
          } finally {
            scope.dispose();
          }
        } catch (error) {
          providerStatus = error instanceof CancellationError ? "cancelled" : "error";
          providerSpan.recordError(error);
          throw error;
        } finally {
          this.streamDiagnosticsBySession.set(sessionId, response.diagnostics);
          recordMetric(
            this.metrics,
            "kaji.provider.duration_ms",
            Math.max(0, this.clock.nowMonotonic() - providerStarted),
            { provider_family: family, status: providerStatus },
          );
          providerSpan.end();
        }

        // Finalize the assistant text for THIS iteration before touching tools.
        // Mirrors the Python reference (runtime.py:134): a turn that streams both
        // text and tool calls must still emit AgentMessageCompleted, or the text
        // is lost from replayed state. Guarded on truthy content so an empty
        // tool-only turn (and max-iteration exhaustion) emits no phantom turn (C1).
        const content = response.content();
        this.streamDiagnosticsBySession.set(sessionId, response.diagnostics);
        if (content) {
          await emit({
            type: EventType.AGENT_MESSAGE_COMPLETED,
            content,
            ...(usage ? { tokens: usage } : {}),
            ...(costUsd !== undefined ? { cost_usd: costUsd } : {}),
          });
        }

        const toolCalls = response.toolCalls;
        if (toolCalls.length === 0 || !this.allowToolCalls) {
          break;
        }

        if (turnContext.principalId === undefined) throw new MissingToolIdentityError();

        await this.resolvePlanner(tools).executeBatch(
          sessionId,
          toolCalls.map((tc) => ({
            id: tc.id,
            name: tc.name,
            arguments: tc.args,
          })),
          bindEmitterToCommitter(
            async (event) => this.appendEvent(KajiEvent.parse({ ...event, turn_id: turnId })),
            this.committer,
          ),
          turnId,
          turnContext,
          token.signal,
        );
        // Loop: next iteration replays state including the new tool results.
        if (i === this.maxToolIterations - 1) {
          await emit({
            type: EventType.AGENT_TURN_EXHAUSTED,
            max_iterations: this.maxToolIterations,
            pending_tool_calls: toolCalls.map((tc) => ({
              id: tc.id,
              name: tc.name,
              arguments: tc.args,
            })),
            reason: "max_iterations",
          });
        }
      }
    } catch (error) {
      if (
        error instanceof CancellationError ||
        (token.isCancelled && isCompatibleAbortError(error))
      ) {
        turnOutcome = "cancelled";
        await emit({ type: EventType.CANCELLATION_COMPLETED });
        return;
      }
      turnOutcome = "failed";
      turnSpan.recordError(error);
      await this.recordTurnFailure(sessionId, turnId, error);
      throw error;
    } finally {
      recordMetric(
        this.metrics,
        "kaji.turn.duration_ms",
        Math.max(0, this.clock.nowMonotonic() - turnStarted),
        { outcome: turnOutcome },
      );
      recordMetric(this.metrics, "kaji.turn.iterations", iterations, { outcome: turnOutcome });
      turnSpan.end();
    }
  }

  private async recordTurnFailure(
    sessionId: string,
    turnId: string,
    error: unknown,
  ): Promise<void> {
    const timeout = error instanceof TurnTimeoutError ? error : undefined;
    const providerViolation =
      error instanceof ProviderCancellationContractViolation ? error : undefined;
    const outputLimit = error instanceof ProviderOutputLimitError ? error : undefined;
    try {
      await this.appendEvent(
        this.event({
          type: EventType.AGENT_TURN_FAILED,
          session_id: sessionId,
          turn_id: turnId,
          error:
            timeout !== undefined
              ? "Agent turn timed out"
              : outputLimit !== undefined
                ? outputLimit.message
                : PUBLIC_TURN_FAILURE,
          ...(timeout === undefined
            ? outputLimit !== undefined
              ? {
                  error_code: outputLimit.code,
                  phase: outputLimit.phase,
                  retryable: outputLimit.retryable,
                  outcome: outputLimit.outcome,
                }
              : providerViolation === undefined
                ? {}
                : {
                    error_code: providerViolation.code,
                    phase: providerViolation.phase,
                    retryable: providerViolation.retryable,
                    outcome: providerViolation.outcome,
                  }
            : {
                error_code: timeout.code,
                phase: timeout.phase,
                retryable: timeout.retryable,
                outcome: timeout.outcome,
              }),
        }),
      );
    } catch {
      // The original operation failure remains the public API result.
    }
  }
}
