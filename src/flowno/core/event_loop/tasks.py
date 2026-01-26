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
from types import coroutine
from typing import TYPE_CHECKING, Generic, TypeVar, cast, final

from .types import RawTask

if TYPE_CHECKING:
    from .event_loop import EventLoop  # Only import during type checking

from .commands import CancelCommand, Command, JoinCommand

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

    def cancel(
        self,
    ) -> Generator[CancelCommand[_T_co], object, _T_co]:
        """
        Cancel this task and wait for it to complete.

        This method immediately initiates cancellation of the task and returns
        an awaitable that can be used to wait for the cancellation to complete
        and retrieve any return value from the cancelled task.

        If the task is still running, it will receive a TaskCancelled exception.
        If the task has already finished, errored, or been cancelled, this method
        returns the existing result or exception without sending TaskCancelled.

        When awaited, you will receive:
        - The value returned by the task (e.g., from finally block or except handler)
        - None if the task let TaskCancelled propagate (successful cancellation)
        - Any other exception raised during cleanup or prior to cancellation

        Returns:
            An awaitable that resolves to the task's result.

        Raises:
            Exception: Any exception that was raised by the task (only when awaited).

        Note:
            Even if you don't await the return value, running tasks will still be
            cancelled. Awaiting allows you to wait for cleanup to complete and get
            any return value.
        """
        # Immediately initiate cancellation (fire-and-forget for non-awaited case)
        self.event_loop.cancel(self.raw_task)

        # Return an awaitable that yields CancelCommand for the event loop to handle
        # The CancelCommand handler will wait for the task to finish and return its result
        @coroutine
        def _wait_for_cancellation() -> Generator[CancelCommand[_T_co], object, _T_co]:
            received = yield CancelCommand(self)
            return cast(_T_co, received)

        return _wait_for_cancellation()

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


__all__ = [
    "TaskHandle",
    "TaskCancelled",
]
