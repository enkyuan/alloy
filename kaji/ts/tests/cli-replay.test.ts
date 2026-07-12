/**
 * Tests for `kaji replay` — the JSONL pretty-printer CLI command.
 *
 * Drives `replay(argv, opts)` directly (no subprocess) using a fixture JSONL
 * written to a temp file. Event types use the wire-format dot-notation strings
 * (e.g. "user.message") matching EventType constants in events/types.ts.
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { replay } from "@/cli/replay";
import { REPLAY_SAFE_ERROR_CODES } from "@/cli/render";

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
  it("keeps the replay error allowlist exactly synchronized with the canonical contract", () => {
    const contract = JSON.parse(
      readFileSync(resolve(import.meta.dirname, "../contracts/errors/error-codes.json"), "utf8"),
    ) as { codes: string[] };

    expect(REPLAY_SAFE_ERROR_CODES).toEqual(contract.codes);
    expect(REPLAY_SAFE_ERROR_CODES).toContain("INTEGRATION_SCHEMA_INVALID");
    expect(REPLAY_SAFE_ERROR_CODES).toContain("INTEGRATION_EXPERIMENTAL");
  });

  it("--format tree renders USER / ASSISTANT / TOOL sections", async () => {
    const { code, out } = await run([fixturePath, "--format", "tree"]);
    expect(code).toBe(0);
    expect(out).toMatch(/USER/);
    expect(out).toMatch(/ASSISTANT/);
    expect(out).toMatch(/TOOL/);
    expect(out).not.toMatch(/Hello agent/);
    expect(out).not.toMatch(/Hi there!/);
    expect(out).not.toMatch(/"message":"test"/);
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
    const projected = JSON.parse(
      (await run([mixedSessionsPath, "--format", "json"])).out,
    ) as Array<{ session_id: string }>;
    const lines = out.split("\n").filter((line) => line.length > 0);

    expect(code).toBe(0);
    expect(lines).toHaveLength(2);
    expect(projected[0]?.session_id).toBe(projected[2]?.session_id);
    expect(projected[0]?.session_id).not.toBe(projected[1]?.session_id);
    expect(lines[0]).toContain(`Session ${projected[0]?.session_id}`);
    expect(lines[0]).toContain("turns=2");
    expect(lines[1]).toContain(`Session ${projected[1]?.session_id}`);
    expect(lines[1]).toContain("turns=1");
  });

  it("--format json renders a JSON array", async () => {
    const { code, out } = await run([fixturePath, "--format", "json"]);
    expect(code).toBe(0);
    const parsed: unknown = JSON.parse(out);
    expect(Array.isArray(parsed)).toBe(true);
    expect((parsed as unknown[]).length).toBe(10);
    for (const event of parsed as Array<Record<string, unknown>>) {
      expect(event).not.toHaveProperty("content");
      expect(event).not.toHaveProperty("tool_args");
      expect(event).not.toHaveProperty("result");
      expect(event).not.toHaveProperty("metadata");
      expect(event).not.toHaveProperty("error");
    }
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

  it("--grep filters on source events but still emits only safe fields", async () => {
    const { code, out } = await run([fixturePath, "--format", "json", "--grep", "hello"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out) as Array<Record<string, unknown>>;
    expect(parsed.length).toBeGreaterThan(0);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.type).toBe("user.message");
    expect(JSON.stringify(parsed).toLowerCase()).not.toContain("hello");
  });

  it("--tail shows only last 20 safe projections (drops first 5 of 25)", async () => {
    const { code, out } = await run([tailFixturePath, "--format", "json", "--tail"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out) as Array<{ id: string }>;
    expect(parsed).toHaveLength(20);
    expect(parsed[0]?.id).toMatch(/^event_[0-9a-f]{16}$/);
    expect(parsed.at(-1)?.id).toMatch(/^event_[0-9a-f]{16}$/);
    expect(parsed[0]?.id).not.toBe(parsed.at(-1)?.id);
    expect(out).not.toContain("te6");
    expect(out).not.toContain("te25");
  });

  it("missing file returns exit code 1", async () => {
    const { code, err } = await run(["/tmp/does-not-exist-kaji-test.jsonl"]);
    expect(code).toBe(1);
    expect(err).toBe("error_code=REPLAY_READ_FAILED reason=unreadable_file");
  });

  it("invalid --format returns usage exit code 2", async () => {
    const { code, err } = await run([fixturePath, "--format", "invalid-format"]);
    expect(code).toBe(2);
    expect(err).toMatch(/--format must be/);
  });

  it("fails closed on the first malformed JSONL line", async () => {
    const mixedPath = join(tmpDir, "mixed.jsonl");
    const mixed = [
      `{"type":"user.message","session_id":"s2","id":"m1","version":"1.0","timestamp":5000,"metadata":{},"content":"valid"}`,
      `not valid json at all`,
      `{"incomplete":`,
      `{"type":"user.message","session_id":"s2","id":"m2","version":"1.0","timestamp":5001,"metadata":{},"content":"also valid"}`,
    ].join("\n");
    writeFileSync(mixedPath, mixed, "utf-8");

    const { code, out, err } = await run([mixedPath, "--format", "json"]);
    expect(code).toBe(1);
    expect(out).toBe("");
    expect(err).toBe("error_code=INVALID_REPLAY_LOG line=2 reason=invalid_json");
    expect(err).not.toContain("not valid json at all");
  });

  it("no file argument returns usage exit code 2", async () => {
    const { code, err } = await run(["--format", "tree"]);
    expect(code).toBe(2);
    expect(err).toMatch(/usage:/i);
  });

  it("fails closed when the file has content but zero parseable events", async () => {
    const garbagePath = join(tmpDir, "garbage.jsonl");
    writeFileSync(garbagePath, "not json\nstill not json\n", "utf-8");

    const { code, out, err } = await run([garbagePath]);
    expect(code).toBe(1);
    expect(out).toBe("");
    expect(err).toBe("error_code=INVALID_REPLAY_LOG line=1 reason=invalid_json");
  });

  it("does not warn on a genuinely empty file", async () => {
    const emptyPath = join(tmpDir, "empty.jsonl");
    writeFileSync(emptyPath, "", "utf-8");

    const { code, err } = await run([emptyPath]);
    expect(code).toBe(0);
    expect(err).toBe("");
  });

  it("renders only stable safe diagnostic fields for failures", async () => {
    const failurePath = join(tmpDir, "failure.jsonl");
    writeFileSync(
      failurePath,
      JSON.stringify({
        type: "agent.turn.failed",
        session_id: "safe-session",
        turn_id: "safe-turn",
        id: "safe-event",
        version: "1.0",
        timestamp: 5000,
        sequence: 1,
        metadata: { api_key: "secret-metadata" },
        error: "raw provider cause secret-error",
        error_code: "TURN_TIMEOUT",
        phase: "provider_stream",
        retryable: true,
        outcome: "unknown",
      }),
      "utf-8",
    );

    for (const format of ["tree", "json"] as const) {
      const { code, out, err } = await run([failurePath, "--format", format]);
      expect(code).toBe(0);
      expect(err).toBe("");
      expect(out).toContain("TURN_TIMEOUT");
      expect(out).toContain("provider_stream");
      expect(out).toContain("unknown");
      expect(out).not.toContain("secret-metadata");
      expect(out).not.toContain("secret-error");
      expect(out).not.toContain("api_key");
      expect(out).not.toContain("raw provider cause");
    }
  });

  it("pseudonymizes tool identity and result pointer for invalid tool results", async () => {
    const failurePath = join(tmpDir, "invalid-tool-result.jsonl");
    writeFileSync(
      failurePath,
      JSON.stringify({
        type: "tool.call.failed",
        session_id: "safe-session",
        turn_id: "safe-turn",
        id: "safe-event",
        version: "1.0",
        timestamp: 5000,
        sequence: 1,
        metadata: { api_key: "secret-metadata" },
        tool_name: "payments.charge",
        tool_call_id: "safe-call",
        error: "raw tool result contains secret-value",
        error_code: "INVALID_TOOL_RESULT",
        error_path: "/result/value",
        retryable: false,
        outcome: "unknown",
      }),
      "utf-8",
    );

    const tree = await run([failurePath, "--format", "tree"]);
    expect(tree.code).toBe(0);
    expect(tree.err).toBe("");
    expect(tree.out).toContain("code=INVALID_TOOL_RESULT");
    expect(tree.out).toMatch(/tool=tool_[0-9a-f]{16}/);
    expect(tree.out).toMatch(/path=path_[0-9a-f]{16}/);
    expect(tree.out).toContain("retryable=false");
    expect(tree.out).toContain("outcome=unknown");

    const json = await run([failurePath, "--format", "json"]);
    const [projected] = JSON.parse(json.out) as Array<Record<string, unknown>>;
    expect(projected).toMatchObject({
      error_code: "INVALID_TOOL_RESULT",
      retryable: false,
      outcome: "unknown",
    });
    expect(projected?.error_path).toMatch(/^path_[0-9a-f]{16}$/);
    expect(projected?.tool_name).toMatch(/^tool_[0-9a-f]{16}$/);
    for (const secret of [
      "payments.charge",
      "/result/value",
      "safe-call",
      "safe-session",
      "safe-turn",
      "safe-event",
      "secret-metadata",
      "secret-value",
      "api_key",
      "raw tool result",
    ]) {
      expect(tree.out).not.toContain(secret);
      expect(json.out).not.toContain(secret);
    }
  });

  it("pseudonymizes every opaque field and closes unknown literals in every format", async () => {
    const hostilePath = join(tmpDir, "hostile-safe-fields.jsonl");
    const sharedSession = "sk-live-session-secret";
    writeFileSync(
      hostilePath,
      [
        {
          type: "tool.call.failed",
          session_id: sharedSession,
          turn_id: "sk-live-turn-secret",
          id: "sk-live-event-one-secret",
          version: "1.0",
          timestamp: 5000,
          sequence: 1,
          metadata: {},
          tool_name: "sk-live-tool-secret",
          tool_call_id: "sk-live-call-secret",
          error: "sk-live-cause-secret",
          error_code: "SK_LIVE_UNKNOWN_ERROR_SECRET",
          error_path: "/sk-live-path-secret",
          retryable: false,
          outcome: "unknown",
        },
        {
          type: "agent.turn.failed",
          session_id: sharedSession,
          turn_id: "sk-live-second-turn-secret",
          id: "sk-live-event-two-secret",
          version: "1.0",
          timestamp: 5001,
          sequence: 2,
          metadata: {},
          error: "sk-live-second-cause-secret",
          error_code: "SK_LIVE_SECOND_UNKNOWN_ERROR_SECRET",
          phase: "provider_stream",
          retryable: true,
          outcome: "failed",
        },
        {
          type: "user.message",
          session_id: "sk-live-other-session-secret",
          id: "sk-live-event-three-secret",
          version: "1.0",
          timestamp: 5002,
          sequence: 1,
          metadata: {},
          content: "sk-live-prompt-secret",
        },
      ]
        .map((event) => JSON.stringify(event))
        .join("\n"),
      "utf8",
    );

    const outputs = await Promise.all(
      (["tree", "summary", "json"] as const).map((format) =>
        run([hostilePath, "--format", format]),
      ),
    );
    const secrets = [
      "sk-live-session-secret",
      "sk-live-turn-secret",
      "sk-live-second-turn-secret",
      "sk-live-event-one-secret",
      "sk-live-event-two-secret",
      "sk-live-event-three-secret",
      "sk-live-tool-secret",
      "sk-live-call-secret",
      "sk-live-path-secret",
      "SK_LIVE_UNKNOWN_ERROR_SECRET",
      "SK_LIVE_SECOND_UNKNOWN_ERROR_SECRET",
      "sk-live-cause-secret",
      "sk-live-second-cause-secret",
      "sk-live-other-session-secret",
      "sk-live-prompt-secret",
    ];
    for (const { code, out, err } of outputs) {
      expect(code).toBe(0);
      expect(err).toBe("");
      for (const secret of secrets) expect(out).not.toContain(secret);
    }

    const projected = JSON.parse(outputs[2]!.out) as Array<Record<string, unknown>>;
    expect(projected[0]?.session_id).toBe(projected[1]?.session_id);
    expect(projected[0]?.session_id).not.toBe(projected[2]?.session_id);
    expect(projected[0]?.error_code).toBe("OTHER");
    expect(projected[1]?.error_code).toBe("OTHER");
    expect(projected[0]?.id).toMatch(/^event_[0-9a-f]{16}$/);
    expect(projected[0]?.session_id).toMatch(/^session_[0-9a-f]{16}$/);
    expect(projected[0]?.turn_id).toMatch(/^turn_[0-9a-f]{16}$/);
    expect(projected[0]?.tool_name).toMatch(/^tool_[0-9a-f]{16}$/);
    expect(projected[0]?.tool_call_id).toMatch(/^call_[0-9a-f]{16}$/);
    expect(projected[0]?.error_path).toMatch(/^path_[0-9a-f]{16}$/);
  });

  it("never prints prompt, tool arguments, results, metadata, or key-like fields", async () => {
    const { code, out } = await run([fixturePath, "--format", "json"]);

    expect(code).toBe(0);
    for (const secret of [
      "Hello agent",
      '"message": "test"',
      '"metadata"',
      '"tool_args"',
      '"result"',
    ]) {
      expect(out).not.toContain(secret);
    }
  });
});
