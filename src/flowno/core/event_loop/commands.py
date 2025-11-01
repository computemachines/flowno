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
class QueueGetCommand(Generic[_T], Command):
    """
    Internal command to retrieve an item from an asynchronous queue.

    :param queue: The asynchronous queue from which to retrieve the item.
    :param peek: If True, the command will not remove the item from the queue.

    .. note::
       This command is used internally to implement the blocking get behavior.
    """

    queue: "AsyncQueue[_T]"
    peek: bool = False


@dataclass
class QueuePutCommand(Generic[_T], Command):
    """
    Internal command to put an item into an asynchronous queue.

    :param queue: The asynchronous queue into which the item should be inserted.
    :param item: The item to be inserted.

    .. note::
       This command is used internally to implement the blocking put behavior.
    """

    queue: "AsyncQueue[_T]"
    item: _T


@dataclass
class QueueCloseCommand(Generic[_T], Command):
    """
    Internal command to close an asynchronous queue.

    :param queue: The asynchronous queue to be closed.

    .. note::
       This command is used internally by the event loop when closing queues.
    """

    queue: "AsyncQueue[_T]"


@dataclass
class QueueNotifyGettersCommand(Generic[_T], Command):
    """
    Internal command to notify tasks waiting for items on an asynchronous queue.

    :param queue: The asynchronous queue whose waiting getters should be notified.

    .. note::
       This command is used internally when an item is added to a queue to wake up
       tasks blocked on a get operation.
    """

    queue: "AsyncQueue[_T]"


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
