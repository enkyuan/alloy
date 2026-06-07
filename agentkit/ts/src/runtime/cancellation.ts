/** Cancellation token for the agent loop, mirroring the Python CancellationToken. */
export class CancellationToken {
  private _cancelled = false;

  get isCancelled(): boolean {
    return this._cancelled;
  }

  cancel(): void {
    this._cancelled = true;
  }

  throwIfCancelled(): void {
    if (this._cancelled) {
      throw new Error("Agent run was cancelled");
    }
  }
}
