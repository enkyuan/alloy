/**
 * Shared parser for tool-call argument JSON.
 *
 * OpenAI and Anthropic both stream tool arguments as text that may or may
 * not be valid JSON. When parsing fails we return a sentinel
 * `{__parse_error}` object so the runtime can surface the failure as a
 * tool error rather than dropping it on the floor.
 */

function jsonTypeName(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function isJsonObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseToolArgsJSON(
  raw: string | undefined | null,
  providerLabel: string,
): Record<string, unknown> {
  if (raw === undefined || raw === null || raw === "") return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isJsonObjectRecord(parsed)) {
      return {
        __parse_error: `${providerLabel} tool args must be a JSON object, got ${jsonTypeName(parsed)}`,
      };
    }
    return parsed;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { __parse_error: `${providerLabel} tool args were not valid JSON: ${msg}` };
  }
}
