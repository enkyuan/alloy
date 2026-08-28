export type DurableJsonSubject =
  | "tool_result"
  | "workflow_result"
  | "event_metadata"
  | "memory_document"
  | "pending_tool_call"
  | "event";

export const DURABLE_JSON_SUBJECTS: ReadonlySet<string> = new Set<DurableJsonSubject>([
  "tool_result",
  "workflow_result",
  "event_metadata",
  "memory_document",
  "pending_tool_call",
  "event",
]);

export class InvalidDurableValueError extends Error {
  readonly code = "INVALID_DURABLE_VALUE" as const;

  constructor(readonly subject: DurableJsonSubject) {
    super(`Invalid durable JSON value for ${subject}`);
    this.name = "InvalidDurableValueError";
  }
}

export class DurableJsonLimitError extends Error {
  readonly code = "EVENT_PAYLOAD_TOO_LARGE" as const;

  constructor(
    readonly subject: DurableJsonSubject,
    readonly maxBytes: number,
  ) {
    super(`Durable JSON value for ${subject} exceeds ${maxBytes} UTF-8 bytes`);
    this.name = "DurableJsonLimitError";
  }
}

export class EventSchemaIncompatibleError extends Error {
  readonly code = "EVENT_SCHEMA_INCOMPATIBLE";

  constructor(readonly path: string) {
    super(`Event schema is incompatible at ${path}`);
    this.name = "EventSchemaIncompatibleError";
  }
}

export class EventIdConflictError extends Error {
  readonly code = "EVENT_ID_CONFLICT";

  constructor(readonly eventId: string) {
    super(`Event id ${eventId} already belongs to a different event`);
    this.name = "EventIdConflictError";
  }
}

export class EventStoreCapacityError extends Error {
  readonly code = "EVENT_STORE_CAPACITY_EXCEEDED";

  constructor(
    readonly sessionId: string,
    message: string,
  ) {
    super(message);
    this.name = "EventStoreCapacityError";
  }
}

export type SessionPurgeComponent = "event_store" | "event_delivery" | "tool_idempotency_ledger";

export class SessionPurgeBusyError extends Error {
  readonly code = "SESSION_PURGE_BUSY" as const;

  constructor(readonly sessionId: string) {
    super(`Session ${sessionId} cannot be purged while work is active`);
    this.name = "SessionPurgeBusyError";
  }
}

export class SessionPurgeUnsupportedError extends Error {
  readonly code = "SESSION_PURGE_UNSUPPORTED" as const;

  constructor(
    readonly sessionId: string,
    readonly component: SessionPurgeComponent = "event_store",
  ) {
    super(`Session ${sessionId} cannot be purged by ${component.replaceAll("_", " ")}`);
    this.name = "SessionPurgeUnsupportedError";
  }
}

export class EventBufferOverflowError extends Error {
  readonly code = "EVENT_BUFFER_OVERFLOW";

  constructor(
    readonly lastSequence: number,
    readonly latestSequence: number,
  ) {
    super(
      `Subscriber buffer overflowed after sequence ${lastSequence}; latest sequence is ${latestSequence}`,
    );
    this.name = "EventBufferOverflowError";
  }
}

export type EventDeliveryPhase = "append" | "publish";

export class EventDeliveryError extends Error {
  readonly code: "EVENT_APPEND_FAILED" | "EVENT_PUBLISH_FAILED";

  constructor(
    readonly phase: EventDeliveryPhase,
    readonly eventId: string,
    readonly persisted: boolean,
    options?: ErrorOptions,
  ) {
    super(`Event ${phase} failed for ${eventId}`, options);
    this.name = "EventDeliveryError";
    this.code = phase === "append" ? "EVENT_APPEND_FAILED" : "EVENT_PUBLISH_FAILED";
  }
}
