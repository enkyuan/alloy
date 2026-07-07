/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `kaji.runtime.agents.runtime.AgentRuntime`.
 *
 * runTurn: replay state -> build messages -> stream from provider -> emit
 * events -> execute tool calls concurrently (scatter-gather) -> loop until the
 * provider returns no tool calls -> emit AgentMessageCompleted.
 */
import type { EventBusProtocol } from "@/events/protocols";
import { KajiEvent, type KajiEventInput } from "@/events/schemas";
import { EventType } from "@/events/types";
import type { EventStore } from "@/events/store";
import type { ModelProvider, TokenUsage, ToolCall } from "@/providers/base";
import { replaySession } from "@/sessions/replay";
import { executeTool, listToolSpecs, type ToolSpec } from "@/tools/registry";
import type { ToolPolicy } from "@/tools/policy";
import { ToolPlanner, type AnyApprovalHandler } from "@/tools/planner";
import { defaultUuid } from "@/internal/uuid";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import { buildMessages } from "@/runtime/context";

/** Tuning parameters for the ReAct loop, mirroring Python `AgentStrategy`. */
export interface AgentStrategy {
  /** Maximum tool-call iterations before the loop terminates. Default: 10. */
  maxToolIterations?: number;
}

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  bus: EventBusProtocol;
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
  toolExecutor?: (name: string, args: Record<string, unknown>) => Promise<unknown>;
  /** User identifier threaded into tool execution context. Defaults to "agent". */
  userId?: string;
}

export interface RunTurnOptions {
  cancellationToken?: CancellationToken;
}

export interface TurnOptions {
  /** Existing session to reuse; a fresh UUID is generated when omitted. */
  sessionId?: string;
  cancellationToken?: CancellationToken;
}

/**
 * Result of one `AgentRuntime.turn` call.
 *
 * - `text` is built from `AGENT_MESSAGE_COMPLETED` content joined across
 *   iterations, not delta accumulation. It may be empty when the provider keeps
 *   returning tool calls; inspect `events` for `AGENT_TURN_EXHAUSTED`.
 * - `toolCallEvents` are `KajiEvent`s of type `TOOL_CALL_REQUESTED`, not
 *   provider-neutral `ToolCall` payloads. The name reflects the type.
 * - `events` is the full slice of events appended by this call.
 */
export interface TurnResult {
  text: string;
  sessionId: string;
  toolCallEvents: KajiEvent[];
  events: KajiEvent[];
}

/**
 * One member of the event-input union with `session_id` removed (the runtime
 * supplies it). Distributive so each member keeps its own fields; a plain
 * `Omit<Union, "session_id">` would collapse the union to shared keys and lose
 * per-variant fields like `content` or `delta`.
 */
type EventInputWithoutSession<T = KajiEventInput> = T extends unknown
  ? Omit<T, "session_id">
  : never;

export class AgentRuntime {
  private readonly provider: ModelProvider;
  private readonly store: EventStore;
  private readonly bus: EventBusProtocol;
  private readonly systemPrompt?: string;
  private readonly maxToolIterations: number;
  private readonly fixedTools: ToolSpec[] | undefined;
  private readonly toolExecutor: (name: string, args: Record<string, unknown>) => Promise<unknown>;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: AnyApprovalHandler | undefined;
  private readonly userId: string;
  /**
   * Resolved planner: explicit if caller provided one, cached when the tool
   * set is fixed at construction, `null` when the runtime must rebuild a
   * planner per turn from the dynamic global registry.
   */
  private readonly planner: ToolPlanner | null;

  constructor(options: AgentRuntimeOptions) {
    this.provider = options.provider;
    this.store = options.store;
    this.bus = options.bus;
    this.systemPrompt = options.systemPrompt;
    this.maxToolIterations = options.strategy?.maxToolIterations ?? 10;
    this.fixedTools = options.tools;
    this.userId = options.userId ?? "agent";
    this.policy = options.policy;
    this.approvalHandler = options.approvalHandler;
    this.toolExecutor =
      options.toolExecutor ??
      ((name: string, args: Record<string, unknown>) => executeTool(this.userId, name, args));
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
    });
  }

  private resolvePlanner(tools: ToolSpec[]): ToolPlanner {
    return this.planner ?? this.buildPlanner(tools);
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
    const existing = await this.store.getEvents(sessionId);
    if (existing.length === 0) {
      const created = KajiEvent.parse({
        type: EventType.SESSION_CREATED,
        session_id: sessionId,
      });
      await this.store.append(created);
      await this.bus.publish(created);
    }
    const snapshotLen = existing.length;
    await this.send(sessionId, prompt, {
      cancellationToken: options.cancellationToken,
    });
    const all = await this.store.getEvents(sessionId);
    const turnEvents = all.slice(snapshotLen);
    const text = turnEvents
      .filter((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)
      .map((e) => ("content" in e ? (e.content as string) : ""))
      .join("");
    const toolCallEvents = turnEvents.filter((e) => e.type === EventType.TOOL_CALL_REQUESTED);
    return { text, sessionId, toolCallEvents, events: turnEvents };
  }

  /**
   * Append a user message and immediately run the agent turn.
   *
   * This is the idiomatic one-shot call:
   *   await runtime.send("s1", "What time is it?");
   *
   * For more control (batch-append, replay, pre-seeding) append a USER_MESSAGE
   * event to the store directly and call `runTurn()` separately.
   */
  async send(sessionId: string, content: string, options: RunTurnOptions = {}): Promise<void> {
    const event = KajiEvent.parse({
      type: EventType.USER_MESSAGE,
      session_id: sessionId,
      content,
    });
    await this.store.append(event);
    await this.bus.publish(event);
    await this.runTurn(sessionId, options);
  }

  /**
   * Return the event log for `sessionId` in append order. Shortcut for
   * `runtime.store.getEvents(sessionId)`.
   */
  async history(sessionId: string): Promise<KajiEvent[]> {
    return this.store.getEvents(sessionId);
  }

  async runTurn(sessionId: string, options: RunTurnOptions = {}): Promise<void> {
    const token = options.cancellationToken ?? new CancellationToken();

    const emit = async <T extends KajiEventInput>(
      input: EventInputWithoutSession<T>,
    ): Promise<void> => {
      const event = KajiEvent.parse({ ...input, session_id: sessionId });
      await this.store.append(event);
      await this.bus.publish(event);
    };

    await emit({ type: EventType.AGENT_REASONING_STARTED });

    try {
      const tools = this.fixedTools ?? listToolSpecs();

      for (let i = 0; i < this.maxToolIterations; i++) {
        token.throwIfCancelled();

        const events = await this.store.getEvents(sessionId);
        const state = replaySession(events);
        const messages = buildMessages(state.messages, this.systemPrompt);

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

        await this.resolvePlanner(tools).executeScatterGather(
          sessionId,
          toolCalls.map((tc) => ({
            id: tc.id,
            name: tc.name,
            arguments: tc.args,
          })),
          async (event) => {
            await this.store.append(event);
            await this.bus.publish(event);
          },
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
      if (error instanceof CancellationError || token.isCancelled) {
        await emit({ type: EventType.CANCELLATION_COMPLETED });
        return;
      }
      throw error;
    }
  }
}
