/**
 * Mock LLM provider, mirroring `kaji.runtime.providers.mock`.
 *
 * Default behavior (no options): if tools are offered and no tool result is
 * yet in history, it calls the first tool with schema-satisfying placeholder
 * args; otherwise it returns a fixed text response.
 *
 * Options (`reply` and `toolCall` are mutually exclusive):
 *   `reply`     literal text returned by `generate` / yielded as one chunk by `generateStream`.
 *   `toolCall`  one canned tool call on the first turn; falls through to FINAL_TEXT
 *               once a tool-result message appears in history (so the loop terminates).
 *   `streamChunks` pre-baked deltas for streaming default-text scenarios.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "@/providers/base";
import { throwIfCancellationRequested } from "@/runtime/cancellation";
import type { ToolSpec } from "@/tools/registry";

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
  /** Pre-baked deltas yielded by `generateStream` instead of one chunk. */
  streamChunks?: readonly string[];
  /** Literal text the provider returns; mutually exclusive with `toolCall`. */
  reply?: string;
  /** Canned tool call returned on the first turn; mutually exclusive with `reply`. */
  toolCall?: { name: string; args: Record<string, unknown> };
}

export class MockProvider implements ModelProvider {
  private readonly streamChunks: readonly string[] | undefined;
  private readonly reply: string | undefined;
  private readonly toolCall: { name: string; args: Record<string, unknown> } | undefined;

  constructor(options: MockProviderOptions = {}) {
    if (options.reply !== undefined && options.toolCall !== undefined) {
      throw new Error("MockProvider: pass reply OR toolCall, not both.");
    }
    this.streamChunks = options.streamChunks;
    this.reply = options.reply;
    this.toolCall = options.toolCall;
  }

  private scriptedToolCall(): ToolCall {
    if (this.toolCall === undefined) {
      throw new Error("scriptedToolCall called without toolCall option");
    }
    return {
      id: "mock-call-1",
      name: this.toolCall.name,
      args: this.toolCall.args,
    };
  }

  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    throwIfCancellationRequested(options?.cancellationToken);
    if (this.toolCall !== undefined) {
      if (!hasToolResult(messages)) {
        return { content: "", toolCalls: [this.scriptedToolCall()] };
      }
      return { content: FINAL_TEXT, toolCalls: [] };
    }
    if (this.reply !== undefined) {
      return { content: this.reply, toolCalls: [] };
    }
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
    throwIfCancellationRequested(options?.cancellationToken);
    if (this.toolCall !== undefined) {
      if (!hasToolResult(messages)) {
        yield { delta: "", toolCalls: [this.scriptedToolCall()] };
        return;
      }
      yield { delta: FINAL_TEXT, toolCalls: [] };
      return;
    }
    if (this.reply !== undefined) {
      yield { delta: this.reply, toolCalls: [] };
      return;
    }
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
        throwIfCancellationRequested(options?.cancellationToken);
        yield { delta, toolCalls: [] };
      }
      return;
    }
    yield { delta: FINAL_TEXT, toolCalls: [] };
  }
}
