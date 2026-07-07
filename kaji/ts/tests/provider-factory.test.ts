/**
 * Unit tests for the function-style provider factories.
 *
 * The factories are thin wrappers over the provider constructors; the
 * surface that actually needs coverage is option resolution: positional
 * model string vs options object, env-var fallback, base URL pinning,
 * default model, and HTTP-header merging for OpenRouter.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  anthropic,
  gemini,
  kimi,
  openai,
  openrouter,
  resolveAnthropicOptions,
  resolveGeminiOptions,
  resolveKimiOptions,
  resolveOpenAIOptions,
  resolveOpenRouterOptions,
} from "@/providers/factory";
import { AnthropicProvider } from "@/providers/anthropic";
import { OpenAIProvider } from "@/providers/openai";
import { ProviderConfigError } from "@/providers/errors";

const originalEnv = { ...process.env };

beforeEach(() => {
  delete process.env.OPENAI_API_KEY;
  delete process.env.ANTHROPIC_API_KEY;
  delete process.env.OPENROUTER_API_KEY;
  delete process.env.GEMINI_API_KEY;
  delete process.env.GOOGLE_API_KEY;
});

afterEach(() => {
  process.env = { ...originalEnv };
});

describe("openai()", () => {
  it("returns an OpenAIProvider with the env apiKey and default model", () => {
    process.env.OPENAI_API_KEY = "sk-env";
    const p = openai();
    expect(p).toBeInstanceOf(OpenAIProvider);
    expect(resolveOpenAIOptions().apiKey).toBe("sk-env");
    expect(p.model).toBe("gpt-5.4-mini");
  });

  it("treats a string argument as the model name", () => {
    process.env.OPENAI_API_KEY = "sk-env";
    expect(resolveOpenAIOptions("gpt-4o-mini").model).toBe("gpt-4o-mini");
  });

  it("accepts an options object that overrides the env apiKey", () => {
    process.env.OPENAI_API_KEY = "sk-env";
    const resolved = resolveOpenAIOptions({
      apiKey: "sk-explicit",
      model: "gpt-4o-mini",
      temperature: 0.1,
    });
    expect(resolved.apiKey).toBe("sk-explicit");
    expect(resolved.temperature).toBe(0.1);
  });

  it("throws ProviderConfigError when no apiKey is available", () => {
    expect(() => openai()).toThrow(ProviderConfigError);
  });
});

describe("anthropic()", () => {
  it("returns an AnthropicProvider with the env apiKey", () => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-env";
    const p = anthropic();
    expect(p).toBeInstanceOf(AnthropicProvider);
    expect(resolveAnthropicOptions().apiKey).toBe("sk-ant-env");
  });

  it("treats a string argument as the model name", () => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-env";
    expect(resolveAnthropicOptions("claude-3-5-sonnet-20241022").model).toBe(
      "claude-3-5-sonnet-20241022",
    );
  });

  it("throws ProviderConfigError when no apiKey is available", () => {
    expect(() => anthropic()).toThrow(ProviderConfigError);
  });
});

describe("openrouter()", () => {
  it("pins baseURL to the OpenRouter endpoint", () => {
    process.env.OPENROUTER_API_KEY = "or-key";
    const p = openrouter("anthropic/claude-3.5-sonnet");
    const resolved = resolveOpenRouterOptions("anthropic/claude-3.5-sonnet");
    expect(p).toBeInstanceOf(OpenAIProvider);
    expect(resolved.baseURL).toBe("https://openrouter.ai/api/v1");
    expect(resolved.model).toBe("anthropic/claude-3.5-sonnet");
    expect(resolved.apiKey).toBe("or-key");
  });

  it("falls back to OPENAI_API_KEY when OPENROUTER_API_KEY is unset", () => {
    process.env.OPENAI_API_KEY = "sk-fallback";
    expect(resolveOpenRouterOptions("meta-llama/llama-3.1-70b-instruct").apiKey).toBe(
      "sk-fallback",
    );
  });

  it("merges httpReferer and appTitle into defaultHeaders", () => {
    process.env.OPENROUTER_API_KEY = "or-key";
    const resolved = resolveOpenRouterOptions({
      model: "x/y",
      httpReferer: "https://example.com",
      appTitle: "My Agent",
    });
    expect(resolved.defaultHeaders).toEqual({
      "HTTP-Referer": "https://example.com",
      "X-Title": "My Agent",
    });
  });

  it("returns no defaultHeaders when neither attribution field is set", () => {
    process.env.OPENROUTER_API_KEY = "or-key";
    expect(resolveOpenRouterOptions("x/y").defaultHeaders).toBeUndefined();
  });
});

describe("kimi()", () => {
  it("defaults to moonshotai/kimi-k2 routed through OpenRouter", () => {
    process.env.OPENROUTER_API_KEY = "or-key";
    const p = kimi();
    const resolved = resolveKimiOptions();
    expect(p).toBeInstanceOf(OpenAIProvider);
    expect(resolved.model).toBe("moonshotai/kimi-k2");
    expect(resolved.baseURL).toBe("https://openrouter.ai/api/v1");
  });

  it("forwards a string argument as the model override", () => {
    process.env.OPENROUTER_API_KEY = "or-key";
    expect(resolveKimiOptions("moonshotai/kimi-k2.6").model).toBe("moonshotai/kimi-k2.6");
  });
});

describe("gemini()", () => {
  it("pins baseURL to Google's OpenAI-compatible endpoint with a default model", () => {
    process.env.GEMINI_API_KEY = "g-key";
    const p = gemini();
    const resolved = resolveGeminiOptions();
    expect(p).toBeInstanceOf(OpenAIProvider);
    expect(resolved.baseURL).toBe("https://generativelanguage.googleapis.com/v1beta/openai/");
    expect(resolved.model).toBe("gemini-2.5-flash");
    expect(resolved.apiKey).toBe("g-key");
  });

  it("falls back to GOOGLE_API_KEY when GEMINI_API_KEY is unset", () => {
    process.env.GOOGLE_API_KEY = "g-fallback";
    const resolved = resolveGeminiOptions("gemini-2.5-pro");
    expect(resolved.apiKey).toBe("g-fallback");
    expect(resolved.model).toBe("gemini-2.5-pro");
  });
});
