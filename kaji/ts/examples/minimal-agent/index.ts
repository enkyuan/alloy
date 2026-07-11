/**
 * Minimal Kaji agent — generated example.
 *
 * Prerequisites:
 *   npm install @kaji/sdk zod openai   # or @anthropic-ai/sdk
 *   export OPENAI_API_KEY=sk-...       # or ANTHROPIC_API_KEY
 *
 * Run:
 *   npx tsx index.ts
 */
import {
  AgentBuilder,
  EventBus,
  InMemoryEventStore,
  anthropic,
  functionTool,
  openai,
  type ModelProvider,
} from "@kaji/sdk";
import * as z from "zod";

const getWeather = functionTool(
  {
    description: "Return current weather for a city.",
    parameters: z.object({ city: z.string() }),
    risk: "read",
  },
  async ({ city }) => ({ city, tempF: 68 }),
);

export function providerFromEnv(): ModelProvider {
  if (process.env.OPENAI_API_KEY) return openai();
  if (process.env.ANTHROPIC_API_KEY) return anthropic();
  throw new Error("Set OPENAI_API_KEY or ANTHROPIC_API_KEY before running.");
}

export async function runAgent(provider = providerFromEnv()): Promise<void> {
  const runtime = new AgentBuilder()
    .provider(provider)
    .tool(getWeather)
    .defaultContext({ principalId: "minimal-agent" })
    .systemPrompt("You are a weather assistant.")
    .build({ bus: new EventBus(), store: new InMemoryEventStore() });

  const { text } = await runtime.turn("What is the weather in Seattle?");
  console.log(text);
}

// Entry point when run directly
if (process.argv[1] === new URL(import.meta.url).pathname) {
  runAgent().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
