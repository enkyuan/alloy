"""Echo integration. The simplest possible Kaji integration.

Two pure functions, no auth, no network. Installed by `kaji add echo`.
"""

from __future__ import annotations

import kaji


def _message_parameters() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }


@kaji.function_tool(
    description="Return the input string unchanged.",
    parameters=_message_parameters(),
    risk="read",
    namespace="echo",
    parallel_safe=False,
)
async def say(message: str) -> dict:
    return {"message": message}


@kaji.function_tool(
    description="Return the input string uppercased.",
    parameters=_message_parameters(),
    risk="read",
    namespace="echo",
    parallel_safe=False,
)
async def shout(message: str) -> dict:
    return {"message": message.upper()}


tools = (say, shout)
