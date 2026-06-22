import asyncio


class CancelledError(asyncio.CancelledError):
    """Raised by :meth:`CancellationToken.raise_if_cancelled` when the
    token has been triggered. Subclasses :class:`asyncio.CancelledError`
    so callers can ``except asyncio.CancelledError`` uniformly across the
    SDK and asyncio's own cancellation machinery."""


class CancellationToken:
    """Token to coordinate cancellation across asynchronous boundaries.

    Wraps an :class:`asyncio.Event` so the token composes with asyncio's
    primitives. Use ``token.is_cancelled`` for cheap polling, ``await
    token.wait()`` to integrate with ``asyncio.wait_for`` / select-style
    races, and ``token.raise_if_cancelled()`` at yield points to fail
    fast with :class:`asyncio.CancelledError`.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        """Trigger the cancellation. Idempotent."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._event.is_set()

    @property
    def event(self) -> asyncio.Event:
        """The underlying :class:`asyncio.Event`. Useful for ``await
        token.event.wait()`` or composing with ``asyncio.wait`` to race
        the token against other futures."""
        return self._event

    async def wait(self) -> None:
        """Block until ``cancel()`` is called. Returns immediately if the
        token is already cancelled."""
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`asyncio.CancelledError` if the token is set.
        Use this at yield points (between I/O steps) to participate in
        asyncio's structured cancellation."""
        if self._event.is_set():
            raise CancelledError("Agent run was cancelled")
