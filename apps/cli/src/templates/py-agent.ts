export function pyAgentTemplate(provider: string): string {
  return `"""Minimal kaji scaffold."""

from __future__ import annotations

import asyncio
import os

import kaji


async def main() -> None:
    provider_name = os.environ.get("KAJI_MODEL_PROVIDER", ${JSON.stringify(provider)})
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider(provider_name))
        .system_prompt("You are a helpful assistant.")
        .build()
    )
    result = await runtime.turn("Say hello.")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
`;
}

const PYTHON_EXTRAS: Record<string, string> = {
  openai: "kaji[openai]",
  anthropic: "kaji[anthropic]",
  gemini: "kaji[gemini]",
  kimi: "kaji",
};

function resolvePythonRequirement(provider: string): string {
  const requirement = PYTHON_EXTRAS[provider];
  if (requirement) return requirement;
  throw new Error(
    `Unknown provider '${provider}'. Supported: ${Object.keys(PYTHON_EXTRAS).join(", ")}.`,
  );
}

export function pyRequirementsTemplate(provider: string): string {
  return `${resolvePythonRequirement(provider)}>=0.1.0\n`;
}

export function pyEnvTemplate(provider: string): string {
  return `# kaji
KAJI_MODEL_PROVIDER=${provider}

# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...
# KIMI_API_KEY=...
`;
}
