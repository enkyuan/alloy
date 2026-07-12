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
import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";

import { defaultUuid } from "@/internal/uuid";
import {
  DurableJsonLimitError,
  EventSchemaIncompatibleError,
  InvalidDurableValueError,
  type DurableJsonSubject,
} from "@/events/errors";
import { EventType } from "@/events/types";
import { isClosedRecoveryTuple } from "@/integrations/recovery";
import {
  canonicalJsonValue,
  cloneAndFreezeJson,
  durableJsonSnapshot,
  type DeepReadonly,
  type JsonValue,
} from "@/events/json";
import newEventSchema from "../../contracts/events/new-kaji-event-v1.schema.json";
import storedEventSchema from "../../contracts/events/stored-kaji-event-v1.schema.json";

export const MAX_DURABLE_TOOL_ARGUMENT_BYTES = 64 * 1024;
export const MAX_DURABLE_TOOL_RESULT_BYTES = 64 * 1024;
export const MAX_DURABLE_EVENT_BYTES = 1024 * 1024;

export function durableToolArgumentsSize(value: Record<string, unknown>): number {
  return new TextEncoder().encode(canonicalJsonValue(value, "tool arguments")).byteLength;
}

const durableJsonValue = z.unknown().superRefine((value, ctx) => {
  try {
    canonicalJsonValue(value, "event value");
  } catch {
    ctx.addIssue({ code: "custom", message: "event value must contain only JSON values" });
  }
});

const durableJsonObject = z.record(z.string(), durableJsonValue).superRefine((value, ctx) => {
  try {
    canonicalJsonValue(value, "event value");
  } catch {
    ctx.addIssue({ code: "custom", message: "event value must contain only JSON values" });
  }
});

function durableSubjectValue(subject: DurableJsonSubject, maxBytes: number) {
  return z.unknown().superRefine((value, ctx) => {
    try {
      durableJsonSnapshot(value, subject, maxBytes);
    } catch {
      ctx.addIssue({ code: "custom", message: `${subject} must be bounded durable JSON` });
    }
  });
}

function durableSubjectObject(subject: DurableJsonSubject) {
  return z.record(z.string(), z.unknown()).superRefine((value, ctx) => {
    try {
      durableJsonSnapshot(value, subject, MAX_DURABLE_EVENT_BYTES);
    } catch {
      ctx.addIssue({ code: "custom", message: `${subject} must be bounded durable JSON` });
    }
  });
}

const durableToolArguments = durableJsonObject.superRefine((value, ctx) => {
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
const nonEmptyId = z.string().min(1);
const baseShape = {
  id: nonEmptyId.default(() => defaultUuid()),
  version: z.literal("1.0").default("1.0"),
  timestamp: z.number().default(() => Date.now() / 1000),
  session_id: nonEmptyId,
  turn_id: nonEmptyId.optional(),
  metadata: durableSubjectObject("event_metadata").default(() => ({})),
};

function maxUnicodeCodePoints(field: string) {
  return (value: string, ctx: z.RefinementCtx): void => {
    if (Array.from(value).length > 200) {
      ctx.addIssue({ code: "custom", message: `${field} must contain at most 200 characters` });
    }
  };
}

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
  documents: z.array(durableSubjectObject("memory_document")),
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
    .strict()
    .nullish(),
  cost_usd: z.number().nonnegative().nullish(),
});

export const AgentTurnExhausted = event({
  type: z.literal(EventType.AGENT_TURN_EXHAUSTED),
  max_iterations: z.number().int().nonnegative(),
  pending_tool_calls: z.array(durableSubjectObject("pending_tool_call")),
  reason: z.string().nullish(),
});

export const AgentTurnFailed = event({
  type: z.literal(EventType.AGENT_TURN_FAILED),
  turn_id: z.string().min(1),
  error: z.string().min(1).superRefine(maxUnicodeCodePoints("error")),
  error_code: z.string().optional(),
  phase: z.enum(["queue", "provider_open", "provider_stream", "approval", "tool"]).optional(),
  retryable: z.boolean().optional(),
  outcome: z.enum(["not_started", "failed", "unknown"]).optional(),
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
  result: durableSubjectValue("tool_result", MAX_DURABLE_TOOL_RESULT_BYTES),
  tokens: z
    .object({ input: z.number().int().nonnegative(), output: z.number().int().nonnegative() })
    .strict()
    .nullish(),
  cost_usd: z.number().nonnegative().nullish(),
});

export const ToolCallFailed = event({
  type: z.literal(EventType.TOOL_CALL_FAILED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  error: z.string().min(1).superRefine(maxUnicodeCodePoints("error")),
  error_code: z.string().optional(),
  error_path: z.string().optional(),
  retryable: z.boolean().optional(),
  outcome: z.enum(["not_started", "failed", "unknown"]).optional(),
  reason_code: z.string().optional(),
  recovery_code: z.string().optional(),
  doc_url: z.string().optional(),
}).superRefine((value, ctx) => {
  if (
    !isClosedRecoveryTuple(value.reason_code, value.recovery_code, value.doc_url, value.error_code)
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["reason_code"],
      message: "integration recovery metadata must be a closed tuple",
    });
  }
});

export const ToolApprovalRequested = event({
  type: z.literal(EventType.TOOL_APPROVAL_REQUESTED),
  turn_id: z.string().min(1),
  tool_name: z.string().min(1),
  tool_call_id: z.string().min(1),
  tool_args: durableToolArguments,
  risk: z.enum(["read", "write", "external_effect", "destructive", "admin"]),
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
    "TURN_TIMEOUT",
    "TOOL_CANCELLED",
    "APPROVAL_UNAVAILABLE",
  ]),
  reason: z
    .string()
    .min(1)
    .refine((value) => value.trim().length > 0, "reason must not be blank")
    .superRefine(maxUnicodeCodePoints("reason")),
});

export const WorkflowStarted = event({
  type: z.literal(EventType.WORKFLOW_STARTED),
  workflow_name: z.string(),
});

export const WorkflowCompleted = event({
  type: z.literal(EventType.WORKFLOW_COMPLETED),
  workflow_name: z.string(),
  result: durableSubjectValue("workflow_result", MAX_DURABLE_EVENT_BYTES),
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

const EVENT_TYPES = new Set<string>(Object.values(EventType));
const wireAjv = new Ajv2020({ allErrors: true, strict: false });
const newWireValidator = wireAjv.compile(newEventSchema as object);
const storedWireValidator = wireAjv.compile(storedEventSchema as object);
const variantValidators = new Map<string, ValidateFunction>();

function pointerSegment(value: PropertyKey): string {
  return String(value).replaceAll("~", "~0").replaceAll("/", "~1");
}

function schemaDefName(eventType: string): string {
  const [head, ...tail] = eventType.split(".");
  return `${head!}${tail.map((part) => part[0]!.toUpperCase() + part.slice(1)).join("")}`;
}

function selectedWireValidator(stored: boolean, eventType: string): ValidateFunction {
  const key = `${stored ? "stored" : "new"}:${eventType}`;
  const existing = variantValidators.get(key);
  if (existing !== undefined) return existing;
  const schema = (stored ? storedEventSchema : newEventSchema) as {
    $defs: Record<string, unknown>;
  };
  const compiled = wireAjv.compile({
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $defs: schema.$defs,
    $ref: `#/$defs/${schemaDefName(eventType)}`,
  });
  variantValidators.set(key, compiled);
  return compiled;
}

function schemaErrorPointer(error: ErrorObject): string {
  if (error.keyword === "required") {
    return `${error.instancePath}/${pointerSegment(error.params.missingProperty as string)}`;
  }
  if (error.keyword === "unevaluatedProperties" || error.keyword === "additionalProperties") {
    const property =
      (error.params.unevaluatedProperty as string | undefined) ??
      (error.params.additionalProperty as string | undefined);
    if (property !== undefined) return `${error.instancePath}/${pointerSegment(property)}`;
  }
  return error.instancePath || "/";
}

function firstSchemaErrorPointer(errors: ErrorObject[] | null | undefined): string {
  const pointers = (errors ?? [])
    .filter((error) => error.keyword !== "allOf" && error.keyword !== "oneOf")
    .map(schemaErrorPointer)
    .sort(
      (left, right) => Number(left === "/") - Number(right === "/") || left.localeCompare(right),
    );
  return pointers[0] ?? "/";
}

function wirePreflight(value: unknown, stored: boolean): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EventSchemaIncompatibleError("/");
  }
  const document = value as Record<string, unknown>;
  if (
    [document.reason_code, document.recovery_code, document.doc_url].some(
      (field) => field !== undefined,
    ) &&
    !isClosedRecoveryTuple(
      document.reason_code,
      document.recovery_code,
      document.doc_url,
      document.error_code,
    )
  ) {
    throw new EventSchemaIncompatibleError("/reason_code");
  }
  for (const field of ["id", "version", "timestamp", "type", "session_id"] as const) {
    if (!(field in document)) throw new EventSchemaIncompatibleError(`/${field}`);
  }
  for (const field of ["id", "session_id", "turn_id"] as const) {
    if (document[field] === "") throw new EventSchemaIncompatibleError(`/${field}`);
  }
  if (stored && !("sequence" in document)) throw new EventSchemaIncompatibleError("/sequence");
  if (!stored && "sequence" in document) throw new EventSchemaIncompatibleError("/sequence");
  if (typeof document.type !== "string" || !EVENT_TYPES.has(document.type)) {
    throw new EventSchemaIncompatibleError("/type");
  }
  return document;
}

function zodIssuePointer(error: z.ZodError): string {
  const issue = error.issues[0];
  if (issue === undefined || issue.path.length === 0) return "/";
  const path = [...issue.path];
  if (typeof path[0] === "string" && EVENT_TYPES.has(path[0])) path.shift();
  return `/${path.map(pointerSegment).join("/")}`;
}

function durableErrorPointer(error: InvalidDurableValueError | DurableJsonLimitError): string {
  const pointers: Record<DurableJsonSubject, string> = {
    tool_result: "/result",
    workflow_result: "/result",
    event_metadata: "/metadata",
    memory_document: "/documents",
    pending_tool_call: "/pending_tool_calls",
    event: "/",
  };
  return pointers[error.subject];
}

function ownDataValue(
  document: Record<string, unknown>,
  key: string,
  subject: DurableJsonSubject,
): { readonly present: false } | { readonly present: true; readonly value: unknown } {
  const descriptor = Object.getOwnPropertyDescriptor(document, key);
  if (descriptor === undefined) return { present: false };
  if (!descriptor.enumerable || !("value" in descriptor)) {
    throw new InvalidDurableValueError(subject);
  }
  return { present: true, value: descriptor.value };
}

function snapshotArrayItems(value: unknown, subject: DurableJsonSubject): void {
  if (!Array.isArray(value)) throw new InvalidDurableValueError(subject);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  for (let index = 0; index < value.length; index++) {
    const descriptor = descriptors[String(index)];
    if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
      throw new InvalidDurableValueError(subject);
    }
    durableJsonSnapshot(descriptor.value, subject, MAX_DURABLE_EVENT_BYTES);
  }
}

function snapshotEventSubjects(document: Record<string, unknown>): void {
  const metadata = ownDataValue(document, "metadata", "event_metadata");
  if (metadata.present) {
    durableJsonSnapshot(metadata.value, "event_metadata", MAX_DURABLE_EVENT_BYTES);
  }
  const type = ownDataValue(document, "type", "event");
  if (!type.present) return;
  if (type.value === EventType.TOOL_CALL_COMPLETED) {
    const result = ownDataValue(document, "result", "tool_result");
    if (result.present) {
      durableJsonSnapshot(result.value, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES);
    }
  } else if (type.value === EventType.WORKFLOW_COMPLETED) {
    const result = ownDataValue(document, "result", "workflow_result");
    if (result.present) {
      durableJsonSnapshot(result.value, "workflow_result", MAX_DURABLE_EVENT_BYTES);
    }
  } else if (type.value === EventType.MEMORY_RETRIEVAL_COMPLETED) {
    const documents = ownDataValue(document, "documents", "event");
    if (documents.present) snapshotArrayItems(documents.value, "memory_document");
  } else if (type.value === EventType.AGENT_TURN_EXHAUSTED) {
    const pending = ownDataValue(document, "pending_tool_calls", "event");
    if (pending.present) snapshotArrayItems(pending.value, "pending_tool_call");
  }
}

function durableEventSnapshot(value: unknown): DeepReadonly<JsonValue> {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    snapshotEventSubjects(value as Record<string, unknown>);
  }
  return durableJsonSnapshot(value, "event", MAX_DURABLE_EVENT_BYTES);
}

function descriptorSafeWireSnapshot(value: unknown, ancestors = new Set<object>()): unknown {
  if (value === null || typeof value !== "object") return value;
  if (ancestors.has(value)) throw new InvalidDurableValueError("event");
  const isArray = Array.isArray(value);
  const prototype = Object.getPrototypeOf(value);
  if (!isArray && prototype !== Object.prototype && prototype !== null) {
    throw new InvalidDurableValueError("event");
  }
  if (Object.getOwnPropertySymbols(value).length > 0) {
    throw new InvalidDurableValueError("event");
  }

  const descriptors = Object.getOwnPropertyDescriptors(value);
  const clone: Record<string, unknown> | unknown[] = isArray ? [] : Object.create(prototype);
  ancestors.add(value);
  try {
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (isArray && key === "length") continue;
      if (!descriptor.enumerable || !("value" in descriptor)) {
        throw new InvalidDurableValueError("event");
      }
      Object.defineProperty(clone, key, {
        value: descriptorSafeWireSnapshot(descriptor.value, ancestors),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    if (isArray && (clone as unknown[]).length !== value.length) {
      throw new InvalidDurableValueError("event");
    }
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function validateWireEvent(
  value: unknown,
  stored: boolean,
): { readonly event: KajiEvent; readonly document: Record<string, unknown> } {
  let durableFailure: InvalidDurableValueError | DurableJsonLimitError | undefined;
  let snapshot: DeepReadonly<JsonValue>;
  try {
    snapshot = durableEventSnapshot(value);
  } catch (error) {
    if (error instanceof InvalidDurableValueError || error instanceof DurableJsonLimitError) {
      durableFailure = error;
      try {
        snapshot = descriptorSafeWireSnapshot(value) as DeepReadonly<JsonValue>;
      } catch {
        throw new EventSchemaIncompatibleError(durableErrorPointer(error));
      }
    } else {
      throw new EventSchemaIncompatibleError("/");
    }
  }
  if (typeof snapshot !== "object" || snapshot === null || Array.isArray(snapshot)) {
    throw new EventSchemaIncompatibleError("/");
  }
  const document = wirePreflight(snapshot, stored);
  const validator = stored ? storedWireValidator : newWireValidator;
  const eventType = document.type as string;
  if (!validator(document)) {
    const selected = selectedWireValidator(stored, eventType);
    selected(document);
    throw new EventSchemaIncompatibleError(
      firstSchemaErrorPointer(selected.errors ?? validator.errors),
    );
  }
  if (durableFailure !== undefined) {
    throw new EventSchemaIncompatibleError(durableErrorPointer(durableFailure));
  }
  const candidate = stored
    ? Object.fromEntries(Object.entries(document).filter(([key]) => key !== "sequence"))
    : document;
  const parsed = KajiEvent.safeParse(candidate);
  if (!parsed.success) throw new EventSchemaIncompatibleError(zodIssuePointer(parsed.error));
  return { event: parsed.data, document };
}

/** Validate an untouched new-event mapping before constructor defaults can run. */
export function validateNewEvent(value: unknown): NewKajiEvent {
  return validateWireEvent(value, false).event;
}

/** Subject-aware in-process snapshot used before store/committer admission. */
export function snapshotNewEvent(value: unknown): NewKajiEvent {
  return validateNewEvent(durableEventSnapshot(value));
}

/** Subject-aware stored-candidate snapshot used before backend mutation. */
export function snapshotStoredEventForAppend(value: unknown): StoredKajiEvent {
  return validateStoredEvent(durableEventSnapshot(value));
}

/** Validate an untouched stored-event mapping before constructor defaults can run. */
export function validateStoredEvent(value: unknown): StoredKajiEvent {
  const { event, document } = validateWireEvent(value, true);
  const sequence = document.sequence as number;
  return cloneAndFreezeJson({ ...event, sequence });
}
