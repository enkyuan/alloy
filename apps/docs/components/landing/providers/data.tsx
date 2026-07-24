"use client";

import { OpenAILogo } from "@components/icons/openai";
import { GeminiLogo } from "@components/icons/gemini";
import { OpenRouterLogo } from "@components/icons/openrouter";
import { KimiLogo, AnthropicLogo } from "@components/icons/providers";

export const providerDrivers = [
  {
    name: "OpenAI",
    tier: "beta core",
    icon: () => <OpenAILogo />,
  },
  {
    name: "Anthropic",
    tier: "beta core",
    icon: () => <AnthropicLogo />,
  },
];

export const moreProviders = [
  {
    name: "OpenRouter",
    tier: "experimental",
    icon: () => <OpenRouterLogo />,
  },
  {
    name: "Kimi",
    tier: "experimental",
    icon: () => <KimiLogo />,
  },
  {
    name: "Gemini",
    tier: "experimental",
    icon: () => <GeminiLogo />,
  },
];

export const providerSnippets: Record<string, string> = {
  OpenAI: `import { AgentBuilder, openai } from "kaji-sdk"

const runtime = new AgentBuilder()
  .provider(openai("gpt-5.4-mini"))
  .build()`,
  Anthropic: `import { anthropic } from "kaji-sdk"

const provider = anthropic("claude-sonnet-4-6")`,
  OpenRouter: `import { openrouter } from "kaji-sdk"

const provider = openrouter("anthropic/claude-sonnet-4-6")`,
  Kimi: `import { kimi } from "kaji-sdk"

const provider = kimi()`,
  Gemini: `import { gemini } from "kaji-sdk"

const provider = gemini("gemini-2.5-flash")`,
};

export const serverCodeTs = `import { AgentBuilder, openai } from "kaji-sdk"

const runtime = new AgentBuilder()
  .provider(openai("gpt-5.4-mini"))
  .build()

const result = await runtime.turn("Say hello.", {
  sessionId: "demo-session",
})

console.log(result.text, result.sessionId, result.turnId)`;

export const serverCodePy = `import kaji

runtime = (
    kaji.AgentBuilder()
    .provider(kaji.get_provider("openai"))
    .build()
)

result = await runtime.turn(
    "Say hello.",
    session_id="demo-session",
)

print(result.text, result.session_id, result.turn_id)`;
