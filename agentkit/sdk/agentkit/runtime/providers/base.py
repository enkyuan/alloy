from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, TYPE_CHECKING

from agentkit.runtime.providers.types import GenerateResponse, ModelResponseChunk

if TYPE_CHECKING:
    from agentkit.runtime.agents.cancellation import CancellationToken


class ModelProvider(Protocol):
    """Abstract interface for LLM providers (e.g. Gemini, OpenAI, Kimi).

    Implementations translate the neutral message + tool payload to their
    own API at the boundary; the runtime never imports provider-specific
    types. ``cancellation_token`` is structurally typed: any object with an
    ``is_cancelled`` boolean attribute is accepted, but the canonical type
    is ``agentkit.runtime.agents.cancellation.CancellationToken``.
    """

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional["CancellationToken"] = None,
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
        cancellation_token: Optional["CancellationToken"] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        """Stream a response back given a set of messages and tools."""
        # The `...` + dummy `yield` are how Protocols declare an async-generator
        # return shape to the type checker without committing to a body. The
        # yield is unreachable at runtime.
        ...
        yield ModelResponseChunk()
