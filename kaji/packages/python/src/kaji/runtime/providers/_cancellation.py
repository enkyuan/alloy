"""Shared cancellation helper for model providers.

Providers accept an opaque ``cancellation_token`` so callers can plug in any
compatible token type. The SDK's own
:class:`kaji.runtime.agents.cancellation.CancellationToken` exposes a
``raise_if_cancelled()`` method that raises its own
:class:`asyncio.CancelledError` subclass for discoverability; we prefer it
when present and fall back to the duck-typed ``is_cancelled`` attribute.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional


def raise_if_cancelled(token: Optional[Any]) -> None:
    """Raise :class:`asyncio.CancelledError` if ``token`` reports cancellation.

    Prefers the token's own ``raise_if_cancelled()`` method, then falls back
    to the ``is_cancelled`` attribute. ``None`` is a no-op so providers can
    pass through their optional ``cancellation_token`` argument unchanged.
    """
    if token is None:
        return
    raise_if = getattr(token, "raise_if_cancelled", None)
    if callable(raise_if):
        raise_if()
        return
    if getattr(token, "is_cancelled", False):
        raise asyncio.CancelledError()
