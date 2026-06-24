/**
 * Function-style provider factories.
 *
 * Convenience wrappers so callers can write `openai("gpt-4o")` instead of
 * `new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY!, model: "gpt-4o" })`.
 * Reads the conventional environment variable when no apiKey is given.
 *
 *   import { openai, anthropic, generateText } from "@kaji/sdk";
 *   const { text } = await generateText({
 *     provider: openai("gpt-4o"),
 *     messages: [{ role: "user", content: "Hello" }],
 *   });
 */
import { OpenAIProvider, type OpenAIProviderOptions } from "./openai";
import { AnthropicProvider, type AnthropicProviderOptions } from "./anthropic";

const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";
const DEFAULT_KIMI_MODEL = "moonshotai/kimi-k2";
const GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/";
const DEFAULT_GEMINI_MODEL = "gemini-2.5-flash";

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

/** Optional OpenRouter-specific options for routing and attribution. */
export interface OpenRouterFactoryOptions extends Omit<
  OpenAIProviderOptions,
  "apiKey" | "baseURL"
> {
  apiKey?: string;
  /** Sent as `HTTP-Referer`. OpenRouter shows the app on its leaderboard. */
  httpReferer?: string;
  /** Sent as `X-Title`. Human-readable app name on the OpenRouter dashboard. */
  appTitle?: string;
}

function mergeOpenRouterHeaders(
  base: Record<string, string> | undefined,
  httpReferer: string | undefined,
  appTitle: string | undefined,
): Record<string, string> | undefined {
  const merged: Record<string, string> = { ...(base ?? {}) };
  if (httpReferer) merged["HTTP-Referer"] = httpReferer;
  if (appTitle) merged["X-Title"] = appTitle;
  return Object.keys(merged).length > 0 ? merged : undefined;
}

/**
 * Create an OpenRouter provider. OpenRouter is OpenAI-compatible, so this is
 * an `OpenAIProvider` pointed at the OpenRouter base URL. Reads
 * `OPENROUTER_API_KEY` (falling back to `OPENAI_API_KEY`) when no `apiKey`
 * is passed.
 *
 *   const p = openrouter("anthropic/claude-3.5-sonnet");
 *   const p = openrouter({ model: "meta-llama/llama-3.1-70b-instruct", appTitle: "My agent" });
 */
export function openrouter(arg?: string | OpenRouterFactoryOptions): OpenAIProvider {
  const opts: OpenRouterFactoryOptions = typeof arg === "string" ? { model: arg } : (arg ?? {});
  const apiKey = opts.apiKey ?? process.env.OPENROUTER_API_KEY ?? process.env.OPENAI_API_KEY ?? "";
  return new OpenAIProvider({
    apiKey,
    baseURL: OPENROUTER_BASE_URL,
    model: opts.model,
    temperature: opts.temperature,
    maxTokens: opts.maxTokens,
    defaultHeaders: mergeOpenRouterHeaders(opts.defaultHeaders, opts.httpReferer, opts.appTitle),
  });
}

/**
 * Create a Kimi provider preset. Routes through OpenRouter to Moonshot's Kimi
 * model by default. Pass a string to override the model:
 *
 *   const p = kimi();
 *   const p = kimi("moonshotai/kimi-k2.6");
 */
export function kimi(arg?: string | OpenRouterFactoryOptions): OpenAIProvider {
  if (typeof arg === "string") return openrouter(arg);
  return openrouter({ model: DEFAULT_KIMI_MODEL, ...(arg ?? {}) });
}

/** Optional Gemini factory options. Mirrors the OpenAI/anthropic shape. */
export interface GeminiFactoryOptions extends Omit<OpenAIProviderOptions, "apiKey" | "baseURL"> {
  apiKey?: string;
}

/**
 * Create a Gemini provider via Google's OpenAI-compatible endpoint
 * (https://generativelanguage.googleapis.com/v1beta/openai/). Reads
 * `GEMINI_API_KEY`, falling back to `GOOGLE_API_KEY`, when no `apiKey` is
 * passed. Defaults to model `gemini-2.5-flash`.
 *
 *   const p = gemini();                        // gemini-2.5-flash
 *   const p = gemini("gemini-2.5-pro");
 *   const p = gemini({ model: "gemini-2.5-pro", maxTokens: 2048 });
 *
 * This factory speaks the OpenAI chat-completions wire format, which Google
 * supports as a compatibility layer. Native Gemini features (context
 * caching, safety-setting configuration, response schemas) are not exposed;
 * for those, instantiate `@google/genai` directly and adapt the response to
 * `ModelProvider`.
 */
export function gemini(arg?: string | GeminiFactoryOptions): OpenAIProvider {
  const opts: GeminiFactoryOptions = typeof arg === "string" ? { model: arg } : (arg ?? {});
  const apiKey = opts.apiKey ?? process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY ?? "";
  return new OpenAIProvider({
    apiKey,
    baseURL: GEMINI_OPENAI_BASE_URL,
    model: opts.model ?? DEFAULT_GEMINI_MODEL,
    temperature: opts.temperature,
    maxTokens: opts.maxTokens,
    defaultHeaders: opts.defaultHeaders,
  });
}
