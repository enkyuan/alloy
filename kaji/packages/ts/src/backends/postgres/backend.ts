import type { KajiBackend } from "@/backends/base";

import { PostgresEventCommitter } from "./committer";
import { PostgresTurnCoordinator } from "./coordinator";
import { PostgresToolIdempotencyLedger } from "./idempotency";
import { PostgresEventStore } from "./store";

export interface KajiPostgresBackendOptions {
  maxConnections?: number;
  pollIntervalMs?: number;
}

/** Compose the matching Postgres store, committer, ledger, and coordinator. */
export class KajiPostgresBackend implements KajiBackend {
  readonly store: PostgresEventStore;
  readonly journal: PostgresEventCommitter;
  readonly idempotencyLedger: PostgresToolIdempotencyLedger;
  readonly coordinator: PostgresTurnCoordinator;

  constructor(url: string, options: KajiPostgresBackendOptions = {}) {
    this.store = new PostgresEventStore(url);
    this.journal = new PostgresEventCommitter(this.store, {
      pollIntervalMs: options.pollIntervalMs,
    });
    this.idempotencyLedger = new PostgresToolIdempotencyLedger(url, options.pollIntervalMs);
    this.coordinator = new PostgresTurnCoordinator(
      url,
      options.maxConnections,
      options.pollIntervalMs,
    );
  }

  async close(): Promise<void> {
    await Promise.all([
      this.store.close(),
      this.idempotencyLedger.close(),
      this.coordinator.close(),
    ]);
  }
}

export { KajiPostgresBackend as PostgresBackend };
