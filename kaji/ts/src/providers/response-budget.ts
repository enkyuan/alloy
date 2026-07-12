import { canonicalJsonValue, cloneAndFreezeJson } from "@/events/json";
import {
  resolveProviderResponseLimits,
  type ProviderResponseDiagnostics,
  type ProviderResponseLimits,
  type ToolCall,
} from "@/providers/base";
import { ProviderOutputLimitError } from "@/providers/errors";

export interface ScalarScan {
  readonly scalars: readonly { readonly text: string; readonly bytes: number }[];
  readonly pendingHighSurrogate?: string;
  readonly bytes: number;
}

/** Validate one fragment and return complete Unicode scalars plus a trailing carry. */
export function scanUtf8Scalars(fragment: string, pendingHighSurrogate?: string): ScalarScan {
  if (typeof fragment !== "string")
    throw new TypeError("provider output fragments must be strings");
  const input = `${pendingHighSurrogate ?? ""}${fragment}`;
  const scalars: { text: string; bytes: number }[] = [];
  let bytes = 0;
  let pending: string | undefined;
  for (let index = 0; index < input.length; index += 1) {
    const unit = input.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      if (index + 1 >= input.length) {
        pending = input[index];
        break;
      }
      const low = input.charCodeAt(index + 1);
      if (!(low >= 0xdc00 && low <= 0xdfff)) {
        throw new TypeError("provider output contains an unpaired Unicode surrogate");
      }
      scalars.push({ text: input.slice(index, index + 2), bytes: 4 });
      bytes += 4;
      index += 1;
      continue;
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new TypeError("provider output contains an unpaired Unicode surrogate");
    }
    const scalarBytes = unit <= 0x7f ? 1 : unit <= 0x7ff ? 2 : 3;
    scalars.push({ text: input[index] as string, bytes: scalarBytes });
    bytes += scalarBytes;
  }
  return pending === undefined
    ? { scalars, bytes }
    : { scalars, bytes, pendingHighSurrogate: pending };
}

export function utf8ByteLength(value: string): number {
  const scan = scanUtf8Scalars(value);
  if (scan.pendingHighSurrogate !== undefined) {
    throw new TypeError("provider output contains an unpaired Unicode surrogate");
  }
  return scan.bytes;
}

export interface RawToolCallFragment {
  readonly key: string | number;
  readonly startsCall?: boolean;
  readonly idFragment?: string;
  readonly nameFragment?: string;
  readonly argumentsFragment?: string;
}

interface RawToolCallState {
  argumentBytes: number;
  idPending?: string;
  namePending?: string;
  argumentsPending?: string;
}

export interface ResponseBudgetDiagnostics {
  readonly textBytes: number;
  readonly totalResponseBytes: number;
  readonly toolCalls: number;
  readonly rawFragments: number;
  readonly toolArgumentJoinOperations: number;
}

export interface AcceptedProviderChunk {
  readonly delta: string;
  readonly toolCalls: readonly ToolCall[];
}

export class LinearStringParts {
  private readonly parts: string[] = [];
  private _fragmentCount = 0;
  private _joinOperations = 0;

  get fragmentCount(): number {
    return this._fragmentCount;
  }

  get joinOperations(): number {
    return this._joinOperations;
  }

  append(fragment: string): void {
    if (!fragment) return;
    this.parts.push(fragment);
    this._fragmentCount += 1;
  }

  join(): string {
    this._joinOperations += 1;
    return this.parts.join("");
  }
}

export class ProviderResponseBudget {
  readonly limits: Readonly<ProviderResponseLimits>;
  private textBytes = 0;
  private totalBytes = 0;
  private callCount = 0;
  private rawFragments = 0;
  private argumentJoins = 0;
  private textPendingHighSurrogate: string | undefined;
  private rawToolCalls = new Map<string | number, RawToolCallState>();

  constructor(limits?: Readonly<ProviderResponseLimits>) {
    this.limits = resolveProviderResponseLimits(limits);
  }

  get diagnostics(): Readonly<ResponseBudgetDiagnostics> {
    return Object.freeze({
      textBytes: this.textBytes,
      totalResponseBytes: this.totalBytes,
      toolCalls: this.callCount,
      rawFragments: this.rawFragments,
      toolArgumentJoinOperations: this.argumentJoins,
    });
  }

  get providerDiagnostics(): Readonly<ProviderResponseDiagnostics> {
    return Object.freeze({
      rawFragments: this.rawFragments,
      toolArgumentJoinOperations: this.argumentJoins,
    });
  }

  acceptRaw(input: {
    readonly text?: string;
    readonly toolFragments?: readonly RawToolCallFragment[];
  }): void {
    const text = input.text ?? "";
    const textScan = scanUtf8Scalars(text, this.textPendingHighSurrogate);
    const nextTextBytes = this.textBytes + textScan.bytes;
    if (nextTextBytes > this.limits.textMaxBytes) {
      throw new ProviderOutputLimitError("text", this.limits.textMaxBytes);
    }

    const nextStates = new Map([...this.rawToolCalls].map(([key, state]) => [key, { ...state }]));
    let addedTotal = textScan.bytes;
    let addedCalls = 0;
    let addedFragments = text ? 1 : 0;
    for (const fragment of input.toolFragments ?? []) {
      let state = nextStates.get(fragment.key);
      if (fragment.startsCall) {
        if (state !== undefined) throw new TypeError("provider tool call started more than once");
        state = { argumentBytes: 0 };
        nextStates.set(fragment.key, state);
        addedCalls += 1;
      } else if (state === undefined) {
        throw new TypeError("provider tool fragment must start a call before appending");
      }

      const id = scanUtf8Scalars(fragment.idFragment ?? "", state.idPending);
      const name = scanUtf8Scalars(fragment.nameFragment ?? "", state.namePending);
      const args = scanUtf8Scalars(fragment.argumentsFragment ?? "", state.argumentsPending);
      state.idPending = id.pendingHighSurrogate;
      state.namePending = name.pendingHighSurrogate;
      state.argumentsPending = args.pendingHighSurrogate;
      state.argumentBytes += args.bytes;
      if (state.argumentBytes > this.limits.toolArgumentsMaxBytes) {
        throw new ProviderOutputLimitError("tool_arguments", this.limits.toolArgumentsMaxBytes);
      }
      addedTotal += id.bytes + name.bytes + args.bytes;
      addedFragments += Number(Boolean(fragment.idFragment));
      addedFragments += Number(Boolean(fragment.nameFragment));
      addedFragments += Number(Boolean(fragment.argumentsFragment));
    }

    const nextCalls = this.callCount + addedCalls;
    if (nextCalls > this.limits.toolCallsMax) {
      throw new ProviderOutputLimitError("tool_calls", this.limits.toolCallsMax);
    }
    const nextTotal = this.totalBytes + addedTotal;
    if (nextTotal > this.limits.responseMaxBytes) {
      throw new ProviderOutputLimitError("total_response", this.limits.responseMaxBytes);
    }

    this.textBytes = nextTextBytes;
    this.totalBytes = nextTotal;
    this.callCount = nextCalls;
    this.rawFragments += addedFragments;
    this.textPendingHighSurrogate = textScan.pendingHighSurrogate;
    this.rawToolCalls = nextStates;
  }

  acceptNormalized(delta: string, toolCalls: readonly ToolCall[]): AcceptedProviderChunk {
    const textScan = scanUtf8Scalars(delta, this.textPendingHighSurrogate);
    const nextTextBytes = this.textBytes + textScan.bytes;
    if (nextTextBytes > this.limits.textMaxBytes) {
      throw new ProviderOutputLimitError("text", this.limits.textMaxBytes);
    }

    let addedTotal = textScan.bytes;
    const serializedCalls: {
      readonly id: string;
      readonly name: string;
      readonly encodedArguments: string;
    }[] = [];
    for (const call of toolCalls) {
      const descriptors = Object.getOwnPropertyDescriptors(call);
      const id = dataProperty(descriptors, "id");
      const name = dataProperty(descriptors, "name");
      const args = dataProperty(descriptors, "args");
      if (typeof id !== "string" || typeof name !== "string") {
        throw new TypeError("provider tool call id and name must be strings");
      }
      const encodedArguments = canonicalJsonValue(args ?? {}, "tool arguments");
      const argumentBytes = utf8ByteLength(encodedArguments);
      if (argumentBytes > this.limits.toolArgumentsMaxBytes) {
        throw new ProviderOutputLimitError("tool_arguments", this.limits.toolArgumentsMaxBytes);
      }
      addedTotal += utf8ByteLength(id) + utf8ByteLength(name) + argumentBytes;
      serializedCalls.push({ id, name, encodedArguments });
    }

    const nextCalls = this.callCount + serializedCalls.length;
    if (nextCalls > this.limits.toolCallsMax) {
      throw new ProviderOutputLimitError("tool_calls", this.limits.toolCallsMax);
    }
    const nextTotal = this.totalBytes + addedTotal;
    if (nextTotal > this.limits.responseMaxBytes) {
      throw new ProviderOutputLimitError("total_response", this.limits.responseMaxBytes);
    }

    const detached = serializedCalls.map(({ id, name, encodedArguments }) =>
      Object.freeze({
        id,
        name,
        args: cloneAndFreezeJson(JSON.parse(encodedArguments)) as Record<string, unknown>,
      }),
    );

    this.textBytes = nextTextBytes;
    this.totalBytes = nextTotal;
    this.callCount = nextCalls;
    this.textPendingHighSurrogate = textScan.pendingHighSurrogate;
    return Object.freeze({ delta, toolCalls: Object.freeze(detached) });
  }

  finishRawTool(key: string | number): void {
    const state = this.rawToolCalls.get(key);
    if (state === undefined) throw new TypeError("unknown provider tool call");
    assertNoPendingSurrogate(state.idPending);
    assertNoPendingSurrogate(state.namePending);
    assertNoPendingSurrogate(state.argumentsPending);
  }

  finish(): void {
    assertNoPendingSurrogate(this.textPendingHighSurrogate);
    for (const key of this.rawToolCalls.keys()) this.finishRawTool(key);
  }

  recordToolArgumentJoin(): void {
    this.argumentJoins += 1;
  }
}

function dataProperty(descriptors: PropertyDescriptorMap, key: string): unknown {
  const descriptor = descriptors[key];
  if (descriptor === undefined) return undefined;
  if (!descriptor.enumerable || !("value" in descriptor)) {
    throw new TypeError("provider tool calls must contain enumerable data properties");
  }
  return descriptor.value;
}

function assertNoPendingSurrogate(pending: string | undefined): void {
  if (pending !== undefined) {
    throw new TypeError("provider output contains an unpaired Unicode surrogate");
  }
}

/** Best-effort vendor stream shutdown before typed output-limit propagation. */
export async function closeProviderStream(stream: unknown): Promise<void> {
  if (typeof stream !== "object" || stream === null) return;
  const candidate = stream as {
    controller?: { abort?: () => unknown };
    abort?: () => unknown;
    return?: () => unknown;
    close?: () => unknown;
  };
  const close =
    candidate.controller?.abort?.bind(candidate.controller) ??
    candidate.abort?.bind(candidate) ??
    candidate.return?.bind(candidate) ??
    candidate.close?.bind(candidate);
  if (close === undefined) return;
  try {
    await close();
  } catch {
    // A vendor close failure must not replace the typed output-limit error.
  }
}
