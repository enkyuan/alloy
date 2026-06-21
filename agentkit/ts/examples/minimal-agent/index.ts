/**
 * Minimal AgentKit agent — generated example.
 *
 * Prerequisites:
 *   npm install @agentkit/sdk zod openai   # or @anthropic-ai/sdk
 *   export OPENAI_API_KEY=sk-...           # or ANTHROPIC_API_KEY
 *
 * Run:
 *   npx tsx index.ts
 */
import {
  AgentBuilder,
  EventBus,
  InMemoryEventStore,
  OpenAIProvider,
  Integration,
  tool,
  AgentKitEvent,
  EventType,
} from "@agentkit/sdk";
import { z } from "zod";

class WeatherIntegration extends Integration {
  readonly namespace = "weather";

  readonly getWeather = tool(
    {
      description: "Return current weather for a city.",
      parameters: z.object({ city: z.string() }),
      risk: "read",
    },
    async (_ctx, args) => ({ city: args.city, tempF: 68 }),
  );
}

export async function runAgent(apiKey: string): Promise<void> {
  const store = new InMemoryEventStore();
  const bus = new EventBus();

  const runtime = new AgentBuilder()
    .provider(new OpenAIProvider({ apiKey }))
    .integration(new WeatherIntegration())
    .systemPrompt("You are a weather assistant.")
    .build({ bus, store });

  await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }));
  await runtime.send("s1", "What is the weather in Seattle?");

  const events = await store.getEvents("s1");
  for (const e of events) {
    const text = "content" in e ? e.content : "delta" in e ? e.delta : "";
    if (text) console.log(`[${e.type}] ${text}`);
  }
}

// Entry point when run directly
if (process.argv[1] === new URL(import.meta.url).pathname) {
  const apiKey = process.env.OPENAI_API_KEY ?? process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error("Set OPENAI_API_KEY or ANTHROPIC_API_KEY before running.");
    process.exit(1);
  }
  runAgent(apiKey).catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
