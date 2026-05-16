from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol

from src.providers.types import GenerateResponse, ModelResponseChunk


class ModelProvider(Protocol):
    """Abstract interface for LLM providers (e.g. Gemini, OpenAI, Kimi)."""

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
        """Generate a complete response."""
        ...

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        """Stream a response back given a set of messages and tools."""
        ...
        yield ModelResponseChunk()
