import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

import { StoredKajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import { buildContextFromMessages, type ContextWindow } from "@/runtime/context";
import { SessionProjector } from "@/sessions/projector";
import { applyEvent, type SessionState } from "@/sessions/replay";
import type { MetricMeasurement, MetricsSink } from "@/observability";

function stored(input: Record<string, unknown>) {
  const type = input.type;
  return StoredKajiEvent.parse({
    id: `event-${String(input.sequence)}`,
    version: "1.0",
    timestamp: Number(input.sequence),
    ...input,
    ...(typeof type === "string" && type.startsWith("tool.call.") && input.turn_id === undefined
      ? { turn_id: "turn" }
      : {}),
  });
}

function outcome(call: () => unknown): [string, unknown] {
  try {
    return ["ok", call()];
  } catch (error) {
    return [error instanceof Error ? error.name : "unknown", String(error)];
  }
}

function validHistory(sessionId: string): Record<string, unknown>[] {
  return [
    { type: EventType.AGENT_MESSAGE_COMPLETED, content: "leading assistant" },
    { type: EventType.USER_MESSAGE, content: "hello 😀" },
    { type: EventType.AGENT_MESSAGE_COMPLETED, content: "ready" },
    { type: EventType.TRANSCRIPT_FINAL, text: "voice input" },
    { type: EventType.AGENT_REASONING_STARTED },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-1",
      tool_args: { query: "café" },
    },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-parallel",
      tool_args: { query: "parallel" },
    },
    {
      type: EventType.TOOL_APPROVAL_REQUESTED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-1",
      tool_args: { query: "café" },
      risk: "read",
    },
    {
      type: EventType.TOOL_APPROVAL_APPROVED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-1",
    },
    {
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-parallel",
      result: { answer: "first" },
    },
    {
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: "turn-1",
      tool_name: "lookup",
      tool_call_id: "call-1",
      result: { answer: "🌍" },
    },
    { type: EventType.AGENT_REASONING_STARTED },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-2",
      tool_name: "write",
      tool_call_id: "call-2",
      tool_args: {},
    },
    {
      type: EventType.TOOL_APPROVAL_REQUESTED,
      turn_id: "turn-2",
      tool_name: "write",
      tool_call_id: "call-2",
      tool_args: {},
      risk: "write",
    },
    {
      type: EventType.TOOL_APPROVAL_REJECTED,
      turn_id: "turn-2",
      tool_name: "write",
      tool_call_id: "call-2",
      error_code: "APPROVAL_REJECTED",
      reason: "rejected",
    },
    {
      type: EventType.TOOL_CALL_FAILED,
      turn_id: "turn-2",
      tool_name: "write",
      tool_call_id: "call-2",
      error: "rejected",
    },
    { type: EventType.USER_MESSAGE, content: "12345" },
    { type: EventType.AGENT_MESSAGE_COMPLETED, content: "67890" },
    { type: EventType.AGENT_REASONING_STARTED },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-3",
      tool_name: "lookup",
      tool_call_id: "call-1",
      tool_args: {},
    },
    {
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: "turn-3",
      tool_name: "lookup",
      tool_call_id: "call-1",
      result: true,
    },
  ].map((event, index) => ({
    ...event,
    session_id: sessionId,
    sequence: index + 1,
  }));
}

describe("projection-owned context index", () => {
  it("matches the full-scan oracle for every valid history prefix", () => {
    const window: ContextWindow = { maxTurns: 3, maxCharacters: 80 };
    const projector = new SessionProjector("differential", undefined, window);

    for (const event of validHistory("differential")) {
      projector.apply(stored(event));
      const oracle = outcome(() =>
        buildContextFromMessages(projector.state.messages, "system 😀", window),
      );
      const indexed = outcome(() => projector.buildProjectedContext("system 😀", window));
      expect(indexed).toEqual(oracle);
    }
  });

  it.each(
    [
      [
        {
          type: EventType.TOOL_CALL_COMPLETED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "orphan",
          result: {},
        },
      ],
      [
        { type: EventType.USER_MESSAGE, content: "start" },
        {
          type: EventType.TOOL_CALL_REQUESTED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "duplicate",
          tool_args: {},
        },
        {
          type: EventType.TOOL_CALL_REQUESTED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "duplicate",
          tool_args: {},
        },
      ],
      [
        { type: EventType.USER_MESSAGE, content: "start" },
        {
          type: EventType.TOOL_CALL_REQUESTED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "pending",
          tool_args: {},
        },
        { type: EventType.USER_MESSAGE, content: "interrupt" },
      ],
      [
        { type: EventType.USER_MESSAGE, content: "start" },
        {
          type: EventType.TOOL_CALL_REQUESTED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "done",
          tool_args: {},
        },
        {
          type: EventType.TOOL_CALL_COMPLETED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "done",
          result: {},
        },
        {
          type: EventType.TOOL_CALL_COMPLETED,
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: "done",
          result: {},
        },
      ],
    ].map((events) => [events] as const),
  )("preserves the full-scan first fault for malformed histories", (events) => {
    const projector = new SessionProjector("malformed");
    events.forEach((event, index) => {
      projector.apply(stored({ ...event, session_id: "malformed", sequence: index + 1 }));
      expect(outcome(() => projector.buildProjectedContext("system"))).toEqual(
        outcome(() => buildContextFromMessages(projector.state.messages, "system")),
      );
    });
  });

  it("bounds index work, retains no payload copies, and detaches provider output", () => {
    const window: ContextWindow = { maxTurns: 32, maxCharacters: 100_000 };
    const projector = new SessionProjector("complexity", undefined, window);
    let sequence = 0;
    const apply = (event: Record<string, unknown>) =>
      projector.apply(stored({ ...event, session_id: "complexity", sequence: ++sequence }));

    for (let batch = 0; batch < 2_000; batch++) {
      const callId = `call-${batch}`;
      apply({ type: EventType.USER_MESSAGE, content: String(batch) });
      apply({ type: EventType.AGENT_REASONING_STARTED });
      apply({
        type: EventType.TOOL_CALL_REQUESTED,
        turn_id: `turn-${batch}`,
        tool_name: "lookup",
        tool_call_id: callId,
        tool_args: { nested: { batch } },
      });
      apply({
        type: EventType.TOOL_CALL_COMPLETED,
        turn_id: `turn-${batch}`,
        tool_name: "lookup",
        tool_call_id: callId,
        result: { ok: true },
      });
      apply({ type: EventType.AGENT_MESSAGE_COMPLETED, content: `done-${batch}` });
    }

    let result = projector.buildProjectedContext("system", window);
    for (let iteration = 1; iteration < 5; iteration++) {
      result = projector.buildProjectedContext("system", window);
    }
    const assistant = result.messages.find(
      (message) => message.role === "assistant" && message.toolCalls?.length,
    );
    expect(assistant).toBeDefined();
    (assistant!.toolCalls![0]!.args.nested as { batch: unknown }).batch = "changed";
    const source = projector.state.messages
      .slice(-128)
      .find((message) => message.role === "assistant" && message.toolCalls?.length);
    expect((source!.toolCalls![0]!.args.nested as { batch: unknown }).batch).not.toBe("changed");

    expect(projector.contextIndexStats).toMatchObject({
      fullColdBuilds: 1,
      coldEvents: 10_000,
      incrementalEvents: 0,
      suffixCalls: 5,
      persistentCopiedPayloadBytes: 0,
    });
    expect(projector.contextIndexStats.maxVisitedTurnEntries).toBeLessThanOrEqual(32);
    expect(projector.contextIndexStats.copiedOutputMessages).toBe((result.messages.length - 1) * 5);
    expect(projector.contextIndexStats.turnEntries).toBeLessThanOrEqual(
      projector.contextIndexStats.retainedTurns,
    );
    expect(projector.contextIndexStats.sentinelEntries).toBeLessThanOrEqual(1);
    expect(projector.contextIndexStats.totalEntries).toBe(
      projector.contextIndexStats.turnEntries + projector.contextIndexStats.sentinelEntries,
    );

    apply({ type: EventType.USER_MESSAGE, content: "latest" });
    expect(projector.latestUserContent()).toBe("latest");
    expect(projector.contextIndexStats.incrementalEvents).toBe(1);
    expect(projector.contextIndexStats.latestUserAccesses).toBe(1);
  });

  it("falls back to the oracle for a wider post-compaction window", () => {
    const configured: ContextWindow = { maxTurns: 2, maxCharacters: 20 };
    const projector = new SessionProjector("fallback", undefined, configured);
    [
      { type: EventType.USER_MESSAGE, content: "one" },
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "1" },
      { type: EventType.USER_MESSAGE, content: "two" },
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "2" },
      { type: EventType.USER_MESSAGE, content: "three" },
    ].forEach((event, index) =>
      projector.apply(stored({ ...event, session_id: "fallback", sequence: index + 1 })),
    );
    const window: ContextWindow = { maxTurns: null, maxCharacters: null };
    expect(projector.buildProjectedContext("system", window)).toEqual(
      buildContextFromMessages(projector.state.messages, "system", window),
    );
  });

  it("records exact message and character metrics", () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const projector = new SessionProjector("metrics", metrics);
    [
      { type: EventType.USER_MESSAGE, content: "u" },
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "a" },
      {
        type: EventType.TOOL_CALL_REQUESTED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "c",
        tool_args: { emoji: "😀" },
      },
      {
        type: EventType.TOOL_CALL_COMPLETED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "c",
        result: "ok",
      },
    ].forEach((event, index) =>
      projector.apply(stored({ ...event, session_id: "metrics", sequence: index + 1 })),
    );

    projector.buildProjectedContext("😀");

    expect(measurements.find(({ name }) => name === "kaji.context.messages")?.value).toBe(4);
    expect(measurements.find(({ name }) => name === "kaji.context.characters")?.value).toBe(30);
  });

  it("matches the oracle at an exact limit and preserves error precedence", () => {
    const exact = new SessionProjector("exact");
    exact.apply(
      stored({
        type: EventType.USER_MESSAGE,
        session_id: "exact",
        content: "12345",
        sequence: 1,
      }),
    );
    const exactWindow: ContextWindow = { maxTurns: 1, maxCharacters: 5 };
    expect(exact.buildProjectedContext("system", exactWindow)).toEqual(
      buildContextFromMessages(exact.state.messages, "system", exactWindow),
    );

    const pending = new SessionProjector("pending");
    pending.apply(
      stored({
        type: EventType.USER_MESSAGE,
        session_id: "pending",
        content: "12345",
        sequence: 1,
      }),
    );
    pending.apply(
      stored({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: "pending",
        turn_id: "turn",
        tool_name: "lookup",
        tool_call_id: "call",
        tool_args: {},
        sequence: 2,
      }),
    );
    const narrow: ContextWindow = { maxTurns: 1, maxCharacters: 1 };
    expect(outcome(() => pending.buildProjectedContext("system", narrow))).toEqual(
      outcome(() => buildContextFromMessages(pending.state.messages, "system", narrow)),
    );
    expect(outcome(() => pending.buildProjectedContext("system", narrow))).toEqual([
      "ContextIntegrityError",
      "ContextIntegrityError: Assistant tool calls require matching results",
    ]);
  });

  it.each(["append", "remove"])("isolates external message %s from the projection", (mutation) => {
    const projector = new SessionProjector("owned");
    projector.apply(
      stored({
        type: EventType.USER_MESSAGE,
        session_id: "owned",
        content: "one",
        sequence: 1,
      }),
    );
    const snapshot = projector.state;
    if (mutation === "append") {
      snapshot.messages.push({ role: "user", content: "foreign" });
    } else {
      snapshot.messages.pop();
    }
    expect(projector.state.messages.map(({ content }) => content)).toEqual(["one"]);
    const beforeStats = projector.contextIndexStats;

    projector.apply(
      stored({
        type: EventType.USER_MESSAGE,
        session_id: "owned",
        content: "must-apply",
        sequence: 2,
      }),
    );
    expect(projector.lastSequence).toBe(2);
    expect(projector.appliedEvents).toBe(2);
    expect(projector.state.messages.map(({ content }) => content)).toEqual(["one", "must-apply"]);
    expect(projector.contextIndexStats.coldEvents).toBe(beforeStats.coldEvents + 1);
  });

  it("preserves hidden replay cursor semantics in detached state snapshots", () => {
    const projector = new SessionProjector("snapshot-cursor");
    [
      { type: EventType.USER_MESSAGE, content: "go" },
      { type: EventType.AGENT_REASONING_STARTED },
      {
        type: EventType.TOOL_CALL_REQUESTED,
        turn_id: "turn",
        tool_name: "lookup",
        tool_call_id: "first",
        tool_args: {},
      },
    ].forEach((event, index) =>
      projector.apply(stored({ ...event, session_id: "snapshot-cursor", sequence: index + 1 })),
    );

    const snapshot = projector.state;
    applyEvent(
      snapshot,
      stored({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: "snapshot-cursor",
        turn_id: "turn",
        tool_name: "lookup",
        tool_call_id: "second",
        tool_args: {},
        sequence: 4,
      }),
    );

    const snapshotAssistants = snapshot.messages.filter(({ role }) => role === "assistant");
    expect(snapshotAssistants).toHaveLength(1);
    expect(snapshotAssistants[0]!.toolCalls?.map(({ id }) => id)).toEqual(["first", "second"]);
    expect(projector.state.messages[1]!.toolCalls).toHaveLength(1);
  });

  it("bounds incremental RSS against an index-disabled fresh process", () => {
    const bun = [
      process.env.KAJI_BUN_BINARY,
      process.env.npm_execpath?.includes("bun") ? process.env.npm_execpath : undefined,
      process.env.BUN_INSTALL ? join(process.env.BUN_INSTALL, "bin", "bun") : undefined,
      "/opt/homebrew/bin/bun",
      "/usr/local/bin/bun",
    ].find((candidate): candidate is string => candidate !== undefined && existsSync(candidate));
    expect(bun).toBeDefined();

    const measure = (mode: string) => {
      const completed = spawnSync(bun!, ["tests/context-rss-probe.ts", mode], {
        cwd: process.cwd(),
        encoding: "utf8",
        timeout: 120_000,
      });
      expect(completed.status, completed.stderr).toBe(0);
      return JSON.parse(completed.stdout) as {
        rss: number;
        rawMaxRss: number;
        currentRssBytes: number;
        messages: number;
      };
    };
    const baseline = measure("baseline");
    const indexed = measure("indexed");
    expect(baseline.messages).toBe(8_000);
    expect(indexed.messages).toBe(8_000);
    const delta = Math.max(0, indexed.rss - baseline.rss);
    expect(delta, JSON.stringify({ baseline, indexed, delta })).toBeLessThanOrEqual(67_108_864);
  });

  function ownershipProjector(): SessionProjector {
    const projector = new SessionProjector("ownership");
    [
      { type: EventType.USER_MESSAGE, content: "original" },
      { type: EventType.AGENT_REASONING_STARTED },
      {
        type: EventType.TOOL_CALL_REQUESTED,
        turn_id: "turn",
        tool_name: "lookup",
        tool_call_id: "call",
        tool_args: { nested: { value: "original" } },
      },
      {
        type: EventType.TOOL_CALL_COMPLETED,
        turn_id: "turn",
        tool_name: "lookup",
        tool_call_id: "call",
        result: { ok: true },
      },
    ].forEach((event, index) =>
      projector.apply(stored({ ...event, session_id: "ownership", sequence: index + 1 })),
    );
    return projector;
  }

  function mutateProjectedPayload(messages: SessionState["messages"], mutation: string): void {
    if (mutation === "content") {
      messages[0]!.content = "tampered";
    } else if (mutation === "element") {
      messages[0] = { role: "user", content: "tampered" };
    } else if (mutation === "nested_args") {
      (messages[1]!.toolCalls![0]!.args.nested as { value: string }).value = "tampered";
    } else {
      messages[1]!.toolCalls!.push({ id: "extra", name: "lookup", args: {} });
    }
  }

  it.each(
    ["apply", "suffix", "latest_user"].flatMap((boundary) =>
      ["content", "element", "nested_args", "tool_calls"].map(
        (mutation) => [boundary, mutation] as const,
      ),
    ),
  )("isolates %s-boundary %s snapshot mutation", (boundary, mutation) => {
    const projector = ownershipProjector();
    const snapshot = projector.state;
    const beforeSequence = projector.lastSequence;
    const beforeEvents = projector.appliedEvents;
    const beforeStats = projector.contextIndexStats;
    const clone = structuredClone(snapshot.messages);
    expect(clone).toEqual(snapshot.messages);

    mutateProjectedPayload(snapshot.messages, mutation);

    expect(projector.lastSequence).toBe(beforeSequence);
    expect(projector.appliedEvents).toBe(beforeEvents);
    expect(projector.contextIndexStats).toEqual(beforeStats);
    expect(projector.state.messages).toEqual(clone);

    if (boundary === "apply") {
      projector.apply(
        stored({
          type: EventType.AGENT_REASONING_STARTED,
          session_id: "ownership",
          sequence: 5,
        }),
      );
      expect(projector.lastSequence).toBe(beforeSequence + 1);
      expect(projector.appliedEvents).toBe(beforeEvents + 1);
      expect(projector.contextIndexStats.coldEvents).toBe(beforeStats.coldEvents + 1);
    } else if (boundary === "suffix") {
      expect(projector.buildProjectedContext("system")).toEqual(
        buildContextFromMessages(clone, "system"),
      );
      expect(projector.contextIndexStats.suffixCalls).toBe(beforeStats.suffixCalls + 1);
    } else {
      expect(projector.latestUserContent()).toBe("original");
      expect(projector.contextIndexStats.latestUserAccesses).toBe(
        beforeStats.latestUserAccesses + 1,
      );
    }

    expect(projector.state.messages).toEqual(clone);
  });

  it("scans each newly appended tool call exactly once", () => {
    const projector = new SessionProjector("linear-calls", undefined, {
      maxTurns: null,
      maxCharacters: null,
    });
    projector.apply(
      stored({
        type: EventType.USER_MESSAGE,
        session_id: "linear-calls",
        content: "go",
        sequence: 1,
      }),
    );
    projector.apply(
      stored({
        type: EventType.AGENT_REASONING_STARTED,
        session_id: "linear-calls",
        sequence: 2,
      }),
    );
    const encoder = new TextEncoder();
    let expectedArgumentBytes = 0;
    for (let index = 0; index < 100; index++) {
      const args = { index };
      expectedArgumentBytes += encoder.encode(JSON.stringify(args)).byteLength;
      projector.apply(
        stored({
          type: EventType.TOOL_CALL_REQUESTED,
          session_id: "linear-calls",
          turn_id: "turn",
          tool_name: "lookup",
          tool_call_id: `call-${index}`,
          tool_args: args,
          sequence: index + 3,
        }),
      );
    }

    expect(projector.contextIndexStats.scannedToolCalls).toBe(100);
    expect(projector.contextIndexStats.scannedToolArgumentBytes).toBe(expectedArgumentBytes);
  });

  it("validates and defensively snapshots retained and requested windows", () => {
    const configured: ContextWindow = { maxTurns: 2, maxCharacters: null };
    const projector = new SessionProjector("windows", undefined, configured);
    configured.maxTurns = 1;
    [
      { type: EventType.USER_MESSAGE, content: "one" },
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "1" },
      { type: EventType.USER_MESSAGE, content: "two" },
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "2" },
      { type: EventType.USER_MESSAGE, content: "three" },
    ].forEach((event, index) =>
      projector.apply(stored({ ...event, session_id: "windows", sequence: index + 1 })),
    );
    expect(
      projector
        .buildProjectedContext("system")
        .messages.slice(1)
        .map(({ content }) => content),
    ).toEqual(["two", "2", "three"]);

    const invalid: ContextWindow = { maxTurns: 0, maxCharacters: 100 };
    expect(outcome(() => projector.buildProjectedContext("system", invalid))).toEqual(
      outcome(() => buildContextFromMessages(projector.state.messages, "system", invalid)),
    );
    expect(outcome(() => projector.buildProjectedContext("system", invalid))).toEqual([
      "RangeError",
      "RangeError: maxTurns must be a positive integer or null",
    ]);
  });
});
