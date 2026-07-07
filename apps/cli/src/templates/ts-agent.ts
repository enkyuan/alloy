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

const TS_PROVIDER_DEPS: Record<TsProvider, Record<string, string>> = {
  openai: { openai: "^6.42.0" },
  anthropic: { "@anthropic-ai/sdk": "^0.104.1" },
  kimi: { openai: "^6.42.0" },
  gemini: { openai: "^6.42.0" },
};

function resolveFactory(provider: string): string {
  if (provider in TS_FACTORIES) return TS_FACTORIES[provider as TsProvider];
  throw new Error(
    `Unknown provider '${provider}'. Supported: ${Object.keys(TS_FACTORIES).join(", ")}.`,
  );
}

function resolveProviderDeps(provider: string): Record<string, string> {
  if (provider in TS_PROVIDER_DEPS) return TS_PROVIDER_DEPS[provider as TsProvider];
  throw new Error(
    `Unknown provider '${provider}'. Supported: ${Object.keys(TS_PROVIDER_DEPS).join(", ")}.`,
  );
}

export function tsAgentTemplate(provider: string): string {
  const factoryName = resolveFactory(provider);
  return `import { AgentBuilder, ${factoryName} } from "@kaji/sdk";

async function main() {
  const agent = new AgentBuilder()
    .provider(${factoryName}())
    .systemPrompt("You are a helpful assistant.")
    .build();

  const result = await agent.turn("Say hello.");
  console.log(result.text);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
`;
}

export function tsPackageTemplate(provider: string): string {
  const providerDeps = resolveProviderDeps(provider);
  return (
    JSON.stringify(
      {
        name: "my-kaji-agent",
        version: "0.1.0",
        private: true,
        type: "module",
        scripts: { start: "tsx agent.ts" },
        dependencies: { "@kaji/sdk": "^0.1.0", ...providerDeps },
        devDependencies: { tsx: "^4.0.0", typescript: "^5.4.0" },
      },
      null,
      2,
    ) + "\n"
  );
}

export function tsConfigTemplate(): string {
  return (
    JSON.stringify(
      {
        compilerOptions: {
          target: "ES2022",
          module: "ESNext",
          moduleResolution: "Bundler",
          strict: true,
          esModuleInterop: true,
          skipLibCheck: true,
        },
        include: ["*.ts"],
      },
      null,
      2,
    ) + "\n"
  );
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
