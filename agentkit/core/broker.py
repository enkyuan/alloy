"""
Taskiq configuration for background job processing.
"""

from functools import lru_cache
from typing import Any

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from agentkit.core.config import get_settings


@lru_cache(maxsize=1)
def get_broker() -> ListQueueBroker:
    """Return the process-wide Taskiq broker, built on first use.

    Deferred (rather than created at import time) so importing this module does
    not require ``REDIS_URL``. The Taskiq CLI target ``agentkit.core.broker:broker``
    still resolves: ``broker`` is provided lazily via module ``__getattr__``.
    """
    settings = get_settings()
    return ListQueueBroker(
        url=settings.REDIS_URL,
        queue_name="default",
    ).with_result_backend(
        RedisAsyncResultBackend(redis_url=settings.REDIS_URL)
    )


def __getattr__(name: str) -> Any:
    # PEP 562: resolve ``broker`` lazily so `taskiq worker agentkit.core.broker:broker`
    # (which does getattr(module, "broker")) works without building it at import.
    if name == "broker":
        return get_broker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Define queues
QUEUE_HIGH_PRIORITY = "queue:high_priority"
QUEUE_BACKGROUND = "queue:background"
