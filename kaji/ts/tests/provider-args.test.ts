/**
 * Unit tests for the shared `parseToolArgsJSON` helper. Pins the behavior
 * that empty/missing args resolve to `{}` (not a parse error), so streaming
 * fragments that complete with an empty buffer are treated as a zero-arg
 * tool call rather than surfaced to the model as a tool failure.
 */
import { describe, expect, it } from "vitest";

import { parseToolArgsJSON } from "@/providers/args";

describe("parseToolArgsJSON", () => {
  it("returns {} for null", () => {
    expect(parseToolArgsJSON(null, "OpenAI")).toEqual({});
  });

  it("returns {} for undefined", () => {
    expect(parseToolArgsJSON(undefined, "OpenAI")).toEqual({});
  });

  it("returns {} for empty string", () => {
    // Empty string means "no args", not "malformed args". Both OpenAI and
    // Anthropic streamed tool-call completions that produce an empty buffer
    // should be treated as a zero-arg invocation.
    expect(parseToolArgsJSON("", "OpenAI")).toEqual({});
  });

  it("parses valid JSON", () => {
    expect(parseToolArgsJSON('{"city":"Seattle"}', "OpenAI")).toEqual({ city: "Seattle" });
  });

  it("returns a labeled __parse_error sentinel for valid non-object JSON", () => {
    for (const raw of ["[]", '"hello"', "1", "true"]) {
      const out = parseToolArgsJSON(raw, "OpenAI");
      expect(out).toHaveProperty("__parse_error");
      expect(out.__parse_error).toMatch(/OpenAI tool args must be a JSON object/);
    }
  });

  it("returns a labeled __parse_error sentinel for malformed JSON", () => {
    const out = parseToolArgsJSON("{not json", "Anthropic");
    expect(out).toHaveProperty("__parse_error");
    expect(out.__parse_error).toMatch(/Anthropic tool args were not valid JSON/);
  });
});
