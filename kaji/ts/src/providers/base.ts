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
import type { RetryOptions } from "@/providers/openai";
import type { ToolSpec } from "@/tools/registry";

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
}

/** Common interface every LLM provider implements. */
export interface ModelProvider {
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
      lastError = error;
      await cancellableDelay(retryAfterMs, cancellationToken);
    }
  }
  throw lastError;
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
