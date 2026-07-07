/**
 * Session-state projection from the event log, mirroring
 * `kaji.infra.events.replay`. The append-only log is the source of truth;
 * `SessionState` is a read model derived by replaying events in time order.
 */
import { EventType } from "@/events/types";
import type { KajiEvent } from "@/events/schemas";

/** A single conversation turn in the projected state. */
export interface MessageToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool messages. */
  name?: string;
  /** Set only for tool messages: the id from the originating tool call request. */
  toolCallId?: string;
  /** Set only for assistant messages that requested tools. */
  toolCalls?: MessageToolCall[];
}

/** Accumulated token counts across all turns in the session. */
export interface SessionTokens {
  input: number;
  output: number;
}

/** A projection of the event log into current session state. */
export interface SessionState {
  sessionId: string;
  isActive: boolean;
  messages: Message[];
  /**
   * tool_call_ids that emitted TOOL_APPROVAL_REQUESTED but have not yet been
   * approved or rejected. The set drains as APPROVED / REJECTED events arrive.
   */
  pendingApprovals: Set<string>;
  /** tool_call_ids the host approved via TOOL_APPROVAL_APPROVED. */
  approvedToolCallIds: Set<string>;
  /** tool_call_ids the host rejected via TOOL_APPROVAL_REJECTED. */
  rejectedToolCallIds: Set<string>;
  /** Total tokens consumed in this session (summed from AGENT_MESSAGE_COMPLETED events). */
  totalTokens: SessionTokens;
  /** Estimated total cost in USD for this session. */
  totalCostUsd: number;
}

/**
 * Reconstruct session state by replaying a sequence of events. Events from
 * `EventStore` arrive in append order; out-of-order inputs (e.g. constructed
 * in tests) are sorted on the fly. Throws on an empty log, matching Python.
 *
 * TOOL_CALL_REQUESTED events are attached to the most recent assistant message
 * so provider history includes the assistant-side tool call before the matching
 * role:tool result. OpenAI and Anthropic reject orphan tool-result messages.
 */
export function replaySession(events: readonly KajiEvent[]): SessionState {
  const first = events[0];
  if (first === undefined) {
    throw new Error("Cannot replay empty event log");
  }

  const state: SessionState = {
    sessionId: first.session_id,
    isActive: false,
    messages: [],
    pendingApprovals: new Set<string>(),
    approvedToolCallIds: new Set<string>(),
    rejectedToolCallIds: new Set<string>(),
    totalTokens: { input: 0, output: 0 },
    totalCostUsd: 0,
  };

  let ordered: readonly KajiEvent[] = events;
  for (let i = 1; i < events.length; i++) {
    if (events[i]!.timestamp < events[i - 1]!.timestamp) {
      ordered = [...events].sort((a, b) => a.timestamp - b.timestamp);
      break;
    }
  }

  let lastAssistant: Message | undefined;

  for (const event of ordered) {
    switch (event.type) {
      case EventType.SESSION_CREATED:
        state.isActive = true;
        break;
      case EventType.SESSION_CLOSED:
        state.isActive = false;
        break;
      case EventType.USER_MESSAGE:
        state.messages.push({ role: "user", content: event.content });
        lastAssistant = undefined;
        break;
      case EventType.AGENT_MESSAGE_COMPLETED:
        lastAssistant = { role: "assistant", content: event.content };
        state.messages.push(lastAssistant);
        if (event.tokens) {
          state.totalTokens.input += event.tokens.input;
          state.totalTokens.output += event.tokens.output;
        }
        if (event.cost_usd) {
          state.totalCostUsd += event.cost_usd;
        }
        break;
      case EventType.TRANSCRIPT_FINAL:
        // For voice sessions, the final transcript acts as a user message.
        state.messages.push({ role: "user", content: event.text });
        lastAssistant = undefined;
        break;
      case EventType.TOOL_CALL_REQUESTED:
        if (lastAssistant === undefined) {
          lastAssistant = { role: "assistant", content: "", toolCalls: [] };
          state.messages.push(lastAssistant);
        }
        lastAssistant.toolCalls ??= [];
        lastAssistant.toolCalls.push({
          id: event.tool_call_id,
          name: event.tool_name,
          args: event.tool_args,
        });
        break;
      case EventType.TOOL_CALL_COMPLETED:
        state.messages.push({
          role: "tool",
          name: event.tool_name,
          content: stringifyResult(event.result),
          // H3: carry the real tool_call_id through so buildMessages can
          // reference it; a real provider rejects a tool result whose id does
          // not match the originating request.
          toolCallId: event.tool_call_id,
        });
        break;
      case EventType.TOOL_CALL_FAILED:
        // Record the failure as a tool message so the agent loop sees the error
        // in history and can react, instead of re-requesting the same tool on
        // every iteration until maxToolIterations is exhausted. Matches Python.
        state.messages.push({
          role: "tool",
          name: event.tool_name,
          content: `Error: ${event.error}`,
          toolCallId: event.tool_call_id,
        });
        break;
      case EventType.TOOL_APPROVAL_REQUESTED:
        state.pendingApprovals.add(event.tool_call_id);
        break;
      case EventType.TOOL_APPROVAL_APPROVED:
        state.pendingApprovals.delete(event.tool_call_id);
        state.approvedToolCallIds.add(event.tool_call_id);
        break;
      case EventType.TOOL_APPROVAL_REJECTED:
        state.pendingApprovals.delete(event.tool_call_id);
        state.rejectedToolCallIds.add(event.tool_call_id);
        break;
      // NOTE: AGENT_MESSAGE_DELTA and TOOL_CALL_STARTED are intentionally NOT
      // projected. Deltas are transient, and STARTED does not carry provider
      // history data beyond the preceding TOOL_CALL_REQUESTED event.
      default:
        break;
    }
  }

  return state;
}

/**
 * Render a tool result as message content. Objects are JSON-encoded (the Python
 * SDK uses `str()`, which yields an unparseable repr; JSON is the useful TS
 * equivalent); primitives fall back to `String`.
 */
function stringifyResult(result: unknown): string {
  if (result !== null && typeof result === "object") {
    return JSON.stringify(result);
  }
  return String(result);
}
