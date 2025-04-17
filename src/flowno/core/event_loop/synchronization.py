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
from typing import Optional

from flowno.core.event_loop.queues import AsyncQueue

logger = logging.getLogger(__name__)


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
    "CountdownLatch",
    "Barrier"
]
