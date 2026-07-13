/**
 * Provider interface for LLM backends, mirroring
 * `kaji.runtime.providers.base.ModelProvider`.
 *
 * Each provider translates the neutral message + tool format to its own API at
 * its boundary. The runtime never imports provider-specific types.
 */
import {
  CancellationError,
  throwIfCancellationRequested,
  type CancellationTokenLike,
} from "@/runtime/cancellation";
import type { ToolSpec } from "@/tools/registry";
import { NOOP_METRICS, recordMetric, type MetricsSink, type ProviderFamily } from "@/observability";

/** A message in the conversation history passed to the provider. */
export interface ProviderMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool-result messages. */
  name?: string;
  /** Set only for tool-result messages: id from the originating tool call. */
  tool_call_id?: string;
  /** Set only for assistant messages that requested tools. */
  toolCalls?: ToolCall[];
}

/** A tool call the model wants to make. */
export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

/** A streaming chunk from the provider. */
export interface ModelResponseChunk {
  delta: string;
  toolCalls: ToolCall[];
  /** Token usage, if the provider reported it during streaming. */
  usage?: TokenUsage;
  /** Estimated cost in USD, if the model is in the cost table. */
  costUsd?: number;
}

/** Token usage from a provider response. */
export interface TokenUsage {
  /** Prompt / input tokens consumed. */
  input: number;
  /** Completion / output tokens generated. */
  output: number;
}

/** A complete non-streaming response. */
export interface ModelResponse {
  content: string;
  toolCalls: ToolCall[];
  /** Token usage, if the provider reported it. */
  usage?: TokenUsage;
  /** Estimated cost in USD, if the model is in the cost table. */
  costUsd?: number;
}

/** Immutable per-call provider response bounds. */
export interface ProviderResponseLimits {
  readonly textMaxBytes: number;
  readonly toolArgumentsMaxBytes: number;
  readonly responseMaxBytes: number;
  readonly toolCallsMax: number;
}

/** Linear-assembly evidence captured for one provider response. */
export interface ProviderResponseDiagnostics {
  readonly rawFragments: number;
  readonly toolArgumentJoinOperations: number;
}

/** Internal per-call sink used by the runtime without changing stream chunks. */
export interface ProviderResponseDiagnosticsSink {
  record(diagnostics: Readonly<ProviderResponseDiagnostics>): void;
}

const PROVIDER_RESPONSE_DIAGNOSTICS: unique symbol = Symbol.for(
  "kaji.provider.responseDiagnostics",
);

type InternalModelProviderOptions = ModelProviderOptions & {
  readonly [PROVIDER_RESPONSE_DIAGNOSTICS]?: ProviderResponseDiagnosticsSink;
};

/** @internal Attach runtime-owned diagnostics without exposing a public option. */
export function withProviderResponseDiagnostics(
  options: ModelProviderOptions,
  sink: ProviderResponseDiagnosticsSink,
): ModelProviderOptions {
  const internal: InternalModelProviderOptions = { ...options };
  Object.defineProperty(internal, PROVIDER_RESPONSE_DIAGNOSTICS, {
    value: sink,
    enumerable: false,
  });
  return internal;
}

/** @internal Read the runtime-owned per-call diagnostics sink. */
export function getProviderResponseDiagnostics(
  options: ModelProviderOptions | undefined,
): ProviderResponseDiagnosticsSink | undefined {
  return (options as InternalModelProviderOptions | undefined)?.[PROVIDER_RESPONSE_DIAGNOSTICS];
}

export const DEFAULT_PROVIDER_RESPONSE_LIMITS: Readonly<ProviderResponseLimits> = Object.freeze({
  textMaxBytes: 262_144,
  toolArgumentsMaxBytes: 65_536,
  responseMaxBytes: 524_288,
  toolCallsMax: 64,
});

export function resolveProviderResponseLimits(
  limits: Readonly<ProviderResponseLimits> | undefined,
): Readonly<ProviderResponseLimits> {
  const resolved = { ...DEFAULT_PROVIDER_RESPONSE_LIMITS, ...limits };
  for (const [name, value] of Object.entries(resolved)) {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new RangeError(`${name} must be a positive safe integer`);
    }
  }
  return Object.freeze(resolved);
}

/**
 * Per-call options that callers may override from the constructor defaults.
 *
 * `cancellationToken` is structurally typed: any object with an
 * `isCancelled` boolean is accepted. Pass a full `CancellationToken`
 * (which also carries an `AbortSignal` under `.signal`) to let the
 * provider abort the underlying HTTP call, not just poll out at the next
 * yield point.
 */
export interface ModelProviderOptions {
  temperature?: number;
  maxTokens?: number;
  cancellationToken?: CancellationTokenLike;
  /** Runtime-injected metrics sink. Provider implementations must keep labels low-cardinality. */
  metricsSink?: MetricsSink;
  /** Runtime-injected immutable response limits. */
  responseLimits?: Readonly<ProviderResponseLimits>;
}

/** Common interface every LLM provider implements. */
export interface ModelProvider {
  /**
   * Custom providers are cooperative cancellation boundaries. Both methods
   * must observe `options.cancellationToken` while opening and streaming,
   * stop their underlying request, and let the returned iterator settle when
   * cancellation is requested. A provider that misses the configured grace
   * causes a typed contract violation and quarantines that session until a
   * successful `drainProviders()`. Custom adapters must pass the SDK's
   * cancellation-contract suite before being described as production-safe.
   */
  /** Stable low-cardinality family identifier for observability. */
  readonly providerFamily?: ProviderFamily;
  generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): Promise<ModelResponse>;
  generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk>;
}

/** Rate-limit retry configuration shared by HTTP-backed providers. */
export interface RetryOptions {
  /** Maximum retry attempts on 429 rate-limit responses. Defaults to 3. */
  maxAttempts?: number;
  /** Base delay in ms before first retry. Doubles each attempt. Defaults to 1000. */
  baseDelayMs?: number;
}

function parseRetryAfterMs(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const headers =
    "headers" in error
      ? (error as { headers: unknown }).headers
      : "response" in error && typeof (error as { response: unknown }).response === "object"
        ? ((error as { response: { headers?: unknown } }).response?.headers ?? null)
        : null;
  if (typeof headers !== "object" || headers === null) return undefined;
  const retryAfter = (headers as Record<string, string>)["retry-after"];
  if (!retryAfter) return undefined;
  const seconds = Number(retryAfter);
  return Number.isFinite(seconds) ? seconds * 1000 : undefined;
}

/**
 * Retry wrapper for rate-limited (429) responses. Backs off exponentially
 * (honoring a `Retry-After` header when present), up to `retry.maxAttempts`
 * total attempts. Shared by every HTTP-backed provider.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  retry: Required<RetryOptions>,
  cancellationToken?: CancellationTokenLike,
  metricsSink: MetricsSink = NOOP_METRICS,
  providerFamily: ProviderFamily = "custom",
): Promise<T> {
  const { maxAttempts, baseDelayMs } = retry;
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    throwIfCancellationRequested(cancellationToken);
    try {
      return await fn();
    } catch (error) {
      const statusCode =
        typeof error === "object" && error !== null && "status" in error
          ? (error as { status: unknown }).status
          : undefined;
      if (statusCode !== 429 || attempt === maxAttempts) {
        throw error;
      }
      const retryAfterMs = parseRetryAfterMs(error) ?? baseDelayMs * 2 ** (attempt - 1);
      recordMetric(metricsSink, "kaji.provider.retries", 1, {
        provider_family: providerFamily,
      });
      lastError = error;
      await cancellableDelay(retryAfterMs, cancellationToken);
    }
  }
  throw lastError;
}

/** Retry only until a stream yields its first item; never replay partial output. */
export async function openStreamWithRetry<T>(
  create: () => AsyncIterable<T> | Promise<AsyncIterable<T>>,
  retry: Required<RetryOptions>,
  cancellationToken?: CancellationTokenLike,
  metricsSink: MetricsSink = NOOP_METRICS,
  providerFamily: ProviderFamily = "custom",
): Promise<AsyncIterableIterator<T>> {
  const opened = await withRetry(
    async () => {
      const stream = await create();
      const iterator = stream[Symbol.asyncIterator]();
      try {
        return { iterator, first: await iterator.next() };
      } catch (error) {
        try {
          await iterator.return?.();
        } catch {
          // Preserve the provider error that controls retryability.
        }
        throw error;
      }
    },
    retry,
    cancellationToken,
    metricsSink,
    providerFamily,
  );
  return new BufferedAsyncIterator(opened.iterator, opened.first);
}

/**
 * Iterator wrapper for the item consumed while opening a retryable stream.
 *
 * A native async generator does not enter its body when `return()` or
 * `throw()` is called before the first `next()`, so its `finally` block cannot
 * close the already-open provider iterator. This wrapper owns that lifecycle
 * explicitly.
 */
class BufferedAsyncIterator<T> implements AsyncIterableIterator<T> {
  private firstPending = true;
  private closed = false;
  private closePromise: Promise<void> | undefined;

  constructor(
    private readonly inner: AsyncIterator<T>,
    private readonly first: IteratorResult<T>,
  ) {}

  async next(): Promise<IteratorResult<T>> {
    if (this.closed) return { value: undefined, done: true };
    if (this.firstPending) {
      this.firstPending = false;
      if (this.first.done) this.markNaturallyClosed();
      return this.first;
    }
    try {
      const next = await this.inner.next();
      if (next.done) this.markNaturallyClosed();
      return next;
    } catch (error) {
      try {
        await this.close();
      } catch {
        // Preserve the provider failure that ended the stream.
      }
      throw error;
    }
  }

  async return(value?: unknown): Promise<IteratorResult<T>> {
    await this.close();
    return { value: value as T, done: true };
  }

  async throw(error?: unknown): Promise<IteratorResult<T>> {
    await this.close();
    throw error;
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<T> {
    return this;
  }

  private markNaturallyClosed(): void {
    this.closed = true;
    this.closePromise = Promise.resolve();
  }

  private close(): Promise<void> {
    if (this.closePromise !== undefined) return this.closePromise;
    this.closed = true;
    this.firstPending = false;
    try {
      const result = this.inner.return?.();
      this.closePromise = Promise.resolve(result).then(() => undefined);
    } catch (error) {
      this.closePromise = Promise.reject(error);
    }
    return this.closePromise;
  }
}

async function cancellableDelay(
  delayMs: number,
  cancellationToken?: CancellationTokenLike,
): Promise<void> {
  throwIfCancellationRequested(cancellationToken);
  if (cancellationToken === undefined) {
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
    return;
  }
  const signal = cancellationToken?.signal;
  if (signal === undefined) {
    const deadline = globalThis.performance.now() + delayMs;
    while (globalThis.performance.now() < deadline) {
      throwIfCancellationRequested(cancellationToken);
      await new Promise<void>((resolve) =>
        setTimeout(resolve, Math.min(10, deadline - globalThis.performance.now())),
      );
    }
    throwIfCancellationRequested(cancellationToken);
    return;
  }
  if (signal.aborted) throw new CancellationError();
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      reject(new CancellationError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}
