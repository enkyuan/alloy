import { InMemoryEventCommitter } from "@/events/committer";
import type { EventCommitter } from "@/events/protocols";
import { InMemoryEventStore, type EventStore } from "@/events/store";
import {
  InMemorySessionTurnCoordinator,
  type SessionTurnCoordinator,
} from "@/runtime/session/coordinator";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";

import type { KajiBackend } from "@/backends/base";

/** A fully in-memory, process-local {@link KajiBackend} for tests and local composition. */
export class InMemoryBackend implements KajiBackend {
  constructor(
    readonly store: EventStore = new InMemoryEventStore(),
    readonly journal: EventCommitter = new InMemoryEventCommitter(store),
    readonly coordinator: SessionTurnCoordinator = new InMemorySessionTurnCoordinator(),
    readonly idempotencyLedger: ToolIdempotencyLedger = new InMemoryToolIdempotencyLedger(),
  ) {}
}
