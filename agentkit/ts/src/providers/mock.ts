/**
 * Mock LLM provider, mirroring `agentkit.runtime.providers.mock`.
 *
 * If tools are offered and no tool result is yet in history, it calls the first
 * tool with empty args; otherwise it returns a fixed text response. This drives
 * the full tool loop without a network call.
 */
import type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "./base";
import type { ToolSpec } from "../tools/registry";

const FINAL_TEXT = "The mock provider has completed the tool loop.";

function hasToolResult(messages: ProviderMessage[]): boolean {
  return messages.some((m) => m.role === "tool");
}

export class MockProvider implements ModelProvider {
  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): Promise<ModelResponse> {
    const first = tools[0];
    if (first !== undefined && !hasToolResult(messages)) {
      return {
        content: "",
        toolCalls: [{ id: "mock-call-1", name: first.name, args: {} }],
      };
    }
    return { content: FINAL_TEXT, toolCalls: [] };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk> {
    const result = await this.generate(messages, tools);
    yield { delta: result.content, toolCalls: result.toolCalls };
  }
}
