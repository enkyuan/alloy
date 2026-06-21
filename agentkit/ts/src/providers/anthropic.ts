/**
 * Anthropic Messages API provider, mirroring
 * `agentkit.runtime.providers.anthropic`.
 *
 * Translates the neutral ToolSpec list to Anthropic's `input_schema` format
 * and reassembles fragmented `input_json_delta` streaming events into complete
 * tool calls before yielding. Enable with
 * `registerProvider("anthropic", new AnthropicProvider(...))`.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "./base";
import { ProviderConfigError, ProviderError, providerAPIErrorFromUnknown } from "./errors";
import type { ToolSpec } from "../tools/registry";

export interface AnthropicProviderOptions {
  apiKey: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
}

function toAnthropicTools(tools: ToolSpec[]) {
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.parameters,
  }));
}

/** Split system messages out; Anthropic takes system as a top-level string. */
function splitMessages(messages: ProviderMessage[]): {
  system: string | undefined;
  messages: any[];
} {
  const systemParts: string[] = [];
  const anthropicMessages: any[] = [];

  for (const m of messages) {
    if (m.role === "system") {
      systemParts.push(m.content);
    } else if (m.role === "tool") {
      // Anthropic tool results use content blocks inside a user turn.
      anthropicMessages.push({
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: m.tool_call_id ?? "",
            content: m.content,
          },
        ],
      });
    } else {
      anthropicMessages.push({ role: m.role, content: m.content });
    }
  }

  return {
    system: systemParts.length > 0 ? systemParts.join("\n\n") : undefined,
    messages: anthropicMessages,
  };
}

function parseContentBlocks(blocks: any[]): { content: string; toolCalls: ToolCall[] } {
  let content = "";
  const toolCalls: ToolCall[] = [];
  for (const block of blocks ?? []) {
    if (block.type === "text") content += block.text ?? "";
    else if (block.type === "tool_use") {
      toolCalls.push({
        id: block.id ?? "",
        name: block.name ?? "",
        args: block.input ?? {},
      });
    }
  }
  return { content, toolCalls };
}

export class AnthropicProvider implements ModelProvider {
  private readonly opts: Required<AnthropicProviderOptions>;
  private client: any = null;

  constructor(opts: AnthropicProviderOptions) {
    if (!opts.apiKey?.trim()) {
      throw new ProviderConfigError("Anthropic API key is not configured.", {
        service: "anthropic",
      });
    }
    this.opts = {
      model: "claude-sonnet-4-6",
      temperature: 0.7,
      maxTokens: 4096,
      ...opts,
    };
  }

  private async getClient(): Promise<any> {
    if (this.client !== null) return this.client;
    try {
      const { default: Anthropic } = await import("@anthropic-ai/sdk");
      this.client = new Anthropic({ apiKey: this.opts.apiKey });
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderConfigError("Anthropic provider requires the @anthropic-ai/sdk package.", {
        service: "anthropic",
        cause: error,
      });
    }
    return this.client;
  }

  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const client = await this.getClient();
    const { system, messages: anthropicMessages } = splitMessages(messages);

    const params: any = {
      model: this.opts.model,
      messages: anthropicMessages,
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (system) params.system = system;
    if (tools.length > 0) params.tools = toAnthropicTools(tools);

    try {
      const response = await client.messages.create(params);
      return parseContentBlocks(response.content);
    } catch (error) {
      throw providerAPIErrorFromUnknown("anthropic", error);
    }
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const client = await this.getClient();
    const { system, messages: anthropicMessages } = splitMessages(messages);

    const params: any = {
      model: this.opts.model,
      messages: anthropicMessages,
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (system) params.system = system;
    if (tools.length > 0) params.tools = toAnthropicTools(tools);

    // Anthropic streams tool_use blocks as fragmented input_json_delta events
    // that must be accumulated before the args are parseable.
    let pendingTool: { id: string; name: string; argsRaw: string } | null = null;

    try {
      const stream = client.messages.stream(params);

      for await (const event of stream) {
        const type: string = (event as any).type;

        if (type === "content_block_start") {
          const block = (event as any).content_block;
          if (block?.type === "tool_use") {
            pendingTool = { id: block.id ?? "", name: block.name ?? "", argsRaw: "" };
          }
        } else if (type === "content_block_delta") {
          const delta = (event as any).delta;
          if (delta?.type === "text_delta") {
            yield { delta: delta.text ?? "", toolCalls: [] };
          } else if (delta?.type === "input_json_delta" && pendingTool !== null) {
            pendingTool.argsRaw += delta.partial_json ?? "";
          }
        } else if (type === "content_block_stop" && pendingTool !== null) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(pendingTool.argsRaw);
          } catch {
            /* leave empty */
          }
          yield {
            delta: "",
            toolCalls: [{ id: pendingTool.id, name: pendingTool.name, args }],
          };
          pendingTool = null;
        }
      }
    } catch (error) {
      throw providerAPIErrorFromUnknown("anthropic", error);
    }
  }
}
