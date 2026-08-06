import type {
  ModelResponseChunk,
  ProviderResponseDiagnostics,
  ProviderResponseDiagnosticsSink,
  ProviderResponseLimits,
  ToolCall,
} from "@/providers/base";
import { ProviderResponseBudget, scanUtf8Scalars } from "@/providers/response-budget";

export interface DeltaAccumulatorDiagnostics {
  readonly inputFragments: number;
  readonly outputChunks: number;
  readonly joinOperations: number;
}

/** Deterministic byte-bounded durable delta coalescer. */
export class DeltaAccumulator {
  private readonly pending: string[] = [];
  private pendingBytes = 0;
  private _totalBytes = 0;
  private inputFragments = 0;
  private outputChunks = 0;
  private joinOperations = 0;
  private pendingHighSurrogate: string | undefined;

  constructor(readonly maxChunkBytes = 4_096) {
    if (!Number.isSafeInteger(maxChunkBytes) || maxChunkBytes < 4) {
      throw new RangeError("maxChunkBytes must be a safe integer of at least four bytes");
    }
  }

  get totalBytes(): number {
    return this._totalBytes;
  }

  get diagnostics(): Readonly<DeltaAccumulatorDiagnostics> {
    return Object.freeze({
      inputFragments: this.inputFragments,
      outputChunks: this.outputChunks,
      joinOperations: this.joinOperations,
    });
  }

  push(delta: string): readonly string[] {
    if (!delta) return [];
    const scan = scanUtf8Scalars(delta, this.pendingHighSurrogate);
    this.inputFragments += 1;
    this.pendingHighSurrogate = scan.pendingHighSurrogate;
    const emitted: string[] = [];
    for (const scalar of scan.scalars) {
      if (this.pending.length > 0 && this.pendingBytes + scalar.bytes > this.maxChunkBytes) {
        emitted.push(this.drain());
      }
      this.pending.push(scalar.text);
      this.pendingBytes += scalar.bytes;
      this._totalBytes += scalar.bytes;
      if (this.pendingBytes === this.maxChunkBytes) emitted.push(this.drain());
    }
    return emitted;
  }

  flush(options: { readonly allowIncomplete?: boolean } = {}): string | undefined {
    if (this.pendingHighSurrogate !== undefined) {
      if (!options.allowIncomplete) {
        throw new TypeError("provider output contains an unpaired Unicode surrogate");
      }
      this.pendingHighSurrogate = undefined;
    }
    return this.pending.length > 0 ? this.drain() : undefined;
  }

  private drain(): string {
    this.joinOperations += 1;
    this.outputChunks += 1;
    const chunk = this.pending.join("");
    this.pending.length = 0;
    this.pendingBytes = 0;
    return chunk;
  }
}

export interface StreamDiagnostics {
  readonly inputFragments: number;
  readonly durableDeltaEvents: number;
  readonly deltaJoinOperations: number;
  readonly responseJoinOperations: number;
  readonly textBytes: number;
  readonly totalResponseBytes: number;
  readonly toolCalls: number;
  readonly rawFragments: number;
  readonly toolArgumentJoinOperations: number;
}

/** Runtime second boundary for normalized custom-provider chunks. */
export class RuntimeStreamAccumulator {
  private readonly budget: ProviderResponseBudget;
  private readonly deltas = new DeltaAccumulator();
  private readonly responseParts: string[] = [];
  private readonly calls: ToolCall[] = [];
  private joinedContent: string | undefined;
  private responseJoinOperations = 0;
  private providerDiagnostics: Readonly<ProviderResponseDiagnostics> = Object.freeze({
    rawFragments: 0,
    toolArgumentJoinOperations: 0,
  });

  readonly responseDiagnostics: ProviderResponseDiagnosticsSink = Object.freeze({
    record: (diagnostics: Readonly<ProviderResponseDiagnostics>): void => {
      const { rawFragments, toolArgumentJoinOperations } = diagnostics;
      if (
        !Number.isSafeInteger(rawFragments) ||
        rawFragments < 0 ||
        !Number.isSafeInteger(toolArgumentJoinOperations) ||
        toolArgumentJoinOperations < 0
      ) {
        throw new RangeError("provider response diagnostics must be non-negative safe integers");
      }
      this.providerDiagnostics = Object.freeze({ rawFragments, toolArgumentJoinOperations });
    },
  });

  constructor(limits: Readonly<ProviderResponseLimits>) {
    this.budget = new ProviderResponseBudget(limits);
  }

  get toolCalls(): readonly ToolCall[] {
    return this.calls;
  }

  get diagnostics(): Readonly<StreamDiagnostics> {
    const delta = this.deltas.diagnostics;
    const budget = this.budget.diagnostics;
    return Object.freeze({
      inputFragments: delta.inputFragments,
      durableDeltaEvents: delta.outputChunks,
      deltaJoinOperations: delta.joinOperations,
      responseJoinOperations: this.responseJoinOperations,
      textBytes: budget.textBytes,
      totalResponseBytes: budget.totalResponseBytes,
      toolCalls: budget.toolCalls,
      rawFragments: this.providerDiagnostics.rawFragments,
      toolArgumentJoinOperations: this.providerDiagnostics.toolArgumentJoinOperations,
    });
  }

  accept(chunk: ModelResponseChunk): readonly string[] {
    const accepted = this.budget.acceptNormalized(chunk.delta, chunk.toolCalls);
    if (accepted.delta) this.responseParts.push(accepted.delta);
    this.calls.push(...accepted.toolCalls);
    return this.deltas.push(accepted.delta);
  }

  finish(): void {
    this.budget.finish();
  }

  flush(allowIncomplete = false): string | undefined {
    return this.deltas.flush({ allowIncomplete });
  }

  content(): string {
    if (this.joinedContent === undefined) {
      this.responseJoinOperations += 1;
      this.joinedContent = this.responseParts.join("");
    }
    return this.joinedContent;
  }
}
