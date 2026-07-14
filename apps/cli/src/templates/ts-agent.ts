const TS_FACTORIES = {
  openai: "openai",
  anthropic: "anthropic",
  kimi: "kimi",
  gemini: "gemini",
} as const;

type TsProvider = keyof typeof TS_FACTORIES;

const TS_PROVIDER_DEPS: Record<TsProvider, Record<string, string>> = {
  openai: { openai: ">=4 <8" },
  anthropic: { "@anthropic-ai/sdk": ">=0.30 <2" },
  kimi: { openai: ">=4 <8" },
  gemini: { openai: ">=4 <8" },
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

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Kaji agent failed");
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
        engines: { node: "22.x || 24.x" },
        scripts: { start: "tsx agent.ts", typecheck: "tsc --noEmit" },
        dependencies: {
          "@kaji/sdk": "^0.2.0-beta.1",
          zod: ">=4.3 <5",
          ...providerDeps,
        },
        devDependencies: {
          "@types/node": "^22.10.2",
          tsx: "^4.21.0",
          typescript: "^6.0.2",
        },
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
          skipLibCheck: false,
          types: ["node"],
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
# OPENROUTER_API_KEY=...  # Kimi/OpenRouter
`;
}
