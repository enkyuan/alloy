/**
 * Cancellation token for the agent loop, mirroring the Python
 * `CancellationToken`. Carries a backing `AbortController` so the same
 * cancel signal can be plumbed into platform APIs that accept an
 * `AbortSignal` (the `openai` / `@anthropic-ai/sdk` clients, `fetch`,
 * `EventTarget` listeners, etc.). The boolean `isCancelled` flag remains
 * for the polling style the runtime already uses; both fire together.
 */
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
      throw new Error("Agent run was cancelled");
    }
  }
}
