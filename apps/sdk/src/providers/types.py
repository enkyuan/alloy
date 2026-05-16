from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
