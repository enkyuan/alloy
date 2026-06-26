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


class ModelResponseChunk(BaseModel):
    """A generic output chunk from an LLM provider."""

    delta: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)


class ModelMetadata(BaseModel):
    provider_name: str
    model_name: str


class TokenMetrics(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GenerateResponse(BaseModel):
    text: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Optional[ModelMetadata] = None
    metrics: Optional[TokenMetrics] = None
