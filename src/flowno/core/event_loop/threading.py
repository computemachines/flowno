"""
Threading primitives for the Flowno event loop.

This module provides tools for running async code in separate threads while
maintaining communication with the main event loop. This enables blocking
operations (like `input()` or blocking I/O) to be performed without blocking
the main event loop.

Examples:
    Basic thread spawning:

    >>> from flowno.core.event_loop import EventLoop
    >>> from flowno.core.event_loop.threading import spawn_thread
    >>> from flowno.core.event_loop.queues import AsyncQueue
    >>> import time
    >>>
    >>> async def main():
    ...     queue = AsyncQueue()
    ...
    ...     # Spawn a worker thread
    ...     handle = spawn_thread(worker, args=(queue,))
    ...
    ...     # Receive results from the worker
    ...     results = []
    ...     async for item in queue:
    ...         results.append(item)
    ...
    ...     # Wait for the thread to finish
    ...     await handle.join()
    ...     return results
    ...
    >>> async def worker(queue: AsyncQueue):
    ...     for i in range(3):
    ...         time.sleep(0.1)  # Blocking operation
    ...         await queue.put(i)
    ...     await queue.close()
    >>>
    >>> loop = EventLoop()
    >>> loop.run_until_complete(main(), join=True)
    [0, 1, 2]
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Generic, TypeVar, TYPE_CHECKING
from types import coroutine
from typing import Generator

from flowno.core.event_loop.commands import Command
from flowno.core.event_loop.types import RawTask
from flowno.core.event_loop.synchronization import Event

if TYPE_CHECKING:
    from flowno.core.event_loop.event_loop import EventLoop

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class ThreadHandle(Generic[_T]):
    """
    A handle for managing a spawned thread running an async function.

    This handle allows the calling code to wait for the thread to complete
    and retrieve its result or exception.

    The join() method uses a Flowno Event for efficient cross-thread
    notification, avoiding polling overhead.

    Attributes:
        thread: The underlying Python thread
        result: The result of the async function (set when complete)
        exception: Any exception raised by the async function
    """

    def __init__(self, thread: threading.Thread) -> None:
        """
        Initialize a ThreadHandle.

        Args:
            thread: The thread being managed
        """
        self._thread = thread
        self._result: _T | None = None
        self._exception: BaseException | None = None
        # Use Flowno Event for cross-thread notification (no polling!)
        self._completed_event = Event()
        # Also keep threading.Event for synchronous checking
        self._completed_threading = threading.Event()
        # Store the calling event loop when join() is first called
        self._caller_loop: "EventLoop | None" = None

    @property
    def thread(self) -> threading.Thread:
        """Get the underlying thread."""
        return self._thread

    @property
    def is_alive(self) -> bool:
        """Check if the thread is still running."""
        return self._thread.is_alive()

    @property
    def is_finished(self) -> bool:
        """Check if the thread has completed."""
        return self._completed_threading.is_set()

    @property
    def is_error(self) -> bool:
        """Check if the thread completed with an exception."""
        return self._completed_threading.is_set() and self._exception is not None

    def _set_result(self, result: _T, source_loop: "EventLoop") -> None:
        """Set the result and mark as completed. Called by the thread."""
        self._result = result
        self._completed_threading.set()
        # Signal the Flowno Event, waking any waiters across threads
        if self._caller_loop is not None:
            all_waiters = self._completed_event.set_nowait(source_loop)
            # Wake all waiters
            for loop, waiters in all_waiters.items():
                # Decrement the waiting counter for woken tasks
                loop._waiting_on_sync_primitives -= len(waiters)
                for waiter in waiters:
                    # Cancel any pending timeout for this waiter
                    if waiter in loop._event_wait_timeouts:
                        loop._event_wait_timeouts[waiter]["cancelled"] = True
                        del loop._event_wait_timeouts[waiter]
                with loop._tasks_lock:
                    for waiter in waiters:
                        loop.tasks.append((waiter, True, None))  # True = event was set
                try:
                    loop._wakeup_writer.send(b"\x00")
                except (BlockingIOError, OSError):
                    pass
        else:
            # No caller loop yet, just mark as set
            self._completed_event._set = True

    def _set_exception(self, exception: BaseException, source_loop: "EventLoop") -> None:
        """Set the exception and mark as completed. Called by the thread."""
        self._exception = exception
        self._completed_threading.set()
        # Signal the Flowno Event, waking any waiters across threads
        if self._caller_loop is not None:
            all_waiters = self._completed_event.set_nowait(source_loop)
            # Wake all waiters
            for loop, waiters in all_waiters.items():
                # Decrement the waiting counter for woken tasks
                loop._waiting_on_sync_primitives -= len(waiters)
                for waiter in waiters:
                    # Cancel any pending timeout for this waiter
                    if waiter in loop._event_wait_timeouts:
                        loop._event_wait_timeouts[waiter]["cancelled"] = True
                        del loop._event_wait_timeouts[waiter]
                with loop._tasks_lock:
                    for waiter in waiters:
                        loop.tasks.append((waiter, True, None))  # True = event was set
                try:
                    loop._wakeup_writer.send(b"\x00")
                except (BlockingIOError, OSError):
                    pass
        else:
            # No caller loop yet, just mark as set
            self._completed_event._set = True

    async def join(self, timeout: float | None = None) -> _T:
        """
        Wait for the thread to complete and return its result.

        This method uses a cross-thread Event for efficient notification,
        avoiding polling overhead. The calling task is suspended until
        the thread completes, without busy-waiting.

        Args:
            timeout: Maximum time to wait in seconds. If None, wait indefinitely.

        Returns:
            The result of the async function run in the thread.

        Raises:
            TimeoutError: If timeout is reached before the thread completes.
            Exception: Any exception raised by the thread's async function.
        """
        from flowno.core.event_loop.event_loop import current_event_loop

        # Record the caller's event loop so the worker thread can wake it
        self._caller_loop = current_event_loop()

        # Wait for the thread to complete, with optional timeout
        completed = await self._completed_event.wait(timeout=timeout)

        if not completed:
            raise TimeoutError(f"Thread did not complete within {timeout} seconds")

        if self._exception is not None:
            raise self._exception

        return self._result  # type: ignore[return-value]


def spawn_thread(
    target: Callable[..., RawTask[Command, Any, _T]],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    daemon: bool = True,
) -> ThreadHandle[_T]:
    """
    Spawn a new thread running an async function with its own event loop.

    This function creates a new thread with its own Flowno EventLoop, runs
    the specified async function in that thread, and returns a handle for
    managing the thread.

    The async function can communicate with the main event loop's tasks
    through AsyncQueues that are passed as arguments.

    Args:
        target: An async function to run in the new thread. This function
                should return a coroutine (like any async def function).
        args: Positional arguments to pass to the target function.
        kwargs: Keyword arguments to pass to the target function.
        daemon: If True (default), the thread will be a daemon thread and
                will be terminated when the main program exits.

    Returns:
        A ThreadHandle that can be used to wait for the thread to complete
        and retrieve its result.

    Examples:
        >>> from flowno import EventLoop, AsyncQueue
        >>> from flowno.core.event_loop.threading import spawn_thread
        >>> import time
        >>>
        >>> async def worker(queue: AsyncQueue, count: int):
        ...     for i in range(count):
        ...         time.sleep(0.1)  # Simulate blocking work
        ...         await queue.put(i * 2)
        ...     await queue.close()
        ...     return "done"
        >>>
        >>> async def main():
        ...     queue = AsyncQueue()
        ...     handle = spawn_thread(worker, args=(queue, 5))
        ...
        ...     results = []
        ...     async for item in queue:
        ...         results.append(item)
        ...
        ...     result = await handle.join()
        ...     return results, result
        >>>
        >>> loop = EventLoop()
        >>> loop.run_until_complete(main(), join=True)
        ([0, 2, 4, 6, 8], 'done')
    """
    from flowno.core.event_loop.event_loop import EventLoop

    if kwargs is None:
        kwargs = {}

    handle: ThreadHandle[_T] = ThreadHandle(threading.Thread())  # Placeholder

    def thread_runner() -> None:
        """Run the async function in a new event loop."""
        loop = EventLoop()
        try:
            # Create the coroutine by calling the target function
            coro = target(*args, **kwargs)
            # Run it in the event loop
            result = loop.run_until_complete(coro, join=True)
            handle._set_result(result, loop)
        except BaseException as e:
            logger.exception(f"Thread raised exception: {e}")
            handle._set_exception(e, loop)

    thread = threading.Thread(target=thread_runner, daemon=daemon)
    handle._thread = thread
    thread.start()

    return handle


__all__ = [
    "ThreadHandle",
    "spawn_thread",
]
