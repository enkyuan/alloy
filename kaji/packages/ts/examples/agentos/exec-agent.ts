/**
 * Interop example: a kaji agent that runs code in an isolated agentOS VM.
 *
 * Platform: darwin/linux, x64/arm64, Node >= 22, ESM-only. See ./README.md.
 *
 * Run (from examples/agentos):
 *   npm install
 *   OPENAI_API_KEY=... npm start        # or ANTHROPIC_API_KEY=...
 */
import { AgentBuilder, anthropic, openai, type ModelProvider } from "kaji";

import { AgentOsIntegration, createLockedDownVm } from "./agentos-integration.ts";

function providerFromEnv(): ModelProvider {
  if (process.env.OPENAI_API_KEY) return openai();
  if (process.env.ANTHROPIC_API_KEY) return anthropic();
  throw new Error("Set OPENAI_API_KEY or ANTHROPIC_API_KEY before running.");
}

export async function main(): Promise<void> {
  // Boot a VM with egress denied. createLockedDownVm() reframes an
  // absent/unsupported agentos-core into an actionable install error.
  const vm = await createLockedDownVm();
  const integration = new AgentOsIntegration(vm);
  try {
    const runtime = new AgentBuilder()
      .provider(providerFromEnv())
      .integration(integration)
      .defaultContext({ principalId: "agentos-example" })
      .systemPrompt(
        "You run commands in an isolated Linux VM using the agentos tools. " +
          "Always report the exit_code and stderr when a command fails.",
      )
      .build();

    const { text } = await runtime.turn(
      "Run `echo hello from agentos` and tell me the exact stdout.",
    );
    console.log(text);
  } finally {
    // Always tear the VM down, even if the turn threw.
    await integration.close();
  }
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
