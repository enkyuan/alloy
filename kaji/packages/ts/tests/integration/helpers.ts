/**
 * Shared helpers for integration tests.
 *
 * Integration tests require real API keys and make live network calls.
 * Import `hasKey` to skip a suite automatically when the required key is absent.
 */

/**
 * Use with `describe.skipIf(!hasKey("OPENAI_API_KEY"))(...)`.
 */
export function hasKey(envVar: string): boolean {
  return Boolean(process.env[envVar]);
}
