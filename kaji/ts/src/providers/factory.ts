/**
 * Function-style provider factories.
 *
 * Convenience wrappers so callers can write `openai("gpt-5.4-mini")` instead of
 * `new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY!, model: "gpt-5.4-mini" })`.
 * Reads the conventional environment variable when no apiKey is given.
 *
 *   import { openai, anthropic, generateText } from "kaji-sdk";
 *   const { text } = await generateText({
 *     provider: openai("gpt-5.4-mini"),
 *     messages: [{ role: "user", content: "Hello" }],
 *   });
 */
import { OpenAIProvider, type OpenAIProviderOptions } from "@/providers/openai";
import { AnthropicProvider, type AnthropicProviderOptions } from "@/providers/anthropic";

const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";
const DEFAULT_KIMI_MODEL = "moonshotai/kimi-k2.6";
const GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/";
const DEFAULT_GEMINI_MODEL = "gemini-3.5-flash";

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

/** @internal */
export function resolveOpenAIOptions(
  arg?: ModelOrOptions<OpenAIProviderOptions>,
): OpenAIProviderOptions {
  return resolveOptions<OpenAIProviderOptions>("OPENAI_API_KEY", {}, arg);
}

/** Create an OpenAI provider. Reads `OPENAI_API_KEY` from the environment when no `apiKey` is passed. */
export function openai(arg?: ModelOrOptions<OpenAIProviderOptions>): OpenAIProvider {
  return new OpenAIProvider(resolveOpenAIOptions(arg));
}

/** @internal */
export function resolveAnthropicOptions(
  arg?: ModelOrOptions<AnthropicProviderOptions>,
): AnthropicProviderOptions {
  return resolveOptions<AnthropicProviderOptions>("ANTHROPIC_API_KEY", {}, arg);
}

/** Create an Anthropic provider. Reads `ANTHROPIC_API_KEY` from the environment when no `apiKey` is passed. */
export function anthropic(arg?: ModelOrOptions<AnthropicProviderOptions>): AnthropicProvider {
  return new AnthropicProvider(resolveAnthropicOptions(arg));
}

/** Optional OpenRouter-specific options for routing and attribution. */
export interface OpenRouterFactoryOptions extends Omit<
  OpenAIProviderOptions,
  "apiKey" | "baseURL"
> {
  apiKey?: string;
  /** Sent as `HTTP-Referer`. OpenRouter shows the app on its leaderboard. */
  httpReferer?: string;
  /** Sent as `X-OpenRouter-Title`. Human-readable app name on the OpenRouter dashboard. */
  appTitle?: string;
}

function mergeOpenRouterHeaders(
  base: Record<string, string> | undefined,
  httpReferer: string | undefined,
  appTitle: string | undefined,
): Record<string, string> | undefined {
  const merged: Record<string, string> = { ...base };
  if (httpReferer) merged["HTTP-Referer"] = httpReferer;
  if (appTitle) merged["X-OpenRouter-Title"] = appTitle;
  return Object.keys(merged).length > 0 ? merged : undefined;
}

/**
 * Create an OpenRouter provider. OpenRouter is OpenAI-compatible, so this is
 * an `OpenAIProvider` pointed at the OpenRouter base URL. Reads
 * `OPENROUTER_API_KEY` when no `apiKey` is passed.
 *
 *   const p = openrouter("openai/gpt-5.4-mini");
 *   const p = openrouter({ model: "anthropic/claude-sonnet-4.6", appTitle: "My agent" });
 */
/** @internal */
export function resolveOpenRouterOptions(
  arg?: string | OpenRouterFactoryOptions,
): OpenAIProviderOptions {
  const opts: OpenRouterFactoryOptions = typeof arg === "string" ? { model: arg } : (arg ?? {});
  const apiKey = opts.apiKey ?? process.env.OPENROUTER_API_KEY ?? "";
  return {
    apiKey,
    baseURL: OPENROUTER_BASE_URL,
    model: opts.model,
    temperature: opts.temperature,
    maxTokens: opts.maxTokens,
    requestTimeoutMs: opts.requestTimeoutMs,
    defaultHeaders: mergeOpenRouterHeaders(opts.defaultHeaders, opts.httpReferer, opts.appTitle),
  };
}

export function openrouter(arg?: string | OpenRouterFactoryOptions): OpenAIProvider {
  return new OpenAIProvider(resolveOpenRouterOptions(arg));
}

/**
 * Create a Kimi provider preset. Routes through OpenRouter to Moonshot's Kimi
 * model by default. Pass a string to override the model:
 *
 *   const p = kimi();
 *   const p = kimi("moonshotai/kimi-k2.6");
 */
/** @internal */
export function resolveKimiOptions(arg?: string | OpenRouterFactoryOptions): OpenAIProviderOptions {
  if (typeof arg === "string") return resolveOpenRouterOptions(arg);
  return resolveOpenRouterOptions({ model: DEFAULT_KIMI_MODEL, ...arg });
}

export function kimi(arg?: string | OpenRouterFactoryOptions): OpenAIProvider {
  return new OpenAIProvider(resolveKimiOptions(arg));
}

/** Optional Gemini factory options. Mirrors the OpenAI/anthropic shape. */
export interface GeminiFactoryOptions extends Omit<OpenAIProviderOptions, "apiKey" | "baseURL"> {
  apiKey?: string;
}

/**
 * Create a Gemini provider via Google's OpenAI-compatible endpoint
 * (https://generativelanguage.googleapis.com/v1beta/openai/). Reads
 * `GEMINI_API_KEY`, falling back to `GOOGLE_API_KEY`, when no `apiKey` is
 * passed. Defaults to model `gemini-3.5-flash`.
 *
 *   const p = gemini();                        // gemini-3.5-flash
 *   const p = gemini("gemini-3.5-flash");
 *   const p = gemini({ model: "gemini-3.5-flash", maxTokens: 2048 });
 *
 * This factory speaks the OpenAI chat-completions wire format, which Google
 * supports as a compatibility layer. Native Gemini features (context
 * caching, safety-setting configuration, response schemas) are not exposed;
 * for those, instantiate `@google/genai` directly and adapt the response to
 * `ModelProvider`.
 */
/** @internal */
export function resolveGeminiOptions(arg?: string | GeminiFactoryOptions): OpenAIProviderOptions {
  const opts: GeminiFactoryOptions = typeof arg === "string" ? { model: arg } : (arg ?? {});
  const apiKey = opts.apiKey ?? process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY ?? "";
  return {
    apiKey,
    baseURL: GEMINI_OPENAI_BASE_URL,
    model: opts.model ?? DEFAULT_GEMINI_MODEL,
    temperature: opts.temperature,
    maxTokens: opts.maxTokens,
    requestTimeoutMs: opts.requestTimeoutMs,
    defaultHeaders: opts.defaultHeaders,
  };
}

export function gemini(arg?: string | GeminiFactoryOptions): OpenAIProvider {
  return new OpenAIProvider(resolveGeminiOptions(arg));
}
