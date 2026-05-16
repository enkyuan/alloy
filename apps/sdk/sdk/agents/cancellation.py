import asyncio


class CancellationToken:
    """Token to coordinate cancellation across asynchronous boundaries."""

    def __init__(self):
        self._event = asyncio.Event()

    def cancel(self) -> None:
        """Trigger the cancellation."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._event.is_set()
