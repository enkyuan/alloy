export function pyAgentTemplate(provider: string): string {
  return `"""Minimal kaji scaffold."""

from __future__ import annotations

import asyncio
import os

import kaji


async def main() -> None:
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()
    provider_name = os.environ.get("KAJI_MODEL_PROVIDER", ${JSON.stringify(provider)})
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider(provider_name))
        .system_prompt("You are a helpful assistant.")
        .build(bus=bus, store=store)
    )
    await store.append(kaji.UserMessage(session_id="s1", content="Hello!"))
    await runtime.run_turn("s1")
    for e in await store.get_events("s1"):
        print(e.type, getattr(e, "content", getattr(e, "delta", "")))


if __name__ == "__main__":
    asyncio.run(main())
`;
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
