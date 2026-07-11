/**
 * Anthropic Messages API provider, mirroring
 * `kaji.runtime.providers.anthropic`.
 *
 * Translates the neutral ToolSpec list to Anthropic's `input_schema` format
 * and reassembles fragmented `input_json_delta` streaming events into complete
 * tool calls before yielding. Enable with
 * `registerProvider("anthropic", new AnthropicProvider(...))`.
 */
import type Anthropic from "@anthropic-ai/sdk";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  TokenUsage,
  ToolCall,
} from "@/providers/base";
import { openStreamWithRetry, withRetry } from "@/providers/base";
import type { RetryOptions } from "@/providers/openai";
import {
  ProviderConfigError,
  ProviderError,
  providerAPIErrorFromUnknown,
} from "@/providers/errors";
import { parseToolArgsJSON } from "@/providers/args";
import { calculateCostUsd } from "@/providers/costs";
import { throwIfCancellationRequested } from "@/runtime/cancellation";
import type { ToolSpec } from "@/tools/registry";

type AnthropicMessageParam = Anthropic.Messages.MessageParam;
type AnthropicTool = Anthropic.Messages.Tool;
type AnthropicContentBlock = Anthropic.Messages.ContentBlock;
type AnthropicStreamEvent = Anthropic.Messages.RawMessageStreamEvent;

export interface AnthropicProviderOptions {
  apiKey: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  /** Rate-limit retry configuration. */
  retry?: RetryOptions;
}

function toAnthropicTools(tools: ToolSpec[]): AnthropicTool[] {
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.parameters as AnthropicTool["input_schema"],
  }));
}

/** Split system messages out; Anthropic takes system as a top-level string. */
function splitMessages(messages: ProviderMessage[]): {
  system: string | undefined;
  messages: AnthropicMessageParam[];
} {
  const systemParts: string[] = [];
  const anthropicMessages: AnthropicMessageParam[] = [];

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
    } else if (m.role === "assistant" && m.toolCalls?.length) {
      anthropicMessages.push({
        role: "assistant",
        content: [
          ...(m.content ? [{ type: "text" as const, text: m.content }] : []),
          ...m.toolCalls.map((tc) => ({
            type: "tool_use" as const,
            id: tc.id,
            name: tc.name,
            input: tc.args ?? {},
          })),
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

function parseContentBlocks(blocks: AnthropicContentBlock[] | undefined | null): {
  content: string;
  toolCalls: ToolCall[];
} {
  let content = "";
  const toolCalls: ToolCall[] = [];
  for (const block of blocks ?? []) {
    if (block.type === "text") {
      content += block.text;
    } else if (block.type === "tool_use") {
      toolCalls.push({
        id: block.id,
        name: block.name,
        args: (block.input ?? {}) as Record<string, unknown>,
      });
    }
  }
  return { content, toolCalls };
}

function usageFromEvent(
  event: AnthropicStreamEvent,
  current: TokenUsage | undefined,
): TokenUsage | undefined {
  const rawUsage =
    "usage" in event
      ? (event as { usage?: { input_tokens?: number; output_tokens?: number } }).usage
      : undefined;
  if (!rawUsage) return current;
  return {
    input: rawUsage.input_tokens ?? current?.input ?? 0,
    output: rawUsage.output_tokens ?? current?.output ?? 0,
  };
}

interface ResolvedAnthropicOptions {
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
  retry: Required<RetryOptions>;
}

export class AnthropicProvider implements ModelProvider {
  readonly providerFamily = "anthropic" as const;
  private readonly opts: ResolvedAnthropicOptions;
  private client: Anthropic | null = null;

  constructor(opts: AnthropicProviderOptions) {
    if (!opts.apiKey?.trim()) {
      throw new ProviderConfigError("Anthropic API key is not configured.", {
        service: "anthropic",
      });
    }
    this.opts = {
      model: opts.model ?? "claude-sonnet-4-6",
      temperature: opts.temperature ?? 0.7,
      maxTokens: opts.maxTokens ?? 4096,
      apiKey: opts.apiKey,
      retry: {
        maxAttempts: opts.retry?.maxAttempts ?? 3,
        baseDelayMs: opts.retry?.baseDelayMs ?? 1000,
      },
    };
  }

  get model(): string {
    return this.opts.model;
  }

  protected async createClient(): Promise<Anthropic> {
    const { default: AnthropicDefault } = await import("@anthropic-ai/sdk");
    return new AnthropicDefault({ apiKey: this.opts.apiKey, maxRetries: 0 });
  }

  private async getClient(): Promise<Anthropic> {
    if (this.client !== null) return this.client;
    try {
      this.client = await this.createClient();
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
    throwIfCancellationRequested(options?.cancellationToken);
    const client = await this.getClient();
    const { system, messages: anthropicMessages } = splitMessages(messages);

    const params: Anthropic.Messages.MessageCreateParamsNonStreaming = {
      model: this.opts.model as string,
      messages: anthropicMessages,
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (system) params.system = system;
    if (tools.length > 0) params.tools = toAnthropicTools(tools);

    try {
      const response = await withRetry(
        () => client.messages.create(params, { signal: options?.cancellationToken?.signal }),
        this.opts.retry,
        options?.cancellationToken,
        options?.metricsSink,
        "anthropic",
      );
      const { content, toolCalls } = parseContentBlocks(response.content);
      const usage = response.usage
        ? { input: response.usage.input_tokens, output: response.usage.output_tokens }
        : undefined;
      const costUsd = usage
        ? calculateCostUsd(this.opts.model, usage.input, usage.output)
        : undefined;
      return { content, toolCalls, usage, costUsd };
    } catch (error) {
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("anthropic", error);
    }
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    throwIfCancellationRequested(options?.cancellationToken);
    const client = await this.getClient();
    const { system, messages: anthropicMessages } = splitMessages(messages);

    const params: Anthropic.Messages.MessageStreamParams = {
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
    let latestUsage: TokenUsage | undefined;

    try {
      const stream = await openStreamWithRetry(
        () =>
          client.messages.stream(params, {
            signal: options?.cancellationToken?.signal,
          }) as AsyncIterable<AnthropicStreamEvent>,
        this.opts.retry,
        options?.cancellationToken,
        options?.metricsSink,
        "anthropic",
      );

      for await (const event of stream) {
        latestUsage = usageFromEvent(event, latestUsage);
        if (event.type === "content_block_start") {
          const block = event.content_block;
          if (block.type === "tool_use") {
            pendingTool = { id: block.id, name: block.name, argsRaw: "" };
          }
        } else if (event.type === "content_block_delta") {
          const delta = event.delta;
          if (delta.type === "text_delta") {
            yield { delta: delta.text, toolCalls: [] };
          } else if (delta.type === "input_json_delta" && pendingTool !== null) {
            pendingTool.argsRaw += delta.partial_json ?? "";
          }
        } else if (event.type === "content_block_stop" && pendingTool !== null) {
          yield {
            delta: "",
            toolCalls: [
              {
                id: pendingTool.id,
                name: pendingTool.name,
                args: parseToolArgsJSON(pendingTool.argsRaw, "Anthropic"),
              },
            ],
          };
          pendingTool = null;
        }
      }
      if (latestUsage) {
        yield {
          delta: "",
          toolCalls: [],
          usage: latestUsage,
          costUsd: calculateCostUsd(this.opts.model, latestUsage.input, latestUsage.output),
        };
      }
    } catch (error) {
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("anthropic", error);
    }
  }
}
