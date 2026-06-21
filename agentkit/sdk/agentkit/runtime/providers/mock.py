"""Mock model provider for tests and zero-dependency local runs."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from agentkit.runtime.providers.registry import register_provider
from agentkit.runtime.providers.types import GenerateResponse, ModelResponseChunk


def _tool_already_called(messages: List[Dict[str, Any]]) -> bool:
    """True once a tool result is present in the history.

    Lets the mock drive a full request -> execute -> continue loop and then
    terminate: it asks for a tool on the first pass, then replies with plain
    text once the result comes back.
    """
    return any(msg.get("role") == "tool" for msg in messages)


class MockProvider:
    """Returns canned responses without calling external APIs.

    When ``tools`` are offered and none have been called yet, it requests the
    first tool so the agent loop's tool path is exercised; otherwise it returns
    a plain-text response.
    """

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
    ) -> GenerateResponse:
        _ = (
            system_instruction,
            temperature,
            max_tokens,
            response_format,
            cancellation_token,
        )
        if tools and not _tool_already_called(messages):
            return GenerateResponse(
                text="", tool_calls=cast(Any, [_first_tool_call(tools)])
            )
        return GenerateResponse(text="mock response", tool_calls=[])

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        _ = (system_instruction, temperature, max_tokens, cancellation_token)
        if tools and not _tool_already_called(messages):
            yield ModelResponseChunk(
                delta="", tool_calls=cast(Any, [_first_tool_call(tools)])
            )
            return
        yield ModelResponseChunk(delta="mock")


def _first_tool_call(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a canned call for the first offered tool."""
    name = tools[0].get("name", "unknown")
    return {"id": "mock-call-1", "name": name, "arguments": {}}


register_provider("mock", MockProvider)
