/**
 * Session-state projection from the event log, mirroring
 * `agentkit.infra.events.replay`. The append-only log is the source of truth;
 * `SessionState` is a read model derived by replaying events in time order.
 */
import { EventType } from "../events/types";
import type { AgentKitEvent } from "../events/schemas";

/** A single conversation turn in the projected state. */
export interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool messages. */
  name?: string;
  /** Set only for tool messages: the id from the originating tool call request. */
  toolCallId?: string;
}

/** A projection of the event log into current session state. */
export interface SessionState {
  sessionId: string;
  isActive: boolean;
  messages: Message[];
}

/**
 * Reconstruct session state by replaying a sequence of events. Events from
 * `EventStore` arrive in append order; out-of-order inputs (e.g. constructed
 * in tests) are sorted on the fly. Throws on an empty log, matching Python.
 */
export function replaySession(events: readonly AgentKitEvent[]): SessionState {
  const first = events[0];
  if (first === undefined) {
    throw new Error("Cannot replay empty event log");
  }

  const state: SessionState = {
    sessionId: first.session_id,
    isActive: false,
    messages: [],
  };

  let ordered: readonly AgentKitEvent[] = events;
  for (let i = 1; i < events.length; i++) {
    if (events[i]!.timestamp < events[i - 1]!.timestamp) {
      ordered = [...events].sort((a, b) => a.timestamp - b.timestamp);
      break;
    }
  }

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
        break;
      case EventType.AGENT_MESSAGE_COMPLETED:
        state.messages.push({ role: "assistant", content: event.content });
        break;
      case EventType.TRANSCRIPT_FINAL:
        // For voice sessions, the final transcript acts as a user message.
        state.messages.push({ role: "user", content: event.text });
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
      // NOTE: AGENT_MESSAGE_DELTA and the transient tool events (REQUESTED,
      // STARTED) are intentionally NOT projected. The agent loop's termination
      // depends on only AGENT_MESSAGE_COMPLETED -> assistant and
      // TOOL_CALL_COMPLETED / TOOL_CALL_FAILED -> tool appearing in replayed
      // history. Projecting deltas as assistant turns would make a tool-driven
      // mock never see a tool result and loop forever.
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
