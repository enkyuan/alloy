/**
 * Function-style provider factories.
 *
 * Convenience wrappers so callers can write `openai("gpt-4o")` instead of
 * `new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY!, model: "gpt-4o" })`.
 * Reads the conventional environment variable when no apiKey is given.
 *
 *   import { openai, anthropic, generateText } from "@agentkit/sdk";
 *   const { text } = await generateText({
 *     provider: openai("gpt-4o"),
 *     messages: [{ role: "user", content: "Hello" }],
 *   });
 */
import { OpenAIProvider, type OpenAIProviderOptions } from "./openai";
import { AnthropicProvider, type AnthropicProviderOptions } from "./anthropic";

type ModelOrOptions<TOpts> = string | (Omit<TOpts, "apiKey"> & { apiKey?: string });

function resolveOptions<TOpts extends { apiKey: string; model?: string }>(
  envVar: string,
  defaults: Partial<TOpts>,
  arg: ModelOrOptions<TOpts> | undefined,
): TOpts {
  const apiKey = process.env[envVar] ?? "";
  if (typeof arg === "string") {
    return { ...defaults, apiKey, model: arg } as TOpts;
  }
  return { ...defaults, apiKey, ...arg } as TOpts;
}

/** Create an OpenAI provider. Reads `OPENAI_API_KEY` from the environment when no `apiKey` is passed. */
export function openai(arg?: ModelOrOptions<OpenAIProviderOptions>): OpenAIProvider {
  return new OpenAIProvider(resolveOptions<OpenAIProviderOptions>("OPENAI_API_KEY", {}, arg));
}

/** Create an Anthropic provider. Reads `ANTHROPIC_API_KEY` from the environment when no `apiKey` is passed. */
export function anthropic(arg?: ModelOrOptions<AnthropicProviderOptions>): AnthropicProvider {
  return new AnthropicProvider(
    resolveOptions<AnthropicProviderOptions>("ANTHROPIC_API_KEY", {}, arg),
  );
}
