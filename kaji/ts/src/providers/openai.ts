/**
 * OpenAI chat-completions provider, mirroring
 * `kaji.runtime.providers.openai`.
 *
 * Translates the neutral ToolSpec list to OpenAI's function-tool format at its
 * boundary. Enable with `registerProvider("openai", new OpenAIProvider(...))`.
 *
 * The openai package is a peer/optional dep — it is imported lazily so the SDK
 * tree-shakes it out when unused.
 */
import type OpenAI from "openai";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "@/providers/base";
import { openStreamWithRetry, withRetry } from "@/providers/base";
import {
  ProviderConfigError,
  ProviderError,
  providerAPIErrorFromUnknown,
} from "@/providers/errors";
import { parseToolArgsJSON } from "@/providers/args";
import { calculateCostUsd } from "@/providers/costs";
import { toOpenAIChatMessages } from "@/providers/openai-format";
import { throwIfCancellationRequested } from "@/runtime/cancellation";
import type { ToolSpec } from "@/tools/registry";

type ChatTool = OpenAI.Chat.Completions.ChatCompletionTool;
type ChatToolCall = OpenAI.Chat.Completions.ChatCompletionMessageToolCall;

export interface RetryOptions {
  /** Maximum retry attempts on 429 rate-limit responses. Defaults to 3. */
  maxAttempts?: number;
  /** Base delay in ms before first retry. Doubles each attempt. Defaults to 1000. */
  baseDelayMs?: number;
}

export interface OpenAIProviderOptions {
  apiKey: string;
  model?: string;
  baseURL?: string;
  temperature?: number;
  maxTokens?: number;
  /** Extra HTTP headers to send with every request. Used by OpenAI-compatible
   * gateways (OpenRouter, Together, Groq) to attach attribution or routing
   * metadata. Ignored when the value is empty. */
  defaultHeaders?: Record<string, string>;
  /** Rate-limit retry configuration. */
  retry?: RetryOptions;
}

function toOpenAITools(tools: ToolSpec[]): ChatTool[] {
  return tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    },
  }));
}

function parseToolCalls(raw: ChatToolCall[] | undefined | null): ToolCall[] {
  return (raw ?? []).map((tc) => {
    if (tc.type !== "function") {
      return { id: tc.id ?? "", name: "", args: {} };
    }
    const argsRaw = tc.function?.arguments;
    return {
      id: tc.id ?? "",
      name: tc.function?.name ?? "",
      // The OpenAI SDK types arguments as `string`; treat non-strings as
      // already-parsed for forward-compat with mocked SDK shapes.
      args:
        typeof argsRaw === "string"
          ? parseToolArgsJSON(argsRaw, "OpenAI")
          : ((argsRaw ?? {}) as Record<string, unknown>),
    };
  });
}

interface ResolvedOpenAIOptions {
  apiKey: string;
  model: string;
  baseURL: string;
  temperature: number;
  maxTokens: number;
  defaultHeaders: Record<string, string> | undefined;
  retry: Required<RetryOptions>;
}

export class OpenAIProvider implements ModelProvider {
  readonly providerFamily = "openai" as const;
  private readonly opts: ResolvedOpenAIOptions;
  private client: OpenAI | null = null;

  constructor(opts: OpenAIProviderOptions) {
    if (!opts.apiKey?.trim()) {
      throw new ProviderConfigError("OpenAI API key is not configured.", { service: "openai" });
    }
    this.opts = {
      apiKey: opts.apiKey,
      model: opts.model ?? "gpt-5.4-mini",
      baseURL: opts.baseURL ?? "",
      temperature: opts.temperature ?? 0.7,
      maxTokens: opts.maxTokens ?? 4096,
      defaultHeaders:
        opts.defaultHeaders && Object.keys(opts.defaultHeaders).length > 0
          ? opts.defaultHeaders
          : undefined,
      retry: {
        maxAttempts: opts.retry?.maxAttempts ?? 3,
        baseDelayMs: opts.retry?.baseDelayMs ?? 1000,
      },
    };
  }

  /** Expose the model name for downstream cost calculation. */
  get model(): string {
    return this.opts.model;
  }

  protected async createClient(): Promise<OpenAI> {
    const { default: OpenAIDefault } = await import("openai");
    return new OpenAIDefault({
      apiKey: this.opts.apiKey,
      maxRetries: 0,
      ...(this.opts.baseURL ? { baseURL: this.opts.baseURL } : {}),
      ...(this.opts.defaultHeaders ? { defaultHeaders: this.opts.defaultHeaders } : {}),
    });
  }

  private async getClient(): Promise<OpenAI> {
    if (this.client !== null) return this.client;
    // Dynamic import so the package is optional at bundle time.
    try {
      this.client = await this.createClient();
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderConfigError("OpenAI provider requires the openai package.", {
        service: "openai",
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
    const params: OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming = {
      model: this.opts.model,
      messages: toOpenAIChatMessages(messages),
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (tools.length > 0) params.tools = toOpenAITools(tools);

    try {
      const response = await withRetry(
        () =>
          client.chat.completions.create(params, { signal: options?.cancellationToken?.signal }),
        this.opts.retry,
        options?.cancellationToken,
        options?.metricsSink,
        "openai",
      );
      const choice = response.choices[0];
      if (!choice) {
        return { content: "", toolCalls: [], usage: undefined };
      }
      const message = choice.message;
      const usage = response.usage
        ? { input: response.usage.prompt_tokens, output: response.usage.completion_tokens }
        : undefined;
      const costUsd = usage
        ? calculateCostUsd(this.opts.model, usage.input, usage.output)
        : undefined;
      return {
        content: message.content ?? "",
        toolCalls: parseToolCalls(message.tool_calls),
        usage,
        costUsd,
      };
    } catch (error) {
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("openai", error, "request");
    }
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    throwIfCancellationRequested(options?.cancellationToken);
    const client = await this.getClient();
    const params: OpenAI.Chat.Completions.ChatCompletionCreateParamsStreaming = {
      model: this.opts.model,
      messages: toOpenAIChatMessages(messages),
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
      stream: true,
      stream_options: { include_usage: true },
    };
    if (tools.length > 0) params.tools = toOpenAITools(tools);

    try {
      const stream = await openStreamWithRetry(
        () =>
          client.chat.completions.create(params, {
            signal: options?.cancellationToken?.signal,
          }),
        this.opts.retry,
        options?.cancellationToken,
        options?.metricsSink,
        "openai",
      );

      // Accumulate partial tool call args across chunks.
      const pendingCalls: Map<number, { id: string; name: string; argsRaw: string }> = new Map();

      for await (const chunk of stream) {
        const usage = chunk.usage
          ? { input: chunk.usage.prompt_tokens, output: chunk.usage.completion_tokens }
          : undefined;
        if (usage) {
          yield {
            delta: "",
            toolCalls: [],
            usage,
            costUsd: calculateCostUsd(this.opts.model, usage.input, usage.output),
          };
          continue;
        }

        const delta = chunk.choices[0]?.delta;
        if (!delta) continue;

        const text = delta.content ?? "";
        const incomingCalls: ToolCall[] = [];

        for (const tc of delta.tool_calls ?? []) {
          const idx: number = tc.index ?? 0;
          if (!pendingCalls.has(idx)) {
            pendingCalls.set(idx, { id: tc.id ?? "", name: tc.function?.name ?? "", argsRaw: "" });
          }
          const entry = pendingCalls.get(idx)!;
          entry.argsRaw += tc.function?.arguments ?? "";
          if (tc.id) entry.id = tc.id;
          if (tc.function?.name) entry.name = tc.function.name;
        }

        // Flush completed tool calls when a finish_reason is present.
        if (chunk.choices[0]?.finish_reason === "tool_calls") {
          for (const entry of pendingCalls.values()) {
            incomingCalls.push({
              id: entry.id,
              name: entry.name,
              args: parseToolArgsJSON(entry.argsRaw, "OpenAI"),
            });
          }
          pendingCalls.clear();
        }

        if (text || incomingCalls.length > 0) {
          yield { delta: text, toolCalls: incomingCalls };
        }
      }
    } catch (error) {
      throwIfCancellationRequested(options?.cancellationToken);
      throw providerAPIErrorFromUnknown("openai", error, "stream");
    }
  }
}
