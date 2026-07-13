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
  RetryOptions,
  TokenUsage,
  ToolCall,
} from "@/providers/base";
import { getProviderResponseDiagnostics, openStreamWithRetry, withRetry } from "@/providers/base";
import {
  ProviderConfigError,
  ProviderError,
  ProviderOutputLimitError,
  providerAPIErrorFromUnknown,
} from "@/providers/errors";
import { parseToolArgsJSON } from "@/providers/args";
import { calculateCostUsd } from "@/providers/costs";
import {
  closeProviderStream,
  LinearStringParts,
  ProviderResponseBudget,
} from "@/providers/response-budget";
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
  /** Per-request timeout in milliseconds. Must be a positive finite integer. */
  requestTimeoutMs?: number;
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

function parseBoundedContentBlocks(
  blocks: AnthropicContentBlock[] | undefined | null,
  budget: ProviderResponseBudget,
): { content: string; toolCalls: ToolCall[] } {
  const content = new LinearStringParts();
  const toolCalls: ToolCall[] = [];
  for (const block of blocks ?? []) {
    if (block.type === "text") {
      const accepted = budget.acceptNormalized(block.text, []);
      content.append(accepted.delta);
    } else if (block.type === "tool_use") {
      const accepted = budget.acceptNormalized("", [
        {
          id: block.id,
          name: block.name,
          args: (block.input ?? {}) as Record<string, unknown>,
        },
      ]);
      toolCalls.push(...accepted.toolCalls);
    }
  }
  budget.finish();
  return { content: content.join(), toolCalls };
}

interface PendingAnthropicToolCall {
  readonly id: LinearStringParts;
  readonly name: LinearStringParts;
  readonly arguments: LinearStringParts;
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
  requestTimeoutMs: number | undefined;
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
    if (
      opts.requestTimeoutMs !== undefined &&
      (!Number.isFinite(opts.requestTimeoutMs) ||
        !Number.isInteger(opts.requestTimeoutMs) ||
        opts.requestTimeoutMs <= 0)
    ) {
      throw new RangeError("requestTimeoutMs must be a positive finite integer");
    }
    this.opts = {
      model: opts.model ?? "claude-sonnet-4-6",
      temperature: opts.temperature ?? 0.7,
      maxTokens: opts.maxTokens ?? 4096,
      requestTimeoutMs: opts.requestTimeoutMs,
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

  protected async createClient(): Promise<object> {
    const { default: AnthropicDefault } = await import("@anthropic-ai/sdk");
    return new AnthropicDefault({ apiKey: this.opts.apiKey, maxRetries: 0 });
  }

  private async getClient(): Promise<Anthropic> {
    if (this.client !== null) return this.client;
    try {
      this.client = (await this.createClient()) as Anthropic;
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderConfigError("Anthropic provider requires the @anthropic-ai/sdk package.", {
        service: "anthropic",
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

    const budget = new ProviderResponseBudget(options?.responseLimits);
    try {
      const response = await withRetry(
        () =>
          client.messages.create(params, {
            signal: options?.cancellationToken?.signal,
            ...(this.opts.requestTimeoutMs === undefined
              ? {}
              : { timeout: this.opts.requestTimeoutMs }),
          }),
        this.opts.retry,
        options?.cancellationToken,
        options?.metricsSink,
        "anthropic",
      );
      const { content, toolCalls } = parseBoundedContentBlocks(response.content, budget);
      const usage = response.usage
        ? { input: response.usage.input_tokens, output: response.usage.output_tokens }
        : undefined;
      const costUsd = usage
        ? calculateCostUsd(this.opts.model, usage.input, usage.output)
        : undefined;
      return { content, toolCalls, usage, costUsd };
    } catch (error) {
      if (error instanceof ProviderOutputLimitError) throw error;
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("anthropic", error, "request");
    } finally {
      getProviderResponseDiagnostics(options)?.record(budget.providerDiagnostics);
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
    const pendingTools = new Map<number, PendingAnthropicToolCall>();
    let latestUsage: TokenUsage | undefined;
    const budget = new ProviderResponseBudget(options?.responseLimits);
    let stream: AsyncIterableIterator<AnthropicStreamEvent> | undefined;

    try {
      stream = await openStreamWithRetry(
        () =>
          client.messages.stream(params, {
            signal: options?.cancellationToken?.signal,
            ...(this.opts.requestTimeoutMs === undefined
              ? {}
              : { timeout: this.opts.requestTimeoutMs }),
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
            budget.acceptRaw({
              toolFragments: [
                {
                  key: event.index,
                  startsCall: true,
                  idFragment: block.id,
                  nameFragment: block.name,
                },
              ],
            });
            const pending: PendingAnthropicToolCall = {
              id: new LinearStringParts(),
              name: new LinearStringParts(),
              arguments: new LinearStringParts(),
            };
            pending.id.append(block.id);
            pending.name.append(block.name);
            pendingTools.set(event.index, pending);
          }
        } else if (event.type === "content_block_delta") {
          const delta = event.delta;
          if (delta.type === "text_delta") {
            budget.acceptRaw({ text: delta.text });
            yield { delta: delta.text, toolCalls: [] };
          } else if (delta.type === "input_json_delta") {
            const pending = pendingTools.get(event.index);
            if (pending !== undefined) {
              const fragment = delta.partial_json ?? "";
              budget.acceptRaw({
                toolFragments: [{ key: event.index, argumentsFragment: fragment }],
              });
              pending.arguments.append(fragment);
            }
          }
        } else if (event.type === "content_block_stop") {
          const pending = pendingTools.get(event.index);
          if (pending !== undefined) {
            budget.finishRawTool(event.index);
            budget.recordToolArgumentJoin();
            yield {
              delta: "",
              toolCalls: [
                {
                  id: pending.id.join(),
                  name: pending.name.join(),
                  args: parseToolArgsJSON(pending.arguments.join(), "Anthropic"),
                },
              ],
            };
            pendingTools.delete(event.index);
          }
        }
      }
      budget.finish();
      if (latestUsage) {
        yield {
          delta: "",
          toolCalls: [],
          usage: latestUsage,
          costUsd: calculateCostUsd(this.opts.model, latestUsage.input, latestUsage.output),
        };
      }
    } catch (error) {
      if (error instanceof ProviderOutputLimitError) {
        await closeProviderStream(stream);
        throw error;
      }
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("anthropic", error, "stream");
    } finally {
      getProviderResponseDiagnostics(options)?.record(budget.providerDiagnostics);
    }
  }
}
