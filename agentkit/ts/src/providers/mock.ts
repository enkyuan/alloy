/**
 * Mock LLM provider, mirroring `agentkit.runtime.providers.mock`.
 *
 * If tools are offered and no tool result is yet in history, it calls the first
 * tool with schema-satisfying placeholder args; otherwise it returns a fixed
 * text response. This drives the full tool loop without a network call.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "./base";
import type { ToolSpec } from "../tools/registry";

const FINAL_TEXT = "The mock provider has completed the tool loop.";

const JSON_TYPE_PLACEHOLDERS: Record<string, unknown> = {
  string: "mock",
  integer: 0,
  number: 0,
  boolean: false,
  array: [],
  object: {},
  null: null,
};

function hasToolResult(messages: ProviderMessage[]): boolean {
  return messages.some((m) => m.role === "tool");
}

function placeholderArgs(spec: ToolSpec): Record<string, unknown> {
  const params = (spec.parameters ?? {}) as Record<string, unknown>;
  const props = (params.properties as Record<string, { type?: string }>) ?? {};
  const required = (params.required as string[]) ?? [];
  const args: Record<string, unknown> = {};
  for (const key of required) {
    const type = props[key]?.type ?? "string";
    args[key] = JSON_TYPE_PLACEHOLDERS[type] ?? "mock";
  }
  return args;
}

export class MockProvider implements ModelProvider {
  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const first = tools[0];
    if (first !== undefined && !hasToolResult(messages)) {
      return {
        content: "",
        toolCalls: [{ id: "mock-call-1", name: first.name, args: placeholderArgs(first) }],
      };
    }
    return { content: FINAL_TEXT, toolCalls: [] };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    const result = await this.generate(messages, tools, options);
    yield { delta: result.content, toolCalls: result.toolCalls };
  }
}
