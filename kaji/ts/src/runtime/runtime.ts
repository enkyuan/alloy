/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `kaji.runtime.agents.runtime.AgentRuntime`.
 *
 * runTurn: replay state -> build messages -> stream from provider -> emit
 * events -> execute tool calls concurrently (scatter-gather) -> loop until the
 * provider returns no tool calls -> emit AgentMessageCompleted.
 */
import type { EventBusProtocol } from "@/events/protocols";
import type { EventCommitter } from "@/events/protocols";
import {
  KajiEvent,
  StoredKajiEvent,
  type KajiEventInput,
  type NewKajiEvent,
} from "@/events/schemas";
import { EventType } from "@/events/types";
import type { EventStore } from "@/events/store";
import { SplitEventCommitter } from "@/events/committer";
import type { ModelProvider, TokenUsage, ToolCall } from "@/providers/base";
import { SessionProjector } from "@/sessions/projector";
import { executeTool, listToolSpecs, type ToolSpec } from "@/tools/registry";
import type { ToolPolicy } from "@/tools/policy";
import { ToolPlanner, type AnyApprovalHandler, type ToolExecutor } from "@/tools/planner";
import { ToolExecutionController, type ToolExecutionLimits } from "@/tools/execution";
import type { ToolIdempotencyLedger } from "@/tools/idempotency";
import { defaultUuid } from "@/internal/uuid";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import {
  DEFAULT_CONTEXT_WINDOW,
  MissingToolIdentityError,
  assertNonEmptyContextId,
  assertValidDeadline,
  buildContext,
  normalizePrincipalId,
  snapshotContextMetadata,
  validateContextWindow,
  type ContextDiagnostics,
  type ContextWindow,
  type TurnContext,
} from "@/runtime/context";
import {
  InMemorySessionTurnCoordinator,
  type SessionTurnCoordinator,
} from "@/runtime/session-turn-coordinator";

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
  /** Maximum tool-call iterations before the loop terminates. Default: 10. */
  maxToolIterations?: number;
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
  /** Explicit defaults for a single-tenant application. */
  defaultContext?: TurnContext;
  /**
   * Defaults to one process-local coordinator per store object. Inject a
   * distributed implementation when runtimes span processes.
   */
  turnCoordinator?: SessionTurnCoordinator;
  /** Complete-turn provider-history bounds. Defaults to 32 turns / 100,000 characters. */
  contextWindow?: ContextWindow;
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

interface ResolvedTurnContext extends TurnContext {
  readonly requestId: string;
  readonly traceId: string;
  readonly metadata: Readonly<Record<string, unknown>>;
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
  private readonly toolExecutionController: ToolExecutionController;
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
    this.store = options.store;
    if (options.committer !== undefined) {
      if (options.committer.store !== options.store) {
        throw new Error("AgentRuntime store must match the injected committer store");
      }
      this.committer = options.committer;
    } else if (options.bus !== undefined) {
      this.committer = new SplitEventCommitter(options.store, options.bus);
    } else {
      throw new Error("AgentRuntime requires an event committer or compatibility bus");
    }
    this.systemPrompt = options.systemPrompt;
    this.maxToolIterations = options.strategy?.maxToolIterations ?? 10;
    this.fixedTools = options.tools;
    if (options.defaultContext === undefined) {
      this.defaultContext = undefined;
    } else {
      const context = options.defaultContext;
      if (context.requestId !== undefined) assertNonEmptyContextId(context.requestId, "requestId");
      if (context.traceId !== undefined) assertNonEmptyContextId(context.traceId, "traceId");
      assertValidDeadline(context.deadlineMs);
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

  private resolveTurnContext(context?: TurnContext): ResolvedTurnContext {
    const fallback = this.defaultContext;
    const metadata = {
      ...(fallback?.metadata ?? {}),
      ...(context?.metadata ?? {}),
    };
    const principalId = context?.principalId ?? fallback?.principalId;
    const requestId = context?.requestId ?? fallback?.requestId ?? defaultUuid();
    const traceId = context?.traceId ?? fallback?.traceId ?? defaultUuid();
    const deadlineMs = context?.deadlineMs ?? fallback?.deadlineMs;
    const db = context?.db ?? fallback?.db;
    assertNonEmptyContextId(requestId, "requestId");
    assertNonEmptyContextId(traceId, "traceId");
    assertValidDeadline(deadlineMs);
    return Object.freeze({
      ...(principalId === undefined ? {} : { principalId: normalizePrincipalId(principalId) }),
      requestId,
      traceId,
      ...(deadlineMs === undefined ? {} : { deadlineMs }),
      ...(db === undefined ? {} : { db }),
      metadata: snapshotContextMetadata(metadata),
    });
  }

  /** Canonical application write path for event drafts. */
  async appendEvent(event: NewKajiEvent): Promise<StoredKajiEvent> {
    return this.withProjectionSession(event.session_id, () =>
      this.withProjectionLock(event.session_id, async () => {
        const projector = this.projectorFor(event.session_id);
        if (!projector.initialized) await projector.sync(this.store);
        const stored = await this.committer.commit(event);
        if (stored.sequence === projector.lastSequence + 1) {
          projector.apply(stored);
        } else if (stored.sequence > projector.lastSequence) {
          // A canonical writer committed during the active turn. Pull the gap
          // plus this event before the next provider iteration reads state.
          await projector.sync(this.store);
        }
        if (stored.turn_id !== undefined) {
          this.turnEventCollectors.get(stored.turn_id)?.push(cloneStoredEvent(stored));
        }
        return cloneStoredEvent(stored);
      }),
    );
  }

  private projectorFor(sessionId: string): SessionProjector {
    let projector = this.projectors.get(sessionId);
    if (projector === undefined) {
      projector = new SessionProjector(sessionId);
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

  /**
   * Run one full agent turn and return a structured result.
   *
   * Wraps the ceremony of bootstrapping a session, sending the prompt,
   * running the ReAct loop, and slicing the new events out of the store.
   * Errors from the underlying loop propagate unchanged.
   */
  async turn(prompt: string, options: TurnOptions = {}): Promise<TurnResult> {
    const sessionId = options.sessionId ?? defaultUuid();
    const turnId = defaultUuid();
    const token = options.cancellationToken ?? new CancellationToken();
    const context = this.resolveTurnContext(options.context);
    return this.turnCoordinator.runExclusive(sessionId, token, () =>
      this.withProjectionSession(sessionId, async () => {
        const projector = await this.syncProjection(sessionId);
        const turnEvents: StoredKajiEvent[] = [];
        this.turnEventCollectors.set(turnId, turnEvents);
        try {
          if (projector.lastSequence === 0) {
            const created = KajiEvent.parse({
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
    const turnId = defaultUuid();
    const token = options.cancellationToken ?? new CancellationToken();
    const context = this.resolveTurnContext(options.context);
    await this.turnCoordinator.runExclusive(sessionId, token, () =>
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
    const event = KajiEvent.parse({
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
    return this.store.getEvents(sessionId, { ...options, limit: options.limit ?? 1_024 });
  }

  async runTurn(sessionId: string, options: RunTurnOptions = {}): Promise<void> {
    const token = options.cancellationToken ?? new CancellationToken();
    const turnId = defaultUuid();
    const context = this.resolveTurnContext(options.context);
    await this.turnCoordinator.runExclusive(sessionId, token, () =>
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

    const emit = async <T extends KajiEventInput>(
      input: EventInputWithoutRuntimeContext<T>,
    ): Promise<void> => {
      const event = KajiEvent.parse({ ...input, session_id: sessionId, turn_id: turnId });
      await this.appendEvent(event);
    };

    try {
      const tools = this.fixedTools ?? listToolSpecs();
      if (tools.length > 0 && turnContext.principalId === undefined) {
        throw new MissingToolIdentityError();
      }

      for (let i = 0; i < this.maxToolIterations; i++) {
        token.throwIfCancelled();

        // Persist a provider-output/tool-batch boundary for deterministic
        // cold replay of consecutive tool-only iterations.
        await emit({ type: EventType.AGENT_REASONING_STARTED });

        const state = this.projectorFor(sessionId).state;
        const providerContext = buildContext(state.messages, this.systemPrompt, this.contextWindow);
        this.contextDiagnosticsBySession.set(
          sessionId,
          Object.freeze({ ...providerContext.diagnostics }),
        );
        const messages = providerContext.messages;

        let content = "";
        const toolCalls: ToolCall[] = [];
        let usage: TokenUsage | undefined;
        let costUsd: number | undefined;

        for await (const chunk of this.provider.generateStream(messages, tools, {
          cancellationToken: token,
        })) {
          token.throwIfCancelled();
          if (chunk.delta) {
            content += chunk.delta;
            await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta: chunk.delta });
          }
          toolCalls.push(...chunk.toolCalls);
          if (chunk.usage) usage = chunk.usage;
          if (chunk.costUsd !== undefined) costUsd = chunk.costUsd;
        }

        // Finalize the assistant text for THIS iteration before touching tools.
        // Mirrors the Python reference (runtime.py:134): a turn that streams both
        // text and tool calls must still emit AgentMessageCompleted, or the text
        // is lost from replayed state. Guarded on truthy content so an empty
        // tool-only turn (and max-iteration exhaustion) emits no phantom turn (C1).
        if (content) {
          await emit({
            type: EventType.AGENT_MESSAGE_COMPLETED,
            content,
            ...(usage ? { tokens: usage } : {}),
            ...(costUsd !== undefined ? { cost_usd: costUsd } : {}),
          });
        }

        if (toolCalls.length === 0) {
          break;
        }

        if (turnContext.principalId === undefined) throw new MissingToolIdentityError();

        await this.resolvePlanner(tools).executeScatterGather(
          sessionId,
          toolCalls.map((tc) => ({
            id: tc.id,
            name: tc.name,
            arguments: tc.args,
          })),
          async (event) => {
            await this.appendEvent(KajiEvent.parse({ ...event, turn_id: turnId }));
          },
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
        await emit({ type: EventType.CANCELLATION_COMPLETED });
        return;
      }
      try {
        await emit({ type: EventType.AGENT_TURN_FAILED, error: PUBLIC_TURN_FAILURE });
      } catch {
        // Keep the operation failure as the public API result if recording its
        // terminal event independently fails.
      }
      throw error;
    }
  }
}
