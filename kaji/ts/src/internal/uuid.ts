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
