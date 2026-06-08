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
import { executeTool, listToolSpecs } from "../tools/registry";
import { CancellationToken } from "./cancellation";
import { buildMessages } from "./context";

const MAX_TOOL_ITERATIONS = 10;

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  bus: EventBus;
  systemPrompt?: string;
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

  constructor(options: AgentRuntimeOptions) {
    this.provider = options.provider;
    this.store = options.store;
    this.bus = options.bus;
    this.systemPrompt = options.systemPrompt;
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

    const tools = listToolSpecs();

    for (let i = 0; i < MAX_TOOL_ITERATIONS; i++) {
      token.throwIfCancelled();

      const events = await this.store.getEvents(sessionId);
      const state = replaySession(events);
      const messages = buildMessages(state.messages, this.systemPrompt);

      let content = "";
      const toolCalls: ToolCall[] = [];

      for await (const chunk of this.provider.generateStream(messages, tools)) {
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

      // Announce all requests first (matches the Python planner's ordering).
      for (const tc of toolCalls) {
        await emit({
          type: EventType.TOOL_CALL_REQUESTED,
          tool_name: tc.name,
          tool_args: tc.args,
          tool_call_id: tc.id,
        });
      }

      // Scatter-gather: run concurrently, emit started/completed|failed per call.
      await Promise.all(
        toolCalls.map(async (tc) => {
          await emit({
            type: EventType.TOOL_CALL_STARTED,
            tool_name: tc.name,
            tool_call_id: tc.id,
          });
          try {
            const result = await executeTool("runtime", tc.name, tc.args);
            await emit({
              type: EventType.TOOL_CALL_COMPLETED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              result,
            });
          } catch (err) {
            await emit({
              type: EventType.TOOL_CALL_FAILED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              error: err instanceof Error ? err.message : String(err),
            });
          }
        }),
      );
      // Loop: next iteration replays state including the new tool results.
    }
  }
}
