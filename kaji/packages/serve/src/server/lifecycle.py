"""Shared service lifecycle registry for app shutdown cleanup."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from kaji.core.safe_logging import log_redacted_failure

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
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Failed to close registered service",
                error,
                identifiers={"service": name},
            )
