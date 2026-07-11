/**
 * Build the provider message list from replayed session state. Mirrors the
 * message construction in `kaji.runtime.agents.runtime`.
 */
import type { ProviderMessage } from "@/providers/base";
import type { Message } from "@/sessions/replay";
import { NOOP_METRICS, recordMetric, type MetricsSink } from "@/observability";

/** Caller-owned context applied to one agent turn. */
export interface TurnContext {
  readonly principalId?: string;
  readonly requestId?: string;
  readonly traceId?: string;
  /** Absolute Unix epoch deadline in milliseconds. */
  readonly deadlineMs?: number;
  readonly db?: unknown;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

/** Fully resolved authorization and correlation context for one tool call. */
export interface ToolExecutionContext {
  readonly principalId: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly requestId: string;
  readonly traceId: string;
  readonly toolCallId: string;
  readonly idempotencyKey: string;
  readonly deadlineMs?: number;
  readonly signal: AbortSignal;
  readonly db?: unknown;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export class MissingToolIdentityError extends Error {
  readonly code = "MISSING_TOOL_IDENTITY" as const;
  readonly retryable = false;
  readonly outcome = "not_started" as const;

  constructor() {
    super("Tool execution requires a principal identity");
    this.name = "MissingToolIdentityError";
  }
}

function invalidMetadata(): TypeError {
  return new TypeError("metadata must contain only JSON-like values");
}

function snapshotMetadataValue(value: unknown, active: WeakSet<object>): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw invalidMetadata();
    return value;
  }
  if (typeof value !== "object") throw invalidMetadata();
  if (active.has(value)) throw invalidMetadata();
  active.add(value);
  try {
    if (Array.isArray(value)) {
      const keys = Reflect.ownKeys(value);
      if (
        keys.some((key) => {
          if (key === "length") return false;
          if (typeof key !== "string" || !/^(0|[1-9]\d*)$/.test(key)) return true;
          const descriptor = Object.getOwnPropertyDescriptor(value, key);
          return descriptor === undefined || !descriptor.enumerable || !("value" in descriptor);
        }) ||
        Object.keys(value).length !== value.length
      ) {
        throw invalidMetadata();
      }
      const snapshot = value.map((item) => snapshotMetadataValue(item, active));
      return Object.freeze(snapshot);
    }

    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) throw invalidMetadata();
    const snapshot: Record<string, unknown> = {};
    for (const key of Reflect.ownKeys(value)) {
      if (typeof key !== "string") throw invalidMetadata();
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        throw invalidMetadata();
      }
      Object.defineProperty(snapshot, key, {
        value: snapshotMetadataValue(descriptor.value, active),
        enumerable: true,
        writable: false,
        configurable: false,
      });
    }
    return Object.freeze(snapshot);
  } finally {
    active.delete(value);
  }
}

/** Detach caller-owned metadata and recursively freeze nested objects and arrays. */
export function snapshotContextMetadata(
  metadata: Readonly<Record<string, unknown>> = {},
): Readonly<Record<string, unknown>> {
  if (
    typeof metadata !== "object" ||
    metadata === null ||
    Array.isArray(metadata) ||
    (Object.getPrototypeOf(metadata) !== Object.prototype &&
      Object.getPrototypeOf(metadata) !== null)
  ) {
    throw new TypeError("metadata must be an object");
  }
  return snapshotMetadataValue(metadata, new WeakSet()) as Readonly<Record<string, unknown>>;
}

/** Normalize a required principal identity at an authorization boundary. */
export function normalizePrincipalId(value: unknown): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new MissingToolIdentityError();
  }
  return value.trim();
}

export function assertNonEmptyContextId(value: unknown, field: string): asserts value is string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
}

export function assertValidDeadline(deadlineMs: unknown): asserts deadlineMs is number | undefined {
  if (
    deadlineMs !== undefined &&
    (typeof deadlineMs !== "number" || !Number.isFinite(deadlineMs) || deadlineMs < 0)
  ) {
    throw new TypeError("deadlineMs must be a finite non-negative number");
  }
}

export function assertAbortSignal(signal: unknown): asserts signal is AbortSignal {
  if (
    typeof signal !== "object" ||
    signal === null ||
    typeof (signal as AbortSignal).aborted !== "boolean" ||
    typeof (signal as AbortSignal).addEventListener !== "function" ||
    typeof (signal as AbortSignal).removeEventListener !== "function" ||
    typeof (signal as AbortSignal).dispatchEvent !== "function"
  ) {
    throw new TypeError("signal must be an AbortSignal");
  }
}

/** Validate and detach the canonical context accepted by tool registries. */
export function snapshotToolExecutionContext(context: ToolExecutionContext): ToolExecutionContext {
  if (typeof context !== "object" || context === null || Array.isArray(context)) {
    throw new TypeError("ToolExecutionContext must be an object");
  }
  const principalId = normalizePrincipalId(context.principalId);
  assertNonEmptyContextId(context.sessionId, "sessionId");
  assertNonEmptyContextId(context.turnId, "turnId");
  assertNonEmptyContextId(context.requestId, "requestId");
  assertNonEmptyContextId(context.traceId, "traceId");
  assertNonEmptyContextId(context.toolCallId, "toolCallId");
  if (context.idempotencyKey !== `${context.sessionId}:${context.toolCallId}`) {
    throw new TypeError("idempotencyKey must equal sessionId:toolCallId");
  }
  assertValidDeadline(context.deadlineMs);
  assertAbortSignal(context.signal);
  if (context.metadata === undefined) throw new TypeError("metadata must be an object");
  return {
    principalId,
    sessionId: context.sessionId,
    turnId: context.turnId,
    requestId: context.requestId,
    traceId: context.traceId,
    toolCallId: context.toolCallId,
    idempotencyKey: context.idempotencyKey,
    ...(context.deadlineMs === undefined ? {} : { deadlineMs: context.deadlineMs }),
    signal: context.signal,
    ...(context.db === undefined ? {} : { db: context.db }),
    metadata: snapshotContextMetadata(context.metadata),
  };
}

export interface ContextWindow {
  maxTurns: number | null;
  maxCharacters: number | null;
}

export interface ContextDiagnostics {
  readonly droppedTurns: number;
  readonly droppedMessages: number;
  readonly droppedCharacters: number;
}

export interface ContextBuildResult {
  messages: ProviderMessage[];
  diagnostics: ContextDiagnostics;
}

export const DEFAULT_CONTEXT_WINDOW: Readonly<ContextWindow> = Object.freeze({
  maxTurns: 32,
  maxCharacters: 100_000,
});

export class ContextWindowOverflowError extends Error {
  readonly currentTurnCharacters: number;
  readonly maxCharacters: number;

  constructor(currentTurnCharacters: number, maxCharacters: number) {
    super(
      `Current turn exceeds the context window (${currentTurnCharacters} characters, limit ${maxCharacters})`,
    );
    this.name = "ContextWindowOverflowError";
    this.currentTurnCharacters = currentTurnCharacters;
    this.maxCharacters = maxCharacters;
  }
}

export class ContextIntegrityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContextIntegrityError";
  }
}

export function validateContextWindow(window: ContextWindow): void {
  for (const [name, value] of [
    ["maxTurns", window.maxTurns],
    ["maxCharacters", window.maxCharacters],
  ] as const) {
    if (value !== null && (!Number.isInteger(value) || value < 1)) {
      throw new RangeError(`${name} must be a positive integer or null`);
    }
  }
}

function turnGroups(messages: readonly Message[]): Message[][] {
  const groups: Message[][] = [];
  const pending = new Set<string>();
  for (const message of messages) {
    if (message.role === "user") {
      if (pending.size > 0) {
        throw new ContextIntegrityError("A user message cannot begin while tool calls are pending");
      }
      groups.push([]);
    } else if (groups.length === 0) {
      groups.push([]);
    }
    groups.at(-1)!.push(message);

    if (message.role === "assistant") {
      for (const call of message.toolCalls ?? []) {
        if (call.id.length === 0) {
          throw new ContextIntegrityError("Assistant tool calls require a non-empty id");
        }
        if (pending.has(call.id)) {
          throw new ContextIntegrityError(`Overlapping assistant tool call id ${call.id}`);
        }
        pending.add(call.id);
      }
    } else if (message.role === "tool") {
      const callId = message.toolCallId;
      if (callId === undefined || callId.length === 0) {
        throw new ContextIntegrityError("Tool results require a non-empty toolCallId");
      }
      if (!pending.has(callId)) {
        throw new ContextIntegrityError(`Orphan tool result id ${callId}`);
      }
      pending.delete(callId);
    }
  }
  if (pending.size > 0) {
    throw new ContextIntegrityError("Assistant tool calls require matching results");
  }
  return groups;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function textCharacters(value: string): number {
  return Array.from(value).length;
}

/** Count semantic text visible to the model, including structured tool payloads. */
function messageCharacters(message: Message): number {
  let count = textCharacters(message.content);
  if (message.role === "assistant") {
    for (const call of message.toolCalls ?? []) {
      count += textCharacters(call.id);
      count += textCharacters(call.name);
      count += textCharacters(canonicalJson(call.args));
    }
  } else if (message.role === "tool") {
    count += textCharacters(message.name ?? "");
    count += textCharacters(message.toolCallId ?? "");
  }
  return count;
}

function providerMessage(message: Message): ProviderMessage {
  if (message.role === "tool") {
    return {
      role: "tool",
      content: message.content,
      name: message.name,
      tool_call_id: message.toolCallId ?? message.name ?? "unknown",
    };
  }
  return {
    role: message.role,
    content: message.content,
    toolCalls: message.toolCalls?.map((call) => ({
      id: call.id,
      name: call.name,
      args: structuredClone(call.args),
    })),
  };
}

function providerMessageCharacters(message: ProviderMessage): number {
  let count = textCharacters(message.content);
  if (message.role === "assistant") {
    for (const call of message.toolCalls ?? []) {
      count += textCharacters(call.id);
      count += textCharacters(call.name);
      count += textCharacters(canonicalJson(call.args));
    }
  } else if (message.role === "tool") {
    count += textCharacters(message.name ?? "");
    count += textCharacters(message.tool_call_id ?? "");
  }
  return count;
}

export function buildContext(
  messages: readonly Message[],
  systemPrompt?: string,
  window: ContextWindow = DEFAULT_CONTEXT_WINDOW,
  metricsSink: MetricsSink = NOOP_METRICS,
): ContextBuildResult {
  validateContextWindow(window);
  const groups = turnGroups(messages);
  const groupCharacters = groups.map((group) =>
    group.reduce((total, message) => total + messageCharacters(message), 0),
  );

  if (groups.length > 0 && window.maxCharacters !== null) {
    const currentTurnCharacters = groupCharacters.at(-1)!;
    if (currentTurnCharacters > window.maxCharacters) {
      throw new ContextWindowOverflowError(currentTurnCharacters, window.maxCharacters);
    }
  }

  let keptStart = groups.length;
  let keptTurns = 0;
  let keptCharacters = 0;
  for (let index = groups.length - 1; index >= 0; index--) {
    const characters = groupCharacters[index]!;
    if (window.maxTurns !== null && keptTurns >= window.maxTurns) break;
    if (window.maxCharacters !== null && keptCharacters + characters > window.maxCharacters) break;
    keptStart = index;
    keptTurns++;
    keptCharacters += characters;
  }

  const dropped = groups.slice(0, keptStart);
  const result: ProviderMessage[] = [];
  if (systemPrompt) result.push({ role: "system", content: systemPrompt });
  for (const group of groups.slice(keptStart)) {
    for (const message of group) result.push(providerMessage(message));
  }
  recordMetric(metricsSink, "kaji.context.messages", result.length, {});
  recordMetric(
    metricsSink,
    "kaji.context.characters",
    result.reduce((total, message) => total + providerMessageCharacters(message), 0),
    {},
  );
  return {
    messages: result,
    diagnostics: {
      droppedTurns: dropped.length,
      droppedMessages: dropped.reduce((total, group) => total + group.length, 0),
      droppedCharacters: groupCharacters
        .slice(0, keptStart)
        .reduce((total, count) => total + count, 0),
    },
  };
}

export function buildMessages(
  messages: readonly Message[],
  systemPrompt?: string,
  window: ContextWindow = DEFAULT_CONTEXT_WINDOW,
): ProviderMessage[] {
  return buildContext(messages, systemPrompt, window).messages;
}
