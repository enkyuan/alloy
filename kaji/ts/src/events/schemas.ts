/**
 * Zod schemas for all Kaji events, mirroring
 * `kaji.infra.events.schemas`. Field names stay snake_case because they are
 * the shared wire format with the Python SDK.
 *
 * `BaseEvent` is `.strict()` to match Pydantic's `extra="forbid"`. The
 * id/version/timestamp/metadata defaults mirror the Python `default_factory`
 * fields, so constructing an event needs only its own payload plus session_id.
 */
import * as z from "zod";

import { defaultUuid } from "@/internal/uuid";
import { EventType } from "@/events/types";
import { canonicalJsonValue, cloneAndFreezeJson, type DeepReadonly } from "@/events/json";

export const MAX_DURABLE_TOOL_ARGUMENT_BYTES = 64 * 1024;

export function durableToolArgumentsSize(value: Record<string, unknown>): number {
  return new TextEncoder().encode(canonicalJsonValue(value, "tool arguments")).byteLength;
}

const durableToolArguments = z.record(z.string(), z.unknown()).superRefine((value, ctx) => {
  let size: number;
  try {
    size = durableToolArgumentsSize(value);
  } catch {
    ctx.addIssue({ code: "custom", message: "tool_args must contain only JSON values" });
    return;
  }
  if (size > MAX_DURABLE_TOOL_ARGUMENT_BYTES) {
    ctx.addIssue({
      code: "custom",
      message: "tool_args cannot exceed 65536 serialized bytes; payload redacted",
    });
  }
});

/** Fields shared by every event. No provider- or voice-specific fields here. */
const baseShape = {
  id: z.string().default(() => defaultUuid()),
  version: z.literal("1.0").default("1.0"),
  timestamp: z.number().default(() => Date.now() / 1000),
  session_id: z.string(),
  turn_id: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).default(() => ({})),
};

/** Helper: a strict event schema with the base fields plus a literal `type`. */
function event<T extends z.ZodRawShape>(shape: T) {
  return z.object(baseShape).extend(shape).strict();
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

export const AgentTurnFailed = event({
  type: z.literal(EventType.AGENT_TURN_FAILED),
  turn_id: z.string().min(1),
  error: z.string().min(1).max(200),
});

export const ToolCallRequested = event({
  type: z.literal(EventType.TOOL_CALL_REQUESTED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_args: durableToolArguments,
  tool_call_id: z.string().min(1),
});

export const ToolCallStarted = event({
  type: z.literal(EventType.TOOL_CALL_STARTED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
});

export const ToolCallCompleted = event({
  type: z.literal(EventType.TOOL_CALL_COMPLETED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  result: z.unknown(),
  tokens: z
    .object({ input: z.number().int().nonnegative(), output: z.number().int().nonnegative() })
    .optional(),
  cost_usd: z.number().nonnegative().optional(),
});

export const ToolCallFailed = event({
  type: z.literal(EventType.TOOL_CALL_FAILED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  error: z
    .string()
    .min(1)
    .refine(
      (value) => Array.from(value).length <= 200,
      "error must contain at most 200 characters",
    ),
  error_code: z.string().optional(),
  error_path: z.string().optional(),
  retryable: z.boolean().optional(),
  outcome: z.enum(["not_started", "failed", "unknown"]).optional(),
});

export const ToolApprovalRequested = event({
  type: z.literal(EventType.TOOL_APPROVAL_REQUESTED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  tool_args: durableToolArguments,
  risk: z.enum(["read", "write", "external_effect", "financial", "destructive", "admin"]),
});

export const ToolApprovalApproved = event({
  type: z.literal(EventType.TOOL_APPROVAL_APPROVED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
});

export const ToolApprovalRejected = event({
  type: z.literal(EventType.TOOL_APPROVAL_REJECTED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  error_code: z.enum([
    "APPROVAL_REJECTED",
    "APPROVAL_TIMEOUT",
    "TOOL_CANCELLED",
    "APPROVAL_UNAVAILABLE",
  ]),
  reason: z
    .string()
    .min(1)
    .refine((value) => value.trim().length > 0, "reason must not be blank")
    .refine(
      (value) => Array.from(value).length <= 200,
      "reason must contain at most 200 characters",
    ),
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
  AgentTurnFailed,
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

/** An event draft accepted by stores and committers. Drafts never carry sequence. */
export const NewKajiEvent = KajiEvent;
export type NewKajiEvent = KajiEvent;

/** A persisted event. Stores assign a positive session-local sequence. */
export type StoredKajiEvent = DeepReadonly<KajiEvent & { sequence: number }>;
export const StoredKajiEvent = z
  .object({ sequence: z.number().int().positive() })
  .loose()
  .transform((value, ctx): StoredKajiEvent => {
    const { sequence, ...candidate } = value;
    const parsed = KajiEvent.safeParse(candidate);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) ctx.addIssue({ ...issue });
      return z.NEVER;
    }
    return cloneAndFreezeJson({ ...parsed.data, sequence });
  });
