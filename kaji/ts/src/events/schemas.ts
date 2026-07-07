/**
 * Zod schemas for all Kaji events, mirroring
 * `kaji.infra.events.schemas`. Field names stay snake_case because they are
 * the shared wire format with the Python SDK.
 *
 * `BaseEvent` is `.strict()` to match Pydantic's `extra="forbid"`. The
 * id/version/timestamp/metadata defaults mirror the Python `default_factory`
 * fields, so constructing an event needs only its own payload plus session_id.
 */
import { z } from "zod";

import { defaultUuid } from "@/internal/uuid";
import { EventType } from "@/events/types";

/** Fields shared by every event. No provider- or voice-specific fields here. */
const baseShape = {
  id: z.string().default(() => defaultUuid()),
  version: z.string().default("1.0"),
  timestamp: z.number().default(() => Date.now() / 1000),
  session_id: z.string(),
  metadata: z.record(z.string(), z.unknown()).default(() => ({})),
};

/** Helper: a strict event schema with the base fields plus a literal `type`. */
function event<T extends z.ZodRawShape>(shape: T) {
  return z.object({ ...baseShape, ...shape }).strict();
}

export const SessionCreated = event({
  type: z.literal(EventType.SESSION_CREATED),
});

export const SessionClosed = event({
  type: z.literal(EventType.SESSION_CLOSED),
  reason: z.string().nullish(),
});

export const UserMessage = event({
  type: z.literal(EventType.USER_MESSAGE),
  content: z.string(),
});

export const UserAudioChunk = event({
  type: z.literal(EventType.USER_AUDIO_CHUNK),
  chunk_size_bytes: z.number().int(),
});

export const TranscriptPartial = event({
  type: z.literal(EventType.TRANSCRIPT_PARTIAL),
  text: z.string(),
});

export const TranscriptFinal = event({
  type: z.literal(EventType.TRANSCRIPT_FINAL),
  text: z.string(),
});

export const MemoryRetrievalStarted = event({
  type: z.literal(EventType.MEMORY_RETRIEVAL_STARTED),
  query: z.string(),
});

export const MemoryRetrievalCompleted = event({
  type: z.literal(EventType.MEMORY_RETRIEVAL_COMPLETED),
  query: z.string(),
  documents: z.array(z.record(z.string(), z.unknown())),
});

export const AgentReasoningStarted = event({
  type: z.literal(EventType.AGENT_REASONING_STARTED),
});

export const AgentMessageDelta = event({
  type: z.literal(EventType.AGENT_MESSAGE_DELTA),
  delta: z.string(),
});

export const AgentMessageCompleted = event({
  type: z.literal(EventType.AGENT_MESSAGE_COMPLETED),
  content: z.string(),
  tokens: z
    .object({ input: z.number().int().nonnegative(), output: z.number().int().nonnegative() })
    .optional(),
  cost_usd: z.number().nonnegative().optional(),
});

export const AgentTurnExhausted = event({
  type: z.literal(EventType.AGENT_TURN_EXHAUSTED),
  max_iterations: z.number().int().nonnegative(),
  pending_tool_calls: z.array(z.record(z.string(), z.unknown())),
  reason: z.string().nullish(),
});

export const ToolCallRequested = event({
  type: z.literal(EventType.TOOL_CALL_REQUESTED),
  tool_name: z.string(),
  tool_args: z.record(z.string(), z.unknown()),
  tool_call_id: z.string(),
});

export const ToolCallStarted = event({
  type: z.literal(EventType.TOOL_CALL_STARTED),
  tool_name: z.string(),
  tool_call_id: z.string(),
});

export const ToolCallCompleted = event({
  type: z.literal(EventType.TOOL_CALL_COMPLETED),
  tool_name: z.string(),
  tool_call_id: z.string(),
  result: z.unknown(),
  tokens: z
    .object({ input: z.number().int().nonnegative(), output: z.number().int().nonnegative() })
    .optional(),
  cost_usd: z.number().nonnegative().optional(),
});

export const ToolCallFailed = event({
  type: z.literal(EventType.TOOL_CALL_FAILED),
  tool_name: z.string(),
  tool_call_id: z.string(),
  error: z.string(),
});

export const ToolApprovalRequested = event({
  type: z.literal(EventType.TOOL_APPROVAL_REQUESTED),
  tool_name: z.string(),
  tool_call_id: z.string(),
  tool_args: z.record(z.string(), z.unknown()),
  risk: z.string().nullish(),
});

export const ToolApprovalApproved = event({
  type: z.literal(EventType.TOOL_APPROVAL_APPROVED),
  tool_name: z.string(),
  tool_call_id: z.string(),
});

export const ToolApprovalRejected = event({
  type: z.literal(EventType.TOOL_APPROVAL_REJECTED),
  tool_name: z.string(),
  tool_call_id: z.string(),
  reason: z.string().nullish(),
});

export const WorkflowStarted = event({
  type: z.literal(EventType.WORKFLOW_STARTED),
  workflow_name: z.string(),
});

export const WorkflowCompleted = event({
  type: z.literal(EventType.WORKFLOW_COMPLETED),
  workflow_name: z.string(),
  result: z.unknown(),
});

export const WorkflowFailed = event({
  type: z.literal(EventType.WORKFLOW_FAILED),
  workflow_name: z.string(),
  error: z.string(),
});

export const CancellationRequested = event({
  type: z.literal(EventType.CANCELLATION_REQUESTED),
  reason: z.string(),
});

export const CancellationCompleted = event({
  type: z.literal(EventType.CANCELLATION_COMPLETED),
});

/** Discriminated union over every event, keyed on `type`. */
export const KajiEvent = z.discriminatedUnion("type", [
  SessionCreated,
  SessionClosed,
  UserMessage,
  UserAudioChunk,
  TranscriptPartial,
  TranscriptFinal,
  MemoryRetrievalStarted,
  MemoryRetrievalCompleted,
  AgentReasoningStarted,
  AgentMessageDelta,
  AgentMessageCompleted,
  AgentTurnExhausted,
  ToolCallRequested,
  ToolCallStarted,
  ToolCallCompleted,
  ToolCallFailed,
  ToolApprovalRequested,
  ToolApprovalApproved,
  ToolApprovalRejected,
  WorkflowStarted,
  WorkflowCompleted,
  WorkflowFailed,
  CancellationRequested,
  CancellationCompleted,
]);

/** A validated Kaji event (output type, with defaults applied). */
export type KajiEvent = z.infer<typeof KajiEvent>;

/** The input type accepted by `KajiEvent.parse` (defaults optional). */
export type KajiEventInput = z.input<typeof KajiEvent>;

/** Base event fields, useful for typing helpers that touch any event. */
export type BaseEvent = z.infer<typeof SessionCreated>;
