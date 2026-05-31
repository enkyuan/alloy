"""Mock model provider for tests."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from agentkit.providers.types import GenerateResponse, ModelResponseChunk


class MockProvider:
    """Returns canned responses without calling external APIs."""

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
        _ = (messages, tools, system_instruction, temperature, max_tokens, response_format, cancellation_token)
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
        _ = (messages, tools, system_instruction, temperature, max_tokens, cancellation_token)
        yield ModelResponseChunk(delta="mock")
