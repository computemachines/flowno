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

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Optional, Generator, TYPE_CHECKING, Any
from types import coroutine

from timeit import default_timer as timer

from flowno.core.event_loop.commands import (
    EventWaitCommand,
    EventSetCommand,
    LockAcquireCommand,
    LockReleaseCommand,
)

if TYPE_CHECKING:
    from flowno.core.event_loop.event_loop import EventLoop
    from flowno.core.event_loop.types import RawTask
    from flowno.core.event_loop.commands import Command

logger = logging.getLogger(__name__)


class SyncContext:
    """
    Thread-safe context for managing waiters across multiple event loops.

    This class provides thread-safe storage for tasks waiting on synchronization
    primitives. It's used when a primitive is accessed from multiple event loops
    (threads), enabling cross-thread coordination.

    The design allows primitives to start with simple, lock-free waiter storage
    for the common single-loop case, and upgrade to SyncContext only when
    cross-thread access is detected.
    """

    def __init__(self) -> None:
        """Initialize a new SyncContext with thread-safe waiter storage."""
        self._lock = threading.Lock()
        # Maps event loops to their waiting tasks
        self._waiters: dict["EventLoop", set["RawTask[Command, Any, Any]"]] = {}

    def add_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> None:
        """
        Add a waiting task for a specific event loop.

        Args:
            loop: The event loop the task belongs to
            task: The task to add to the waiters set
        """
        with self._lock:
            if loop not in self._waiters:
                self._waiters[loop] = set()
            self._waiters[loop].add(task)

    def remove_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> bool:
        """
        Remove a waiting task from a specific event loop.

        Args:
            loop: The event loop the task belongs to
            task: The task to remove

        Returns:
            True if the task was found and removed, False otherwise
        """
        with self._lock:
            if loop in self._waiters and task in self._waiters[loop]:
                self._waiters[loop].discard(task)
                return True
            return False

    def pop_waiter(self, loop: "EventLoop") -> "RawTask[Command, Any, Any] | None":
        """
        Pop and return one waiter from a specific event loop's set.

        Args:
            loop: The event loop to pop a waiter from

        Returns:
            A waiting task, or None if no waiters exist for that loop
        """
        with self._lock:
            if loop in self._waiters and self._waiters[loop]:
                return self._waiters[loop].pop()
            return None

    def get_all_waiters(self) -> dict["EventLoop", set["RawTask[Command, Any, Any]"]]:
        """
        Get all waiters grouped by event loop, clearing internal storage.

        This is used when waking all waiters (e.g., Event.set()).

        Returns:
            Dict mapping event loops to their waiting tasks
        """
        with self._lock:
            result = self._waiters
            self._waiters = {}
            return result

    def has_waiters(self) -> bool:
        """Check if there are any waiters across all event loops."""
        with self._lock:
            return any(waiters for waiters in self._waiters.values())

    def has_waiters_for_loop(self, loop: "EventLoop") -> bool:
        """Check if there are any waiters for a specific event loop."""
        with self._lock:
            return bool(self._waiters.get(loop))


class LockSyncContext:
    """
    Thread-safe context for Lock waiters using FIFO ordering.

    Similar to SyncContext but uses deques instead of sets to maintain
    FIFO ordering for lock acquisition fairness.
    """

    def __init__(self) -> None:
        """Initialize a new LockSyncContext with thread-safe waiter storage."""
        self._lock = threading.Lock()
        # Maps event loops to their waiting tasks (in FIFO order)
        self._waiters: dict["EventLoop", deque["RawTask[Command, Any, Any]"]] = {}

    def add_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> None:
        """
        Add a waiting task for a specific event loop (FIFO order).

        Args:
            loop: The event loop the task belongs to
            task: The task to add to the waiters queue
        """
        with self._lock:
            if loop not in self._waiters:
                self._waiters[loop] = deque()
            self._waiters[loop].append(task)

    def pop_waiter(self, loop: "EventLoop") -> "RawTask[Command, Any, Any] | None":
        """
        Pop and return the first waiter from a specific event loop's queue.

        Args:
            loop: The event loop to pop a waiter from

        Returns:
            A waiting task, or None if no waiters exist for that loop
        """
        with self._lock:
            if loop in self._waiters and self._waiters[loop]:
                return self._waiters[loop].popleft()
            return None

    def pop_any_waiter(self) -> tuple["EventLoop | None", "RawTask[Command, Any, Any] | None"]:
        """
        Pop and return the first waiter from any event loop.

        Returns:
            Tuple of (event_loop, task), or (None, None) if no waiters
        """
        with self._lock:
            for loop, waiters in self._waiters.items():
                if waiters:
                    return loop, waiters.popleft()
            return None, None

    def has_waiters(self) -> bool:
        """Check if there are any waiters across all event loops."""
        with self._lock:
            return any(waiters for waiters in self._waiters.values())

    def has_waiters_for_loop(self, loop: "EventLoop") -> bool:
        """Check if there are any waiters for a specific event loop."""
        with self._lock:
            return bool(self._waiters.get(loop))

    def get_all_waiters(self) -> dict["EventLoop", deque["RawTask[Command, Any, Any]"]]:
        """
        Get all waiters grouped by event loop, clearing internal storage.

        Returns:
            Dict mapping event loops to their waiting task queues
        """
        with self._lock:
            result = self._waiters
            self._waiters = {}
            return result


class Event:
    """
    A one-shot synchronization primitive for waking multiple waiting tasks.

    An Event starts in the "not set" state. Tasks can wait() on the event,
    blocking until another task calls set(). Once set, the event remains set
    permanently, and all current and future wait() calls return immediately.

    This primitive is ideal for signaling completion of an initialization
    phase or broadcasting a one-time notification to multiple consumers.

    Thread Safety:
        Events support cross-thread coordination with zero overhead for the
        common single-loop case. When accessed from multiple event loops,
        the Event automatically upgrades to thread-safe waiter storage.

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
        # Lazy SyncContext - only created when cross-thread access detected
        self._sync: SyncContext | None = None
        # Home loop - the first event loop to access this event
        self._home_loop: "EventLoop | None" = None
        # Simple waiters for single-loop case (no lock needed)
        self._simple_waiters: set["RawTask[Command, Any, Any]"] | None = set()

    def is_set(self) -> bool:
        """
        Check if the event is set.

        Returns:
            True if the event has been set, False otherwise.
        """
        return self._set

    def _get_or_create_sync(self) -> SyncContext:
        """
        Get or create the SyncContext, migrating simple waiters if needed.

        This is called when cross-thread access is detected.
        """
        if self._sync is None:
            self._sync = SyncContext()
            # Migrate existing simple waiters to SyncContext
            if self._simple_waiters and self._home_loop is not None:
                for waiter in self._simple_waiters:
                    self._sync.add_waiter(self._home_loop, waiter)
            self._simple_waiters = None  # No longer using simple path
        return self._sync

    def _add_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> None:
        """
        Add a waiting task. Uses fast path for single-loop, upgrades for cross-thread.

        Args:
            loop: The event loop the task belongs to
            task: The task waiting on this event
        """
        if self._home_loop is None:
            # First access - set home loop
            self._home_loop = loop

        if loop is self._home_loop and self._sync is None:
            # Fast path: single loop, no lock needed
            assert self._simple_waiters is not None
            self._simple_waiters.add(task)
        else:
            # Slow path: cross-thread access, upgrade to SyncContext
            sync = self._get_or_create_sync()
            sync.add_waiter(loop, task)

    def _wake_all_waiters(self) -> dict["EventLoop", set["RawTask[Command, Any, Any]"]]:
        """
        Get all waiters grouped by event loop, clearing waiter storage.

        Returns:
            Dict mapping event loops to their waiting tasks
        """
        if self._sync is not None:
            # Using SyncContext - get all waiters thread-safely
            return self._sync.get_all_waiters()
        elif self._simple_waiters is not None and self._home_loop is not None:
            # Using simple waiters
            waiters = self._simple_waiters
            self._simple_waiters = set()
            if waiters:
                return {self._home_loop: waiters}
        return {}

    def _has_waiters(self) -> bool:
        """Check if there are any waiters."""
        if self._sync is not None:
            return self._sync.has_waiters()
        return bool(self._simple_waiters)

    def _remove_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> bool:
        """
        Remove a waiting task from this event.

        Args:
            loop: The event loop the task belongs to
            task: The task to remove

        Returns:
            True if the task was found and removed, False otherwise.
        """
        if self._sync is not None:
            return self._sync.remove_waiter(loop, task)
        elif self._simple_waiters is not None:
            if task in self._simple_waiters:
                self._simple_waiters.discard(task)
                return True
        return False

    @coroutine
    def _wait_impl(self, timeout: float | None = None) -> Generator[EventWaitCommand, bool, bool]:
        """Internal coroutine for waiting on the event."""
        end_time = (timer() + timeout) if timeout is not None else None
        result: bool = yield EventWaitCommand(event=self, timeout=end_time)
        return result

    async def wait(self, timeout: float | None = None) -> bool:
        """
        Wait for the event to be set.

        If the event is already set, return immediately with True.
        Otherwise, block until another task calls set() or the timeout expires.

        Args:
            timeout: Optional timeout in seconds. If None, wait indefinitely.

        Returns:
            True if the event was set, False if the timeout expired.
        """
        if self._set:
            return True  # Fast path: event already set
        return await self._wait_impl(timeout)

    @coroutine
    def _set_impl(self) -> Generator[EventSetCommand, None, None]:
        """Internal coroutine for setting the event."""
        self._set = True
        yield EventSetCommand(event=self)

    async def set(self) -> None:
        """
        Set the event, waking all waiting tasks.

        Once set, the event remains set permanently. All current and future
        wait() calls will return immediately.
        """
        if not self._set:
            await self._set_impl()

    def set_nowait(self, source_loop: "EventLoop") -> dict["EventLoop", set["RawTask[Command, Any, Any]"]]:
        """
        Synchronously set the event and return all waiters grouped by loop.

        This method is designed for cross-thread use. It sets the event
        and returns waiters so the caller can wake them appropriately.

        Args:
            source_loop: The event loop initiating the set (for wakeup)

        Returns:
            Dict mapping event loops to their waiting tasks
        """
        self._set = True
        return self._wake_all_waiters()

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

    Thread Safety:
        Locks support cross-thread coordination with zero overhead for the
        common single-loop case. When accessed from multiple event loops,
        the Lock automatically upgrades to thread-safe waiter storage.

    Examples:
        >>> from flowno.core.event_loop.event_loop import EventLoop
        >>> from flowno.core.event_loop.primitives import spawn
        >>> from flowno.core.event_loop.synchronization import Lock
        >>>
        >>> async def critical_section(name: str, lock: Lock, shared_counter: list):
        ...     print(f"{name}: Waiting for lock")
        ...     async with lock:  # Automatically acquires and releases
        ...         print(f"{name}: Acquired lock, in critical section")
        ...         # Simulate work in critical section
        ...         shared_counter[0] += 1
        ...         print(f"{name}: Counter = {shared_counter[0]}")
        ...     print(f"{name}: Released lock")
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
        self._owner: "RawTask[Command, Any, Any] | None" = None
        # Lazy LockSyncContext - only created when cross-thread access detected
        self._sync: LockSyncContext | None = None
        # Home loop - the first event loop to access this lock
        self._home_loop: "EventLoop | None" = None
        # Simple waiters for single-loop case (no lock needed)
        self._simple_waiters: deque["RawTask[Command, Any, Any]"] | None = deque()

    def is_locked(self) -> bool:
        """
        Check if the lock is currently held.

        Returns:
            True if the lock is held by any task, False otherwise.
        """
        return self._locked

    def _get_or_create_sync(self) -> LockSyncContext:
        """
        Get or create the LockSyncContext, migrating simple waiters if needed.

        This is called when cross-thread access is detected.
        """
        if self._sync is None:
            self._sync = LockSyncContext()
            # Migrate existing simple waiters to LockSyncContext
            if self._simple_waiters and self._home_loop is not None:
                for waiter in self._simple_waiters:
                    self._sync.add_waiter(self._home_loop, waiter)
            self._simple_waiters = None  # No longer using simple path
        return self._sync

    def _add_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> None:
        """
        Add a waiting task. Uses fast path for single-loop, upgrades for cross-thread.

        Args:
            loop: The event loop the task belongs to
            task: The task waiting on this lock
        """
        if self._home_loop is None:
            # First access - set home loop
            self._home_loop = loop

        if loop is self._home_loop and self._sync is None:
            # Fast path: single loop, no lock needed
            assert self._simple_waiters is not None
            self._simple_waiters.append(task)
        else:
            # Slow path: cross-thread access, upgrade to LockSyncContext
            sync = self._get_or_create_sync()
            sync.add_waiter(loop, task)

    def _pop_waiter(self, loop: "EventLoop") -> "RawTask[Command, Any, Any] | None":
        """
        Pop the next waiter for a specific event loop (FIFO order).

        Args:
            loop: The event loop to get a waiter for

        Returns:
            The next waiting task, or None if no waiters
        """
        if self._sync is not None:
            return self._sync.pop_waiter(loop)
        elif self._simple_waiters:
            return self._simple_waiters.popleft()
        return None

    def _pop_any_waiter(self) -> tuple["EventLoop | None", "RawTask[Command, Any, Any] | None"]:
        """
        Pop the next waiter from any event loop.

        Returns:
            Tuple of (event_loop, task), or (None, None) if no waiters
        """
        if self._sync is not None:
            return self._sync.pop_any_waiter()
        elif self._simple_waiters and self._home_loop is not None:
            return self._home_loop, self._simple_waiters.popleft()
        return None, None

    def _has_waiters(self) -> bool:
        """Check if there are any waiters."""
        if self._sync is not None:
            return self._sync.has_waiters()
        return bool(self._simple_waiters)

    @coroutine
    def _acquire(self) -> Generator[LockAcquireCommand, None, None]:
        """Internal coroutine for acquiring the lock."""
        yield LockAcquireCommand(lock=self)

    async def acquire(self) -> None:
        """
        Acquire the lock.

        If the lock is available, acquire it immediately and return.
        If the lock is held by another task, block until it becomes available.
        Tasks waiting for the lock are served in FIFO order.
        """
        await self._acquire()

    @coroutine
    def _release(self) -> Generator[LockReleaseCommand, None, None]:
        """Internal coroutine for releasing the lock."""
        yield LockReleaseCommand(lock=self)

    async def release(self) -> None:
        """
        Release the lock.

        The lock must be held by the current task. If other tasks are waiting,
        the next task in FIFO order will acquire the lock.

        Raises:
            AssertionError: If the lock is not held by the current task (checked by event loop).
        """
        await self._release()

    async def __aenter__(self) -> "Lock":
        """
        Acquire the lock when entering an async context.

        This allows using the lock with async with:
            async with lock:
                # critical section

        Returns:
            The lock instance.
        """
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Release the lock when exiting an async context.

        The lock is released even if an exception occurred in the context.
        """
        await self.release()

    def __repr__(self) -> str:
        """Return a string representation of the Lock."""
        state = "locked" if self._locked else "unlocked"
        owner = f" by {self._owner}" if self._owner else ""
        return f"Lock({state}{owner})"


class Condition:
    """
    A condition variable for coordinating tasks based on arbitrary conditions.

    A Condition is always associated with a Lock. It provides wait() and notify()
    operations that allow tasks to wait for a condition to become true and to
    signal when the condition changes.

    Thread Safety:
        Conditions support cross-thread coordination with zero overhead for the
        common single-loop case. When accessed from multiple event loops,
        the Condition automatically upgrades to thread-safe waiter storage.

    Typical usage pattern:
        lock = Lock()
        condition = Condition(lock)

        # Waiter:
        async with condition:
            while not some_condition:
                await condition.wait()  # Atomically releases lock and waits
            # Lock is reacquired here

        # Notifier:
        async with condition:
            # Change the condition
            await condition.notify()  # or notify_all()

    Note: Condition also supports async with syntax, which acquires/releases
    the associated lock automatically.
    """

    def __init__(self, lock: Optional[Lock] = None) -> None:
        """
        Initialize a Condition variable.

        Args:
            lock: The Lock to associate with this condition. If None, a new Lock is created.
        """
        self._lock = lock if lock is not None else Lock()
        # Lazy SyncContext - only created when cross-thread access detected
        self._sync: SyncContext | None = None
        # Home loop - the first event loop to access this condition
        self._home_loop: "EventLoop | None" = None
        # Simple waiters for single-loop case (no lock needed)
        self._simple_waiters: set["RawTask[Command, Any, Any]"] | None = set()

    @property
    def lock(self) -> Lock:
        """Get the associated lock."""
        return self._lock

    def _get_or_create_sync(self) -> SyncContext:
        """
        Get or create the SyncContext, migrating simple waiters if needed.

        This is called when cross-thread access is detected.
        """
        if self._sync is None:
            self._sync = SyncContext()
            # Migrate existing simple waiters to SyncContext
            if self._simple_waiters and self._home_loop is not None:
                for waiter in self._simple_waiters:
                    self._sync.add_waiter(self._home_loop, waiter)
            self._simple_waiters = None  # No longer using simple path
        return self._sync

    def _add_waiter(self, loop: "EventLoop", task: "RawTask[Command, Any, Any]") -> None:
        """
        Add a waiting task. Uses fast path for single-loop, upgrades for cross-thread.

        Args:
            loop: The event loop the task belongs to
            task: The task waiting on this condition
        """
        if self._home_loop is None:
            # First access - set home loop
            self._home_loop = loop

        if loop is self._home_loop and self._sync is None:
            # Fast path: single loop, no lock needed
            assert self._simple_waiters is not None
            self._simple_waiters.add(task)
        else:
            # Slow path: cross-thread access, upgrade to SyncContext
            sync = self._get_or_create_sync()
            sync.add_waiter(loop, task)

    def _pop_waiter(self, loop: "EventLoop") -> "RawTask[Command, Any, Any] | None":
        """
        Pop one waiter for a specific event loop.

        Args:
            loop: The event loop to get a waiter for

        Returns:
            A waiting task, or None if no waiters
        """
        if self._sync is not None:
            return self._sync.pop_waiter(loop)
        elif self._simple_waiters:
            return self._simple_waiters.pop()
        return None

    def _get_all_waiters(self) -> dict["EventLoop", set["RawTask[Command, Any, Any]"]]:
        """
        Get all waiters grouped by event loop, clearing waiter storage.

        Returns:
            Dict mapping event loops to their waiting tasks
        """
        if self._sync is not None:
            return self._sync.get_all_waiters()
        elif self._simple_waiters is not None and self._home_loop is not None:
            waiters = self._simple_waiters
            self._simple_waiters = set()
            if waiters:
                return {self._home_loop: waiters}
        return {}

    def _has_waiters(self) -> bool:
        """Check if there are any waiters."""
        if self._sync is not None:
            return self._sync.has_waiters()
        return bool(self._simple_waiters)

    def _has_waiters_for_loop(self, loop: "EventLoop") -> bool:
        """Check if there are any waiters for a specific event loop."""
        if self._sync is not None:
            return self._sync.has_waiters_for_loop(loop)
        return bool(self._simple_waiters) and self._home_loop is loop

    @coroutine
    def _wait(self) -> Generator:
        """Internal coroutine for waiting on the condition."""
        from .commands import ConditionWaitCommand
        yield ConditionWaitCommand(condition=self)

    async def wait(self) -> None:
        """
        Wait for the condition to be notified.

        This method atomically releases the associated lock and blocks the task
        until another task calls notify() or notify_all(). When the task wakes up,
        it automatically reacquires the lock before returning.

        The task must hold the lock before calling wait().

        Typical usage is in a while loop checking the condition:
            async with lock:
                while not condition_is_met():
                    await condition.wait()
        """
        await self._wait()

    @coroutine
    def _notify(self, n: int = 1) -> Generator:
        """Internal coroutine for notifying waiters."""
        from .commands import ConditionNotifyCommand

        if n == 1:
            yield ConditionNotifyCommand(condition=self, all=False)
        else:
            # For n > 1, we'd need to extend the command to support count
            # For now, delegate to notify_all if n > 1
            yield ConditionNotifyCommand(condition=self, all=True)

    async def notify(self, n: int = 1) -> None:
        """
        Wake up one or more tasks waiting on this condition.

        The task must hold the lock before calling notify().
        Woken tasks are moved to the lock's wait queue and will reacquire
        the lock in FIFO order.

        :param n: Number of tasks to wake (default 1). Use notify_all() to wake all.
        """
        await self._notify(n)

    @coroutine
    def _notify_all(self) -> Generator:
        """Internal coroutine for notifying all waiters."""
        from .commands import ConditionNotifyCommand
        yield ConditionNotifyCommand(condition=self, all=True)

    async def notify_all(self) -> None:
        """
        Wake up all tasks waiting on this condition.

        The task must hold the lock before calling notify_all().
        All woken tasks are moved to the lock's wait queue and will reacquire
        the lock in FIFO order.
        """
        await self._notify_all()

    def notify_nowait(self, target_loop: "EventLoop") -> bool:
        """
        Synchronously notify one waiter on this condition.

        This method is thread-safe and can be called from any thread.
        It notifies one waiter and moves them to the lock's waiter queue.

        Args:
            target_loop: The event loop where the waiter should be woken

        Returns:
            True if a waiter was notified, False otherwise
        """
        waiter = self._pop_waiter(target_loop)
        if waiter is None:
            return False

        # Move waiter to lock's waiter queue (they need to reacquire lock)
        # If the lock is free, we can wake the waiter immediately and give it the lock
        if not self._lock._locked:
            self._lock._locked = True
            self._lock._owner = waiter
            # Task is now running, decrement waiting counter
            target_loop._waiting_on_sync_primitives -= 1
            with target_loop._tasks_lock:
                target_loop.tasks.append((waiter, None, None))
        else:
            # Lock is held, move waiter to lock waiters (still waiting, no counter change)
            self._lock._add_waiter(target_loop, waiter)

        return True

    def notify_all_nowait(self, target_loop: "EventLoop") -> int:
        """
        Synchronously notify all waiters on this condition.

        This method is thread-safe and can be called from any thread.
        It handles waiter notification synchronously through the event loop.

        Unlike the normal notify_all path, this does NOT require holding the lock.

        Args:
            target_loop: The event loop where waiters should be woken

        Returns:
            The number of waiters that were notified
        """
        count = 0
        while True:
            waiter = self._pop_waiter(target_loop)
            if waiter is None:
                break
            count += 1

            # If the lock is free, we can wake the first waiter immediately and give it the lock
            if not self._lock._locked:
                self._lock._locked = True
                self._lock._owner = waiter
                # Task is now running, decrement waiting counter
                target_loop._waiting_on_sync_primitives -= 1
                with target_loop._tasks_lock:
                    target_loop.tasks.append((waiter, None, None))
            else:
                # Lock is held, move waiter to lock waiters (still waiting, no counter change)
                self._lock._add_waiter(target_loop, waiter)

        return count

    async def __aenter__(self) -> "Condition":
        """
        Acquire the associated lock when entering an async context.

        This allows using the condition with async with:
            async with condition:
                while not some_condition:
                    await condition.wait()

        Returns:
            The condition instance.
        """
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Release the associated lock when exiting an async context.

        The lock is released even if an exception occurred in the context.
        """
        await self._lock.release()

    def __repr__(self) -> str:
        """Return a string representation of the Condition."""
        return f"Condition(lock={self._lock})"


class CountdownLatch:
    """
    A synchronization primitive that allows one or more tasks to wait until
    a set of operations in other tasks completes.

    The latch is initialized with a given count. Tasks can then wait on the latch,
    and each count_down() call decreases the counter. When the counter reaches zero,
    all waiting tasks are released.

    This is currently used in :py:mod:`~flowno.core.node_base` where a node needs to ensure
    all downstream nodes have consumed its previous output before generating new data.

    Implementation uses Event and Lock primitives:
    - Event provides the one-shot signal when count reaches zero
    - Lock protects the counter during decrements

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
        self._event = Event()
        self._lock = Lock()
        # If count is already 0, set the event so wait() doesn't block
        if count == 0:
            self._event._set = True

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

        Warning:
            This is not thread-safe. Should only be used when you know no other
            tasks are accessing the latch.
        """
        if count < 0:
            raise ValueError("CountdownLatch count must be non-negative")
        self._count = count

    @coroutine
    def _wait(self) -> Generator[EventWaitCommand, None, None]:
        """Internal coroutine for waiting on the event."""
        yield EventWaitCommand(event=self._event)

    async def wait(self) -> None:
        """
        Block until the latch has counted down to zero.

        This coroutine will not complete until count_down() has been called
        the specified number of times.

        Multiple tasks can wait on the same latch; they will all be released
        when the count reaches zero.
        """
        await self._wait()

    class ZeroLatchError(Exception):
        """
        Exception raised when trying to count down a latch that is already at zero.

        This exception is used internally to indicate that the latch has already
        been counted down to zero, and no further countdowns are possible.
        """
        pass

    @coroutine
    def _count_down(self, exception_if_zero: bool = False) -> Generator[LockAcquireCommand | LockReleaseCommand | EventSetCommand, None, None]:
        """Internal coroutine for counting down the latch."""
        # Acquire lock
        yield LockAcquireCommand(lock=self._lock)

        # Check and decrement count
        if self._count == 0:
            # Release lock before raising/warning
            yield LockReleaseCommand(lock=self._lock)
            if exception_if_zero:
                raise self.ZeroLatchError("Cannot count down a latch that is already at zero")
            else:
                logger.warning(f"counted down on already zero latch: {self}")
        else:
            logger.debug(f"counting down latch: {self}")
            self._count -= 1
            if self._count == 0:
                # Set event while holding lock
                yield EventSetCommand(event=self._event)
            # Release lock
            yield LockReleaseCommand(lock=self._lock)

    async def count_down(self, exception_if_zero: bool = False) -> None:
        """
        Decrement the latch count by one.

        If the count reaches zero as a result of this call, all waiting
        tasks will be unblocked by setting the internal event.

        If the latch is already at zero, this method logs a warning (or raises
        an exception if exception_if_zero is True).

        Args:
            exception_if_zero: If True, raise ZeroLatchError when trying to
                             count down a latch that is already at zero.

        Raises:
            ZeroLatchError: If exception_if_zero is True and the latch is already at zero.
        """
        await self._count_down(exception_if_zero)

    def countdown_nowait(self, target_loop: "EventLoop") -> None:
        """
        Synchronously decrement the latch count by one.

        This method is designed to be called from within a command handler,
        where async operations are not possible. It handles waiter notification
        synchronously through the event loop.

        Args:
            target_loop: The event loop to use for notifying waiters
        """
        if self._count == 0:
            logger.warning(f"countdown_nowait called on already zero latch: {self}")
            return

        self._count -= 1
        if self._count == 0:
            # Set event and wake all waiting tasks using the Event's waiter management
            all_waiters = self._event.set_nowait(target_loop)

            # Schedule all waiters to run
            for loop, waiters in all_waiters.items():
                # Decrement waiting counter for woken tasks
                loop._waiting_on_sync_primitives -= len(waiters)
                if loop is target_loop:
                    # Same loop - add directly
                    for waiter in waiters:
                        target_loop.tasks.append((waiter, None, None))
                else:
                    # Different loop - need to wake it up
                    with loop._tasks_lock:
                        for waiter in waiters:
                            loop.tasks.append((waiter, None, None))
                    try:
                        loop._wakeup_writer.send(b"\x00")
                    except (BlockingIOError, OSError):
                        pass
    
    def __repr__(self) -> str:
        """
        Return a string representation of the CountdownLatch.

        This representation includes the current count value.
        """
        return f"CountdownLatch(count={self._count}, set={self._event.is_set()})"


__all__ = [
    "Event",
    "Lock",
    "Condition",
    "CountdownLatch",
]
