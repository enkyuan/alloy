/**
 * Build the provider message list from replayed session state. Mirrors the
 * message construction in `kaji.runtime.agents.runtime`.
 */
import type { ProviderMessage } from "@/providers/base";
import type { Message } from "@/sessions/replay";

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

export function buildContext(
  messages: readonly Message[],
  systemPrompt?: string,
  window: ContextWindow = DEFAULT_CONTEXT_WINDOW,
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
