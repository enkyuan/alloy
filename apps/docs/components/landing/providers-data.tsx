export const providerDrivers = [
  {
    name: "OpenAI",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91a6.05 6.05 0 0 0-6.51-2.9A6.07 6.07 0 0 0 4.981 4.18a5.99 5.99 0 0 0-3.998 2.9a6.05 6.05 0 0 0 .743 7.097a5.98 5.98 0 0 0 .51 4.911a6.05 6.05 0 0 0 6.515 2.9A5.98 5.98 0 0 0 13.26 24a6.06 6.06 0 0 0 5.772-4.206a5.99 5.99 0 0 0 3.997-2.9a6.06 6.06 0 0 0-.747-7.073M13.26 22.43a4.48 4.48 0 0 1-2.876-1.04l.141-.081l4.779-2.758a.8.8 0 0 0 .392-.681v-6.737l2.02 1.168a.07.07 0 0 1 .038.052v5.583a4.5 4.5 0 0 1-4.494 4.494M3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085l4.783 2.759a.77.77 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646M2.34 7.896a4.5 4.5 0 0 1 2.366-1.973V11.6a.77.77 0 0 0 .388.677l5.815 3.354l-2.02 1.168a.08.08 0 0 1-.071 0l-4.83-2.786A4.5 4.5 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.08.08 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667m2.01-3.023l-.141-.085l-4.774-2.782a.78.78 0 0 0-.785 0L9.409 9.23V6.897a.07.07 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08l-4.778 2.758a.8.8 0 0 0-.393.681zm1.097-2.365l2.602-1.5l2.607 1.5v2.999l-2.597 1.5l-2.607-1.5z"
        />
      </svg>
    ),
  },
  {
    name: "Kimi",
    icon: () => (
      // Moonshot AI / Kimi — crescent moon mark
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    ),
  },
  {
    name: "Gemini",
    icon: () => (
      // Google Gemini — four-pointed star
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M12 2c.46 5.17 4.83 9.54 10 10c-5.17.46-9.54 4.83-10 10c-.46-5.17-4.83-9.54-10-10C7.17 11.54 11.54 7.17 12 2z" />
      </svg>
    ),
  },
];

export const moreProviders = [
  {
    name: "Mock",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          d="M4 6h16M4 12h16M4 18h10"
        />
      </svg>
    ),
  },
  {
    name: "Anthropic",
    icon: () => (
      // Anthropic — official A-triangle mark from simpleicons
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M13.827 3.9h3.453L24 20.1h-3.819l-1.404-3.891H9.232l-1.404 3.89H4.01zm1.725 5.068L13.23 14.9h4.645zm-8.683-5.067H3.416L0 20.1h3.819l1.404-3.891h9.545l.654-1.82H6.273z" />
      </svg>
    ),
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
  Kimi: `provider: new KimiProvider({
  apiKey: process.env.KIMI_API_KEY,
})`,
  Gemini: `provider: new GeminiProvider({
  apiKey: process.env.GEMINI_API_KEY,
})`,
  Mock: `provider: new MockProvider()`,
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
