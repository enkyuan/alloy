export function tsAgentTemplate(provider: string): string {
  return `import { AgentBuilder, InMemoryEventBus, InMemoryEventStore, GetProvider, UserMessage } from "@agentkit/sdk";

async function main() {
  const bus = new InMemoryEventBus();
  const store = new InMemoryEventStore();
  const providerName = process.env.AGENTKIT_MODEL_PROVIDER ?? ${JSON.stringify(provider)};
  const runtime = new AgentBuilder()
    .provider(GetProvider(providerName))
    .systemPrompt("You are a helpful assistant.")
    .build({ bus, store });

  await store.append(new UserMessage({ sessionId: "s1", content: "Hello!" }));
  await runtime.runTurn("s1");
  for (const e of await store.getEvents("s1")) console.log(e.type, (e as any).content ?? (e as any).delta ?? "");
}

main().catch((e) => { console.error(e); process.exit(1); });
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
