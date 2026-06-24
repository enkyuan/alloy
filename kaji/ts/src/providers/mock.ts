/**
 * Mock LLM provider, mirroring `kaji.runtime.providers.mock`.
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

/** Optional configuration for `MockProvider` to drive specific test scenarios. */
export interface MockProviderOptions {
  /**
   * Pre-baked deltas to yield from `generateStream` instead of emitting the
   * whole final text as a single chunk. Useful for testing consumers that
   * react to partial output (token-by-token UIs, cancellation mid-stream).
   * The deltas are concatenated to form the final text on the non-streaming
   * `generate` path as well.
   */
  streamChunks?: readonly string[];
}

export class MockProvider implements ModelProvider {
  private readonly streamChunks: readonly string[] | undefined;

  constructor(options: MockProviderOptions = {}) {
    this.streamChunks = options.streamChunks;
  }

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
    const content = this.streamChunks ? this.streamChunks.join("") : FINAL_TEXT;
    return { content, toolCalls: [] };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const first = tools[0];
    if (first !== undefined && !hasToolResult(messages)) {
      yield {
        delta: "",
        toolCalls: [{ id: "mock-call-1", name: first.name, args: placeholderArgs(first) }],
      };
      return;
    }
    if (this.streamChunks && this.streamChunks.length > 0) {
      for (const delta of this.streamChunks) {
        if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
        yield { delta, toolCalls: [] };
      }
      return;
    }
    yield { delta: FINAL_TEXT, toolCalls: [] };
  }
}
