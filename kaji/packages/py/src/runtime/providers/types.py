from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


# --- Neutral wire types between runtime and providers ------------------------
#
# These are TypedDicts (not Pydantic models) because providers receive plain
# dicts at the boundary and translate them per-API. A TypedDict lets the type
# checker enforce shape without paying for Pydantic validation on every turn.

# total=False because the optional keys depend on the role (tool_calls only
# on assistant, name/tool_call_id only on tool, etc.).
ProviderMessage = TypedDict(
    "ProviderMessage",
    {
        "role": Literal["system", "user", "assistant", "tool"],
        "content": str,
        # Set only on assistant turns that produced tool calls.
        "tool_calls": List[Dict[str, Any]],
        # Set only on tool-result turns.
        "name": str,
        "tool_call_id": str,
    },
    total=False,
)


class ProviderToolSpec(TypedDict):
    """Neutral tool payload providers see; each translates to its own
    function-tool format at the boundary."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResponseLimits:
    """Immutable bounds applied independently by providers and the runtime."""

    text_max_bytes: int = 262_144
    tool_arguments_max_bytes: int = 65_536
    response_max_bytes: int = 524_288
    tool_calls_max: int = 64

    def __post_init__(self) -> None:
        for name in (
            "text_max_bytes",
            "tool_arguments_max_bytes",
            "response_max_bytes",
            "tool_calls_max",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be a positive integer")
            if value < 1:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_PROVIDER_RESPONSE_LIMITS = ProviderResponseLimits()


class ModelMetadata(BaseModel):
    provider_name: str
    model_name: str


class TokenMetrics(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelResponseChunk(BaseModel):
    """A generic output chunk from an LLM provider."""

    delta: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Optional[TokenMetrics] = None
    cost_usd: Optional[float] = None


class GenerateResponse(BaseModel):
    text: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Optional[ModelMetadata] = None
    metrics: Optional[TokenMetrics] = None
    cost_usd: Optional[float] = None
