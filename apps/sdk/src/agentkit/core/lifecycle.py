"""Shared service lifecycle registry for app shutdown cleanup."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

AsyncCloser = Callable[[], Awaitable[None]]

_REGISTERED_CLOSERS: dict[str, AsyncCloser] = {}


def register_close_handler(name: str, closer: AsyncCloser) -> None:
    """Register or replace a named async closer."""
    _REGISTERED_CLOSERS[name] = closer


async def close_registered_services() -> None:
    """Close registered services in reverse registration order."""
    for name, closer in reversed(list(_REGISTERED_CLOSERS.items())):
        try:
            await closer()
        except Exception:
            logger.exception("Failed to close registered service %s", name)
