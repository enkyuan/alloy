/**
 * Provider interface for LLM backends, mirroring
 * `kaji.runtime.providers.base.ModelProvider`.
 *
 * Each provider translates the neutral message + tool format to its own API at
 * its boundary. The runtime never imports provider-specific types.
 */
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
  cancellationToken?: { isCancelled: boolean; signal?: AbortSignal };
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
