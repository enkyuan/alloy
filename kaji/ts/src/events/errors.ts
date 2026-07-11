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
