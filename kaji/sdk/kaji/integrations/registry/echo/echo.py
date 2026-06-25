"""Echo integration. The simplest possible Kaji integration.

Two pure functions, no auth, no network. Installed by `kaji add echo`.
"""

from __future__ import annotations

import kaji


@kaji.function_tool(description="Return the input string unchanged.", risk="read")
async def say(message: str) -> dict:
    return {"message": message}


@kaji.function_tool(description="Return the input string uppercased.", risk="read")
async def shout(message: str) -> dict:
    return {"message": message.upper()}
