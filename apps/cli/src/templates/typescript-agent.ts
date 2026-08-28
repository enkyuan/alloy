import type { Provider } from "../providers.js";

export const TYPESCRIPT_SDK_RANGE = "^0.2.0-beta.11";
export const ZOD_RANGE = ">=4.3 <5";
const DOTENVX_VERSION = "2.9.0";

export const TYPESCRIPT_PROVIDER_RANGES = {
  mock: {},
  openai: { openai: ">=4 <8" },
  anthropic: { "@anthropic-ai/sdk": ">=0.30 <2" },
} as const;

const TS_PROVIDER_SOURCE: Record<Provider, { imports: string; setup: string }> = {
  mock: {
    imports:
      'import { AgentBuilder } from "@irogane/kaji";\n' +
      'import { MockProvider } from "@irogane/kaji/testing";',
    setup: "const provider = new MockProvider();",
  },
  openai: {
    imports:
      'import { AgentBuilder } from "@irogane/kaji";\n' +
      'import { OpenAIProvider } from "@irogane/kaji/openai";',
    setup: `const apiKey = process.env.OPENAI_API_KEY;
if (!apiKey) throw new Error("OPENAI_API_KEY is required for the openai scaffold");
const provider = new OpenAIProvider({ apiKey });`,
  },
  anthropic: {
    imports:
      'import { AgentBuilder } from "@irogane/kaji";\n' +
      'import { AnthropicProvider } from "@irogane/kaji/anthropic";',
    setup: `const apiKey = process.env.ANTHROPIC_API_KEY;
if (!apiKey) throw new Error("ANTHROPIC_API_KEY is required for the anthropic scaffold");
const provider = new AnthropicProvider({ apiKey });`,
  },
};

function resolveProviderDeps(provider: Provider): Record<string, string> {
  return TYPESCRIPT_PROVIDER_RANGES[provider];
}

export function typescriptAgentTemplate(provider: Provider): string {
  const source = TS_PROVIDER_SOURCE[provider];
  return `${source.imports}

async function main(): Promise<void> {
  ${source.setup.replaceAll("\n", "\n  ")}
  const runtime = new AgentBuilder()
    .provider(provider)
    .systemPrompt("You are a helpful assistant.")
    .build();

  const result = await runtime.turn("Say hello.");
  const finalSequence = Math.max(...result.events.map((event) => event.sequence));
  console.log(\`text=\${result.text}\`);
  console.log(\`turn_id=\${result.turnId}\`);
  console.log(\`final_sequence=\${finalSequence}\`);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Kaji agent failed");
  process.exit(1);
});
`;
}

export function typescriptPackageTemplate(provider: Provider): string {
  const providerDeps = resolveProviderDeps(provider);
  return (
    JSON.stringify(
      {
        name: "my-kaji-agent",
        version: "0.1.0",
        private: true,
        type: "module",
        engines: { node: "22.x || 24.x" },
        scripts: {
          start: "dotenvx run --ignore=MISSING_ENV_FILE -- tsx agent.ts",
          typecheck: "tsc --noEmit",
        },
        dependencies: { kaji: TYPESCRIPT_SDK_RANGE, zod: ZOD_RANGE, ...providerDeps },
        devDependencies: {
          "@dotenvx/dotenvx": DOTENVX_VERSION,
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

export function typescriptConfigTemplate(): string {
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

export function typescriptEnvTemplate(provider: Provider): string {
  const credentials: Record<Provider, string> = {
    mock: "# No provider credentials required.",
    openai: "OPENAI_API_KEY=",
    anthropic: "ANTHROPIC_API_KEY=",
  };
  const credential = credentials[provider];
  return `# kaji provider: ${provider}\nKAJI_MODEL_PROVIDER=${provider}\n${credential}\n`;
}
