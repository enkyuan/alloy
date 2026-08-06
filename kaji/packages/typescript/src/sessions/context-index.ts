import type { ProviderMessage } from "@/providers/base";
import {
  buildContextFromMessages,
  contextMessageCharacters,
  contextProviderMessageCharacters,
  ContextIntegrityError,
  ContextWindowOverflowError,
  DEFAULT_CONTEXT_WINDOW,
  measureContextToolCall,
  projectProviderMessage,
  validateContextWindow,
  type ContextBuildResult,
  type ContextWindow,
} from "@/runtime/context";
import type { Message, SessionState } from "@/sessions/replay";
import { NOOP_METRICS, recordMetric, type MetricsSink } from "@/observability";

interface ContextTurn {
  messageStart: number;
  messageEnd: number;
  characters: number;
  pendingToolCallIds: Set<string>;
}

export interface ContextIndexStats {
  readonly fullColdBuilds: number;
  readonly coldEvents: number;
  readonly incrementalEvents: number;
  readonly suffixCalls: number;
  readonly maxVisitedTurnEntries: number;
  readonly copiedOutputMessages: number;
  readonly persistentCopiedPayloadBytes: number;
  readonly retainedTurns: number;
  readonly turnEntries: number;
  readonly sentinelEntries: number;
  readonly totalEntries: number;
  readonly latestUserAccesses: number;
  readonly scannedToolCalls: number;
  readonly scannedToolArgumentBytes: number;
}

export class ContextProjectionMutationError extends Error {
  constructor() {
    super("SessionState.messages changed outside SessionProjector");
    this.name = "ContextProjectionMutationError";
  }
}

/** Projection-owned range/count index; message payloads remain in SessionState. */
export class ContextIndex {
  private readonly messages: Message[];
  private readonly retentionWindow: Readonly<ContextWindow>;
  private readonly turns: ContextTurn[] = [];
  private retainedCharacters = 0;
  private prefixTurns = 0;
  private prefixMessages = 0;
  private prefixCharacters = 0;
  private latestUserIndex: number | undefined;
  private integrityError: string | undefined;
  private mutableMessageIndex: number | undefined;
  private projectedMessageCount = 0;

  private coldOpen = true;
  private readonly fullColdBuilds = 1;
  private coldEvents = 0;
  private incrementalEvents = 0;
  private suffixCalls = 0;
  private maxVisitedTurnEntries = 0;
  private copiedOutputMessages = 0;
  private latestUserAccesses = 0;
  private scannedToolCalls = 0;
  private scannedToolArgumentBytes = 0;

  constructor(
    private readonly state: SessionState,
    retentionWindow: Readonly<ContextWindow> = DEFAULT_CONTEXT_WINDOW,
  ) {
    validateContextWindow(retentionWindow);
    this.retentionWindow = Object.freeze({ ...retentionWindow });
    this.messages = state.messages;
  }

  get stats(): Readonly<ContextIndexStats> {
    const turnEntries = this.turns.length;
    const sentinelEntries = this.prefixTurns > 0 ? 1 : 0;
    return Object.freeze({
      fullColdBuilds: this.fullColdBuilds,
      coldEvents: this.coldEvents,
      incrementalEvents: this.incrementalEvents,
      suffixCalls: this.suffixCalls,
      maxVisitedTurnEntries: this.maxVisitedTurnEntries,
      copiedOutputMessages: this.copiedOutputMessages,
      persistentCopiedPayloadBytes: 0,
      retainedTurns: this.turns.length,
      turnEntries,
      sentinelEntries,
      totalEntries: turnEntries + sentinelEntries,
      latestUserAccesses: this.latestUserAccesses,
      scannedToolCalls: this.scannedToolCalls,
      scannedToolArgumentBytes: this.scannedToolArgumentBytes,
    });
  }

  sealColdBuild(): void {
    this.coldOpen = false;
  }

  assertProjectionOwned(): void {
    if (
      this.state.messages !== this.messages ||
      this.messages.length !== this.projectedMessageCount
    ) {
      throw new ContextProjectionMutationError();
    }
  }

  apply(messageIndex: number | null): void {
    if (this.coldOpen) this.coldEvents++;
    else this.incrementalEvents++;
    if (messageIndex === null) return;

    const message = this.messages[messageIndex]!;
    const appended = messageIndex >= this.projectedMessageCount;
    this.projectedMessageCount = this.messages.length;
    if (!appended) {
      this.updateAssistant(messageIndex, message);
      this.compact();
      return;
    }

    if (message.role === "user") {
      if (this.pendingIds().size > 0) {
        this.fault("A user message cannot begin while tool calls are pending");
      }
      this.latestUserIndex = messageIndex;
      this.appendTurn(messageIndex, message);
    } else {
      const turn = this.currentTurn(messageIndex);
      const characters =
        message.role === "assistant"
          ? this.assistantCharacters(message)
          : contextMessageCharacters(message);
      turn.messageEnd = messageIndex + 1;
      turn.characters += characters;
      this.retainedCharacters += characters;
      if (message.role === "assistant") {
        this.mutableMessageIndex = messageIndex;
        for (const call of message.toolCalls ?? []) this.requestToolCall(turn, call.id);
      } else {
        this.resolveToolCall(turn, message.toolCallId);
      }
    }
    this.compact();
  }

  suffix(
    systemPrompt?: string,
    window: ContextWindow = this.retentionWindow,
    metrics: MetricsSink = NOOP_METRICS,
  ): ContextBuildResult {
    validateContextWindow(window);
    const resolved = Object.freeze({ ...window });
    this.assertProjectionOwned();
    this.sealColdBuild();
    this.suffixCalls++;

    if (this.integrityError !== undefined) throw new ContextIntegrityError(this.integrityError);
    if (this.pendingIds().size > 0) {
      throw new ContextIntegrityError("Assistant tool calls require matching results");
    }
    if (this.prefixTurns > 0 && this.isWiderThanRetention(resolved)) {
      return buildContextFromMessages(this.messages, systemPrompt, resolved, metrics);
    }

    const current = this.turns.at(-1);
    if (
      current !== undefined &&
      resolved.maxCharacters !== null &&
      current.characters > resolved.maxCharacters
    ) {
      throw new ContextWindowOverflowError(current.characters, resolved.maxCharacters);
    }

    let keptStart = this.turns.length;
    let keptTurns = 0;
    let keptCharacters = 0;
    let visited = 0;
    for (let index = this.turns.length - 1; index >= 0; index--) {
      visited++;
      const turn = this.turns[index]!;
      if (resolved.maxTurns !== null && keptTurns >= resolved.maxTurns) break;
      if (
        resolved.maxCharacters !== null &&
        keptCharacters + turn.characters > resolved.maxCharacters
      ) {
        break;
      }
      keptStart = index;
      keptTurns++;
      keptCharacters += turn.characters;
    }
    this.maxVisitedTurnEntries = Math.max(this.maxVisitedTurnEntries, visited);

    const droppedTurns = this.prefixTurns + keptStart;
    const droppedMessages =
      this.prefixMessages +
      this.turns
        .slice(0, keptStart)
        .reduce((total, turn) => total + turn.messageEnd - turn.messageStart, 0);
    const droppedCharacters =
      this.prefixCharacters +
      this.turns.slice(0, keptStart).reduce((total, turn) => total + turn.characters, 0);

    const result: ProviderMessage[] = [];
    if (systemPrompt) result.push({ role: "system", content: systemPrompt });
    if (keptStart < this.turns.length) {
      const start = this.turns[keptStart]!.messageStart;
      const end = this.turns.at(-1)!.messageEnd;
      for (const message of this.messages.slice(start, end)) {
        result.push(projectProviderMessage(message));
        this.copiedOutputMessages++;
      }
    }
    recordMetric(metrics, "kaji.context.messages", result.length, {});
    recordMetric(
      metrics,
      "kaji.context.characters",
      result.reduce((total, message) => total + contextProviderMessageCharacters(message), 0),
      {},
    );
    return {
      messages: result,
      diagnostics: { droppedTurns, droppedMessages, droppedCharacters },
    };
  }

  latestUserContent(): string | undefined {
    this.assertProjectionOwned();
    this.latestUserAccesses++;
    if (this.latestUserIndex === undefined) return undefined;
    return this.messages[this.latestUserIndex]?.content;
  }

  private appendTurn(messageIndex: number, message: Message): void {
    const characters = contextMessageCharacters(message);
    this.turns.push({
      messageStart: messageIndex,
      messageEnd: messageIndex + 1,
      characters,
      pendingToolCallIds: new Set(),
    });
    this.retainedCharacters += characters;
    this.mutableMessageIndex = undefined;
  }

  private currentTurn(messageIndex: number): ContextTurn {
    let turn = this.turns.at(-1);
    if (turn === undefined) {
      turn = {
        messageStart: messageIndex,
        messageEnd: messageIndex,
        characters: 0,
        pendingToolCallIds: new Set(),
      };
      this.turns.push(turn);
    }
    return turn;
  }

  private updateAssistant(messageIndex: number, message: Message): void {
    const turn = this.currentTurn(messageIndex);
    if (this.mutableMessageIndex !== messageIndex) {
      this.fault("Projected context update does not target the current assistant");
      return;
    }
    const call = message.toolCalls?.at(-1);
    if (call === undefined) {
      this.fault("Projected assistant update requires a tool call");
      return;
    }
    const characters = this.scanToolCall(call);
    turn.characters += characters;
    this.retainedCharacters += characters;
    this.requestToolCall(turn, call.id);
  }

  private assistantCharacters(message: Message): number {
    let characters = contextMessageCharacters({ role: "assistant", content: message.content });
    for (const call of message.toolCalls ?? []) characters += this.scanToolCall(call);
    return characters;
  }

  private scanToolCall(call: NonNullable<Message["toolCalls"]>[number]): number {
    const measurement = measureContextToolCall(call);
    this.scannedToolCalls++;
    this.scannedToolArgumentBytes += measurement.argumentBytes;
    return measurement.characters;
  }

  private requestToolCall(turn: ContextTurn, callId: string | undefined): void {
    if (callId === undefined || callId.length === 0) {
      this.fault("Assistant tool calls require a non-empty id");
      return;
    }
    if (turn.pendingToolCallIds.has(callId)) {
      this.fault(`Overlapping assistant tool call id ${callId}`);
      return;
    }
    turn.pendingToolCallIds.add(callId);
  }

  private resolveToolCall(turn: ContextTurn, callId: string | undefined): void {
    if (callId === undefined || callId.length === 0) {
      this.fault("Tool results require a non-empty toolCallId");
      return;
    }
    if (!turn.pendingToolCallIds.delete(callId)) {
      this.fault(`Orphan tool result id ${callId}`);
    }
  }

  private pendingIds(): Set<string> {
    return this.turns.at(-1)?.pendingToolCallIds ?? new Set();
  }

  private fault(message: string): void {
    this.integrityError ??= message;
  }

  private compact(): void {
    while (this.turns.length > 1) {
      const exceedsTurns =
        this.retentionWindow.maxTurns !== null && this.turns.length > this.retentionWindow.maxTurns;
      const exceedsCharacters =
        this.retentionWindow.maxCharacters !== null &&
        this.retainedCharacters > this.retentionWindow.maxCharacters;
      if (!exceedsTurns && !exceedsCharacters) return;
      const dropped = this.turns.shift()!;
      this.retainedCharacters -= dropped.characters;
      this.prefixTurns++;
      this.prefixMessages += dropped.messageEnd - dropped.messageStart;
      this.prefixCharacters += dropped.characters;
    }
  }

  private isWiderThanRetention(window: ContextWindow): boolean {
    return (
      ContextIndex.isWider(window.maxTurns, this.retentionWindow.maxTurns) ||
      ContextIndex.isWider(window.maxCharacters, this.retentionWindow.maxCharacters)
    );
  }

  private static isWider(requested: number | null, retained: number | null): boolean {
    if (retained === null) return false;
    return requested === null || requested > retained;
  }
}
