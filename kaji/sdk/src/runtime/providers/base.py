from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, TYPE_CHECKING

from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderMessage,
    ProviderToolSpec,
)

if TYPE_CHECKING:
    from kaji.runtime.agents.cancellation import CancellationToken


# Re-export the neutral payload shapes here so callers can write
# ``from kaji.runtime.providers.base import ProviderMessage``. The
# Protocol signature stays on ``List[Dict[str, Any]]`` because the runtime
# and the existing concrete providers operate on plain dicts; the TypedDicts
# are documentation + opt-in typing for callers who want it.
__all__ = ["ModelProvider", "ProviderMessage", "ProviderToolSpec"]


class ModelProvider(Protocol):
    """Abstract interface for LLM providers (e.g. Gemini, OpenAI, Kimi).

    Implementations translate the neutral message + tool payload to their
    own API at the boundary; the runtime never imports provider-specific
    types.

    The runtime sends plain ``dict`` messages and tool specs that conform
    to :class:`ProviderMessage` and :class:`ProviderToolSpec` (see
    ``kaji.runtime.providers.types``). Callers that want compile-time
    checking can construct those TypedDicts; the Protocol stays loose so
    duck-typed dicts flow through without ceremony.

    ``cancellation_token`` is structurally typed: any object with an
    ``is_cancelled`` boolean attribute is accepted, but the canonical type
    is ``kaji.runtime.agents.cancellation.CancellationToken``.

    Custom providers are cooperative cancellation boundaries. Both methods
    must observe ``cancellation_token`` while opening and streaming, stop the
    underlying request, and let the returned iterator settle when cancellation
    is requested. Missing the configured grace raises a typed contract
    violation and quarantines the session until ``drain_providers()`` succeeds.
    A custom adapter must pass the SDK cancellation-contract suite before it is
    described as production-safe.
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
