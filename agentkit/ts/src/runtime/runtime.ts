/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `agentkit.runtime.agents.runtime.AgentRuntime`.
 *
 * runTurn: replay state -> build messages -> stream from provider -> emit
 * events -> execute tool calls concurrently (scatter-gather) -> loop until the
 * provider returns no tool calls -> emit AgentMessageCompleted.
 */
import { EventBus } from "../events/bus";
import { AgentKitEvent, type AgentKitEventInput } from "../events/schemas";
import { EventType } from "../events/types";
import type { EventStore } from "../events/store";
import type { ModelProvider, ToolCall } from "../providers/base";
import { replaySession } from "../sessions/replay";
import { executeTool, listToolSpecs, type ToolSpec } from "../tools/registry";
import type { ToolPolicy } from "../tools/policy";
import { ToolPlanner, type ApprovalHandler } from "../tools/planner";
import { CancellationToken } from "./cancellation";
import { buildMessages } from "./context";

/** Tuning parameters for the ReAct loop, mirroring Python `AgentStrategy`. */
export interface AgentStrategy {
  /** Maximum tool-call iterations before the loop terminates. Default: 10. */
  maxToolIterations?: number;
}

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  bus: EventBus;
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
  approvalHandler?: ApprovalHandler;
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

/**
 * One member of the event-input union with `session_id` removed (the runtime
 * supplies it). Distributive so each member keeps its own fields; a plain
 * `Omit<Union, "session_id">` would collapse the union to shared keys and lose
 * per-variant fields like `content` or `delta`.
 */
type EventInputWithoutSession<T = AgentKitEventInput> = T extends unknown
  ? Omit<T, "session_id">
  : never;

export class AgentRuntime {
  private readonly provider: ModelProvider;
  private readonly store: EventStore;
  private readonly bus: EventBus;
  private readonly systemPrompt?: string;
  private readonly maxToolIterations: number;
  private readonly _tools: ToolSpec[] | undefined;
  private readonly planner: ToolPlanner | undefined;
  private readonly toolExecutor: (name: string, args: Record<string, unknown>) => Promise<unknown>;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: ApprovalHandler | undefined;
  private readonly userId: string;

  constructor(options: AgentRuntimeOptions) {
    this.provider = options.provider;
    this.store = options.store;
    this.bus = options.bus;
    this.systemPrompt = options.systemPrompt;
    this.maxToolIterations = options.strategy?.maxToolIterations ?? 10;
    this._tools = options.tools;
    this.userId = options.userId ?? "agent";
    this.policy = options.policy;
    this.approvalHandler = options.approvalHandler;
    this.toolExecutor =
      options.toolExecutor ??
      ((name: string, args: Record<string, unknown>) => executeTool(this.userId, name, args));
    this.planner = options.planner;
  }

  private makePlanner(tools: ToolSpec[]): ToolPlanner {
    if (this.planner !== undefined) return this.planner;
    return new ToolPlanner({
      executor: this.toolExecutor,
      policy: this.policy,
      approvalHandler: this.approvalHandler,
      specs: new Map(tools.map((spec) => [spec.name, spec])),
    });
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
    const event = AgentKitEvent.parse({
      type: EventType.USER_MESSAGE,
      session_id: sessionId,
      content,
    });
    await this.store.append(event);
    await this.bus.publish(event);
    await this.runTurn(sessionId, options);
  }

  async runTurn(sessionId: string, options: RunTurnOptions = {}): Promise<void> {
    const token = options.cancellationToken ?? new CancellationToken();
    token.throwIfCancelled();

    const emit = async <T extends AgentKitEventInput>(
      input: EventInputWithoutSession<T>,
    ): Promise<void> => {
      const event = AgentKitEvent.parse({ ...input, session_id: sessionId });
      await this.store.append(event);
      await this.bus.publish(event);
    };

    await emit({ type: EventType.AGENT_REASONING_STARTED });

    const tools = this._tools ?? listToolSpecs();

    for (let i = 0; i < this.maxToolIterations; i++) {
      token.throwIfCancelled();

      const events = await this.store.getEvents(sessionId);
      const state = replaySession(events);
      const messages = buildMessages(state.messages, this.systemPrompt);

      let content = "";
      const toolCalls: ToolCall[] = [];

      for await (const chunk of this.provider.generateStream(messages, tools, {
        cancellationToken: token,
      })) {
        token.throwIfCancelled();
        if (chunk.delta) {
          content += chunk.delta;
          await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta: chunk.delta });
        }
        toolCalls.push(...chunk.toolCalls);
      }

      // Finalize the assistant text for THIS iteration before touching tools.
      // Mirrors the Python reference (runtime.py:134): a turn that streams both
      // text and tool calls must still emit AgentMessageCompleted, or the text
      // is lost from replayed state. Guarded on truthy content so an empty
      // tool-only turn (and max-iteration exhaustion) emits no phantom turn (C1).
      if (content) {
        await emit({ type: EventType.AGENT_MESSAGE_COMPLETED, content });
      }

      if (toolCalls.length === 0) {
        break;
      }

      await this.makePlanner(tools).executeScatterGather(
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
    }
  }
}
