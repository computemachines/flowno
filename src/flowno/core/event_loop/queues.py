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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

from flowno.core.event_loop.instrumentation import get_current_instrument
from flowno.core.event_loop.synchronization import Condition, Lock
from flowno.utilities.logging import log_async
from typing_extensions import override

if TYPE_CHECKING:
    from flowno.core.event_loop.event_loop import EventLoop

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class QueueClosedError(Exception):
    """Raised when attempting to put/get on a closed queue."""
    pass



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
        self.maxsize: int | None = maxsize
        self._closed: bool = False
        self._lock = Lock()
        self._not_empty = Condition(self._lock)
        self._not_full = Condition(self._lock)
        logger.debug(f"AsyncQueue created: {self}")

    @property
    def closed(self) -> bool:
        return self._closed

    @closed.setter
    def closed(self, value: bool) -> None:
        self._closed = value

    @override
    def __repr__(self) -> str:
        return f"<AsyncQueue id={id(self)} maxsize={self.maxsize} items={list(self.items)} closed={self._closed}>"

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
        async with self._lock:
            # Wait while the queue is full
            while self.maxsize is not None and len(self.items) >= self.maxsize:
                if self._closed:
                    raise QueueClosedError("Cannot put item into closed queue")
                await self._not_full.wait()
            
            if self._closed:
                raise QueueClosedError("Cannot put item into closed queue")
            
            get_current_instrument().on_queue_put(queue=self, item=item, immediate=True)
            self.items.append(item)
            await self._not_empty.notify()
            logger.debug(f"AsyncQueue.put {item} into {self}")

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
        async with self._lock:
            # Wait while the queue is empty
            while not self.items:
                if self._closed:
                    logger.debug(f"AsyncQueue.get sees closed queue {self}")
                    raise QueueClosedError("Queue has been closed and is empty")
                await self._not_empty.wait()
            
            item = self.items.popleft()
            get_current_instrument().on_queue_get(queue=self, item=item, immediate=True)
            await self._not_full.notify()
            logger.debug(f"AsyncQueue.get {item} from {self}")
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
        async with self._lock:
            # Wait while the queue is empty
            while not self.items:
                if self.closed:
                    raise QueueClosedError("Queue has been closed and is empty")
                await self._not_empty.wait()
            
            return self.items[0]

    async def close(self) -> None:
        """
        Close the queue, preventing further put operations.
        
        After closing:
            - put() will raise QueueClosedError
            - get() will succeed until the queue is empty, then raise QueueClosedError
            - AsyncIterator interface will stop iteration when the queue is empty
        """
        logger.debug(f"AsyncQueue.close called on {self}", stack_info=True)
        async with self._lock:
            self.closed = True
            # Wake up all waiting tasks so they can see the queue is closed
            await self._not_empty.notify_all()
            await self._not_full.notify_all()

    def close_nowait(self, event_loop: "EventLoop") -> None:
        """
        Synchronously close the queue.
        
        This method is designed to be called from within a command handler,
        where async operations are not possible. It handles waiter notification
        synchronously through the event loop.
        
        Args:
            event_loop: The event loop to use for notifying waiters
        """
        logger.debug(f"AsyncQueue.close_nowait called on {self}", stack_info=True)
        self.closed = True
        # Notify all waiters so they can see the queue is closed
        self._not_empty.notify_all_nowait(event_loop)
        self._not_full.notify_all_nowait(event_loop)

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
        async with self._lock:
            if item in self.items:
                return
            
            # Wait while the queue is full
            while self.maxsize is not None and len(self.items) >= self.maxsize:
                await self._not_full.wait()
            
            if self.closed:
                raise QueueClosedError("Cannot put item into closed queue")

            get_current_instrument().on_queue_put(queue=self, item=item, immediate=True)
            self.items.append(item)
            logger.debug(f"AsyncSetQueue.put: Added {item} to queue, items now: {list(self.items)}")
            await self._not_empty.notify()
            logger.debug(f"AsyncSetQueue.put: After notify, items: {list(self.items)}")

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

    def __contains__(self, item: _T) -> bool:
        """
        Check if an item is in the queue.
        
        Args:
            item: The item to check for
            
        Returns:
            True if the item is in the queue, False otherwise
        """
        return item in self.items

    def put_nowait(self, item: _T, event_loop: "EventLoop") -> bool:
        """
        Synchronously put an item into the queue if not already present.
        
        This method is designed to be called from within a command handler,
        where async operations are not possible. It handles waiter notification
        synchronously through the event loop.
        
        Args:
            item: The item to put into the queue
            event_loop: The event loop to use for notifying waiters
            
        Returns:
            True if the item was added, False if it was already present
            
        Raises:
            QueueClosedError: If the queue is closed
        """
        if item in self.items:
            return False
        
        if self.closed:
            raise QueueClosedError("Cannot put item into closed queue")
        
        get_current_instrument().on_queue_put(queue=self, item=item, immediate=True)
        self.items.append(item)
        
        # Notify one waiter if any are waiting on _not_empty
        self._not_empty.notify_nowait(event_loop)
        
        return True


_K = TypeVar("_K")


class AsyncMapQueue(Generic[_K]):
    """
    An async queue that maps keys to lists of causes (reasons).

    This queue maintains unique keys in FIFO order while accumulating
    multiple causes for each key. When a key is put multiple times,
    the causes are appended to that key's list rather than duplicating
    the key in the queue.

    Example:
        >>> from flowno.core.event_loop.event_loop import EventLoop
        >>> from flowno.core.event_loop.queues import AsyncMapQueue
        >>>
        >>> async def map_queue_example():
        ...     queue = AsyncMapQueue()
        ...
        ...     # Put same key multiple times with different reasons
        ...     await queue.put(("node1", "completed generation (0,)"))
        ...     await queue.put(("node2", "barrier released"))
        ...     await queue.put(("node1", "received stalled request"))
        ...
        ...     print(len(queue))  # 2 (unique keys: node1, node2)
        ...
        ...     # Get returns (key, [causes])
        ...     key, causes = await queue.get()
        ...     print(key, causes)
        ...     # ('node1', ['completed generation (0,)', 'received stalled request'])
        ...
        ...     key, causes = await queue.get()
        ...     print(key, causes)
        ...     # ('node2', ['barrier released'])
        ...
        ...     return "done"
        >>>
        >>> loop = EventLoop()
        >>> loop.run_until_complete(map_queue_example(), join=True)
        2
        node1 ['completed generation (0,)', 'received stalled request']
        node2 ['barrier released']
        'done'
    """

    def __init__(self, maxsize: int | None = None):
        """
        Initialize the AsyncMapQueue.

        Args:
            maxsize: Maximum number of unique keys allowed in the queue.
                     If None, the queue size is unbounded.
        """
        self._queue: AsyncQueue[_K] = AsyncQueue(maxsize=maxsize)
        self._map: dict[_K, list[str]] = {}

    def __repr__(self) -> str:
        return f"<AsyncMapQueue keys={list(self._map.keys())} causes={self._map}>"

    async def put(self, item: tuple[_K, str]) -> None:
        """
        Put a (key, cause) pair into the queue.

        If the key already exists in the queue, the cause is appended
        to that key's list. Otherwise, the key is added to the queue
        with a new list containing the cause.

        Args:
            item: A tuple of (key, cause) where cause describes why
                  the key was enqueued

        Raises:
            QueueClosedError: If the queue is closed
            ValueError: If item is not a 2-tuple of (key, cause)
        """
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError(
                f"AsyncMapQueue.put() expects a tuple of (key, cause), got {type(item).__name__}: {item!r}"
            )
        key, cause = item

        if key in self._map:
            # Key already exists, append the cause
            self._map[key].append(cause)
            get_current_instrument().on_queue_put(queue=self._queue, item=(key, cause), immediate=True)
        else:
            # New key, create list and add to queue
            self._map[key] = [cause]
            await self._queue.put(key)

    async def get(self) -> tuple[_K, list[str]]:
        """
        Get the next (key, causes) pair from the queue.

        Returns the key and all accumulated causes for that key,
        then removes the key from the queue and map.

        Returns:
            A tuple of (key, list of causes)

        Raises:
            QueueClosedError: If the queue is closed and empty
        """
        key = await self._queue.get()
        causes = self._map.pop(key)
        return (key, causes)

    async def peek(self) -> tuple[_K, list[str]]:
        """
        Peek at the next (key, causes) pair without removing it.

        Returns:
            A tuple of (key, list of causes)

        Raises:
            QueueClosedError: If the queue is closed and empty
        """
        key = await self._queue.peek()
        causes = self._map[key]
        return (key, causes)

    async def close(self) -> None:
        """Close the queue, preventing further put operations."""
        await self._queue.close()

    def is_closed(self) -> bool:
        """Check if the queue is closed."""
        return self._queue.is_closed()

    def __len__(self) -> int:
        """Get the number of unique keys in the queue."""
        return len(self._queue)


__all__ = [
    "AsyncQueue",
    "AsyncSetQueue",
    "AsyncMapQueue",
    "QueueClosedError",
]
