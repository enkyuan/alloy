"""Shared Gemini response function-call extraction helpers."""

from typing import Any


def extract_response_function_calls(response: Any) -> list[Any]:
    """Return function_call parts from a Gemini response object."""
    function_calls: list[Any] = []
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return function_calls

    candidate = candidates[0]
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None)
    if not parts:
        return function_calls

    for part in parts:
        function_call = getattr(part, "function_call", None)
        if function_call:
            function_calls.append(function_call)
    return function_calls
