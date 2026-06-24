// Maps the --provider CLI choice to the TS SDK factory function name.
// All four are zero-arg ready (each reads the appropriate API key from
// the env), so the generated agent just imports and calls one of them.
const TS_FACTORIES = {
  openai: "openai",
  anthropic: "anthropic",
  kimi: "kimi",
  gemini: "gemini",
} as const;

type TsProvider = keyof typeof TS_FACTORIES;

function resolveFactory(provider: string): string {
  if (provider in TS_FACTORIES) return TS_FACTORIES[provider as TsProvider];
  throw new Error(
    `Unknown provider '${provider}'. Supported: ${Object.keys(TS_FACTORIES).join(", ")}.`,
  );
}

export function tsAgentTemplate(provider: string): string {
  const factoryName = resolveFactory(provider);
  return `import {
  AgentBuilder,
  KajiEvent,
  EventBus,
  EventType,
  InMemoryEventStore,
  ${factoryName},
} from "@kaji/sdk";

async function main() {
  const bus = new EventBus();
  const store = new InMemoryEventStore();

  const runtime = new AgentBuilder()
    .provider(${factoryName}())
    .systemPrompt("You are a helpful assistant.")
    .build({ bus, store });

  const sessionCreated = KajiEvent.parse({
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
  return `# kaji
KAJI_MODEL_PROVIDER=${provider}

# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...
# KIMI_API_KEY=...
`;
}
