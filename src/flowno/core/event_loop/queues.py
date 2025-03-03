"""
Asynchronous queue implementations for the Flowno event loop.

This module provides queue classes that integrate with Flowno's custom event loop,
allowing tasks to safely exchange data and coordinate their execution. These queues
implement the AsyncIterator protocol, making them convenient for use in async for loops.

Examples:
    Basic queue operations:
    
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.queues import AsyncQueue
    >>> 
    >>> async def producer_consumer():
    ...     # Create a queue with maximum size 2
    ...     queue = AsyncQueue(maxsize=2)
    ...     
    ...     # Put some items into the queue
    ...     await queue.put("task 1")
    ...     await queue.put("task 2")
    ...     
    ...     # Peek at the first item without removing it
    ...     first = await queue.peek()
    ...     
    ...     # Get and process items
    ...     item1 = await queue.get()
    ...     item2 = await queue.get()
    ...     
    ...     # Close the queue when done
    ...     await queue.close()
    ...     return (first, item1, item2)
    >>> 
    >>> loop = EventLoop()
    >>> result = loop.run_until_complete(producer_consumer(), join=True)
    >>> result
    ('task 1', 'task 1', 'task 2')
    
    Using a queue as an async iterator:
    
    >>> async def queue_iterator_example():
    ...     queue = AsyncQueue()
    ...     
    ...     # Add some items
    ...     for i in range(3):
    ...         await queue.put(f"item {i}")
    ...     
    ...     # Process all items using async for
    ...     results = []
    ...     async for item in queue.until_empty():
    ...         results.append(item)
    ...     
    ...     return results
    >>> 
    >>> loop = EventLoop()
    >>> loop.run_until_complete(queue_iterator_example(), join=True)
    ['item 0', 'item 1', 'item 2']
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass
from types import coroutine
from typing import Any, Generic, TypeVar

from flowno.core.event_loop.instrumentation import get_current_instrument
from flowno.utilities.logging import log_async
from typing_extensions import override

from .commands import (
    QueueCloseCommand,
    QueueGetCommand,
    QueueNotifyGettersCommand,
    QueuePutCommand,
)
from .types import RawTask

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class QueueClosedError(Exception):
    """Raised when attempting to put/get on a closed queue."""
    pass


@dataclass(frozen=True)
class TaskWaitingOnQueueGet(Generic[_T]):
    """Internal class for tracking tasks waiting to get an item."""
    task: RawTask[QueueGetCommand[_T], Any, Any]  # pyright: ignore[reportExplicitAny]
    peek: bool


@dataclass(frozen=True)
class TaskWaitingOnQueuePut(Generic[_T]):
    """Internal class for tracking tasks waiting to put an item."""
    task: RawTask[QueuePutCommand[_T], Any, None] # pyright: ignore[reportExplicitAny]
    item: _T


class AsyncQueue(Generic[_T], AsyncIterator[_T]):
    """
    An asynchronous queue for the Flowno event loop.
    
    This queue allows tasks to exchange data safely, with proper
    synchronization handled by the event loop. When used as an
    async iterator, it yields items until the queue is closed.
    
    Args:
        maxsize: The maximum number of items allowed in the queue.
                 When the queue reaches this size, put() operations
                 will block until items are removed. If None, the queue
                 size is unbounded.
    """
    def __init__(self, maxsize: int | None = None):
        self.items: deque[_T] = deque()
        self.maxsize: int | None = None
        self.closed: bool = False
        self._get_waiting: deque[TaskWaitingOnQueueGet[object]] = deque()
        self._put_waiting: deque[TaskWaitingOnQueuePut[object]] = deque()

    @override
    def __repr__(self) -> str:
        return f"<AsyncQueue maxsize={self.maxsize} items={self.items} num_tasks_blocked_on_get={len(self._get_waiting)} num_tasks_blocked_on_put={len(self._put_waiting)}>"

    @coroutine
    def _put(self, item: _T) -> Generator[QueuePutCommand[_T] | QueueNotifyGettersCommand[_T], None, None]:
        """        Put an item into the queue and notify blocked tasks or wait for room on the queue.
        
        Raises:
            QueueClosedError: If the queue is closed.
        """
        if self.closed:
            raise QueueClosedError("Cannot put item into closed queue")
            
        if self.maxsize is not None and len(self.items) >= self.maxsize:
            # Queue is full, block until an item is removed
            yield QueuePutCommand(queue=self, item=item)
        else:
            # Queue is not full, add the item directly and notify any waiting tasks
            get_current_instrument().on_queue_put(queue=self, item=item, immediate=True)
            self.items.append(item)

            if self._get_waiting:
                yield QueueNotifyGettersCommand(queue=self)

            return None

    async def put(self, item: _T) -> None:
        """
        Put an item into the queue.
        
        If the queue is full and has a maxsize, this will
        wait until space is available.
        
        Args:
            item: The item to put into the queue
            
        Raises:
            QueueClosedError: If the queue is closed
        """
        await self._put(item)

    @coroutine
    def _get(self) -> Generator[QueueGetCommand[_T], _T, _T]:
        """
        Pop an item from the queue or block until an item is available.
        
        Raises:
            QueueClosedError: If the queue is closed and empty.
        """
    # TODO: BUG! If the queue is full, it needs to inform the event loop
        # that a spot has openned up.

        if self.items:
            item = self.items.popleft()
            get_current_instrument().on_queue_get(queue=self, item=item, immediate=True)
            return item
        elif self.closed:
            raise QueueClosedError("Queue has been closed and is empty")
        else:
            item = yield QueueGetCommand(self)
            return item

    async def get(self) -> _T:
        """
        Get an item from the queue.
        
        If the queue is empty, this will wait until an item
        is put into the queue.
        
        Returns:
            The next item from the queue
            
        Raises:
            QueueClosedError: If the queue is closed and empty
        """
        return await self._get()

    @coroutine
    def _peek(self) -> Generator[QueueGetCommand[_T], _T, _T]:
        """
        Peek at the next item without removing it from the queue.
        
        Raises:
            QueueClosedError: If the queue is closed and empty.
        """
        if self.items:
            return self.items[0]
        elif self.closed:
            raise QueueClosedError("Queue has been closed and is empty")
        else:
            item = yield QueueGetCommand(self, peek=True)
            return item

    async def peek(self) -> _T:
        """
        Peek at the next item without removing it from the queue.
        
        If the queue is empty, this will wait until an item
        is put into the queue.
        
        Returns:
            The next item from the queue (without removing it)
            
        Raises:
            QueueClosedError: If the queue is closed and empty
        """
        return await self._peek()

    @coroutine
    def _close(self) -> Generator[QueueCloseCommand[_T], None, None]:
        """Close the queue, preventing further put operations."""
        self.closed = True
        yield QueueCloseCommand(self)

    async def close(self) -> None:
        """
        Close the queue, preventing further put operations.
        
        After closing:
            - put() will raise QueueClosedError
            - get() will succeed until the queue is empty, then raise QueueClosedError
            - AsyncIterator interface will stop iteration when the queue is empty
        """
        await self._close()

    def is_closed(self) -> bool:
        """
        Check if the queue is closed.
        
        Returns:
            True if the queue is closed, False otherwise
        """
        return self.closed

    def __len__(self) -> int:
        """
        Get the current number of items in the queue.
        
        Returns:
            Number of items currently in the queue
        """
        return len(self.items)

    @override
    def __aiter__(self) -> AsyncIterator[_T]:
        """
        Use the queue as an async iterator.
        
        The iterator will yield items until the queue is closed and empty.
        
        Returns:
            An async iterator that yields items from the queue
        """
        return self

    @log_async
    @override
    async def __anext__(self) -> _T:
        """
        Get the next item from the queue.
        
        Raises:
            StopAsyncIteration: If the queue is closed and empty
        """
        try:
            return await self.get()
        except QueueClosedError:
            raise StopAsyncIteration

    def until_empty(self) -> AsyncIterator[_T]:
        """
        Get an async iterator that consumes all items until the queue is empty.
        
        This iterator will close the queue automatically when all items are consumed,
        unless specified otherwise.
        
        Returns:
            An async iterator that yields items until the queue is empty
        """
        return _UntilEmptyIterator(self)


class _UntilEmptyIterator(Generic[_T], AsyncIterator[_T]):
    """Helper class for implementing the until_empty method."""
    
    def __init__(self, queue: AsyncQueue[_T], self_closing: bool = True):
        self.queue: AsyncQueue[_T] = queue
        self.self_closing: bool = self_closing

    @override
    async def __anext__(self) -> _T:
        if not self.queue.items:
            if self.self_closing:
                await self.queue.close()
            raise StopAsyncIteration
        try:
            return await self.queue.get()
        except QueueClosedError:
            raise StopAsyncIteration


class AsyncSetQueue(Generic[_T], AsyncQueue[_T]):
    """
    A queue variant that ensures each item appears only once.
    
    This queue behaves like a standard AsyncQueue, but automatically
    deduplicates items based on equality.
    
    Example:
        >>> from flowno.core.event_loop.event_loop import EventLoop
        >>> from flowno.core.event_loop.queues import AsyncSetQueue
        >>> 
        >>> async def set_queue_example():
        ...     queue = AsyncSetQueue()
        ...     
        ...     # Add some items with duplicates
        ...     await queue.put("apple")
        ...     await queue.put("banana")
        ...     await queue.put("apple")  # This won't be added again
        ...     await queue.put("cherry")
        ...     
        ...     # Get all unique items
        ...     items = []
        ...     while len(queue) > 0:
        ...         items.append(await queue.get())
        ...     
        ...     return items
        >>> 
        >>> loop = EventLoop()
        >>> loop.run_until_complete(set_queue_example(), join=True)
        ['apple', 'banana', 'cherry']
    """
    
    @override
    async def put(self, item: _T) -> None:
        """
        Put an item into the queue if it's not already present.
        
        Args:
            item: The item to put into the queue
            
        Raises:
            QueueClosedError: If the queue is closed
        """
        if item in self.items:
            return
        await super()._put(item)

    async def putAll(self, items: list[_T]) -> None:
        """
        Put multiple unique items into the queue.
        
        Args:
            items: A list of items to add to the queue
            
        Raises:
            QueueClosedError: If the queue is closed
        """
        for item in items:
            await self.put(item)


__all__ = [
    "AsyncQueue",
    "AsyncSetQueue",
    "QueueClosedError",
]
