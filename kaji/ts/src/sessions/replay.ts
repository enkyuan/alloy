/**
 * Session-state projection from the event log, mirroring
 * `kaji.infra.events.replay`. The append-only log is the source of truth;
 * `SessionState` is a read model derived by replaying events in store order.
 */
import { EventType } from "@/events/types";
import { canonicalJsonValue } from "@/events/json";
import { type StoredKajiEvent, validateStoredEvent } from "@/events/schemas";

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

declare const APPROVAL_KEY: unique symbol;
/** Stable value key for the approval security/correlation tuple. */
export type ApprovalKey = string & { readonly [APPROVAL_KEY]: true };
export type ApprovalFailureCode =
  | "APPROVAL_REJECTED"
  | "APPROVAL_TIMEOUT"
  | "TURN_TIMEOUT"
  | "TOOL_CANCELLED"
  | "APPROVAL_UNAVAILABLE";

export function approvalKey(turnId: string, toolCallId: string, toolName: string): ApprovalKey {
  return JSON.stringify([turnId, toolCallId, toolName]) as ApprovalKey;
}

/** A projection of the event log into current session state. */
export interface SessionState {
  sessionId: string;
  isActive: boolean;
  messages: Message[];
  /**
   * Correlation triples that emitted TOOL_APPROVAL_REQUESTED but have not yet
   * been approved or rejected.
   */
  pendingApprovals: Set<ApprovalKey>;
  approvedApprovals: Set<ApprovalKey>;
  rejectedApprovals: Map<ApprovalKey, ApprovalFailureCode>;
  /** Total tokens consumed in this session (summed from AGENT_MESSAGE_COMPLETED events). */
  totalTokens: SessionTokens;
  /** Estimated total cost in USD for this session. */
  totalCostUsd: number;
}

const lastAssistantIndexes = new WeakMap<SessionState, number>();

/** Deep-clone a state value while preserving its hidden replay cursor. */
export function cloneSessionState(state: SessionState): SessionState {
  const snapshot = structuredClone(state);
  const lastAssistantIndex = lastAssistantIndexes.get(state);
  if (lastAssistantIndex !== undefined) {
    lastAssistantIndexes.set(snapshot, lastAssistantIndex);
  }
  return snapshot;
}

/** Create an empty projection for incremental application. */
export function createSessionState(sessionId: string): SessionState {
  return {
    sessionId,
    isActive: false,
    messages: [],
    pendingApprovals: new Set<ApprovalKey>(),
    approvedApprovals: new Set<ApprovalKey>(),
    rejectedApprovals: new Map<ApprovalKey, ApprovalFailureCode>(),
    totalTokens: { input: 0, output: 0 },
    totalCostUsd: 0,
  };
}

/**
 * Reconstruct session state from stored events. Sequences must already be
 * strictly monotonic.
 *
 * TOOL_CALL_REQUESTED events are attached to the most recent assistant message
 * so provider history includes the assistant-side tool call before the matching
 * role:tool result. OpenAI and Anthropic reject orphan tool-result messages.
 */
export function replaySession(events: readonly StoredKajiEvent[]): SessionState {
  const validated = events.map(validateStoredEvent);
  const first = validated[0];
  if (first === undefined) {
    throw new Error("Cannot replay empty event log");
  }

  if (validated.some((event) => event.session_id !== first.session_id)) {
    throw new Error("Cannot replay events from mixed sessions");
  }

  const seen = new Set<number>();
  let previous = 0;
  for (const event of validated) {
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

  const state = createSessionState(first.session_id);
  for (const event of validated) applyEvent(state, event);
  return state;
}

/** Apply one persisted event to an existing session projection in place. */
export function applyEvent(state: SessionState, event: StoredKajiEvent): number | null {
  if (event.session_id !== state.sessionId) {
    throw new Error("Cannot project events from mixed sessions");
  }
  return applyKajiEvent(state, event);
}

function applyKajiEvent(state: SessionState, event: StoredKajiEvent): number | null {
  switch (event.type) {
    case EventType.SESSION_CREATED:
      state.isActive = true;
      break;
    case EventType.SESSION_CLOSED:
      state.isActive = false;
      break;
    case EventType.AGENT_REASONING_STARTED:
      // One explicit provider-output/tool batch starts here. Parallel calls
      // share the following assistant; the next iteration gets a fresh one.
      lastAssistantIndexes.delete(state);
      break;
    case EventType.USER_MESSAGE:
      state.messages.push({ role: "user", content: event.content });
      lastAssistantIndexes.delete(state);
      return state.messages.length - 1;
    case EventType.AGENT_MESSAGE_COMPLETED:
      {
        const lastAssistant = { role: "assistant", content: event.content } as Message;
        state.messages.push(lastAssistant);
        lastAssistantIndexes.set(state, state.messages.length - 1);
      }
      if (event.tokens) {
        state.totalTokens.input += event.tokens.input;
        state.totalTokens.output += event.tokens.output;
      }
      if (event.cost_usd) {
        state.totalCostUsd += event.cost_usd;
      }
      return state.messages.length - 1;
    case EventType.TRANSCRIPT_FINAL:
      // For voice sessions, the final transcript acts as a user message.
      state.messages.push({ role: "user", content: event.text });
      lastAssistantIndexes.delete(state);
      return state.messages.length - 1;
    case EventType.TOOL_CALL_REQUESTED: {
      let lastAssistantIndex = lastAssistantIndexes.get(state);
      if (lastAssistantIndex === undefined) {
        state.messages.push({ role: "assistant", content: "", toolCalls: [] });
        lastAssistantIndex = state.messages.length - 1;
        lastAssistantIndexes.set(state, lastAssistantIndex);
      }
      const lastAssistant = state.messages[lastAssistantIndex]!;
      lastAssistant.toolCalls ??= [];
      lastAssistant.toolCalls.push({
        id: event.tool_call_id,
        name: event.tool_name,
        args: structuredClone(event.tool_args),
      });
      return lastAssistantIndex;
    }
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
      return state.messages.length - 1;
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
      if (event.turn_id !== undefined) {
        state.pendingApprovals.delete(
          approvalKey(event.turn_id, event.tool_call_id, event.tool_name),
        );
      }
      return state.messages.length - 1;
    case EventType.TOOL_APPROVAL_REQUESTED:
      {
        const key = approvalKey(event.turn_id, event.tool_call_id, event.tool_name);
        if (!state.approvedApprovals.has(key) && !state.rejectedApprovals.has(key)) {
          state.pendingApprovals.add(key);
        }
      }
      break;
    case EventType.TOOL_APPROVAL_APPROVED:
      {
        const key = approvalKey(event.turn_id, event.tool_call_id, event.tool_name);
        if (state.pendingApprovals.delete(key)) state.approvedApprovals.add(key);
      }
      break;
    case EventType.TOOL_APPROVAL_REJECTED:
      {
        const key = approvalKey(event.turn_id, event.tool_call_id, event.tool_name);
        if (state.pendingApprovals.delete(key)) {
          state.rejectedApprovals.set(key, event.error_code);
        }
      }
      break;
    // NOTE: AGENT_MESSAGE_DELTA and TOOL_CALL_STARTED are intentionally NOT
    // projected. Deltas are transient, and STARTED does not carry provider
    // history data beyond the preceding TOOL_CALL_REQUESTED event.
    default:
      break;
  }
  return null;
}

/**
 * Serialize a JSON value with the cross-SDK replay policy.
 *
 * Arrays retain their order; plain string-keyed objects use UTF-16 lexical
 * key order; strings retain Unicode text; and numbers use the finite IEEE-754
 * domain with ECMAScript's shortest round-trip spelling and fixed/exponent
 * boundaries. Unsupported values, including BigInt and non-plain objects,
 * fail instead of being silently coerced or omitted.
 */
function stringifyResult(result: unknown): string {
  return canonicalJsonValue(result, "tool result");
}
