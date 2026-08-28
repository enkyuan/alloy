import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
import math
from typing import Any, Generic, TypeVar

from kaji.runtime.agents.limits import (
    ProviderCancellationContractViolation,
    TurnTimeoutError,
)
from kaji.core.determinism import Clock, TimerScheduler


T = TypeVar("T")


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


class ProviderDeadlineScope(Generic[T]):
    """Own one provider iterator, deadline timer, and cooperative shutdown."""

    def __init__(
        self,
        *,
        parent: CancellationToken,
        deadline_monotonic: float,
        cancellation_grace_seconds: float,
        clock: Clock,
        scheduler: TimerScheduler,
    ) -> None:
        if isinstance(deadline_monotonic, bool) or not isinstance(
            deadline_monotonic, (int, float)
        ):
            raise TypeError("deadline_monotonic must be a finite non-negative number")
        if not math.isfinite(float(deadline_monotonic)) or deadline_monotonic < 0:
            raise ValueError("deadline_monotonic must be a finite non-negative number")
        if isinstance(cancellation_grace_seconds, bool) or not isinstance(
            cancellation_grace_seconds, (int, float)
        ):
            raise TypeError("cancellation_grace_seconds must be a positive number")
        if (
            not math.isfinite(float(cancellation_grace_seconds))
            or cancellation_grace_seconds <= 0
        ):
            raise ValueError("cancellation_grace_seconds must be a positive number")
        self.parent = parent
        self.token = CancellationToken()
        self.deadline_monotonic = deadline_monotonic
        self.cancellation_grace_seconds = cancellation_grace_seconds
        self.clock = clock
        self.scheduler = scheduler
        self._parent_wait: asyncio.Task[None] | None = None
        self._deadline_wait: asyncio.Future[None] | None = None
        self._deadline_timer: Any = None
        self._iterator: AsyncIterator[T] | None = None
        self._active_next: asyncio.Task[T] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._transferred = False
        self._yielded = False
        self._dispatched = False
        self._cancellation_requested_at: float | None = None
        self._cancellation_source: str | None = None

    async def __aenter__(self) -> "ProviderDeadlineScope[T]":
        loop = asyncio.get_running_loop()
        self._parent_wait = asyncio.create_task(self.parent.wait())
        self._deadline_wait = loop.create_future()
        self._deadline_timer = self.scheduler.call_later(
            max(0.0, self.deadline_monotonic - self.clock.now_monotonic()),
            self._request_deadline_cancellation,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self._transferred:
            await self._finish_close()
        if self._deadline_timer is not None:
            self._deadline_timer.cancel()
        if self._parent_wait is not None:
            self._parent_wait.cancel()
            with suppress(asyncio.CancelledError):
                await self._parent_wait
        if self._deadline_wait is not None and not self._deadline_wait.done():
            self._deadline_wait.cancel()

    async def consume(self, stream: Any) -> AsyncIterator[T]:
        iterator = stream.__aiter__()
        self._iterator = iterator
        provider_error: BaseException | None = None
        try:
            while True:
                if self.parent.is_cancelled:
                    await self._abort(caller_cancelled=True, source="parent")
                if self.clock.now_monotonic() >= self.deadline_monotonic:
                    await self._abort(caller_cancelled=False, source="deadline")
                if self.token.is_cancelled and self._cancellation_source is None:
                    await self._abort(caller_cancelled=True, source="provider")

                settled_at: float | None = None
                settled_source: str | None = None
                settled_parent_cancelled = False
                settled_token_cancelled = False

                async def next_with_evidence() -> T:
                    nonlocal settled_at
                    nonlocal settled_source
                    nonlocal settled_parent_cancelled
                    nonlocal settled_token_cancelled
                    try:
                        return await iterator.__anext__()
                    finally:
                        settled_at = self.clock.now_monotonic()
                        settled_source = self._cancellation_source
                        settled_parent_cancelled = self.parent.is_cancelled
                        settled_token_cancelled = self.token.is_cancelled

                self._dispatched = True
                next_task = asyncio.create_task(next_with_evidence())
                self._active_next = next_task
                assert self._parent_wait is not None
                assert self._deadline_wait is not None
                await asyncio.wait(
                    {next_task, self._parent_wait, self._deadline_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if next_task.done() and not next_task.cancelled():
                    provider_exception = next_task.exception()
                    if provider_exception is not None and not isinstance(
                        provider_exception, StopAsyncIteration
                    ):
                        assert settled_at is not None
                        if (
                            settled_parent_cancelled or settled_source == "parent"
                        ) and (
                            isinstance(provider_exception, asyncio.CancelledError)
                            or type(provider_exception).__name__ == "AbortError"
                        ):
                            await self._abort(caller_cancelled=True, source="parent")
                        if (
                            settled_source == "deadline"
                            or settled_at >= self.deadline_monotonic
                        ):
                            await self._abort(
                                caller_cancelled=False,
                                source="deadline",
                            )
                        if settled_source == "provider" or (
                            settled_token_cancelled and settled_source is None
                        ):
                            await self._abort(caller_cancelled=True, source="provider")
                        self._active_next = None
                        raise provider_exception

                # Explicit priority for control signals: caller, then deadline.
                if self.parent.is_cancelled:
                    await self._abort(caller_cancelled=True, source="parent")
                if self._deadline_wait.done() or (
                    self.clock.now_monotonic() >= self.deadline_monotonic
                ):
                    await self._abort(caller_cancelled=False, source="deadline")
                if self.token.is_cancelled and self._cancellation_source is None:
                    await self._abort(caller_cancelled=True, source="provider")

                try:
                    chunk = next_task.result()
                except StopAsyncIteration:
                    self._active_next = None
                    return
                self._active_next = None
                self._yielded = True
                yield chunk
        except ProviderCancellationContractViolation:
            self._transferred = True
            raise
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                await self._abort(caller_cancelled=True, source="external")
            raise
        except BaseException as error:
            provider_error = error
            raise
        finally:
            if not self._transferred:
                try:
                    await self._finish_close()
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling() > 0:
                        await self._abort(caller_cancelled=True, source="external")
                        raise
                    if provider_error is None:
                        raise
                except ProviderCancellationContractViolation as close_error:
                    if provider_error is not None:
                        raise close_error from provider_error
                    raise
                except BaseException:
                    if provider_error is None:
                        raise

    async def _abort(self, *, caller_cancelled: bool, source: str) -> None:
        self._request_cancellation(source)
        active = self._active_next
        if active is not None and not active.done():
            active.cancel()

        cleanup = asyncio.create_task(self._settle_and_close(active))
        grace_wait = asyncio.get_running_loop().create_future()
        requested_at = self._cancellation_requested_at
        assert requested_at is not None
        timer = self.scheduler.call_later(
            max(
                0.0,
                requested_at
                + self.cancellation_grace_seconds
                - self.clock.now_monotonic(),
            ),
            lambda: grace_wait.set_result(None) if not grace_wait.done() else None,
        )
        try:
            await asyncio.wait(
                {cleanup, grace_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cleanup.done():
                try:
                    cleanup.result()
                except BaseException:
                    self._transferred = True
                    raise ProviderCancellationContractViolation(
                        settlement=cleanup,
                        phase="provider_stream" if self._yielded else "provider_open",
                    )
                if caller_cancelled:
                    raise CancelledError("Agent run was cancelled")
                raise TurnTimeoutError(
                    phase="provider_stream" if self._yielded else "provider_open",
                    retryable=True,
                    outcome="unknown" if self._dispatched else "not_started",
                )
            self._transferred = True
            raise ProviderCancellationContractViolation(
                settlement=cleanup,
                phase="provider_stream" if self._yielded else "provider_open",
            )
        finally:
            timer.cancel()
            if not grace_wait.done():
                grace_wait.cancel()

    def _request_cancellation(self, source: str) -> None:
        if self._cancellation_requested_at is None:
            self._cancellation_requested_at = self.clock.now_monotonic()
        if self._cancellation_source is None:
            self._cancellation_source = source
        self.token.cancel()

    def _request_deadline_cancellation(self) -> None:
        self._request_cancellation("deadline")
        if self._deadline_wait is not None and not self._deadline_wait.done():
            self._deadline_wait.set_result(None)

    async def _settle_and_close(self, active: asyncio.Task[T] | None) -> None:
        if active is not None:
            with suppress(BaseException):
                await active
            if self._active_next is active:
                self._active_next = None
        await self._close_once()

    async def _close_once(self) -> None:
        if self._iterator is None:
            return
        if self._close_task is None:

            async def close_serialized() -> None:
                active = self._active_next
                if active is not None and not active.done():
                    with suppress(BaseException):
                        await active
                close = getattr(self._iterator, "aclose", None)
                if callable(close):
                    await close()

            self._close_task = asyncio.create_task(close_serialized())
        await self._close_task

    async def _finish_close(self) -> None:
        if self._iterator is None:
            return
        close_task = asyncio.create_task(self._close_once())
        assert self._parent_wait is not None
        assert self._deadline_wait is not None
        await asyncio.wait(
            {close_task, self._parent_wait, self._deadline_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if close_task.done():
            try:
                close_task.result()
            except BaseException:
                self._transferred = True
                raise ProviderCancellationContractViolation(
                    settlement=close_task,
                    phase="provider_stream" if self._yielded else "provider_open",
                )
            return
        if self.parent.is_cancelled:
            await self._abort(caller_cancelled=True, source="parent")
        if self._deadline_wait.done() or (
            self.clock.now_monotonic() >= self.deadline_monotonic
        ):
            await self._abort(caller_cancelled=False, source="deadline")
        await close_task
