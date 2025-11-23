"""
Task management for the Flowno event loop.

This module provides classes for creating, managing, and interacting with asynchronous 
tasks in the Flowno event loop. The main class is TaskHandle, which represents a 
spawned task and allows operations like cancellation and joining.

Examples:
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.primitives import spawn
    >>> 
    >>> async def worker():
    ...     # Some async work
    ...     return 42
    >>> 
    >>> async def main():
    ...     # Spawn a new task
    ...     task = await spawn(worker())
    ...     
    ...     # Check if it's a TaskHandle
    ...     print(f"task is a TaskHandle: {isinstance(task, TaskHandle)}")
    ...     
    ...     # Wait for the task to complete
    ...     result = await task.join()
    ...     print(f"Task result: {result}")
    ...     
    ...     return result
    >>> 
    >>> # Run the example
    >>> loop = EventLoop()
    >>> result = loop.run_until_complete(main(), join=True)
    task is a TaskHandle: True
    Task result: 42
    >>> print(result)
    42
"""

from collections.abc import Generator
from dataclasses import dataclass
from threading import Thread
from types import coroutine
from typing import TYPE_CHECKING, Generic, TypeVar, cast, final

from .types import RawTask

if TYPE_CHECKING:
    from .event_loop import EventLoop  # Only import during type checking
    from .queues import AsyncQueue

from .commands import Command, JoinCommand, ThreadException, ThreadResult

_T_co = TypeVar("_T_co", covariant=True)


@final
class TaskHandle(Generic[_T_co]):
    """
    A handle to a spawned task that allows cancellation and joining.
    
    TaskHandle objects are returned by the spawn primitive and represent
    concurrent tasks running in the event loop. They can be used to:
    
    - Check if a task has completed, failed, or been cancelled
    - Cancel a running task
    - Join (wait for) a task to complete and get its return value
    """

    def __init__(self, event_loop: "EventLoop", raw_task: RawTask[Command, object, _T_co]):
        """
        Initialize a TaskHandle.
        
        Args:
            event_loop: The event loop managing this task
            raw_task: The raw coroutine task being managed
        """
        self.event_loop = event_loop
        self.raw_task = raw_task

    def cancel(self) -> bool:
        """
        Cancel this task if it's still running.
        
        Returns:
            True if the task was successfully cancelled, False if it was
            already finished or had an error.
        """
        return self.event_loop.cancel(self.raw_task)

    @property
    def is_finished(self) -> bool:
        """
        Check if the task completed successfully.
        
        Returns:
            True if the task has finished execution without errors.
        """
        return self.raw_task in self.event_loop.finished

    @property
    def is_error(self) -> bool:
        """
        Check if the task completed with an error.
        
        Returns:
            True if the task raised an exception (not including cancellation).
        """
        return self.raw_task in self.event_loop.exceptions and not self.is_cancelled

    @property
    def is_cancelled(self) -> bool:
        """
        Check if the task was cancelled.
        
        Returns:
            True if the task was cancelled.
        """
        return self.raw_task in self.event_loop.cancelled

    @coroutine
    def join(
        self,
    ) -> Generator[JoinCommand[_T_co], object, _T_co]:
        """
        Wait for this task to complete and get its result.
        
        This is a coroutine that yields a JoinCommand for the event loop to process.
        When the task completes, this coroutine will resume with its result.
        
        Returns:
            The value returned by the task.
            
        Raises:
            Exception: Any exception that was raised by the task.
            TaskCancelled: If the task was cancelled.
        """
        received = yield JoinCommand(self)
        return cast(_T_co, received)


@dataclass
class TaskCancelled(Exception):
    """
    Exception raised when a task is cancelled.

    This exception is raised when attempting to join a task that
    has been cancelled.
    """
    by: TaskHandle[object]

    def __str__(self) -> str:
        return f"Task was cancelled"


@final
class ThreadHandle(Generic[_T_co]):
    """
    A handle to a spawned thread that allows joining.

    ThreadHandle objects are returned by the spawn_in_thread primitive and
    represent blocking functions running in separate OS threads. They can be
    used to wait for the thread to complete and retrieve its result.
    """

    def __init__(self, thread: Thread, result_queue: "AsyncQueue[ThreadResult[_T_co] | ThreadException]"):
        """
        Initialize a ThreadHandle.

        Args:
            thread: The Thread object executing the blocking function
            result_queue: AsyncQueue to receive the result from the thread
        """
        self._thread = thread
        self._result_queue = result_queue

    @property
    def is_alive(self) -> bool:
        """
        Check if the thread is still running.

        Returns:
            True if the thread is still executing.
        """
        return self._thread.is_alive()

    @coroutine
    def join(self) -> Generator[object, object, _T_co]:
        """
        Wait for this thread to complete and get its result.

        This is a coroutine that waits on the result queue for the thread
        to push its result or exception.

        Returns:
            The value returned by the blocking function.

        Raises:
            Exception: Any exception that was raised by the blocking function.
        """
        result_wrapper = yield from self._result_queue.get()

        if isinstance(result_wrapper, ThreadException):
            raise result_wrapper.exception
        else:
            return cast(_T_co, result_wrapper.value)


__all__ = [
    "TaskHandle",
    "ThreadHandle",
    "TaskCancelled",
]
