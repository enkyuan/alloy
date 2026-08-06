/**
 * One-shot helpers: call a provider without spinning up the full
 * event-sourced runtime. Use when you just want one model response.
 *
 *   const { text } = await generateText({
 *     provider: openai("gpt-5.4-mini"),
 *     messages: [{ role: "user", content: "Hello" }],
 *   });
 *
 * For tool-using ReAct loops, durable replay, batched tools, or policy
 * gating, build an `AgentRuntime`/`AgentBuilder` instead.
 */
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ProviderMessage,
} from "@/providers/base";
import type { ToolSpec } from "@/tools/registry";

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
   * Each of `textStream`, `text`, and `toolCalls` is independently
   * consumable; awaiting any one of them does not require iterating
   * any of the others. All three reject if the source stream errors.
   */
  textStream: AsyncIterable<string>;
  /** Resolves to the concatenated text once the source stream finishes. */
  text: Promise<string>;
  /** Resolves to the tool calls the model emitted, if any. */
  toolCalls: Promise<ModelResponse["toolCalls"]>;
}

/**
 * Stream a single provider call. All three result handles
 * (`textStream`, `text`, `toolCalls`) are independent: the source stream
 * is drained eagerly in the background so awaiting any one of them is
 * sufficient. All three reject if the source errors.
 *
 *   const { textStream, text } = streamText({ provider: openai("gpt-5.4-mini"), messages });
 *   for await (const chunk of textStream) process.stdout.write(chunk);
 *   console.log("\nfinal:", await text);
 *
 * For a non-streaming one-shot, use `generateText`.
 */
export function streamText(options: GenerateTextOptions): StreamTextResult {
  const { provider, messages, tools, ...providerOptions } = options;
  const source = provider.generateStream(messages, tools ?? [], providerOptions);

  let resolveText!: (s: string) => void;
  let rejectText!: (err: unknown) => void;
  let resolveCalls!: (c: ModelResponse["toolCalls"]) => void;
  let rejectCalls!: (err: unknown) => void;
  const text = new Promise<string>((res, rej) => {
    resolveText = res;
    rejectText = rej;
  });
  const toolCalls = new Promise<ModelResponse["toolCalls"]>((res, rej) => {
    resolveCalls = res;
    rejectCalls = rej;
  });

  // Single source of truth: drain appends every delta to `collected` and
  // resolves the current `advance` promise (if any) so awaiting iterators
  // wake up. Iterators read from `collected[cursor]`; they do NOT consume
  // it, so multiple iterators can each replay independently.
  const collected: string[] = [];
  const calls: ModelResponse["toolCalls"] = [];
  let drained = false;
  let drainError: unknown = null;
  let advance: Promise<void> = new Promise(() => {});
  let signalAdvance: () => void = () => {};
  const renewAdvance = () => {
    advance = new Promise<void>((res) => {
      signalAdvance = res;
    });
  };
  renewAdvance();

  async function drain(): Promise<void> {
    try {
      for await (const chunk of source) {
        if (chunk.delta) {
          collected.push(chunk.delta);
          const signal = signalAdvance;
          renewAdvance();
          signal();
        }
        if (chunk.toolCalls?.length) {
          calls.push(...chunk.toolCalls);
        }
      }
      drained = true;
      resolveText(collected.join(""));
      resolveCalls(calls);
      signalAdvance();
    } catch (err) {
      drained = true;
      drainError = err;
      rejectText(err);
      rejectCalls(err);
      signalAdvance();
    }
  }

  // Start draining immediately. Attach noop catches so awaiting only one
  // of `text` / `toolCalls` (or none, in the iterate-only case) does NOT
  // trigger Node's unhandled-rejection warning. Rejections are still
  // delivered to whichever handles the caller awaits.
  void drain();
  text.catch(() => {});
  toolCalls.catch(() => {});

  const textStream: AsyncIterable<string> = {
    [Symbol.asyncIterator](): AsyncIterator<string> {
      let cursor = 0;
      return {
        async next(): Promise<IteratorResult<string>> {
          while (cursor >= collected.length && !drained) {
            await advance;
          }
          if (cursor < collected.length) {
            const value = collected[cursor++] as string;
            return { value, done: false };
          }
          if (drainError) throw drainError;
          return { value: undefined as unknown as string, done: true };
        },
      };
    },
  };

  return { textStream, text, toolCalls };
}
