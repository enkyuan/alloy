/** Emit only caller-selected context and an exception type. */
export function logRedactedFailure(message: string, error: unknown): void {
  try {
    const kind = error instanceof Error ? error.name : typeof error;
    console.error(`[kaji] ${message} (${kind}; details redacted)`);
  } catch {
    // Diagnostics are observational and must not alter runtime behavior.
  }
}
