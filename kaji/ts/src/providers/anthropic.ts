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
  ToolCall,
} from "./base";
import { ProviderConfigError, ProviderError, providerAPIErrorFromUnknown } from "./errors";
import { parseToolArgsJSON } from "./_args";
import { calculateCostUsd } from "./_cost_table";
import type { RetryOptions } from "./openai";
import type { ToolSpec } from "../tools/registry";

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

interface ResolvedAnthropicOptions {
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
  retry: Required<RetryOptions>;
}

export class AnthropicProvider implements ModelProvider {
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

  private async withRetry<T>(fn: () => Promise<T>): Promise<T> {
    const { maxAttempts, baseDelayMs } = this.opts.retry;
    let lastError: unknown;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
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
        const retryAfterMs = this.parseRetryAfterMs(error) ?? baseDelayMs * 2 ** (attempt - 1);
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, retryAfterMs));
      }
    }
    throw lastError;
  }

  private parseRetryAfterMs(error: unknown): number | undefined {
    if (typeof error !== "object" || error === null) return undefined;
    const headers = "headers" in error ? (error as { headers: unknown }).headers : null;
    if (typeof headers !== "object" || headers === null) return undefined;
    const retryAfter = (headers as Record<string, string>)["retry-after"];
    if (!retryAfter) return undefined;
    const seconds = Number(retryAfter);
    return Number.isFinite(seconds) ? seconds * 1000 : undefined;
  }

  private async getClient(): Promise<Anthropic> {
    if (this.client !== null) return this.client;
    try {
      const { default: AnthropicDefault } = await import("@anthropic-ai/sdk");
      this.client = new AnthropicDefault({ apiKey: this.opts.apiKey });
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

    const params: Anthropic.Messages.MessageCreateParamsNonStreaming = {
      model: this.opts.model as string,
      messages: anthropicMessages,
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (system) params.system = system;
    if (tools.length > 0) params.tools = toAnthropicTools(tools);

    try {
      const response = await this.withRetry(() =>
        client.messages.create(params, { signal: options?.cancellationToken?.signal }),
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

    try {
      const stream = client.messages.stream(params, {
        signal: options?.cancellationToken?.signal,
      });

      for await (const event of stream as AsyncIterable<AnthropicStreamEvent>) {
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
    } catch (error) {
      throw providerAPIErrorFromUnknown("anthropic", error);
    }
  }
}
