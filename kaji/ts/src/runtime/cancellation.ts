import type { Clock, TimerHandle, TimerScheduler } from "@/internal/uuid";
import {
  attachProviderViolationSettlement,
  ProviderCancellationContractViolation,
  TurnTimeoutError,
} from "@/runtime/limits";

/**
 * Cancellation token for the agent loop, mirroring the Python
 * `CancellationToken`. Carries a backing `AbortController` so the same
 * cancel signal can be plumbed into platform APIs that accept an
 * `AbortSignal` (the `openai` / `@anthropic-ai/sdk` clients, `fetch`,
 * `EventTarget` listeners, etc.). The boolean `isCancelled` flag remains
 * for the polling style the runtime already uses; both fire together.
 */
export class CancellationError extends Error {
  constructor(message = "Agent run was cancelled") {
    super(message);
    this.name = "CancellationError";
  }
}

export interface CancellationTokenLike {
  isCancelled: boolean;
  signal?: AbortSignal;
  throwIfCancelled?: () => void;
}

export function throwIfCancellationRequested(token?: CancellationTokenLike): void {
  if (!token?.isCancelled) return;
  if (typeof token.throwIfCancelled === "function") {
    token.throwIfCancelled();
  }
  throw new CancellationError();
}

function isCancellationCompatible(error: unknown): boolean {
  return (
    error instanceof CancellationError ||
    (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError")
  );
}

export class CancellationToken {
  private readonly controller = new AbortController();

  /** Whether `cancel()` has been called. */
  get isCancelled(): boolean {
    return this.controller.signal.aborted;
  }

  /**
   * The underlying `AbortSignal`. Pass this directly to APIs that accept
   * one (the OpenAI / Anthropic SDKs, `fetch`, etc.) so the network call
   * aborts on cancel instead of just polling out at the next yield point.
   */
  get signal(): AbortSignal {
    return this.controller.signal;
  }

  cancel(): void {
    if (!this.controller.signal.aborted) {
      this.controller.abort();
    }
  }

  throwIfCancelled(): void {
    if (this.controller.signal.aborted) {
      throw new CancellationError();
    }
  }
}

/** Disposable linked deadline scope that owns one provider iterator. */
export class DeadlineCancellationScope {
  readonly token = new CancellationToken();
  private readonly deadlineWake: Promise<void>;
  private readonly parentWake: Promise<void>;
  private resolveDeadline!: () => void;
  private resolveParent!: () => void;
  private readonly parentAbort: () => void;
  private readonly deadlineTimer: TimerHandle;
  private iterator: AsyncIterator<unknown> | undefined;
  private activeNext: Promise<IteratorResult<unknown>> | undefined;
  private closePromise: Promise<void> | undefined;
  private transferred = false;
  private yielded = false;
  private dispatched = false;
  private cancellationRequestedAtMs: number | undefined;
  private cancellationSource: "parent" | "deadline" | "provider" | undefined;

  constructor(
    private readonly parent: CancellationToken,
    private readonly deadlineMonotonicMs: number,
    private readonly cancellationGraceMs: number,
    private readonly clock: Clock,
    private readonly scheduler: TimerScheduler,
  ) {
    if (!Number.isFinite(deadlineMonotonicMs) || deadlineMonotonicMs < 0) {
      throw new RangeError("deadlineMonotonicMs must be a finite non-negative number");
    }
    if (!Number.isFinite(cancellationGraceMs) || cancellationGraceMs <= 0) {
      throw new RangeError("cancellationGraceMs must be a positive finite number");
    }
    this.deadlineWake = new Promise((resolve) => {
      this.resolveDeadline = resolve;
    });
    this.parentWake = new Promise((resolve) => {
      this.resolveParent = resolve;
    });
    this.parentAbort = () => {
      this.requestCancellation("parent");
      this.resolveParent();
    };
    parent.signal.addEventListener("abort", this.parentAbort, { once: true });
    if (parent.isCancelled) this.parentAbort();
    this.deadlineTimer = scheduler.schedule(
      Math.max(0, deadlineMonotonicMs - clock.nowMonotonic()),
      () => {
        this.requestCancellation("deadline");
        this.resolveDeadline();
      },
    );
  }

  async *consume<T>(stream: AsyncIterable<T>): AsyncGenerator<T> {
    this.iterator = stream[Symbol.asyncIterator]() as AsyncIterator<unknown>;
    let providerError: unknown;
    try {
      while (true) {
        if (this.parent.isCancelled) await this.abort<T>(undefined, true, "parent");
        if (this.clock.nowMonotonic() >= this.deadlineMonotonicMs) {
          await this.abort<T>(undefined, false, "deadline");
        }
        if (this.token.isCancelled && this.cancellationSource === undefined) {
          await this.abort<T>(undefined, true, "provider");
        }

        this.dispatched = true;
        const next = this.iterator.next() as Promise<IteratorResult<T>>;
        this.activeNext = next as Promise<IteratorResult<unknown>>;
        const settlementEvidence = () => ({
          settledAtMs: this.clock.nowMonotonic(),
          cancellationSource: this.cancellationSource,
          parentCancelled: this.parent.isCancelled,
          tokenCancelled: this.token.isCancelled,
        });
        const providerResult = next.then(
          (result) => ({ status: "settled" as const, result, ...settlementEvidence() }),
          (error: unknown) => ({ status: "failed" as const, error, ...settlementEvidence() }),
        );
        const wake = await Promise.race([
          providerResult,
          this.deadlineWake.then(() => ({ status: "deadline" as const })),
          this.parentWake.then(() => ({ status: "parent" as const })),
        ]);

        if (wake.status === "failed") {
          if (
            (wake.parentCancelled || wake.cancellationSource === "parent") &&
            isCancellationCompatible(wake.error)
          ) {
            await this.abort<T>(next, true, "parent");
          }
          if (
            wake.cancellationSource === "deadline" ||
            wake.settledAtMs >= this.deadlineMonotonicMs
          ) {
            await this.abort<T>(next, false, "deadline");
          }
          if (
            wake.cancellationSource === "provider" ||
            (wake.tokenCancelled && wake.cancellationSource === undefined)
          ) {
            await this.abort<T>(next, true, "provider");
          }
          this.activeNext = undefined;
          throw wake.error;
        }
        if (this.parent.isCancelled) await this.abort<T>(next, true, "parent");
        if (wake.status === "deadline" || this.clock.nowMonotonic() >= this.deadlineMonotonicMs) {
          await this.abort<T>(next, false, "deadline");
        }
        if (this.token.isCancelled && this.cancellationSource === undefined) {
          await this.abort<T>(next, true, "provider");
        }
        if (wake.status !== "settled") continue;
        this.activeNext = undefined;
        if (wake.result.done) return;
        this.yielded = true;
        yield wake.result.value;
      }
    } catch (error) {
      if (error instanceof ProviderCancellationContractViolation) {
        this.transferred = true;
      } else {
        providerError = error;
      }
      throw error;
    } finally {
      if (!this.transferred) {
        try {
          await this.finishClose();
        } catch (closeError) {
          if (closeError instanceof ProviderCancellationContractViolation) {
            this.transferred = true;
            if (providerError !== undefined && closeError.cause === undefined) {
              Object.defineProperty(closeError, "cause", {
                value: providerError,
                configurable: true,
              });
            }
            throw closeError;
          }
          if (providerError === undefined) throw closeError;
        }
      }
    }
  }

  dispose(): void {
    this.deadlineTimer.cancel();
    this.parent.signal.removeEventListener("abort", this.parentAbort);
  }

  private async abort<T>(
    active: Promise<IteratorResult<T>> | undefined,
    callerCancelled: boolean,
    source: "parent" | "deadline" | "provider",
  ): Promise<never> {
    this.requestCancellation(source);
    const settlement = Promise.resolve(active)
      .catch(() => undefined)
      .then(() => this.closeOnce());
    let graceTimer: TimerHandle | undefined;
    const grace = new Promise<{ status: "grace" }>((resolve) => {
      const requestedAt = this.cancellationRequestedAtMs ?? this.clock.nowMonotonic();
      const remaining = Math.max(
        0,
        requestedAt + this.cancellationGraceMs - this.clock.nowMonotonic(),
      );
      graceTimer = this.scheduler.schedule(remaining, () => resolve({ status: "grace" }));
    });
    try {
      const result = await Promise.race([
        settlement.then(
          () => ({ status: "settled" as const }),
          () => ({ status: "failed" as const }),
        ),
        grace,
      ]);
      if (result.status === "settled") {
        if (callerCancelled) throw new CancellationError();
        throw new TurnTimeoutError(
          this.yielded ? "provider_stream" : "provider_open",
          true,
          this.dispatched ? "unknown" : "not_started",
        );
      }
      if (result.status === "failed") {
        this.transferred = true;
        throw this.contractViolation(settlement);
      }
      this.transferred = true;
      throw this.contractViolation(settlement);
    } finally {
      graceTimer?.cancel();
    }
  }

  private closeOnce(): Promise<void> {
    if (this.closePromise !== undefined) return this.closePromise;
    const iterator = this.iterator;
    this.closePromise = (async () => {
      if (this.activeNext !== undefined) {
        try {
          await this.activeNext;
        } catch {
          // Provider failure is surfaced by the active next owner.
        }
      }
      await iterator?.return?.();
    })();
    return this.closePromise;
  }

  private async finishClose(): Promise<void> {
    if (this.iterator === undefined) return;
    const close = this.closeOnce();
    const settled = close.then(
      () => ({ status: "settled" as const }),
      () => ({ status: "failed" as const }),
    );
    const wake = await Promise.race([
      settled,
      this.deadlineWake.then(() => ({ status: "deadline" as const })),
      this.parentWake.then(() => ({ status: "parent" as const })),
    ]);
    if (wake.status === "settled") return;
    if (wake.status === "failed") {
      this.transferred = true;
      throw this.contractViolation(close);
    }
    if (this.parent.isCancelled) await this.abort(this.activeNext, true, "parent");
    if (wake.status === "deadline" || this.clock.nowMonotonic() >= this.deadlineMonotonicMs) {
      await this.abort(this.activeNext, false, "deadline");
    }
    await close;
  }

  private requestCancellation(source: "parent" | "deadline" | "provider"): void {
    if (this.cancellationRequestedAtMs === undefined) {
      this.cancellationRequestedAtMs = this.clock.nowMonotonic();
    }
    this.cancellationSource ??= source;
    this.token.cancel();
  }

  private contractViolation(settlement: Promise<void>): ProviderCancellationContractViolation {
    const phase = this.yielded ? "provider_stream" : "provider_open";
    return attachProviderViolationSettlement(
      new ProviderCancellationContractViolation(phase),
      settlement,
    );
  }
}

export function createDeadlineCancellationScope(
  parent: CancellationToken,
  deadlineMonotonicMs: number,
  cancellationGraceMs: number,
  clock: Clock,
  scheduler: TimerScheduler,
): DeadlineCancellationScope {
  return new DeadlineCancellationScope(
    parent,
    deadlineMonotonicMs,
    cancellationGraceMs,
    clock,
    scheduler,
  );
}
