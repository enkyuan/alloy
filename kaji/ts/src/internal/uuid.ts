export type UuidFactory = () => string;

export type IdScope = "event" | "session" | "turn" | "request" | "trace" | "tool_call";

export interface IdFactory {
  next(scope: IdScope): string;
}

export interface Clock {
  nowWallSeconds(): number;
  /** Monotonic milliseconds, matching `performance.now()`. */
  nowMonotonic(): number;
}

export interface TimerHandle {
  cancel(): void;
}

/** Minimal one-shot timer seam used by deadline races. */
export interface TimerScheduler {
  schedule(delayMs: number, callback: () => void): TimerHandle;
}

/**
 * Generate a uuid-shaped id.
 *
 * Prefers Web Crypto's `randomUUID` when available. Falls back to a
 * `Math.random`-based hex pattern for runtimes that ship no Web Crypto
 * (older Workerd, restricted CSP, embedded JS). The fallback is NOT
 * cryptographically secure; use it only for correlation ids, never as
 * a security token.
 */
export function defaultUuid(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  const hex = (bytes: number) =>
    Math.floor(Math.random() * 16 ** (bytes * 2))
      .toString(16)
      .padStart(bytes * 2, "0");
  return `${hex(4)}-${hex(2)}-${hex(2)}-${hex(2)}-${hex(6)}`;
}

export const systemIdFactory: IdFactory = Object.freeze({
  next: (_scope: IdScope) => defaultUuid(),
});

export const systemClock: Clock = Object.freeze({
  nowWallSeconds: () => Date.now() / 1000,
  nowMonotonic: () => globalThis.performance.now(),
});

export const systemTimerScheduler: TimerScheduler = Object.freeze({
  schedule: (delayMs: number, callback: () => void): TimerHandle => {
    if (!Number.isFinite(delayMs) || delayMs < 0) {
      throw new RangeError("delayMs must be a finite non-negative number");
    }
    let remaining = Math.max(0, delayMs);
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const arm = () => {
      const step = Math.min(remaining, 2_147_483_647);
      timer = setTimeout(() => {
        if (cancelled) return;
        remaining -= step;
        if (remaining <= 0) callback();
        else arm();
      }, step);
    };
    arm();
    return {
      cancel: () => {
        cancelled = true;
        if (timer !== undefined) clearTimeout(timer);
      },
    };
  },
});
