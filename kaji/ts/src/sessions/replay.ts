/**
 * Session-state projection from the event log, mirroring
 * `kaji.infra.events.replay`. The append-only log is the source of truth;
 * `SessionState` is a read model derived by replaying events in store order.
 */
import { EventType } from "@/events/types";
import type { KajiEvent, StoredKajiEvent } from "@/events/schemas";

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
 * Reconstruct session state from stored events. Sequences must already be
 * strictly monotonic. Use `replayLegacySession` for fully unsequenced logs.
 *
 * TOOL_CALL_REQUESTED events are attached to the most recent assistant message
 * so provider history includes the assistant-side tool call before the matching
 * role:tool result. OpenAI and Anthropic reject orphan tool-result messages.
 */
export function replaySession(events: readonly StoredKajiEvent[]): SessionState {
  const first = events[0];
  if (first === undefined) {
    throw new Error("Cannot replay empty event log");
  }

  if (events.some((event) => event.session_id !== first.session_id)) {
    throw new Error("Cannot replay events from mixed sessions");
  }

  const sequenced = events.map((event) => "sequence" in event);
  if (sequenced.some(Boolean) && !sequenced.every(Boolean)) {
    throw new Error("Cannot replay mixed sequenced and unsequenced events");
  }
  if (!sequenced.every(Boolean)) {
    throw new Error("Stable replay requires stored events with sequence");
  }

  const seen = new Set<number>();
  let previous = 0;
  for (const event of events) {
    if (!Number.isInteger(event.sequence) || event.sequence <= 0) {
      throw new Error("Stored event sequence must be a positive integer");
    }
    if (seen.has(event.sequence)) throw new Error(`Duplicate event sequence ${event.sequence}`);
    if (event.sequence < previous) {
      throw new Error(`Non-monotonic event sequence ${event.sequence} after ${previous}`);
    }
    seen.add(event.sequence);
    previous = event.sequence;
  }

  return projectSession(events);
}

/** Compatibility entry point for fully unsequenced pre-beta logs. */
export function replayLegacySession(events: readonly KajiEvent[]): SessionState {
  const first = events[0];
  if (first === undefined) throw new Error("Cannot replay empty event log");
  if (events.some((event) => event.session_id !== first.session_id)) {
    throw new Error("Cannot replay events from mixed sessions");
  }
  const sequenced = events.map((event) => "sequence" in event);
  if (sequenced.some(Boolean) && !sequenced.every(Boolean)) {
    throw new Error("Cannot replay mixed sequenced and unsequenced events");
  }
  if (sequenced.some(Boolean)) {
    throw new Error("Legacy replay accepts only fully unsequenced events");
  }
  return projectSession(orderLegacyUnsequencedEvents(events));
}

function projectSession(ordered: readonly (KajiEvent | StoredKajiEvent)[]): SessionState {
  const first = ordered[0]!;
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

/** Compatibility only: new writes are always sequenced by the store. */
export function orderLegacyUnsequencedEvents(events: readonly KajiEvent[]): KajiEvent[] {
  console.warn("Replaying legacy unsequenced events by timestamp and input order");
  return events
    .map((event, index) => ({ event, index }))
    .sort((left, right) => left.event.timestamp - right.event.timestamp || left.index - right.index)
    .map(({ event }) => event);
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
