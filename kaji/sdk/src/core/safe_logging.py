"""Best-effort logging for failure-isolation paths."""

from __future__ import annotations

import logging
from typing import Any


def log_no_throw(
    logger: logging.Logger,
    level: int,
    message: str,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Never let a broken logging handler replace the operation outcome."""
    try:
        logger.log(level, message, *args, **kwargs)
    except Exception:
        return


__all__ = ["log_no_throw"]
