import { describe, expect, it } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import type { ProviderMessage } from "@/providers/base";
import { buildContext, ContextIntegrityError, ContextWindowOverflowError } from "@/runtime/context";
import { AgentRuntime } from "@/runtime/runtime";
import { SessionProjector } from "@/sessions/projector";
import type { Message } from "@/sessions/replay";
import type { ToolSpec } from "@/tools/registry";

function stored(input: Record<string, unknown>) {
  const type = input.type;
  return StoredKajiEvent.parse({
    ...input,
    ...(typeof type === "string" && type.startsWith("tool.call.") && input.turn_id === undefined
      ? { turn_id: "test-turn" }
      : {}),
  });
}

function nestedToolArgs(event: unknown): { nested: { value: string } } {
  if (typeof event !== "object" || event === null || !("tool_args" in event)) {
    throw new Error("expected tool arguments");
  }
  return (event as { tool_args: { nested: { value: string } } }).tool_args;
}

describe("SessionProjector", () => {
  it("applies 10,000 events while indexing each tool call once", () => {
    const projector = new SessionProjector("projection-10k");

    let sequence = 0;
    const apply = (input: Record<string, unknown>) => {
      projector.apply(stored({ ...input, session_id: "projection-10k", sequence: ++sequence }));
    };

    for (let batch = 0; batch < 2_000; batch++) {
      const callId = `call-${batch}`;
      apply({ type: EventType.USER_MESSAGE, content: String(batch) });
      apply({ type: EventType.AGENT_REASONING_STARTED });
      apply({
        type: EventType.TOOL_CALL_REQUESTED,
        tool_name: "lookup",
        tool_call_id: callId,
        tool_args: { batch },
      });
      apply({
        type: EventType.TOOL_CALL_COMPLETED,
        tool_name: "lookup",
        tool_call_id: callId,
        result: { ok: true },
      });
      apply({ type: EventType.AGENT_MESSAGE_COMPLETED, content: `done-${batch}` });
    }

    expect(projector.lastSequence).toBe(10_000);
    expect(projector.appliedEvents).toBe(10_000);
    const snapshot = projector.state;
    expect(snapshot.messages).toHaveLength(8_000);
    expect(snapshot.messages.at(-1)?.content).toBe("done-1999");
    expect(projector.contextIndexStats).toMatchObject({
      coldEvents: 10_000,
      scannedToolCalls: 2_000,
      persistentCopiedPayloadBytes: 0,
    });
  });

  it("separates consecutive batches while grouping parallel calls", () => {
    const projector = new SessionProjector("batches");
    const apply = (sequence: number, input: Record<string, unknown>) =>
      projector.apply(stored({ ...input, session_id: "batches", sequence }));

    apply(1, { type: EventType.USER_MESSAGE, content: "go" });
    apply(2, { type: EventType.AGENT_REASONING_STARTED });
    apply(3, {
      type: EventType.TOOL_CALL_REQUESTED,
      tool_name: "one",
      tool_call_id: "c1",
      tool_args: {},
    });
    apply(4, {
      type: EventType.TOOL_CALL_REQUESTED,
      tool_name: "two",
      tool_call_id: "c2",
      tool_args: {},
    });
    apply(5, {
      type: EventType.TOOL_CALL_COMPLETED,
      tool_name: "one",
      tool_call_id: "c1",
      result: 1,
    });
    apply(6, {
      type: EventType.TOOL_CALL_COMPLETED,
      tool_name: "two",
      tool_call_id: "c2",
      result: 2,
    });
    apply(7, { type: EventType.AGENT_REASONING_STARTED });
    apply(8, {
      type: EventType.TOOL_CALL_REQUESTED,
      tool_name: "three",
      tool_call_id: "c3",
      tool_args: {},
    });
    apply(9, {
      type: EventType.TOOL_CALL_COMPLETED,
      tool_name: "three",
      tool_call_id: "c3",
      result: 3,
    });

    expect(
      projector.state.messages
        .filter((message) => message.role === "assistant")
        .map((message) => message.toolCalls?.map((call) => call.id)),
    ).toEqual([["c1", "c2"], ["c3"]]);
  });

  it("rejects mixed sessions and non-contiguous sequences", () => {
    const projector = new SessionProjector("s1");
    projector.apply(
      stored({ type: EventType.USER_MESSAGE, session_id: "s1", content: "one", sequence: 1 }),
    );

    expect(() =>
      projector.apply(
        stored({ type: EventType.USER_MESSAGE, session_id: "s2", content: "two", sequence: 2 }),
      ),
    ).toThrow(/mixed sessions/);
    expect(() =>
      projector.apply(
        stored({ type: EventType.USER_MESSAGE, session_id: "s1", content: "three", sequence: 3 }),
      ),
    ).toThrow(/expected sequence 2/);
  });
});

describe("complete-turn context window", () => {
  it("keeps a current assistant/tool group intact", () => {
    const messages: Message[] = [
      { role: "user", content: "old" },
      { role: "assistant", content: "bye" },
      { role: "user", content: "current" },
      {
        role: "assistant",
        content: "checking",
        toolCalls: [{ id: "call-1", name: "lookup", args: {} }],
      },
      { role: "tool", content: "done", name: "lookup", toolCallId: "call-1" },
    ];

    const result = buildContext(messages, "system", {
      maxTurns: 1,
      maxCharacters: 100,
    });

    expect(result.messages.map((message) => message.role)).toEqual([
      "system",
      "user",
      "assistant",
      "tool",
    ]);
    expect(result.messages[2]?.toolCalls?.[0]?.id).toBe("call-1");
    expect(result.messages[3]?.tool_call_id).toBe("call-1");
    expect(result.diagnostics).toEqual({
      droppedTurns: 1,
      droppedMessages: 2,
      droppedCharacters: 6,
    });
  });

  it("rejects a new user while a tool call is pending", () => {
    const messages: Message[] = [
      { role: "user", content: "ancient" },
      { role: "assistant", content: "done" },
      { role: "user", content: "start" },
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "call-1", name: "lookup", args: { nested: { value: "original" } } }],
      },
      { role: "user", content: "interrupt" },
      { role: "tool", content: "result", name: "lookup", toolCallId: "call-1" },
    ];

    expect(() =>
      buildContext(messages, "system", {
        maxTurns: 1,
        maxCharacters: 1_000,
      }),
    ).toThrow(/user message.*pending/i);
  });

  it("rejects an unmatched tool request in the current group", () => {
    expect(() =>
      buildContext([
        { role: "user", content: "start" },
        {
          role: "assistant",
          content: "",
          toolCalls: [{ id: "call-1", name: "lookup", args: {} }],
        },
      ]),
    ).toThrow(/matching results/);
  });

  it("fails closed on an orphan tool result", () => {
    expect(() =>
      buildContext([{ role: "tool", content: "result", name: "lookup", toolCallId: "missing" }]),
    ).toThrow(ContextIntegrityError);
  });

  it("drops whole turns by character limit", () => {
    const messages: Message[] = [
      { role: "user", content: "1234" },
      { role: "assistant", content: "5678" },
      { role: "user", content: "12345" },
    ];

    const result = buildContext(messages, "system", {
      maxTurns: null,
      maxCharacters: 5,
    });

    expect(result.messages.slice(1).map((message) => message.content)).toEqual(["12345"]);
    expect(result.diagnostics).toEqual({
      droppedTurns: 1,
      droppedMessages: 2,
      droppedCharacters: 8,
    });
  });

  it("throws when the current complete turn exceeds the character cap", () => {
    const messages: Message[] = [
      { role: "user", content: "12345" },
      { role: "assistant", content: "67" },
    ];

    try {
      buildContext(messages, "system", {
        maxTurns: 1,
        maxCharacters: 6,
      });
      throw new Error("expected context overflow");
    } catch (error) {
      expect(error).toBeInstanceOf(ContextWindowOverflowError);
      expect((error as ContextWindowOverflowError).currentTurnCharacters).toBe(7);
      expect((error as ContextWindowOverflowError).maxCharacters).toBe(6);
    }
  });

  it("counts structured tool names, ids, and canonical JSON arguments", () => {
    const messages: Message[] = [
      { role: "user", content: "old" },
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "c", name: "lookup", args: { query: "xxxxxxxxxx" } }],
      },
      { role: "tool", content: "ok", name: "lookup", toolCallId: "c" },
      { role: "user", content: "now" },
    ];

    const result = buildContext(messages, "system", {
      maxTurns: null,
      maxCharacters: 10,
    });
    expect(result.messages.slice(1).map((message) => message.content)).toEqual(["now"]);
    expect(result.diagnostics.droppedCharacters).toBe(41);

    messages.splice(
      0,
      messages.length,
      { role: "user", content: "now" },
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "c", name: "n", args: { payload: "abcdefghij" } }],
      },
      { role: "tool", content: "", name: "n", toolCallId: "c" },
    );
    expect(() =>
      buildContext(messages, "system", {
        maxTurns: null,
        maxCharacters: 30,
      }),
    ).toThrowError(
      expect.objectContaining<Partial<ContextWindowOverflowError>>({ currentTurnCharacters: 31 }),
    );
  });
});

class CountingStore extends InMemoryEventStore {
  readonly reads: Array<[string, number, number | undefined]> = [];

  override async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ) {
    this.reads.push([sessionId, options.afterSequence ?? 0, options.limit]);
    return super.getEvents(sessionId, options);
  }
}

describe("AgentRuntime incremental projection", () => {
  it("reads one cursor suffix per ten-iteration turn", async () => {
    const store = new CountingStore();
    let providerCalls = 0;
    const provider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream() {
        providerCalls++;
        yield {
          delta: "",
          toolCalls: [{ id: `call-${providerCalls}`, name: "noop", args: {} }],
        };
      },
    };
    const spec: ToolSpec = {
      name: "noop",
      description: "No operation",
      parameters: { type: "object", additionalProperties: false },
      risk: "read",
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      tools: [spec],
      toolExecutor: async () => ({ ok: true }),
      defaultContext: { principalId: "test" },
      strategy: { maxToolIterations: 10 },
    });
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "runtime" }));
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "runtime", content: "first" }),
    );
    store.reads.length = 0;

    await runtime.runTurn("runtime");

    expect(providerCalls).toBe(10);
    expect(store.reads).toEqual([["runtime", 0, undefined]]);

    const cachedCursor = await store.lastSequence("runtime");
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "runtime", content: "second" }),
    );
    store.reads.length = 0;
    await runtime.runTurn("runtime");

    expect(providerCalls).toBe(20);
    expect(store.reads).toEqual([["runtime", cachedCursor, undefined]]);
  });

  it("resyncs only when an external writer creates a same-turn sequence gap", async () => {
    const store = new CountingStore();
    const provider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream() {
        await store.append(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: "interleave",
            turn_id: "approval-bridge",
            tool_name: "noop",
            tool_call_id: "approval-call",
          }),
        );
        yield { delta: "done", toolCalls: [] };
      },
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
    });
    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "interleave" }),
    );
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "interleave", content: "go" }),
    );
    store.reads.length = 0;

    await runtime.runTurn("interleave");

    expect(store.reads).toEqual([
      ["interleave", 0, undefined],
      ["interleave", 3, undefined],
    ]);
    expect((await store.getEvents("interleave")).map((event) => event.sequence)).toEqual([
      1, 2, 3, 4, 5, 6,
    ]);
  });

  it("builds turn results from commits without a second history read", async () => {
    const store = new CountingStore();
    const runtime = new AgentRuntime({
      provider: textProvider("answer"),
      store,
      committer: new InMemoryEventCommitter(store),
    });

    const result = await runtime.turn("question", { sessionId: "result" });

    expect(result.text).toBe("answer");
    expect(store.reads).toEqual([["result", 0, undefined]]);
    expect(result.events.map((event) => event.sequence)).toEqual([1, 2, 3, 4, 5]);
  });

  it("keeps separate runtime caches coherent from their own cursors", async () => {
    const store = new CountingStore();
    const runtimeA = new AgentRuntime({
      provider: textProvider("a"),
      store,
      committer: new InMemoryEventCommitter(store),
    });
    const runtimeB = new AgentRuntime({
      provider: textProvider("b"),
      store,
      committer: new InMemoryEventCommitter(store),
    });
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "shared" }));
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "shared", content: "first" }),
    );
    await runtimeA.runTurn("shared");
    const cursorA = await store.lastSequence("shared");

    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "shared", content: "second" }),
    );
    await runtimeB.runTurn("shared");
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "shared", content: "third" }),
    );
    store.reads.length = 0;

    await runtimeA.runTurn("shared");

    expect(store.reads).toEqual([["shared", cursorA, undefined]]);
  });

  it("exposes dropped context counts without adding model-visible text", async () => {
    const store = new CountingStore();
    let seenRoles: string[] = [];
    const provider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(messages: Array<{ role: string }>) {
        seenRoles = messages.map((message) => message.role);
        yield { delta: "new", toolCalls: [] };
      },
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      contextWindow: { maxTurns: 1, maxCharacters: 100 },
    });
    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "diagnostics" }),
    );
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "diagnostics", content: "old" }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.AGENT_MESSAGE_COMPLETED,
        session_id: "diagnostics",
        content: "bye",
      }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: "diagnostics",
        content: "current",
      }),
    );

    await runtime.runTurn("diagnostics");

    expect(seenRoles).toEqual(["user"]);
    expect(runtime.contextDiagnostics("diagnostics")).toEqual({
      droppedTurns: 1,
      droppedMessages: 2,
      droppedCharacters: 6,
    });
    const diagnostics = runtime.contextDiagnostics("diagnostics")!;
    expect(Object.isFrozen(diagnostics)).toBe(true);
    expect(() => {
      (diagnostics as { droppedTurns: number }).droppedTurns = 999;
    }).toThrow();
    expect(runtime.contextDiagnostics("diagnostics")).toEqual({
      droppedTurns: 1,
      droppedMessages: 2,
      droppedCharacters: 6,
    });
    expect(runtime.contextDiagnostics("diagnostics")).not.toBe(diagnostics);
  });

  it("bounds projection and diagnostics caches to store capacity", async () => {
    const store = new InMemoryEventStore({ maxSessions: 2 });
    const runtime = new AgentRuntime({
      provider: textProvider("unused"),
      store,
      committer: new InMemoryEventCommitter(store),
    });

    for (let index = 0; index < 5; index++) {
      if (index >= 2) {
        await expect(runtime.purgeSession(`closed-${index - 2}`)).resolves.toBe(true);
      }
      const sessionId = `closed-${index}`;
      await runtime.turn("go", { sessionId });
      await runtime.appendEvent(
        KajiEvent.parse({ type: EventType.SESSION_CLOSED, session_id: sessionId }),
      );
    }

    expect(runtime.projectionCacheSize).toBe(2);
  });

  it("exposes immutable context-index stats without creating projectors", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: textProvider("answer"),
      store,
      committer: new InMemoryEventCommitter(store),
    });

    expect(runtime.projectionCacheSize).toBe(0);
    expect(runtime.contextIndexStats("missing")).toBeUndefined();
    expect(runtime.projectionCacheSize).toBe(0);

    await runtime.turn("indexed question", { sessionId: "stats" });
    const stats = runtime.contextIndexStats("stats")!;
    expect(stats).toMatchObject({ fullColdBuilds: 1, suffixCalls: 1 });
    expect(Object.isFrozen(stats)).toBe(true);
    expect(() => {
      (stats as { suffixCalls: number }).suffixCalls = 999;
    }).toThrow();
    const repeated = runtime.contextIndexStats("stats");
    expect(repeated).toEqual(stats);
    expect(repeated).not.toBe(stats);
  });

  it("isolates store input, append results, and reads", async () => {
    const store = new InMemoryEventStore();
    const input = KajiEvent.parse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "store-ownership",
      turn_id: "store-turn",
      tool_name: "ownership",
      tool_call_id: "store-call",
      tool_args: { nested: { value: "original" } },
    });

    const appended = await store.append(input);
    nestedToolArgs(input).nested = { value: "input-mutated" };
    const firstRead = await store.getEvents("store-ownership");
    const firstArgs = nestedToolArgs(firstRead[0]);
    const appendedArgs = nestedToolArgs(appended.event);

    expect(firstArgs.nested.value).toBe("original");
    expect(firstArgs).not.toBe(appendedArgs);
    expect(() => {
      appendedArgs.nested.value = "append-result-mutated";
    }).toThrow();
    expect(() => {
      firstArgs.nested.value = "read-mutated";
    }).toThrow();
    const secondRead = await store.getEvents("store-ownership");
    expect(nestedToolArgs(secondRead[0]).nested.value).toBe("original");
    expect(secondRead[0]).not.toBe(firstRead[0]);
  });

  it("prevents provider and TurnResult mutations across shared runtimes", async () => {
    const store = new InMemoryEventStore();
    const spec: ToolSpec = {
      name: "ownership",
      description: "Ownership probe",
      parameters: { type: "object" },
      risk: "read",
    };
    const owner = ownershipProvider();
    const capture = ownershipCaptureProvider();
    const runtimeA = new AgentRuntime({
      provider: owner.provider,
      store,
      committer: new InMemoryEventCommitter(store),
      tools: [spec],
      toolExecutor: async () => ({ ok: true }),
      defaultContext: { principalId: "test" },
    });
    const runtimeB = new AgentRuntime({
      provider: capture.provider,
      store,
      committer: new InMemoryEventCommitter(store),
      tools: [spec],
      toolExecutor: async () => ({ ok: true }),
      defaultContext: { principalId: "test" },
    });

    const result = await runtimeA.turn("go", { sessionId: "ownership" });
    const eventRequest = result.events.find(
      (event) => event.type === EventType.TOOL_CALL_REQUESTED,
    )!;
    const toolRequest = result.toolCallEvents[0]!;
    const eventArgs = nestedToolArgs(eventRequest);
    const toolArgs = nestedToolArgs(toolRequest);
    expect(eventArgs).not.toBe(toolArgs);
    expect(() => {
      eventArgs.nested.value = "caller-event-mutated";
    }).toThrow();
    expect(() => {
      toolArgs.nested.value = "caller-tool-mutated";
    }).toThrow();

    await runtimeA.send("ownership", "again");
    await runtimeB.send("ownership", "other runtime");

    expect(owner.observed).toEqual(["original", "original"]);
    expect(capture.observed).toEqual(["original"]);
    const persisted = await store.getEvents("ownership");
    const persistedRequest = persisted.find(
      (event) => event.type === EventType.TOOL_CALL_REQUESTED,
    )!;
    expect(nestedToolArgs(persistedRequest).nested.value).toBe("original");
  });
});

function ownershipValues(messages: ProviderMessage[]): string[] {
  return messages.flatMap((message) =>
    (message.toolCalls ?? [])
      .filter((call) => call.id === "ownership-call")
      .map((call) => (call.args as { nested: { value: string } }).nested.value),
  );
}

function ownershipProvider() {
  let calls = 0;
  const observed: string[] = [];
  return {
    observed,
    provider: {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(messages: ProviderMessage[]) {
        calls++;
        if (calls === 1) {
          yield {
            delta: "",
            toolCalls: [
              {
                id: "ownership-call",
                name: "ownership",
                args: { nested: { value: "original" } },
              },
            ],
          };
          return;
        }
        observed.push(...ownershipValues(messages));
        if (calls === 2) {
          for (const message of messages) {
            for (const call of message.toolCalls ?? []) {
              if (call.id === "ownership-call") {
                (call.args as { nested: { value: string } }).nested.value = "provider-mutated";
              }
            }
          }
          messages.length = 0;
        }
        yield { delta: "done", toolCalls: [] };
      },
    },
  };
}

function ownershipCaptureProvider() {
  const observed: string[] = [];
  return {
    observed,
    provider: {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(messages: ProviderMessage[]) {
        observed.push(...ownershipValues(messages));
        yield { delta: "captured", toolCalls: [] };
      },
    },
  };
}

function textProvider(text: string) {
  return {
    async generate() {
      return { content: text, toolCalls: [] };
    },
    async *generateStream() {
      yield { delta: text, toolCalls: [] };
    },
  };
}
