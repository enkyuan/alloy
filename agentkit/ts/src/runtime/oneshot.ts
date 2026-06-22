/**
 * One-shot helpers: call a provider without spinning up the full
 * event-sourced runtime. Use when you just want one model response.
 *
 *   const { text } = await generateText({
 *     provider: openai("gpt-4o"),
 *     messages: [{ role: "user", content: "Hello" }],
 *   });
 *
 * For tool-using ReAct loops, durable replay, scatter-gather, or policy
 * gating, build an `AgentRuntime`/`AgentBuilder` instead.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ProviderMessage,
} from "../providers/base";
import type { ToolSpec } from "../tools/registry";

export interface GenerateTextOptions extends ModelProviderOptions {
  provider: ModelProvider;
  messages: ProviderMessage[];
  /** Optional tool specs to surface to the model. */
  tools?: ToolSpec[];
}

/**
 * Single-call wrapper around `provider.generate`. Returns the full text and
 * any tool calls the model produced. Does not execute tool calls; the caller
 * decides what to do with them.
 */
export async function generateText(options: GenerateTextOptions): Promise<ModelResponse> {
  const { provider, messages, tools, ...providerOptions } = options;
  return provider.generate(messages, tools ?? [], providerOptions);
}

export interface StreamTextResult {
  /**
   * Async-iterable of text deltas as they arrive from the provider.
   *
   * IMPORTANT: this stream drives the rest of the result. The `text` and
   * `toolCalls` promises only resolve after `textStream` has been iterated
   * to completion. If you `await` `text` without iterating `textStream`
   * first (or alongside, via two parallel consumers), it will hang forever.
   *
   * To skip streaming entirely and just collect the full response, use
   * `generateText` instead.
   */
  textStream: AsyncIterable<string>;
  /**
   * Resolves to the concatenated text once `textStream` finishes.
   *
   * Hangs if `textStream` is never iterated. See the note on `textStream`.
   */
  text: Promise<string>;
  /**
   * Resolves to the tool calls the model emitted, if any.
   *
   * Hangs if `textStream` is never iterated. See the note on `textStream`.
   */
  toolCalls: Promise<ModelResponse["toolCalls"]>;
}

/**
 * Stream a single provider call. Iterate `textStream` for tokens; the
 * `text` and `toolCalls` promises resolve only after that iteration
 * completes - awaiting them without iterating `textStream` hangs.
 *
 *   const { textStream, text } = streamText({ provider: openai("gpt-4o"), messages });
 *   for await (const chunk of textStream) process.stdout.write(chunk);
 *   console.log("\nfinal:", await text);
 *
 * For a non-streaming one-shot, use `generateText`.
 */
export function streamText(options: GenerateTextOptions): StreamTextResult {
  const { provider, messages, tools, ...providerOptions } = options;
  const source = provider.generateStream(messages, tools ?? [], providerOptions);

  let resolveText: (s: string) => void;
  let resolveCalls: (c: ModelResponse["toolCalls"]) => void;
  let rejectAll: (err: unknown) => void;
  const text = new Promise<string>((res, rej) => {
    resolveText = res;
    rejectAll = rej;
  });
  const toolCalls = new Promise<ModelResponse["toolCalls"]>((res) => {
    resolveCalls = res;
  });

  async function* textStream(): AsyncGenerator<string> {
    const collected: string[] = [];
    const calls: ModelResponse["toolCalls"] = [];
    try {
      for await (const chunk of source) {
        if (chunk.delta) {
          collected.push(chunk.delta);
          yield chunk.delta;
        }
        if (chunk.toolCalls?.length) {
          calls.push(...chunk.toolCalls);
        }
      }
      resolveText(collected.join(""));
      resolveCalls(calls);
    } catch (err) {
      rejectAll(err);
      resolveCalls(calls);
      throw err;
    }
  }

  return { textStream: textStream(), text, toolCalls };
}
