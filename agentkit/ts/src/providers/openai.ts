/**
 * OpenAI chat-completions provider, mirroring
 * `agentkit.runtime.providers.openai`.
 *
 * Translates the neutral ToolSpec list to OpenAI's function-tool format at its
 * boundary. Enable with `registerProvider("openai", new OpenAIProvider(...))`.
 *
 * The openai package is a peer/optional dep — it is imported lazily so the SDK
 * tree-shakes it out when unused.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "./base";
import type { ToolSpec } from "../tools/registry";

export interface OpenAIProviderOptions {
  apiKey: string;
  model?: string;
  baseURL?: string;
  temperature?: number;
  maxTokens?: number;
}

function toOpenAITools(tools: ToolSpec[]) {
  return tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    },
  }));
}

function parseToolCalls(raw: unknown[]): ToolCall[] {
  return (raw ?? []).map((tc: any) => {
    let args: Record<string, unknown> = {};
    try {
      args =
        typeof tc.function?.arguments === "string"
          ? JSON.parse(tc.function.arguments)
          : (tc.function?.arguments ?? {});
    } catch {
      args = {};
    }
    return { id: tc.id ?? "", name: tc.function?.name ?? "", args };
  });
}

export class OpenAIProvider implements ModelProvider {
  private readonly opts: Required<OpenAIProviderOptions>;
  private client: any = null;

  constructor(opts: OpenAIProviderOptions) {
    this.opts = {
      model: "gpt-4o",
      baseURL: "",
      temperature: 0.7,
      maxTokens: 4096,
      ...opts,
    };
  }

  private async getClient(): Promise<any> {
    if (this.client !== null) return this.client;
    // Dynamic import so the package is optional at bundle time.
    const { default: OpenAI } = await import("openai");
    this.client = new OpenAI({
      apiKey: this.opts.apiKey,
      ...(this.opts.baseURL ? { baseURL: this.opts.baseURL } : {}),
    });
    return this.client;
  }

  private buildMessages(messages: ProviderMessage[]): any[] {
    return messages.map((m) => {
      if (m.role === "tool") {
        return {
          role: "tool" as const,
          content: m.content,
          tool_call_id: m.tool_call_id ?? "",
        };
      }
      return { role: m.role, content: m.content };
    });
  }

  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const client = await this.getClient();
    const params: any = {
      model: this.opts.model,
      messages: this.buildMessages(messages),
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
    };
    if (tools.length > 0) params.tools = toOpenAITools(tools);

    const response = await client.chat.completions.create(params);
    const choice = response.choices[0];
    const message = choice.message;
    return {
      content: message.content ?? "",
      toolCalls: parseToolCalls(message.tool_calls ?? []),
    };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    if (options?.cancellationToken?.isCancelled) throw new Error("Cancelled");
    const client = await this.getClient();
    const params: any = {
      model: this.opts.model,
      messages: this.buildMessages(messages),
      temperature: options?.temperature ?? this.opts.temperature,
      max_tokens: options?.maxTokens ?? this.opts.maxTokens,
      stream: true,
    };
    if (tools.length > 0) params.tools = toOpenAITools(tools);

    const stream = await client.chat.completions.create(params);

    // Accumulate partial tool call args across chunks.
    const pendingCalls: Map<number, { id: string; name: string; argsRaw: string }> = new Map();

    for await (const chunk of stream) {
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
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(entry.argsRaw);
          } catch {
            /* leave empty */
          }
          incomingCalls.push({ id: entry.id, name: entry.name, args });
        }
        pendingCalls.clear();
      }

      if (text || incomingCalls.length > 0) {
        yield { delta: text, toolCalls: incomingCalls };
      }
    }
  }
}
