#!/usr/bin/env bun
/** Export deterministic TypeScript SDK behavior for shared parity scenarios. */
import { readFileSync } from "node:fs";

import { InMemoryEventCommitter } from "@/events/committer";
import { EventSchemaIncompatibleError } from "@/events/errors";
import { KajiEvent, StoredKajiEvent, type StoredKajiEvent as StoredEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import type { Clock, IdFactory, IdScope } from "@/internal/uuid";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "@/providers/base";
import { AnthropicProvider } from "@/providers/anthropic";
import { normalizeProviderError, ProviderError } from "@/providers/errors";
import { OpenAIProvider } from "@/providers/openai";
import type { TypedApprovalHandler } from "@/runtime/approval/types";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import { AgentRuntime, type TurnResult } from "@/runtime/runtime";
import {
  replaySession,
  type ApprovalKey,
  type Message,
  type SessionState,
} from "@/sessions/replay";
import { InMemoryEventStore } from "@/events/store";
import {
  ToolExecutionController,
  type ToolExecutionControllerOutcome,
  type ToolExecutionRequest,
} from "@/tools/execution";
import { ToolExecutionError } from "@/tools/execution-errors";
import { ToolPlanner } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import { UnclassifiedToolRiskError, type ToolSpec } from "@/tools/registry";
import {
  ToolArgumentValidationError,
  ToolSchemaValidationError,
  ToolSchemaValidator,
} from "@/tools/validation";

const REPO_ROOT = new URL("../../../", import.meta.url);
const SCENARIOS_URL = new URL("kaji/contracts/parity/scenarios.json", REPO_ROOT);
const TOOLS_URL = new URL("kaji/contracts/tools/", REPO_ROOT);
const SNAPSHOT_KEYS = [
  "result",
  "events",
  "replay",
  "operation_trace",
  "provider_requests",
  "provider_responses",
] as const;

type JsonObject = Record<string, any>;

class QueueIdFactory implements IdFactory {
  private readonly queues: Map<IdScope, string[]>;

  constructor(queues: Record<IdScope, string[]>) {
    this.queues = new Map(
      Object.entries(queues).map(([scope, values]) => [scope as IdScope, [...values]]),
    );
  }

  next(scope: IdScope): string {
    const value = this.queues.get(scope)?.shift();
    if (value === undefined) throw new Error(`deterministic id queue exhausted: ${scope}`);
    return value;
  }
}

class FixedClock implements Clock {
  constructor(
    private readonly wallSeconds: number,
    private readonly monotonic: number,
  ) {}

  nowWallSeconds(): number {
    return this.wallSeconds;
  }

  nowMonotonic(): number {
    return this.monotonic;
  }
}

function emptySnapshot(): JsonObject {
  return {
    result: {},
    events: [],
    replay: {},
    operation_trace: [],
    provider_requests: [],
    provider_responses: [],
  };
}

function eventWire(event: StoredEvent): JsonObject {
  return structuredClone(event) as JsonObject;
}

function neutralToolCalls(calls: readonly any[]): JsonObject[] {
  return calls.map((call) => {
    let args = structuredClone(call.arguments ?? call.args ?? {});
    if (typeof args === "object" && args !== null && "__parse_error" in args) {
      args = { __parse_error: "invalid JSON" };
    }
    return { id: call.id ?? null, name: call.name ?? "", arguments: args };
  });
}

function neutralMessages(messages: readonly any[]): JsonObject[] {
  return messages.map((message) => {
    const item: JsonObject = { role: message.role, content: message.content ?? "" };
    if (message.name !== undefined) item.name = message.name;
    const callId = message.tool_call_id ?? message.toolCallId;
    if (callId !== undefined) item.tool_call_id = callId;
    const calls = message.tool_calls ?? message.toolCalls;
    if (calls !== undefined) item.tool_calls = neutralToolCalls(calls);
    return item;
  });
}

class ScriptedProvider implements ModelProvider {
  readonly providerFamily = "fixture";
  readonly requests: JsonObject[] = [];
  readonly responses: JsonObject[] = [];

  constructor(
    private readonly batches: JsonObject[],
    private readonly operationTrace: string[],
  ) {}

  async generate(messages: ProviderMessage[], tools: ToolSpec[], options?: ModelProviderOptions) {
    const chunks: ModelResponseChunk[] = [];
    for await (const chunk of this.generateStream(messages, tools, options)) chunks.push(chunk);
    return {
      content: chunks.map((chunk) => chunk.delta).join(""),
      toolCalls: chunks.flatMap((chunk) => chunk.toolCalls),
    };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    const index = this.requests.length;
    const batch = this.batches.shift();
    if (batch === undefined) throw new Error("scripted provider response queue exhausted");
    this.operationTrace.push(`provider:start:${index}`);
    this.requests.push({
      messages: neutralMessages(messages),
      tools: structuredClone(tools).map(({ name, description, parameters }) => ({
        name,
        description,
        parameters,
      })),
    });
    const response = {
      content: batch.content ?? "",
      tool_calls: neutralToolCalls(batch.tool_calls ?? []),
    };
    this.responses.push(response);
    if (response.content) yield { delta: response.content, toolCalls: [] };
    if (response.tool_calls.length > 0) {
      yield {
        delta: "",
        toolCalls: response.tool_calls.map((call) => ({
          id: call.id,
          name: call.name,
          args: call.arguments,
        })) as ToolCall[],
      };
    }
    this.operationTrace.push(`provider:end:${index}`);
  }
}

class FixtureExecutionController extends ToolExecutionController {
  constructor(
    private readonly fixture: string,
    private readonly operationTrace: string[],
    private readonly entered: Map<string, PromiseWithResolvers<void>>,
    private readonly released: Map<string, PromiseWithResolvers<void>>,
    clock: Clock,
  ) {
    super({
      limits: { maxParallel: 4 },
      now: () => clock.nowWallSeconds() * 1000,
      monotonicNow: () => clock.nowMonotonic(),
    });
  }

  override async execute(request: ToolExecutionRequest): Promise<ToolExecutionControllerOutcome> {
    if (this.fixture === "queue-timeout") {
      return {
        status: "failed",
        error: new ToolExecutionError(
          "Tool execution timed out",
          "TOOL_TIMEOUT",
          true,
          "not_started",
        ),
      };
    }
    if (this.fixture === "cancellation-before-start") {
      return {
        status: "failed",
        error: new ToolExecutionError(
          "Tool execution cancelled",
          "TOOL_CANCELLED",
          true,
          "not_started",
        ),
      };
    }
    await request.onStarted();
    const label = request.name.replace(/_tool$/, "");
    this.operationTrace.push(`tool:start:${label}`);
    this.entered.get(label)?.resolve();
    const release = this.released.get(label);
    if (release !== undefined) await release.promise;
    if (this.fixture === "started-timeout") {
      this.operationTrace.push(`tool:end:${label}`);
      return {
        status: "failed",
        error: new ToolExecutionError("Tool execution timed out", "TOOL_TIMEOUT", false, "unknown"),
      };
    }
    if (this.fixture === "cancellation-after-start") {
      this.operationTrace.push(`tool:end:${label}`);
      return {
        status: "failed",
        error: new ToolExecutionError(
          "Tool execution cancelled",
          "TOOL_CANCELLED",
          false,
          "unknown",
        ),
      };
    }
    try {
      const result = await request.execute(request.context);
      this.operationTrace.push(`tool:end:${label}`);
      return { status: "completed", result };
    } catch (cause) {
      this.operationTrace.push(`tool:end:${label}`);
      return {
        status: "failed",
        error: new ToolExecutionError(
          "Tool execution failed",
          "TOOL_EXECUTION_FAILED",
          false,
          "unknown",
          { cause },
        ),
      };
    }
  }
}

class FixtureApprovalHandler implements TypedApprovalHandler {
  constructor(private readonly code: "rejected" | "timeout") {}

  async request(): Promise<any> {
    return {
      granted: false,
      code: this.code,
      reason: this.code === "rejected" ? "Fixture rejected" : "Fixture timed out",
    };
  }
}

function runtimeDefinition(fixture: string): JsonObject {
  const final = { content: "handled", tool_calls: [] };
  const oneCall = {
    content: "",
    tool_calls: [{ id: "call-1", name: "fixture_tool", arguments: { value: 1 } }],
  };
  if (fixture === "text-one-turn") {
    return { batches: [{ content: "hello back", tool_calls: [] }] };
  }
  if (fixture === "text-multi-turn") {
    return {
      batches: [
        { content: "first reply", tool_calls: [] },
        { content: "second reply", tool_calls: [] },
      ],
    };
  }
  if (fixture === "one-tool") {
    return { batches: [oneCall, { content: "tool done", tool_calls: [] }] };
  }
  if (fixture === "parallel-tools-reverse" || fixture === "sequential-tools") {
    return {
      batches: [
        {
          content: "",
          tool_calls: [
            { id: "call-first", name: "first_tool", arguments: {} },
            { id: "call-second", name: "second_tool", arguments: {} },
          ],
        },
        { content: "tools done", tool_calls: [] },
      ],
    };
  }
  if (fixture === "max-iteration-exhaustion") {
    return {
      batches: [
        oneCall,
        {
          content: "",
          tool_calls: [{ id: "call-2", name: "fixture_tool", arguments: { value: 2 } }],
        },
      ],
      max_iterations: 2,
    };
  }
  return { batches: [oneCall, final] };
}

function controlsFor(
  document: JsonObject,
  scenario: JsonObject,
): {
  idFactory: QueueIdFactory;
  clock: FixedClock;
} {
  const controls = document.controlSets[scenario.controls];
  return {
    idFactory: new QueueIdFactory(controls.ids),
    clock: new FixedClock(controls.wallSeconds, controls.monotonic),
  };
}

async function runRuntime(document: JsonObject, scenario: JsonObject): Promise<JsonObject> {
  const snapshot = emptySnapshot();
  const fixture = scenario.fixture as string;
  if (fixture === "missing-risk") {
    try {
      const bad = {
        name: "fixture_tool",
        description: "fixture",
        parameters: { type: "object" },
      } as unknown as ToolSpec;
      new ToolPlanner({ executor: async () => ({}), specs: new Map([[bad.name, bad]]) });
    } catch (error) {
      if (!(error instanceof UnclassifiedToolRiskError)) throw error;
      snapshot.result = {
        error: {
          code: error.code,
          path: "/risk",
          message: error.message,
          retryable: error.retryable,
          outcome: error.outcome,
        },
      };
      return snapshot;
    }
    throw new Error("missing-risk fixture unexpectedly constructed");
  }

  const { idFactory, clock } = controlsFor(document, scenario);
  const operationTrace: string[] = [];
  const definition = runtimeDefinition(fixture);
  const provider = new ScriptedProvider(structuredClone(definition.batches), operationTrace);
  const store = new InMemoryEventStore();
  const committer = new InMemoryEventCommitter(store);
  const barrierNames = scenario.schedule.length > 0 ? ["first", "second"] : [];
  const entered = new Map(barrierNames.map((name) => [name, Promise.withResolvers<void>()]));
  const released = new Map(barrierNames.map((name) => [name, Promise.withResolvers<void>()]));
  const controller = new FixtureExecutionController(
    fixture,
    operationTrace,
    entered,
    released,
    clock,
  );
  const parallel = fixture === "parallel-tools-reverse";
  const toolNames =
    fixture === "parallel-tools-reverse" || fixture === "sequential-tools"
      ? ["first_tool", "second_tool"]
      : fixture.startsWith("text-")
        ? []
        : ["fixture_tool"];
  const risk = fixture.startsWith("approval-") ? "write" : "read";
  const specs: ToolSpec[] = toolNames.map((name) => ({
    name,
    description: "fixture tool",
    parameters: {
      type: "object",
      properties: { value: { type: "integer" } },
      additionalProperties: false,
    },
    risk,
    parallel_safe: parallel,
  }));
  const execute = async (name: string, args: Readonly<Record<string, unknown>>) => {
    if (fixture === "executor-error") throw new Error("private fixture failure");
    return { tool: name, arguments: structuredClone(args) };
  };
  let policy: ToolPolicy | undefined;
  let approvalHandler: any;
  let externalBridge: Promise<void> | undefined;
  if (fixture === "policy-deny") {
    policy = new ToolPolicy({ denied: new Set(["fixture_tool"]) });
  } else if (fixture.startsWith("approval-")) {
    policy = new ToolPolicy({ requireApprovalFor: new Set(["write"]) });
    if (fixture === "approval-reject") approvalHandler = new FixtureApprovalHandler("rejected");
    else if (fixture === "approval-timeout")
      approvalHandler = new FixtureApprovalHandler("timeout");
    else if (fixture === "approval-external-recorded") {
      approvalHandler = new EventApprovalHandler({ idFactory, clock });
      const observer = committer.subscribe(scenario.input.session_id);
      externalBridge = (async () => {
        for await (const event of observer) {
          if (event.type !== EventType.TOOL_APPROVAL_REQUESTED) continue;
          await committer.commit(
            KajiEvent.parse({
              id: idFactory.next("event"),
              timestamp: clock.nowWallSeconds(),
              type: EventType.TOOL_APPROVAL_APPROVED,
              session_id: event.session_id,
              turn_id: event.turn_id,
              tool_name: event.tool_name,
              tool_call_id: event.tool_call_id,
              metadata: {},
            }),
          );
          return;
        }
      })();
    }
  }
  const planner = new ToolPlanner({
    executor: execute,
    policy,
    approvalHandler,
    approvalCommitter: committer,
    specs: new Map(specs.map((spec) => [spec.name, spec])),
    executionController: controller,
    idFactory,
    clock,
  });
  const runtime = new AgentRuntime({
    provider,
    store,
    committer,
    planner,
    tools: specs,
    strategy: { maxToolIterations: definition.max_iterations ?? 5 },
    defaultContext: {
      principalId: "parity-principal",
      requestId: "request-fixed",
      traceId: "trace-fixed",
    },
    systemPrompt: "You are a helpful assistant.",
    idFactory,
    clock,
  });
  const executeTurns = async () => {
    const results: TurnResult[] = [];
    for (const prompt of scenario.input.prompts) {
      results.push(await runtime.turn(prompt, { sessionId: scenario.input.session_id }));
    }
    return results;
  };
  const turnsPromise = executeTurns();
  for (const label of scenario.schedule) {
    await entered.get(label)!.promise;
    released.get(label)!.resolve();
  }
  const turns = await turnsPromise;
  if (externalBridge !== undefined) await externalBridge;
  snapshot.result = {
    turns: turns.map((turn) => ({
      session_id: turn.sessionId,
      turn_id: turn.turnId,
      text: turn.text,
    })),
  };
  snapshot.events = turns.flatMap((turn) => turn.events.map(eventWire));
  snapshot.operation_trace = operationTrace;
  snapshot.provider_requests = provider.requests;
  snapshot.provider_responses = provider.responses;
  return snapshot;
}

async function runToolSchema(scenario: JsonObject): Promise<JsonObject> {
  const snapshot = emptySnapshot();
  const fixture = JSON.parse(
    readFileSync(new URL(scenario.fixtureFile, TOOLS_URL), "utf8"),
  ).cases.find((item: JsonObject) => item.name === scenario.fixture);
  if (fixture === undefined) throw new Error(`missing tool fixture: ${scenario.fixture}`);
  const spec: ToolSpec = {
    name: "fixture_tool",
    description: fixture.name,
    parameters: fixture.schema,
    risk: "read",
  };
  try {
    const validator = new ToolSchemaValidator(new Map([[spec.name, spec]]));
    await validator.validate(spec.name, fixture.arguments);
  } catch (error) {
    if (
      !(error instanceof ToolArgumentValidationError) &&
      !(error instanceof ToolSchemaValidationError)
    ) {
      throw error;
    }
    snapshot.result = {
      fixture: fixture.name,
      accepted: false,
      error: {
        ...error.normalized(),
        retryable: error.retryable,
        outcome: error.outcome,
      },
    };
    return snapshot;
  }
  snapshot.result = { fixture: fixture.name, accepted: true };
  return snapshot;
}

function replayEvents(): StoredEvent[] {
  const raw: JsonObject[] = [
    { type: EventType.SESSION_CREATED },
    { type: EventType.AGENT_REASONING_STARTED, turn_id: "turn-replay" },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-replay",
      tool_name: "lookup",
      tool_call_id: "call-ok",
      tool_args: { q: "café" },
    },
    {
      type: EventType.TOOL_APPROVAL_REQUESTED,
      turn_id: "turn-replay",
      tool_name: "lookup",
      tool_call_id: "call-ok",
      tool_args: { q: "café" },
      risk: "write",
    },
    {
      type: EventType.TOOL_APPROVAL_APPROVED,
      turn_id: "turn-replay",
      tool_name: "lookup",
      tool_call_id: "call-ok",
    },
    {
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: "turn-replay",
      tool_name: "lookup",
      tool_call_id: "call-ok",
      result: { z: 1, a: [2] },
    },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-replay",
      tool_name: "write",
      tool_call_id: "call-failed",
      tool_args: { value: 3 },
    },
    {
      type: EventType.TOOL_APPROVAL_REQUESTED,
      turn_id: "turn-replay",
      tool_name: "write",
      tool_call_id: "call-failed",
      tool_args: { value: 3 },
      risk: "write",
    },
    {
      type: EventType.TOOL_APPROVAL_REJECTED,
      turn_id: "turn-replay",
      tool_name: "write",
      tool_call_id: "call-failed",
      error_code: "APPROVAL_TIMEOUT",
      reason: "Fixture timed out",
    },
    {
      type: EventType.TOOL_CALL_FAILED,
      turn_id: "turn-replay",
      tool_name: "write",
      tool_call_id: "call-failed",
      error: "Tool approval timed out",
      error_code: "APPROVAL_TIMEOUT",
      retryable: true,
      outcome: "not_started",
    },
  ];
  return raw.map((payload, index) =>
    StoredKajiEvent.parse({
      ...KajiEvent.parse({
        id: `replay-event-${index + 1}`,
        version: "1.0",
        timestamp: 1700000000,
        session_id: "session-replay",
        metadata: {},
        ...payload,
      }),
      sequence: index + 1,
    }),
  );
}

function approvalRecords(values: Iterable<ApprovalKey>): JsonObject[] {
  return [...values]
    .map((value) => {
      const [turn_id, tool_call_id, tool_name] = JSON.parse(value) as [string, string, string];
      return { turn_id, tool_call_id, tool_name };
    })
    .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right), "en"));
}

function replayWire(state: SessionState): JsonObject {
  return {
    session_id: state.sessionId,
    is_active: state.isActive,
    messages: neutralMessages(state.messages as Message[]),
    pending_approvals: approvalRecords(state.pendingApprovals),
    approved_approvals: approvalRecords(state.approvedApprovals),
    rejected_approvals: approvalRecords(state.rejectedApprovals.keys()).map((record) => ({
      ...record,
      error_code: state.rejectedApprovals.get(
        JSON.stringify([record.turn_id, record.tool_call_id, record.tool_name]) as ApprovalKey,
      ),
    })),
  };
}

const JSON_REPLAY_RESULTS: Record<string, unknown> = {
  "json-boolean": true,
  "json-null": null,
  "json-number": 7.5,
  "json-integral-float": 1.0,
  "json-negative-zero": -0.0,
  "json-exponent-boundaries": [1e-6, 1.25e-7, 4503599627370495.5, -4503599627370495.5],
  "json-numeric-keys": { 2: "two", 10: "ten" },
  "json-safe-integer-boundary": Number.MAX_SAFE_INTEGER,
  "json-unrepresentable-integer": 2 ** 53,
  "json-utf16-keys": { "\ue000": "bmp", "\u{10000}": "astral" },
  "json-string": "café",
  "json-array": [1, false, null],
};

function replayJsonEvents(result: unknown, replayRejectedValue = false): StoredEvent[] {
  const raw: JsonObject[] = [
    { type: EventType.SESSION_CREATED },
    {
      type: EventType.TOOL_CALL_REQUESTED,
      turn_id: "turn-json",
      tool_name: "fixture",
      tool_call_id: "call-json",
      tool_args: {},
    },
    {
      type: EventType.TOOL_CALL_COMPLETED,
      turn_id: "turn-json",
      tool_name: "fixture",
      tool_call_id: "call-json",
      result,
    },
  ];
  const events = raw.map((payload, index) => {
    const event = KajiEvent.parse({
      id: `json-event-${index + 1}`,
      version: "1.0",
      timestamp: 1700000000,
      session_id: "session-json",
      metadata: {},
      ...payload,
      ...(replayRejectedValue && payload.type === EventType.TOOL_CALL_COMPLETED
        ? { result: null }
        : {}),
    });
    const stored = { ...event, sequence: index + 1 } as StoredEvent;
    return replayRejectedValue ? stored : StoredKajiEvent.parse(stored);
  });
  if (replayRejectedValue) {
    (events.at(-1)! as Extract<StoredEvent, { type: "tool.call.completed" }>).result = result;
  }
  return events;
}

function runReplay(scenario: JsonObject): JsonObject {
  const snapshot = emptySnapshot();
  const events =
    scenario.fixture === "approvals-completed-failed"
      ? replayEvents()
      : replayJsonEvents(
          JSON_REPLAY_RESULTS[scenario.fixture],
          scenario.fixture === "json-unrepresentable-integer",
        );
  if (scenario.fixture === "json-unrepresentable-integer") {
    try {
      replaySession(events);
    } catch (error) {
      if (!(error instanceof EventSchemaIncompatibleError) || error.path !== "/result") {
        throw error;
      }
      snapshot.result = {
        event_count: events.length,
        rejection: "integer_outside_i_json_safe_range",
      };
      return snapshot;
    }
    throw new Error("unrepresentable integer was accepted by replay");
  }
  const state = replaySession(events);
  snapshot.events = events.map(eventWire);
  snapshot.replay = replayWire(state);
  snapshot.result = {
    event_count: events.length,
    ...(scenario.fixture === "approvals-completed-failed"
      ? {}
      : { tool_content: state.messages.at(-1)?.content }),
  };
  return snapshot;
}

class BarrierProvider implements ModelProvider {
  readonly providerFamily = "fixture";
  readonly entered = new Map<string, PromiseWithResolvers<void>>();
  readonly released = new Map<string, PromiseWithResolvers<void>>();
  readonly trace: string[] = [];
  active = 0;
  maxActive = 0;

  barrier(label: string) {
    if (!this.entered.has(label)) this.entered.set(label, Promise.withResolvers<void>());
    if (!this.released.has(label)) this.released.set(label, Promise.withResolvers<void>());
    return { entered: this.entered.get(label)!, released: this.released.get(label)! };
  }

  async generate(messages: ProviderMessage[], tools: ToolSpec[], options?: ModelProviderOptions) {
    const chunks: ModelResponseChunk[] = [];
    for await (const chunk of this.generateStream(messages, tools, options)) chunks.push(chunk);
    return { content: chunks.map((chunk) => chunk.delta).join(""), toolCalls: [] };
  }

  async *generateStream(messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
    const label = [...messages].reverse().find((message) => message.role === "user")!.content;
    const barrier = this.barrier(label);
    this.active++;
    this.maxActive = Math.max(this.maxActive, this.active);
    this.trace.push(`provider:start:${label}`);
    barrier.entered.resolve();
    await barrier.released.promise;
    this.trace.push(`provider:end:${label}`);
    this.active--;
    yield { delta: `reply:${label}`, toolCalls: [] };
  }
}

async function runConcurrency(document: JsonObject, scenario: JsonObject): Promise<JsonObject> {
  const snapshot = emptySnapshot();
  const { idFactory, clock } = controlsFor(document, scenario);
  const provider = new BarrierProvider();
  const store = new InMemoryEventStore();
  const runtime = new AgentRuntime({
    provider,
    store,
    committer: new InMemoryEventCommitter(store),
    idFactory,
    clock,
  });
  let activeBeforeRelease: number;
  let results: TurnResult[];
  if (scenario.fixture === "same-session-serialized") {
    const first = runtime.turn("first", { sessionId: "same" });
    await provider.barrier("first").entered.promise;
    const second = runtime.turn("second", { sessionId: "same" });
    await Promise.resolve();
    activeBeforeRelease = provider.active;
    provider.barrier("first").released.resolve();
    await provider.barrier("second").entered.promise;
    provider.barrier("second").released.resolve();
    results = await Promise.all([first, second]);
  } else {
    const turns = new Map<string, Promise<TurnResult>>();
    turns.set("left", runtime.turn("left", { sessionId: "left" }));
    await provider.barrier("left").entered.promise;
    turns.set("right", runtime.turn("right", { sessionId: "right" }));
    await provider.barrier("right").entered.promise;
    activeBeforeRelease = provider.active;
    for (const label of scenario.release) {
      provider.barrier(label).released.resolve();
      await turns.get(label)!;
    }
    results = await Promise.all([turns.get("left")!, turns.get("right")!]);
  }
  snapshot.result = {
    active_before_release: activeBeforeRelease,
    max_active: provider.maxActive,
    texts: results.map((result) => result.text),
  };
  snapshot.events = results.flatMap((result) => result.events.map(eventWire));
  snapshot.operation_trace = provider.trace;
  return snapshot;
}

function responseWire(response: any): JsonObject {
  const result: JsonObject = {
    content: response.content,
    tool_calls: neutralToolCalls(response.toolCalls),
    tokens: {
      input: response.usage?.input ?? 0,
      output: response.usage?.output ?? 0,
    },
  };
  if (response.costUsd !== undefined) result.cost_usd = response.costUsd;
  return result;
}

function chunkWire(chunk: ModelResponseChunk): JsonObject {
  const result: JsonObject = {
    content: chunk.delta,
    tool_calls: neutralToolCalls(chunk.toolCalls),
  };
  if (chunk.usage !== undefined) result.tokens = chunk.usage;
  if (chunk.costUsd !== undefined) result.cost_usd = chunk.costUsd;
  return result;
}

function aggregateChunks(chunks: JsonObject[]): JsonObject {
  const result: JsonObject = {
    content: chunks.map((chunk) => chunk.content).join(""),
    tool_calls: chunks.flatMap((chunk) => chunk.tool_calls),
  };
  for (const chunk of chunks) {
    if (chunk.tokens !== undefined) result.tokens = chunk.tokens;
    if (chunk.cost_usd !== undefined) result.cost_usd = chunk.cost_usd;
  }
  return result;
}

class FixtureOpenAIProvider extends OpenAIProvider {
  constructor(private readonly fakeClient: any) {
    super({
      apiKey: "fixture",
      model: "gpt-5.4-mini",
      maxTokens: 64,
      retry: { maxAttempts: 1, baseDelayMs: 1 },
    });
  }

  protected override async createClient(): Promise<any> {
    return this.fakeClient;
  }
}

class FixtureAnthropicProvider extends AnthropicProvider {
  constructor(private readonly fakeClient: any) {
    super({
      apiKey: "fixture",
      model: "claude-sonnet-4-6",
      maxTokens: 64,
      retry: { maxAttempts: 1, baseDelayMs: 1 },
    });
  }

  protected override async createClient(): Promise<any> {
    return this.fakeClient;
  }
}

const providerMessages: ProviderMessage[] = [
  { role: "system", content: "system" },
  { role: "user", content: "lookup" },
  {
    role: "assistant",
    content: "",
    toolCalls: [{ id: "prior-call", name: "lookup", args: { q: "old" } }],
  },
  { role: "tool", content: '{"ok":true}', tool_call_id: "prior-call", name: "lookup" },
];
const providerTools: ToolSpec[] = [
  { name: "lookup", description: "Lookup", parameters: { type: "object" }, risk: "read" },
];

async function runOpenAIAdapter(mode: string): Promise<JsonObject> {
  const snapshot = emptySnapshot();
  const captured: JsonObject[] = [];
  let fail = false;
  const successResponse = {
    choices: [
      {
        message: {
          content: "provider text",
          tool_calls: [
            {
              id: "call-ok",
              type: "function",
              function: { name: "lookup", arguments: '{"q":"new"}' },
            },
            { id: "call-bad", type: "function", function: { name: "lookup", arguments: '{"q":' } },
          ],
        },
      },
    ],
    usage: { prompt_tokens: 5, completion_tokens: 3 },
  };
  const streamItems = [
    {
      choices: [{ delta: { content: "provider ", tool_calls: [] }, finish_reason: null }],
      usage: null,
    },
    {
      choices: [
        {
          delta: {
            content: null,
            tool_calls: [
              { index: 0, id: "call-ok", function: { name: "lookup", arguments: '{"q":' } },
            ],
          },
          finish_reason: null,
        },
      ],
      usage: null,
    },
    {
      choices: [
        {
          delta: {
            content: null,
            tool_calls: [
              { index: 0, id: null, function: { name: null, arguments: '"new"}' } },
              { index: 1, id: "call-bad", function: { name: "lookup", arguments: '{"q":' } },
            ],
          },
          finish_reason: null,
        },
      ],
      usage: null,
    },
    {
      choices: [{ delta: { content: "text", tool_calls: [] }, finish_reason: "tool_calls" }],
      usage: null,
    },
    { choices: [], usage: { prompt_tokens: 5, completion_tokens: 3 } },
  ];
  const fakeClient = {
    chat: {
      completions: {
        create: async (params: JsonObject) => {
          if (fail) {
            throw Object.assign(new Error("fixture transport failure"), { code: "ECONNRESET" });
          }
          captured.push(structuredClone(params));
          if (!params.stream) return successResponse;
          return {
            async *[Symbol.asyncIterator]() {
              for (const item of streamItems) yield item;
            },
          };
        },
      },
    },
  };
  const provider = new FixtureOpenAIProvider(fakeClient);
  if (mode === "non-stream") {
    snapshot.result = responseWire(await provider.generate(providerMessages, providerTools));
  } else {
    const chunks: JsonObject[] = [];
    for await (const chunk of provider.generateStream(providerMessages, providerTools)) {
      chunks.push(chunkWire(chunk));
    }
    snapshot.result = aggregateChunks(chunks);
  }
  fail = true;
  try {
    if (mode === "non-stream") await provider.generate(providerMessages, providerTools);
    else {
      for await (const _ of provider.generateStream(providerMessages, providerTools)) void _;
    }
  } catch (error) {
    if (!(error instanceof ProviderError)) throw error;
    snapshot.result.provider_error = normalizeProviderError(error);
  }
  snapshot.provider_requests = captured.map(canonicalOpenAIRequest);
  snapshot.provider_responses = [snapshot.result];
  return snapshot;
}

function canonicalOpenAIRequest(request: JsonObject): JsonObject {
  return {
    model: request.model,
    messages: request.messages.map((raw: JsonObject) => {
      const message: JsonObject = { role: raw.role, content: raw.content ?? "" };
      if (raw.tool_call_id !== undefined) message.tool_call_id = raw.tool_call_id;
      if (raw.tool_calls?.length) {
        message.tool_calls = raw.tool_calls.map((call: JsonObject) => ({
          id: call.id,
          name: call.function.name,
          arguments: JSON.parse(call.function.arguments),
        }));
      }
      return message;
    }),
    tools: (request.tools ?? []).map((tool: JsonObject) => ({
      name: tool.function.name,
      description: tool.function.description,
      parameters: tool.function.parameters,
    })),
    stream: Boolean(request.stream),
  };
}

async function runAnthropicAdapter(mode: string): Promise<JsonObject> {
  const snapshot = emptySnapshot();
  const captured: JsonObject[] = [];
  let fail = false;
  const response = {
    content: [
      { type: "text", text: "provider text" },
      { type: "tool_use", id: "call-ok", name: "lookup", input: { q: "new" } },
    ],
    usage: { input_tokens: 5, output_tokens: 3 },
  };
  const streamEvents = [
    { type: "message_start", usage: { input_tokens: 5, output_tokens: 0 } },
    { type: "content_block_delta", delta: { type: "text_delta", text: "provider text" } },
    {
      type: "content_block_start",
      content_block: { type: "tool_use", id: "call-ok", name: "lookup" },
    },
    { type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '{"q":' } },
    { type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '"new"}' } },
    { type: "content_block_stop" },
    {
      type: "content_block_start",
      content_block: { type: "tool_use", id: "call-bad", name: "lookup" },
    },
    { type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '{"q":' } },
    { type: "content_block_stop" },
    { type: "message_delta", usage: { output_tokens: 3 } },
  ];
  const fakeClient = {
    messages: {
      create: async (params: JsonObject) => {
        if (fail) {
          throw Object.assign(new Error("fixture transport failure"), { code: "ECONNRESET" });
        }
        captured.push(structuredClone(params));
        return response;
      },
      stream: (params: JsonObject) => {
        if (fail) {
          throw Object.assign(new Error("fixture transport failure"), { code: "ECONNRESET" });
        }
        captured.push(structuredClone(params));
        return {
          async *[Symbol.asyncIterator]() {
            for (const event of streamEvents) yield event;
          },
        };
      },
    },
  };
  const provider = new FixtureAnthropicProvider(fakeClient);
  if (mode === "non-stream") {
    snapshot.result = responseWire(await provider.generate(providerMessages, providerTools));
  } else {
    const chunks: JsonObject[] = [];
    for await (const chunk of provider.generateStream(providerMessages, providerTools)) {
      chunks.push(chunkWire(chunk));
    }
    snapshot.result = aggregateChunks(chunks);
  }
  fail = true;
  try {
    if (mode === "non-stream") await provider.generate(providerMessages, providerTools);
    else {
      for await (const _ of provider.generateStream(providerMessages, providerTools)) void _;
    }
  } catch (error) {
    if (!(error instanceof ProviderError)) throw error;
    snapshot.result.provider_error = normalizeProviderError(error);
  }
  snapshot.provider_requests = captured.map((request) =>
    canonicalAnthropicRequest(request, mode === "stream"),
  );
  snapshot.provider_responses = [snapshot.result];
  return snapshot;
}

function canonicalAnthropicRequest(request: JsonObject, stream: boolean): JsonObject {
  const messages: JsonObject[] = [];
  for (const raw of request.messages) {
    if (Array.isArray(raw.content)) {
      const toolResults = raw.content.filter((block: JsonObject) => block.type === "tool_result");
      const toolUses = raw.content.filter((block: JsonObject) => block.type === "tool_use");
      const text = raw.content
        .filter((block: JsonObject) => block.type === "text")
        .map((block: JsonObject) => block.text ?? "")
        .join("");
      if (toolResults.length > 0) {
        for (const block of toolResults) {
          messages.push({
            role: "tool",
            content: block.content,
            tool_call_id: block.tool_use_id,
          });
        }
        continue;
      }
      const item: JsonObject = { role: raw.role, content: text };
      if (toolUses.length > 0) {
        item.tool_calls = toolUses.map((block: JsonObject) => ({
          id: block.id,
          name: block.name,
          arguments: structuredClone(block.input ?? {}),
        }));
      }
      messages.push(item);
    } else {
      messages.push({ role: raw.role, content: raw.content });
    }
  }
  return {
    model: request.model,
    system: request.system ?? "",
    messages,
    tools: (request.tools ?? []).map((tool: JsonObject) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.input_schema,
    })),
    stream,
  };
}

async function runProviderAdapter(scenario: JsonObject): Promise<JsonObject> {
  return scenario.provider === "openai"
    ? runOpenAIAdapter(scenario.mode)
    : runAnthropicAdapter(scenario.mode);
}

function assertJsonValue(value: unknown, path = ""): void {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError(`non-finite number at ${path || "/"}`);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertJsonValue(item, `${path}/${index}`));
    return;
  }
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    for (const [key, item] of Object.entries(value as JsonObject)) {
      assertJsonValue(item, `${path}/${key}`);
    }
    return;
  }
  throw new TypeError(`non-JSON value ${typeof value} at ${path || "/"}`);
}

async function exportParity(): Promise<JsonObject> {
  const document = JSON.parse(readFileSync(SCENARIOS_URL, "utf8"));
  const seen = new Set<string>();
  const scenarios: JsonObject[] = [];
  for (const scenario of document.scenarios) {
    if (seen.has(scenario.id)) throw new Error(`duplicate scenario id: ${scenario.id}`);
    seen.add(scenario.id);
    let snapshot: JsonObject;
    if (scenario.kind === "runtime") snapshot = await runRuntime(document, scenario);
    else if (scenario.kind === "tool-schema") snapshot = await runToolSchema(scenario);
    else if (scenario.kind === "replay") snapshot = runReplay(scenario);
    else if (scenario.kind === "concurrency") snapshot = await runConcurrency(document, scenario);
    else if (scenario.kind === "provider-adapter") snapshot = await runProviderAdapter(scenario);
    else throw new Error(`unknown scenario kind: ${scenario.kind}`);
    if (JSON.stringify(Object.keys(snapshot)) !== JSON.stringify(SNAPSHOT_KEYS)) {
      throw new Error(`incomplete snapshot envelope: ${scenario.id}`);
    }
    scenarios.push({ id: scenario.id, snapshot });
  }
  const result = { version: document.version, scenarios };
  assertJsonValue(result);
  return result;
}

function sortJson(value: any): any {
  if (Array.isArray(value)) return value.map(sortJson);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right, "en"))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}

try {
  const payload = await exportParity();
  process.stdout.write(`${JSON.stringify(sortJson(payload))}\n`);
} catch (error) {
  process.stderr.write(
    `parity exporter failed: ${error instanceof Error ? `${error.name}: ${error.message}` : String(error)}\n`,
  );
  process.exitCode = 1;
}
