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
    if isinstance(tasks, asyncio.Task):
        tasks = [tasks]

    tasks = [task for task in tasks if task and not task.done()]

    # Send message to cancel all tasks.
    for task in tasks:
        # Calling cancel on a task multiple times is ok because it is idempotent.
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = []
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        elif isinstance(result, Exception):
            errors.append(results)
    if errors:
        raise ExceptionGroup("Multiple errors occurred during task cancellation", errors)


async def await_tasks_safe(
    tasks: Union[asyncio.Task, Collection[asyncio.Task]],
) -> None:
    """Wait for an asyncio task to complete.

    If the task is cancelled, do not raise an exception.
    """
    if isinstance(tasks, asyncio.Task):
        tasks = [tasks]

    tasks = [task for task in tasks if task and not task.done()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = []
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        elif isinstance(result, Exception):
            errors.append(results)
    if errors:
        raise ExceptionGroup("Multiple errors occurred during task cancellation", errors)
