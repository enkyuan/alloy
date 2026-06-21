import asyncio
import sys
from typing import Collection, Union

if sys.version_info < (3, 11):

    class ExceptionGroup(Exception):
        """Simple ExceptionGroup implementation for Python < 3.11"""

        def __init__(self, message: str, exceptions: list):
            self.message = message
            self.exceptions = exceptions
            super().__init__(message)


async def cancel_tasks_safe(
    tasks: Union[asyncio.Task, Collection[asyncio.Task]],
) -> None:
    """Cancel an asyncio task safely."""
    active_tasks = _get_active_tasks(tasks)

    # Send message to cancel all tasks.
    for task in active_tasks:
        # Calling cancel on a task multiple times is ok because it is idempotent.
        task.cancel()

    results = await asyncio.gather(*active_tasks, return_exceptions=True)
    _raise_if_task_errors(results)


async def await_tasks_safe(
    tasks: Union[asyncio.Task, Collection[asyncio.Task]],
) -> None:
    """Wait for an asyncio task to complete.

    If the task is cancelled, do not raise an exception.
    """
    active_tasks = _get_active_tasks(tasks)
    results = await asyncio.gather(*active_tasks, return_exceptions=True)
    _raise_if_task_errors(results)


def _get_active_tasks(
    tasks: Union[asyncio.Task, Collection[asyncio.Task]],
) -> list[asyncio.Task]:
    if isinstance(tasks, asyncio.Task):
        tasks = [tasks]
    return [task for task in tasks if task and not task.done()]


def _raise_if_task_errors(results: list[object]) -> None:
    errors = [
        result
        for result in results
        if isinstance(result, Exception)
        and not isinstance(result, asyncio.CancelledError)
    ]
    if errors:
        raise ExceptionGroup(
            "Multiple errors occurred during task cancellation", errors
        )


CancelTasksSafe = cancel_tasks_safe
AwaitTasksSafe = await_tasks_safe
