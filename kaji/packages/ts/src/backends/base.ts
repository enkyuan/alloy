import type { EventCommitter } from "@/events/protocols";
import type { EventStore } from "@/events/store";
import type { SessionTurnCoordinator } from "@/runtime/session/coordinator";
import type { ToolIdempotencyLedger } from "@/tools/idempotency";

/** The four durable seams a Kaji runtime composes. */
export interface KajiBackend {
  readonly store: EventStore;
  readonly journal: EventCommitter;
  readonly idempotencyLedger: ToolIdempotencyLedger;
  readonly coordinator: SessionTurnCoordinator;
}
