export function tsAgentTemplate(provider: string): string {
  const factoryName = provider === "anthropic" ? "anthropic" : "openai";
  return `import {
  AgentBuilder,
  AgentKitEvent,
  EventBus,
  EventType,
  InMemoryEventStore,
  ${factoryName},
} from "@agentkit/sdk";

async function main() {
  const bus = new EventBus();
  const store = new InMemoryEventStore();

  const runtime = new AgentBuilder()
    .provider(${factoryName}())
    .systemPrompt("You are a helpful assistant.")
    .build({ bus, store });

  const sessionCreated = AgentKitEvent.parse({
    type: EventType.SESSION_CREATED,
    session_id: "s1",
  });
  await store.append(sessionCreated);
  await bus.publish(sessionCreated);

  await runtime.send("s1", "Hello!");

  for (const e of await store.getEvents("s1")) {
    const text = "content" in e ? e.content : "delta" in e ? e.delta : "";
    console.log(e.type, text);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
`;
}

export function tsEnvTemplate(provider: string): string {
  return `# agentkit
AGENTKIT_MODEL_PROVIDER=${provider}

# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...
# KIMI_API_KEY=...
`;
}
