"""
Synchronization primitives for the Flowno event loop.

This module provides synchronization tools like CountdownLatch that help
coordinate concurrent tasks in Flowno's dataflow execution model. These primitives
are particularly useful for ensuring proper data flow between nodes.

Examples:
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.primitives import spawn
    >>> from flowno.core.event_loop.synchronization import CountdownLatch
    >>> 
    >>> async def consumer(name: str, latch: CountdownLatch):
    ...     print(f"{name}: Waiting for data...")
    ...     await latch.wait()
    ...     print(f"{name}: Data received, processing...")
    ...     return f"{name} processed"
    >>> 
    >>> async def producer(latch: CountdownLatch):
    ...     print("Producer: Preparing data...")
    ...     # Simulate data preparation
    ...     print("Producer: Data ready, notifying consumers...")
    ...     await latch.count_down()
    ...     await latch.count_down()  # Notify both consumers
    ...     print("Producer: All consumers notified")
    >>> 
    >>> async def main():
    ...     # Create a latch that will block until counted down twice
    ...     latch = CountdownLatch(count=2)
    ...     
    ...     # Start two consumers that wait on the latch
    ...     consumer1 = await spawn(consumer("Consumer1", latch))
    ...     consumer2 = await spawn(consumer("Consumer2", latch))
    ...     
    ...     # Start the producer that will count down the latch
    ...     producer_task = await spawn(producer(latch))
    ...     
    ...     # Wait for all tasks to complete
    ...     await producer_task.join()
    ...     result1 = await consumer1.join()
    ...     result2 = await consumer2.join()
    ...     
    ...     return [result1, result2]
    >>> 
    >>> event_loop = EventLoop()
    >>> results = event_loop.run_until_complete(main(), join=True)
    Producer: Preparing data...
    Consumer1: Waiting for data...
    Consumer2: Waiting for data...
    Producer: Data ready, notifying consumers...
    Producer: All consumers notified
    Consumer1: Data received, processing...
    Consumer2: Data received, processing...
    >>> print(results)
    ['Consumer1 processed', 'Consumer2 processed']
"""

import logging
from typing import Optional, Generator

from flowno.core.event_loop.queues import AsyncQueue
from flowno.core.event_loop.commands import (
    EventWaitCommand,
    EventSetCommand,
    LockAcquireCommand,
    LockReleaseCommand,
)

logger = logging.getLogger(__name__)


class Event:
    """
    A one-shot synchronization primitive for waking multiple waiting tasks.

    An Event starts in the "not set" state. Tasks can wait() on the event,
    blocking until another task calls set(). Once set, the event remains set
    permanently, and all current and future wait() calls return immediately.

    This primitive is ideal for signaling completion of an initialization
    phase or broadcasting a one-time notification to multiple consumers.

    Examples:
        >>> from flowno.core.event_loop.event_loop import EventLoop
        >>> from flowno.core.event_loop.primitives import spawn
        >>> from flowno.core.event_loop.synchronization import Event
        >>>
        >>> async def waiter(name: str, event: Event):
        ...     print(f"{name}: Waiting...")
        ...     await event.wait()
        ...     print(f"{name}: Event set, proceeding!")
        ...     return name
        >>>
        >>> async def setter(event: Event):
        ...     print("Setter: About to set event")
        ...     await event.set()
        ...     print("Setter: Event set")
        >>>
        >>> async def main():
        ...     event = Event()
        ...
        ...     # Start multiple waiters
        ...     w1 = await spawn(waiter("Waiter1", event))
        ...     w2 = await spawn(waiter("Waiter2", event))
        ...
        ...     # Set the event
        ...     s = await spawn(setter(event))
        ...
        ...     # All waiters should proceed
        ...     await w1.join()
        ...     await w2.join()
        ...     await s.join()
        >>>
        >>> event_loop = EventLoop()
        >>> event_loop.run_until_complete(main(), join=True)
        Waiter1: Waiting...
        Waiter2: Waiting...
        Setter: About to set event
        Setter: Event set
        Waiter1: Event set, proceeding!
        Waiter2: Event set, proceeding!
    """

    def __init__(self) -> None:
        """Initialize a new Event in the not-set state."""
        self._set = False

    def is_set(self) -> bool:
        """
        Check if the event is set.

        Returns:
            True if the event has been set, False otherwise.
        """
        return self._set

    async def wait(self) -> None:
        """
        Wait for the event to be set.

        If the event is already set, return immediately.
        Otherwise, block until another task calls set().
        """
        if self._set:
            return  # Fast path: event already set
        yield EventWaitCommand(event=self)

    async def set(self) -> None:
        """
        Set the event, waking all waiting tasks.

        Once set, the event remains set permanently. All current and future
        wait() calls will return immediately.
        """
        if not self._set:
            self._set = True
            yield EventSetCommand(event=self)

    def __repr__(self) -> str:
        """Return a string representation of the Event."""
        state = "set" if self._set else "not set"
        return f"Event({state})"


class Lock:
    """
    A mutual exclusion lock for protecting critical sections.

    A Lock provides mutual exclusion - only one task can hold the lock at a time.
    Tasks that attempt to acquire a held lock will block until the lock is released.
    The lock uses FIFO ordering to prevent starvation.

    Examples:
        >>> from flowno.core.event_loop.event_loop import EventLoop
        >>> from flowno.core.event_loop.primitives import spawn
        >>> from flowno.core.event_loop.synchronization import Lock
        >>>
        >>> async def critical_section(name: str, lock: Lock, shared_counter: list):
        ...     print(f"{name}: Waiting for lock")
        ...     await lock.acquire()
        ...     try:
        ...         print(f"{name}: Acquired lock, in critical section")
        ...         # Simulate work in critical section
        ...         shared_counter[0] += 1
        ...         print(f"{name}: Counter = {shared_counter[0]}")
        ...     finally:
        ...         await lock.release()
        ...         print(f"{name}: Released lock")
        >>>
        >>> async def main():
        ...     lock = Lock()
        ...     counter = [0]
        ...
        ...     # Start two tasks that compete for the lock
        ...     task1 = await spawn(critical_section("Task1", lock, counter))
        ...     task2 = await spawn(critical_section("Task2", lock, counter))
        ...
        ...     await task1.join()
        ...     await task2.join()
        ...     return counter[0]
        >>>
        >>> event_loop = EventLoop()
        >>> result = event_loop.run_until_complete(main(), join=True)
        Task1: Waiting for lock
        Task1: Acquired lock, in critical section
        Task1: Counter = 1
        Task1: Released lock
        Task2: Waiting for lock
        Task2: Acquired lock, in critical section
        Task2: Counter = 2
        Task2: Released lock
        >>> print(result)
        2
    """

    def __init__(self) -> None:
        """Initialize a new Lock in the unlocked state."""
        self._locked = False
        self._owner = None  # Will be set by event loop

    def is_locked(self) -> bool:
        """
        Check if the lock is currently held.

        Returns:
            True if the lock is held by any task, False otherwise.
        """
        return self._locked

    async def acquire(self) -> None:
        """
        Acquire the lock.

        If the lock is available, acquire it immediately and return.
        If the lock is held by another task, block until it becomes available.
        Tasks waiting for the lock are served in FIFO order.
        """
        yield LockAcquireCommand(lock=self)

    async def release(self) -> None:
        """
        Release the lock.

        The lock must be held by the current task. If other tasks are waiting,
        the next task in FIFO order will acquire the lock.

        Raises:
            AssertionError: If the lock is not held by the current task (checked by event loop).
        """
        yield LockReleaseCommand(lock=self)

    def __repr__(self) -> str:
        """Return a string representation of the Lock."""
        state = "locked" if self._locked else "unlocked"
        owner = f" by {self._owner}" if self._owner else ""
        return f"Lock({state}{owner})"


class CountdownLatch:
    """
    A synchronization primitive that allows one or more tasks to wait until
    a set of operations in other tasks completes.
    
    The latch is initialized with a given count. Tasks can then wait on the latch,
    and each count_down() call decreases the counter. When the counter reaches zero,
    all waiting tasks are released.
    
    This is currently used in :py:mod:`~flowno.core.node_base` where a node needs to ensure
    all downstream nodes have consumed its previous output before generating new data.
    
    Attributes:
        count: The initial count that must be counted down to zero
    """

    def __init__(self, count: int) -> None:
        """
        Initialize a new CountdownLatch.
        
        Args:
            count: The number of count_down() calls needed to release waiting tasks.
                  Must be non-negative.
                  
        Raises:
            ValueError: If count is negative.
        """
        if count < 0:
            raise ValueError("CountdownLatch count must be non-negative")
        self._count = count
        self._queue = AsyncQueue()

    @property
    def count(self) -> int:
        """
        Get the current count of the latch.
        
        Returns:
            The current count value.
        """
        return self._count

    def set_count(self, count: int) -> None:
        """
        Set a new count for the latch.
        
        This method should only be called when no tasks are waiting on the latch.
        
        Args:
            count: The new count value. Must be non-negative.
            
        Raises:
            ValueError: If count is negative.
        """
        if count < 0:
            raise ValueError("CountdownLatch count must be non-negative")
        self._count = count

    async def wait(self) -> None:
        """
        Block until the latch has counted down to zero.
        
        This coroutine will not complete until count_down() has been called
        the specified number of times.
        """
        # Retrieve 'count' items from the queue
        for _ in range(self._count):
            await self._queue.get()

    class ZeroLatchError(Exception):
        """
        Exception raised when trying to count down a latch that is already at zero.
        
        This exception is used internally to indicate that the latch has already
        been counted down to zero, and no further countdowns are possible.
        """
        pass

    async def count_down(self, exception_if_zero: bool = False) -> None:
        """
        Decrement the latch count by one.
        
        If the count reaches zero as a result of this call, all waiting
        tasks will be unblocked.
        
        If the latch is already at zero, this method logs a warning.
        """
        if self._count == 0:
            if exception_if_zero:
                raise self.ZeroLatchError("Cannot count down a latch that is already at zero")
            else:
                logger.warning(f"counted down on already zero latch: {self}")
        else:
            logger.debug(f"counting down latch: {self}")
            await self._queue.put(None)
    
    def __repr__(self) -> str:
        """
        Return a string representation of the CountdownLatch.
        
        This representation includes the current count and the maximum size of the queue.
        """
        current_latch_count = len(self._queue._get_waiting)
        return f"CountdownLatch(original_count={self._count}, remaining_counts={current_latch_count})"


class Barrier:
    """
    A synchronization primitive that allows multiple tasks to wait for each other.
    
    A barrier is initialized with a participant count. Each task calls wait() on
    the barrier, and all tasks are blocked until the specified number of tasks
    have called wait().
    
    Note:
        This is a basic implementation. For production use with many participants,
        consider implementing a more efficient version.
    """
    
    def __init__(self, parties: int) -> None:
        """
        Initialize a new barrier.
        
        Args:
            parties: The number of tasks that must call wait() before any are released.
                    Must be greater than zero.
                    
        Raises:
            ValueError: If parties is not positive.
        """
        if parties <= 0:
            raise ValueError("Barrier parties must be positive")
            
        self._parties = parties
        self._count = 0
        self._generation = 0
        self._queues: list[AsyncQueue[None]] = []
        
    async def wait(self) -> int:
        """
        Wait for all parties to reach the barrier.
        
        This method blocks until all parties have called wait() on this barrier.
        When the final party arrives, all waiting parties are released.
        
        Returns:
            The arrival index (0 through parties-1) for this task
        """
        generation = self._generation
        arrival_index = self._count
        
        # Create a queue for this party if needed
        if arrival_index >= len(self._queues):
            self._queues.append(AsyncQueue())
            
        self._count += 1
        
        if self._count == self._parties:
            # This is the last party to arrive
            self._count = 0
            self._generation += 1
            
            # Release all waiting parties
            for i in range(self._parties - 1):
                await self._queues[i].put(None)
                
            return arrival_index
        else:
            # Wait for the last party to arrive
            await self._queues[arrival_index].get()
            
            # Check if we've moved to a new generation while waiting
            if self._generation != generation:
                # If a new generation started, ensure barrier is reset
                pass
                
            return arrival_index


__all__ = [
    "Event",
    "Lock",
    "CountdownLatch",
    "Barrier"
]
