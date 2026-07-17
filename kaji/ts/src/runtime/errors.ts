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
    readonly component: "event_store" | "tool_idempotency_ledger" = "event_store",
  ) {
    super(
      component === "event_store"
        ? `Session ${sessionId} cannot be purged by the configured event store`
        : `Session ${sessionId} cannot be purged by the configured tool idempotency ledger`,
    );
    this.name = "SessionPurgeUnsupportedError";
  }
}
