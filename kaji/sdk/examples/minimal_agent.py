"""Minimal Kaji agent — Python hello-world.

Prerequisites:
    uv sync --extra openai
    export OPENAI_API_KEY=sk-...

Run:
    uv run python -m examples.minimal_agent
"""

from __future__ import annotations

import asyncio
import os

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents import AgentBuilder, TurnContext
from kaji.runtime.integrations import function_tool
from kaji.runtime.providers.openai import OpenAIProvider


@function_tool(description="Return current weather for a city.", risk="read")
async def get_weather(city: str) -> dict:
    return {"city": city, "tempF": 68}


async def main() -> None:
    runtime = (
        AgentBuilder()
        .provider(OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"]))
        .tool(get_weather)
        .default_context(TurnContext(principal_id="quickstart"))
        .system_prompt("You are a weather assistant.")
        .build(bus=InMemoryEventBus(), store=InMemoryEventStore())
    )
    result = await runtime.turn("What is the weather in Seattle?")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
