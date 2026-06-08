/**
 * Provider interface for LLM backends, mirroring
 * `agentkit.runtime.providers.base.ModelProvider`.
 *
 * Each provider translates the neutral message + tool format to its own API at
 * its boundary. The runtime never imports provider-specific types.
 */
import type { ToolSpec } from "../tools/registry";

/** A message in the conversation history passed to the provider. */
export interface ProviderMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool-result messages. */
  name?: string;
  /** Set only for tool-result messages: id from the originating tool call. */
  tool_call_id?: string;
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
}

/** A complete non-streaming response. */
export interface ModelResponse {
  content: string;
  toolCalls: ToolCall[];
}

/** Common interface every LLM provider implements. */
export interface ModelProvider {
  generate(messages: ProviderMessage[], tools: ToolSpec[]): Promise<ModelResponse>;
  generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk>;
}
