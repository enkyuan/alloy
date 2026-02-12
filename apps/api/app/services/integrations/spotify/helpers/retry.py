"""Retry decorator for transient Spotify service failures."""

import asyncio
import logging
from functools import wraps
from typing import Any, Callable

from app.services.integrations.spotify.exceptions import (
    AuthenticationError,
    NoActiveDeviceError,
    PremiumRequiredError,
    SearchNoResultsError,
    SpotifyAPIError,
)

logger = logging.getLogger(__name__)


def retry_on_transient_error(max_retries: int = 2, delay: float = 1.0):
    """Decorator to retry operations on retryable Spotify API failures."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except SpotifyAPIError as error:
                    last_error = error

                    if not error.is_retryable or attempt >= max_retries:
                        raise

                    logger.warning(
                        "Transient error in %s, attempt %s/%s: %s",
                        func.__name__,
                        attempt + 1,
                        max_retries + 1,
                        str(error),
                    )
                    wait_time = delay * (2**attempt)
                    await asyncio.sleep(wait_time)
                except (
                    NoActiveDeviceError,
                    SearchNoResultsError,
                    PremiumRequiredError,
                    AuthenticationError,
                ):
                    raise
                except Exception as error:
                    last_error = error
                    raise

            if last_error:
                raise last_error

        return wrapper

    return decorator
