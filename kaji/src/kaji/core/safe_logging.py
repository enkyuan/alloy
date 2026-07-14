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


def log_redacted_failure(
    logger: logging.Logger,
    level: int,
    message: str,
    error: BaseException,
    *,
    identifiers: dict[str, Any] | None = None,
) -> None:
    """Log only an exception type plus caller-selected stable identifiers."""
    fields = dict(identifiers or {})
    fields["error_type"] = type(error).__name__
    fields["error_details"] = "redacted"
    log_no_throw(
        logger,
        level,
        "%s (%s; details redacted)",
        message,
        type(error).__name__,
        extra=fields,
    )


__all__ = ["log_no_throw", "log_redacted_failure"]
