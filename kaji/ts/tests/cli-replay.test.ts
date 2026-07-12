/**
 * Tests for `kaji replay` — the JSONL pretty-printer CLI command.
 *
 * Drives `replay(argv, opts)` directly (no subprocess) using a fixture JSONL
 * written to a temp file. Event types use the wire-format dot-notation strings
 * (e.g. "user.message") matching EventType constants in events/types.ts.
 */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { replay } from "@/cli/replay";

// ---------------------------------------------------------------------------
// Shared fixture
// ---------------------------------------------------------------------------

const FIXTURE_JSONL = [
  `{"type":"session.created","session_id":"sess-1","id":"e1","version":"1.0","timestamp":1000,"metadata":{}}`,
  `{"type":"user.message","session_id":"sess-1","id":"e2","version":"1.0","timestamp":1001,"metadata":{},"content":"Hello agent"}`,
  `{"type":"agent.message.delta","session_id":"sess-1","id":"e3","version":"1.0","timestamp":1002,"metadata":{},"delta":"Hi"}`,
  `{"type":"agent.message.delta","session_id":"sess-1","id":"e4","version":"1.0","timestamp":1003,"metadata":{},"delta":" there!"}`,
  `{"type":"agent.message.completed","session_id":"sess-1","id":"e5","version":"1.0","timestamp":1004,"metadata":{},"content":"Hi there!"}`,
  `{"type":"tool.call.requested","session_id":"sess-1","turn_id":"turn-1","id":"e6","version":"1.0","timestamp":1005,"metadata":{},"tool_name":"echo.say","tool_args":{"message":"test"},"tool_call_id":"tc1"}`,
  `{"type":"tool.call.started","session_id":"sess-1","turn_id":"turn-1","id":"e7","version":"1.0","timestamp":1006,"metadata":{},"tool_name":"echo.say","tool_call_id":"tc1"}`,
  `{"type":"tool.call.completed","session_id":"sess-1","turn_id":"turn-1","id":"e8","version":"1.0","timestamp":1007,"metadata":{},"tool_name":"echo.say","tool_call_id":"tc1","result":{"message":"test"}}`,
  `{"type":"tool.call.requested","session_id":"sess-1","turn_id":"turn-1","id":"e9","version":"1.0","timestamp":1008,"metadata":{},"tool_name":"echo.say","tool_args":{"message":"fail"},"tool_call_id":"tc2"}`,
  `{"type":"tool.call.failed","session_id":"sess-1","turn_id":"turn-1","id":"e10","version":"1.0","timestamp":1009,"metadata":{},"tool_name":"echo.say","tool_call_id":"tc2","error":"Something went wrong"}`,
].join("\n");

// Fixture for --tail: 25 USER_MESSAGE events (more than the 20 limit)
const TAIL_FIXTURE_JSONL = Array.from({ length: 25 }, (_, i) =>
  JSON.stringify({
    type: "user.message",
    session_id: "tail-sess",
    id: `te${i + 1}`,
    version: "1.0",
    timestamp: 2000 + i,
    metadata: {},
    content: `Message ${i + 1}`,
  }),
).join("\n");

// ---------------------------------------------------------------------------
// Temp-dir setup / teardown
// ---------------------------------------------------------------------------

const tmpDir = mkdtempSync(join(tmpdir(), "kaji-replay-test-"));
const fixturePath = join(tmpDir, "session.jsonl");
const tailFixturePath = join(tmpDir, "tail.jsonl");

writeFileSync(fixturePath, FIXTURE_JSONL, "utf-8");
writeFileSync(tailFixturePath, TAIL_FIXTURE_JSONL, "utf-8");

afterAll(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

async function run(args: string[]): Promise<{ code: number; out: string; err: string }> {
  const outLines: string[] = [];
  const errLines: string[] = [];
  const code = await replay(args, {
    log: (m) => outLines.push(m),
    err: (m) => errLines.push(m),
  });
  return { code, out: outLines.join("\n"), err: errLines.join("\n") };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("kaji replay", () => {
  it("--format tree renders USER / ASSISTANT / TOOL sections", async () => {
    const { code, out } = await run([fixturePath, "--format", "tree"]);
    expect(code).toBe(0);
    expect(out).toMatch(/USER/);
    expect(out).toMatch(/ASSISTANT/);
    expect(out).toMatch(/TOOL/);
    expect(out).toMatch(/Hello agent/);
    expect(out).toMatch(/Hi there!/);
    expect(out).toMatch(/echo\.say/);
  });

  it("--format summary renders one-line summary with counts", async () => {
    const { code, out } = await run([fixturePath, "--format", "summary"]);
    expect(code).toBe(0);
    // One line per session (or two: one per session + trailing newline)
    const nonEmpty = out.split("\n").filter((l) => l.trim().length > 0);
    expect(nonEmpty.length).toBe(1);
    expect(out).toMatch(/turns=1/);
    expect(out).toMatch(/tool_calls=2/);
    expect(out).toMatch(/errors=1/);
    expect(out).toMatch(/duration=/);
  });

  it("--format summary groups interleaved sessions in first-seen order", async () => {
    const mixedSessionsPath = join(tmpDir, "mixed-sessions.jsonl");
    writeFileSync(
      mixedSessionsPath,
      [
        `{"type":"user.message","session_id":"sess-2","id":"s2-1","version":"1.0","timestamp":1000,"metadata":{},"content":"first"}`,
        `{"type":"user.message","session_id":"sess-1","id":"s1-1","version":"1.0","timestamp":1001,"metadata":{},"content":"second"}`,
        `{"type":"user.message","session_id":"sess-2","id":"s2-2","version":"1.0","timestamp":1002,"metadata":{},"content":"third"}`,
      ].join("\n"),
      "utf-8",
    );

    const { code, out } = await run([mixedSessionsPath, "--format", "summary"]);
    const lines = out.split("\n").filter((line) => line.length > 0);

    expect(code).toBe(0);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatch(/Session .*sess-2.*turns=2/);
    expect(lines[1]).toMatch(/Session .*sess-1.*turns=1/);
  });

  it("--format json renders a JSON array", async () => {
    const { code, out } = await run([fixturePath, "--format", "json"]);
    expect(code).toBe(0);
    const parsed: unknown = JSON.parse(out);
    expect(Array.isArray(parsed)).toBe(true);
    expect((parsed as unknown[]).length).toBe(10);
  });

  it("--filter user.message returns only USER_MESSAGE events in json output", async () => {
    const { code, out } = await run([fixturePath, "--format", "json", "--filter", "user.message"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out) as Array<{ type: string }>;
    expect(parsed.length).toBeGreaterThan(0);
    for (const e of parsed) {
      expect(e.type).toBe("user.message");
    }
  });

  it("--grep 'hello' only shows events containing 'hello'", async () => {
    const { code, out } = await run([fixturePath, "--format", "json", "--grep", "hello"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out) as Array<Record<string, unknown>>;
    expect(parsed.length).toBeGreaterThan(0);
    for (const e of parsed) {
      expect(JSON.stringify(e).toLowerCase()).toMatch(/hello/);
    }
  });

  it("--tail shows only last 20 events (drops first 5 of 25)", async () => {
    const { code, out } = await run([tailFixturePath, "--format", "tree", "--tail"]);
    expect(code).toBe(0);
    // Messages 1–5 were trimmed; 6–25 must appear
    expect(out).not.toMatch(/Message 5\b/);
    expect(out).toMatch(/Message 6/);
    expect(out).toMatch(/Message 25/);
  });

  it("missing file returns exit code 1", async () => {
    const { code, err } = await run(["/tmp/does-not-exist-kaji-test.jsonl"]);
    expect(code).toBe(1);
    expect(err).toMatch(/Cannot read file/);
  });

  it("invalid --format returns exit code 1", async () => {
    const { code, err } = await run([fixturePath, "--format", "invalid-format"]);
    expect(code).toBe(1);
    expect(err).toMatch(/--format must be/);
  });

  it("malformed JSONL lines are silently skipped (no crash)", async () => {
    const mixedPath = join(tmpDir, "mixed.jsonl");
    const mixed = [
      `{"type":"user.message","session_id":"s2","id":"m1","version":"1.0","timestamp":5000,"metadata":{},"content":"valid"}`,
      `not valid json at all`,
      `{"incomplete":`,
      `{"type":"user.message","session_id":"s2","id":"m2","version":"1.0","timestamp":5001,"metadata":{},"content":"also valid"}`,
    ].join("\n");
    writeFileSync(mixedPath, mixed, "utf-8");

    const { code, out } = await run([mixedPath, "--format", "json"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out) as unknown[];
    // Only the 2 valid events should be present
    expect(parsed.length).toBe(2);
  });

  it("no file argument returns exit code 1 with usage hint", async () => {
    const { code, err } = await run(["--format", "tree"]);
    expect(code).toBe(1);
    expect(err).toMatch(/usage:/i);
  });

  it("warns when the file has content but zero parseable events", async () => {
    const garbagePath = join(tmpDir, "garbage.jsonl");
    writeFileSync(garbagePath, "not json\nstill not json\n", "utf-8");

    const { code, out, err } = await run([garbagePath]);
    expect(code).toBe(0);
    expect(out).toBe("");
    expect(err).toMatch(/no parseable kaji events/i);
  });

  it("does not warn on a genuinely empty file", async () => {
    const emptyPath = join(tmpDir, "empty.jsonl");
    writeFileSync(emptyPath, "", "utf-8");

    const { code, err } = await run([emptyPath]);
    expect(code).toBe(0);
    expect(err).toBe("");
  });
});
