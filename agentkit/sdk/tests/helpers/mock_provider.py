"""Test-only mock LLM provider — not part of the public SDK."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.providers.types import GenerateResponse, ModelResponseChunk


def _tool_already_called(messages: List[Dict[str, Any]]) -> bool:
    return any(msg.get("role") == "tool" for msg in messages)


class MockProvider(ModelProvider):
    """Returns canned responses without calling external APIs.

    When tools are offered and none have been called yet, it requests the first
    tool so the agent loop's tool path is exercised; otherwise returns plain text.
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


_JSON_TYPE_PLACEHOLDERS: Dict[str, Any] = {
    "string": "mock",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
    "null": None,
}


def _placeholder_args(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Build args that satisfy the tool's JSON Schema 'required' + property types."""
    props = parameters.get("properties") or {}
    required = parameters.get("required") or []
    args: Dict[str, Any] = {}
    for key in required:
        prop = props.get(key, {}) if isinstance(props.get(key, {}), dict) else {}
        args[key] = _JSON_TYPE_PLACEHOLDERS.get(prop.get("type", "string"), "mock")
    return args


def _first_tool_call(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    spec = tools[0]
    name = spec.get("name", "unknown")
    parameters = spec.get("parameters") or {}
    return {
        "id": "mock-call-1",
        "name": name,
        "arguments": _placeholder_args(parameters),
    }
