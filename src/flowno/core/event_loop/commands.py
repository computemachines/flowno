"""
Internal Command Types for the Flowno Event Loop
-------------------------------------------------

This module defines the command types used by the Flowno event loop to implement
its cooperative multitasking system. Commands are yielded by coroutines and
interpreted by the event loop to perform operations like task scheduling,
I/O operations, and synchronization.

.. warning::
    These command types are used internally by the Flowno event loop to control
    task scheduling, socket operations, and asynchronous queue interactions.
    They are not part of the public API. Normal users should rely on the public
    awaitable primitives (e.g. :func:`sleep`, :func:`spawn`, etc.) rather than
    yielding these commands directly.
"""

from abc import ABC
from collections.abc import Generator
from dataclasses import dataclass
from types import coroutine
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from flowno.core.node_base import ObjectDraftNode
    from flowno.core.event_loop.tasks import TaskHandle
    from flowno.core.event_loop.selectors import SocketHandle
    from flowno.core.event_loop.queues import AsyncQueue

from .types import DeltaTime, RawTask

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@dataclass
class Command(ABC):
    """
    Base abstract class for all internal command types.

    .. note::
       These commands are part of the Flowno event loop's internal control
       mechanism. Application developers should not use or yield these commands
       directly.
    """

    pass


@dataclass
class SpawnCommand(Generic[_T_co], Command):
    """
    Internal command to spawn a new raw task.

    :param raw_task: The raw task coroutine to be scheduled.

    .. note::
       Users should use the public :func:`spawn` primitive instead of yielding
       a SpawnCommand directly.
    """

    raw_task: RawTask[Command, Any, _T_co]


@dataclass
class JoinCommand(Generic[_T], Command):
    """
    Internal command to suspend a task until another task finishes.

    :param task_handle: A handle to the task to join.

    .. note::
       This is used internally to implement the :meth:`TaskHandle.join` awaitable.
    """

    task_handle: "TaskHandle[_T]"


@dataclass
class SleepCommand(Command):
    """
    Internal command to suspend a task until a specified time.

    :param end_time: The time (as a DeltaTime) until which the task should sleep.

    .. note::
       Users should use the public :func:`sleep` primitive rather than yielding
       a SleepCommand.
    """

    end_time: DeltaTime


@dataclass
class SocketCommand(Command):
    """
    Base internal command for socket operations.

    :param handle: The socket handle associated with this operation.

    .. note::
       These commands are used by the event loop to implement non-blocking I/O.
    """

    handle: "SocketHandle"


class SocketSendCommand(SocketCommand):
    """
    Internal command indicating that data is to be sent over a socket.
    """

    pass


class SocketRecvCommand(SocketCommand):
    """
    Internal command indicating that data is to be received from a socket.
    """

    pass


class SocketAcceptCommand(SocketCommand):
    """
    Internal command requesting to accept a new connection on a socket.
    """

    pass


@dataclass
class ExitCommand(Command):
    """
    Internal command to forcibly terminate the event loop.

    :param return_value: Optional value to return from run_until_complete (when join=True).
    :param exception: Optional exception to raise from run_until_complete.

    .. note::
       This command causes the event loop to terminate immediately, regardless of
       any remaining tasks. Similar to sys.exit() but specific to the event loop.
    """

    return_value: object = None
    exception: Exception | None = None


@dataclass
class EventWaitCommand(Command):
    """
    Wait for an event to be set (one-shot signal).

    :param event: The Event synchronization primitive to wait on.

    .. note::
       This command blocks the task until the event is set. If the event is
       already set when this command is issued, the task resumes immediately.
    """

    event: Any  # Event type from synchronization.py


@dataclass
class EventSetCommand(Command):
    """
    Set an event, waking all waiting tasks.

    :param event: The Event synchronization primitive to set.

    .. note::
       This command sets the event and wakes all tasks blocked on event.wait().
       The event remains set permanently (one-shot semantics).
    """

    event: Any  # Event type from synchronization.py


@dataclass
class LockAcquireCommand(Command):
    """
    Acquire a lock (mutual exclusion).

    :param lock: The Lock synchronization primitive to acquire.

    .. note::
       This command blocks the task until the lock becomes available.
       If the lock is already available, the task acquires it immediately.
    """

    lock: Any  # Lock type from synchronization.py


@dataclass
class LockReleaseCommand(Command):
    """
    Release a lock, waking the next waiting task.

    :param lock: The Lock synchronization primitive to release.

    .. note::
       This command releases the lock and wakes the next waiting task (FIFO order).
       Only the lock owner can release the lock.
    """

    lock: Any  # Lock type from synchronization.py


@dataclass
class ConditionWaitCommand(Command):
    """
    Wait on a condition variable (atomically releases lock).

    :param condition: The Condition synchronization primitive to wait on.

    .. note::
       This command atomically releases the associated lock and blocks the task
       until another task calls notify() or notify_all() on the condition.
       When the task wakes up, it automatically reacquires the lock before continuing.
       The task must hold the lock before calling wait().
    """

    condition: Any  # Condition type from synchronization.py


@dataclass
class ConditionNotifyCommand(Command):
    """
    Notify waiters on a condition variable.

    :param condition: The Condition synchronization primitive to notify.
    :param all: If True, notify all waiters (notify_all). If False, notify one waiter (notify).

    .. note::
       This command wakes one or all tasks waiting on the condition.
       Notified tasks are moved to the lock's wait queue and must reacquire the lock.
       The task must hold the lock before calling notify().
    """

    condition: Any  # Condition type from synchronization.py
    all: bool  # True = notify_all, False = notify


@dataclass
class CancelCommand(Generic[_T], Command):
    """
    Internal command to cancel a task and wait for its result.

    :param task_handle: A handle to the task to cancel.

    .. note::
       This is used internally to implement the awaitable :meth:`TaskHandle.cancel` method.
       Unlike the non-awaitable cancel, this suspends until the cancelled task finishes
       and returns its result value.
    """

    task_handle: "TaskHandle[_T]"


@dataclass
class StreamCancelCommand(Command):
    """
    Internal command to cancel a stream, causing the producer to receive StreamCancelled.

    :param stream: The stream being cancelled
    :param producer_node: The node producing data to the stream
    :param consumer_input: The input port reference of the consuming node

    .. note::
       This command is yielded by consumers to cancel streams and notify producers.
    """

    stream: "Stream[Any]"
    producer_node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"
    consumer_input: "FinalizedInputPortRef[Any]"
