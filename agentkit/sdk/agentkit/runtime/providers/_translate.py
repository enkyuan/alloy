"""Shared role normalization for all model providers.

Keeps role mapping in one place so a fix propagates everywhere instead of
requiring a per-provider patch.
"""

from __future__ import annotations

# Gemini uses "model" where every other provider uses "assistant".
_ALIASES: dict[str, str] = {
    "model": "assistant",
}

# The set of canonical roles the SDK uses internally.
_CANONICAL = {"user", "assistant", "tool", "system"}


def normalize_role(role: str) -> str:
    """Map a provider-specific role string to a canonical SDK role.

    Recognised aliases
    ------------------
    * ``"model"`` (Gemini) -> ``"assistant"``

    Unknown roles are returned unchanged so callers can decide how to handle
    them (log a warning, raise, or pass through to the provider).
    """
    return _ALIASES.get(role, role)


def to_gemini_role(role: str) -> str:
    """Map a canonical SDK role to Gemini's expected role string.

    Gemini expects ``"model"`` where the SDK uses ``"assistant"``.
    """
    canonical = normalize_role(role)
    if canonical == "assistant":
        return "model"
    return canonical
