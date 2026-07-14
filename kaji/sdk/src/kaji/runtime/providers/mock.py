"""Mock model provider for tests and zero-dependency local runs."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from kaji.runtime.providers.base import (
    ProviderResponseBudget,
    capture_provider_diagnostics,
)
from kaji.runtime.providers.registry import register_provider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderResponseLimits,
)

FINAL_TEXT = "mock response"


def _tool_already_called(messages: List[Dict[str, Any]]) -> bool:
    """True once a tool result is present in the history.

    Lets the mock drive a full request -> execute -> continue loop and then
    terminate: it asks for a tool on the first pass, then replies with plain
    text once the result comes back.
    """
    return any(msg.get("role") == "tool" for msg in messages)


class MockProvider:
    """Returns canned responses without calling external APIs.

    Default behavior (no options): if ``tools`` are offered and none have been
    called yet, it requests the first tool so the agent loop's tool path is
    exercised; otherwise it returns a plain-text response.

    Options (mutually exclusive):
        reply: literal text to return as the response.
        tool_call: ``{"name": str, "args": dict}``. Returns one canned tool
            call on the first turn; falls through to the terminal text once
            a tool result is present in history (so the loop terminates).
    """

    def __init__(
        self,
        *,
        reply: Optional[str] = None,
        tool_call: Optional[Dict[str, Any]] = None,
    ) -> None:
        if reply is not None and tool_call is not None:
            raise ValueError("MockProvider: pass reply OR tool_call, not both.")
        self._reply = reply
        self._tool_call = tool_call

    def _scripted_tool_call(self) -> Dict[str, Any]:
        assert self._tool_call is not None
        return {
            "id": "mock-call-1",
            "name": self._tool_call["name"],
            "arguments": self._tool_call.get("args", {}),
        }

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> GenerateResponse:
        _ = (
            system_instruction,
            temperature,
            max_tokens,
            response_format,
            cancellation_token,
        )
        if self._tool_call is not None:
            if not _tool_already_called(messages):
                response = GenerateResponse(
                    text="", tool_calls=cast(Any, [self._scripted_tool_call()])
                )
            else:
                response = GenerateResponse(text=FINAL_TEXT, tool_calls=[])
        elif self._reply is not None:
            response = GenerateResponse(text=self._reply, tool_calls=[])
        elif tools and not _tool_already_called(messages):
            response = GenerateResponse(
                text="", tool_calls=cast(Any, [_first_tool_call(tools)])
            )
        else:
            response = GenerateResponse(text=FINAL_TEXT, tool_calls=[])
        accepted = ProviderResponseBudget(response_limits).accept_normalized(
            response.text, response.tool_calls
        )
        return response.model_copy(
            update={
                "text": accepted.delta,
                "tool_calls": list(accepted.tool_calls),
            }
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        _ = (system_instruction, temperature, max_tokens, cancellation_token)
        budget = ProviderResponseBudget(response_limits)
        if self._tool_call is not None:
            if not _tool_already_called(messages):
                accepted = budget.accept_normalized(
                    "", cast(Any, [self._scripted_tool_call()])
                )
                yield ModelResponseChunk(tool_calls=list(accepted.tool_calls))
                capture_provider_diagnostics(budget.diagnostics)
                return
            accepted = budget.accept_normalized(FINAL_TEXT, [])
            yield ModelResponseChunk(delta=accepted.delta)
            capture_provider_diagnostics(budget.diagnostics)
            return
        if self._reply is not None:
            accepted = budget.accept_normalized(self._reply, [])
            yield ModelResponseChunk(delta=accepted.delta)
            capture_provider_diagnostics(budget.diagnostics)
            return
        if tools and not _tool_already_called(messages):
            accepted = budget.accept_normalized(
                "", cast(Any, [_first_tool_call(tools)])
            )
            yield ModelResponseChunk(tool_calls=list(accepted.tool_calls))
            capture_provider_diagnostics(budget.diagnostics)
            return
        accepted = budget.accept_normalized("mock", [])
        yield ModelResponseChunk(delta=accepted.delta)
        capture_provider_diagnostics(budget.diagnostics)


def _first_tool_call(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a canned call for the first offered tool."""
    name = tools[0].get("name", "unknown")
    return {"id": "mock-call-1", "name": name, "arguments": {}}


register_provider("mock", MockProvider)
