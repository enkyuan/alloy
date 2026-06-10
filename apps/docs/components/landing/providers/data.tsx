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
  OpenAI: `import { AgentRuntime } from "@agentkit/sdk"
import { OpenAIProvider } from "@agentkit/sdk/providers"
import { InMemoryEventBus } from "@agentkit/sdk/events"

const runtime = new AgentRuntime({
  provider: new OpenAIProvider({
    apiKey: process.env.OPENAI_API_KEY,
    model: "gpt-4o",
  }),
  tools: registry.list(),
  bus: new InMemoryEventBus(),
})`,
  OpenRouter: `provider: new OpenAIProvider({
  apiKey: process.env.OPENROUTER_API_KEY,
  baseURL: "https://openrouter.ai/api/v1",
  model: "anthropic/claude-sonnet-4-5",
})`,
  Kimi: `provider: new KimiProvider({
  apiKey: process.env.KIMI_API_KEY,
})`,
  Gemini: `provider: new GeminiProvider({
  apiKey: process.env.GEMINI_API_KEY,
})`,
  Anthropic: `// roadmap: not yet shipped
provider: new AnthropicProvider()`,
};

export const serverCodeTs = `import { AgentRuntime } from "@agentkit/sdk"
import { OpenAIProvider } from "@agentkit/sdk/providers"
import { InMemoryEventBus } from "@agentkit/sdk/events"
import { ToolRegistry, tool } from "@agentkit/sdk/tools"

const registry = new ToolRegistry()

registry.add(
  tool("get_weather", "Look up the weather for a city", {
    city: { type: "string" },
  }, async ({ city }) => fetchWeather(city)),
)

export const agent = new AgentRuntime({
  provider: new OpenAIProvider({
    apiKey: process.env.OPENAI_API_KEY,
    model: "gpt-4o",
  }),
  tools: registry.list(),
  bus: new InMemoryEventBus(),
})`;

export const serverCodePy = `from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.runtime.providers.openai import OpenAIProvider
from agentkit.infra.events.bus import InMemoryEventBus
from agentkit.runtime.tools.registry import register_tool, tool_spec_from_model


@register_tool(tool_spec_from_model("get_weather", "Look up the weather", WeatherArgs))
async def get_weather(ctx, args):
    return await fetch_weather(args["city"])


agent = AgentRuntime(
    provider=OpenAIProvider(model="gpt-4o"),
    bus=InMemoryEventBus(),
    store=store,
    planner=planner,
)`;
