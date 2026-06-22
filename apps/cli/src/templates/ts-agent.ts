export function tsAgentTemplate(provider: string): string {
  return `import {
  AgentBuilder,
  AgentKitEvent,
  EventBus,
  EventType,
  InMemoryEventStore,
  getProvider,
} from "@agentkit/sdk";

async function main() {
  const bus = new EventBus();
  const store = new InMemoryEventStore();
  const providerName = process.env.AGENTKIT_MODEL_PROVIDER ?? ${JSON.stringify(provider)};
  const runtime = new AgentBuilder()
    .provider(getProvider(providerName))
    .systemPrompt("You are a helpful assistant.")
    .build({ bus, store });

  await store.append(
    AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }),
  );
  await runtime.send("s1", "Hello!");

  for (const e of await store.getEvents("s1")) {
    console.log(e.type, (e as { content?: string; delta?: string }).content ?? (e as { delta?: string }).delta ?? "");
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
