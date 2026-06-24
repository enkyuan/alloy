"use client";

import { OpenAILogo } from "@components/icons/openai";
import { GeminiLogo } from "@components/icons/gemini";
import { OpenRouterLogo } from "@components/icons/openrouter";
import { KimiLogo, AnthropicLogo } from "@components/icons/providers";

export const providerDrivers = [
  {
    name: "OpenAI",
    icon: () => <OpenAILogo />,
  },
  {
    name: "OpenRouter",
    icon: () => <OpenRouterLogo />,
  },
  {
    name: "Kimi",
    icon: () => <KimiLogo />,
  },
  {
    name: "Gemini",
    icon: () => <GeminiLogo />,
  },
];

export const moreProviders = [
  {
    name: "Anthropic",
    icon: () => <AnthropicLogo />,
  },
];

export const providerSnippets: Record<string, string> = {
  OpenAI: `import { AgentBuilder, EventBus, InMemoryEventStore, openai } from "@kaji/sdk"

const runtime = new AgentBuilder()
  .provider(openai("gpt-4o"))
  .build({ bus: new EventBus(), store: new InMemoryEventStore() })`,
  OpenRouter: `import { openrouter } from "@kaji/sdk"

provider: openrouter("anthropic/claude-sonnet-4-5")`,
  Kimi: `import { kimi } from "@kaji/sdk"

provider: kimi()`,
  Gemini: `import { gemini } from "@kaji/sdk"

provider: gemini("gemini-2.5-flash")`,
  Anthropic: `import { anthropic } from "@kaji/sdk"

provider: anthropic("claude-sonnet-4-6")`,
};

export const serverCodeTs = `import { EventType } from "@kaji/sdk"

// Send a message and stream the response
const session = crypto.randomUUID()
await runtime.send(session, "What's the weather in Tokyo?")

for await (const event of bus.subscribe(session)) {
  if (event.type === EventType.AGENT_MESSAGE_DELTA) {
    process.stdout.write(event.delta)
  }
  if (event.type === EventType.AGENT_MESSAGE_COMPLETED) {
    break
  }
}`;

export const serverCodePy = `from kaji.infra.events.types import EventType

# Send a message and stream the response
session_id = "s1"
await runtime.run_turn(session_id)

async for event in bus.subscribe(session_id):
    if event.type == EventType.AGENT_MESSAGE_DELTA:
        print(event.delta, end="", flush=True)
    if event.type == EventType.AGENT_MESSAGE_COMPLETED:
        break`;
