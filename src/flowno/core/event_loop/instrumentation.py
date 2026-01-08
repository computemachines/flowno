"""
Event Loop Instrumentation System.

This module provides a flexible instrumentation system for monitoring and debugging
the Flowno event loop. It captures metrics and events for socket operations, queue
operations, and other event loop activities.

The instrumentation system uses a context manager pattern, allowing multiple
instrumentation hooks to be applied within different scopes of code.

Example:
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.instrumentation import PrintInstrument
    >>> from flowno.core.event_loop.queues import AsyncQueue
    >>> 
    >>> # Define a simple coroutine that uses a queue
    >>> async def queue_example():
    ...     queue = AsyncQueue()
    ...     # Put an item into the queue
    ...     await queue.put(42)
    ...     # Get the item back from the queue
    ...     value = await queue.get()
    ...     return value
    >>> 
    >>> # Create an event loop and run with instrumentation
    >>> event_loop = EventLoop()
    >>> with PrintInstrument():
    ...     result = event_loop.run_until_complete(queue_example(), join=True)
    ...
    [QUEUE-PUT] Item put in queue: 42
    [QUEUE-GET] Item retrieved from queue: 42
    >>> print(result)
    42
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, TypeVar

from typing_extensions import Self, override

if TYPE_CHECKING:
    from flowno.core.event_loop.commands import Command
    from flowno.core.event_loop.queues import AsyncQueue
    from flowno.core.event_loop.selectors import SocketHandle
    from flowno.core.event_loop.types import RawTask, _Address

import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")

_current_instrument: ContextVar["EventLoopInstrument | None"] = ContextVar("_current_instrument", default=None)


@dataclass
class InstrumentationMetadata:
    """Base metadata class for instrumentation events."""
    _task: "RawTask[Any, None, None]"
    _command: "Command"
    socket_handle: "SocketHandle"
    immediate: bool = False
    start_time: float = field(default_factory=time)


@dataclass
class ReadySocketInstrumentationMetadata(InstrumentationMetadata):
    """Metadata for socket operations that have completed."""
    finish_time: float = field(default_factory=time)

    @classmethod
    def from_instrumentation_metadata(
        cls, metadata: InstrumentationMetadata, **kwargs: Any
    ) -> "ReadySocketInstrumentationMetadata":
        return cls(
            _task=metadata._task,
            _command=metadata._command,
            socket_handle=metadata.socket_handle,
            immediate=metadata.immediate,
            start_time=metadata.start_time,
            **kwargs,
        )


@dataclass
class SocketRecvDataMetadata:
    """Metadata for received socket data."""
    socket_handle: "SocketHandle"
    data: bytes


@dataclass
class SocketSendDataMetadata:
    """Metadata for sent socket data."""
    socket_handle: "SocketHandle"
    data: bytes
    bytes_sent: int  # Actual bytes accepted by kernel (may differ from len(data))


@dataclass
class SocketConnectStartMetadata:
    """Metadata for socket connection initiation."""
    socket_handle: "SocketHandle"
    target_address: "_Address"
    immediate: bool = False
    start_time: float = field(default_factory=time)


@dataclass
class SocketConnectReadyMetadata(SocketConnectStartMetadata):
    """Metadata for completed socket connections."""
    finish_time: float = field(default_factory=time)

    @classmethod
    def from_instrumentation_metadata(
        cls, metadata: SocketConnectStartMetadata, **kwargs: Any
    ) -> "SocketConnectReadyMetadata":
        return cls(
            socket_handle=metadata.socket_handle,
            target_address=metadata.target_address,
            immediate=metadata.immediate,
            start_time=metadata.start_time,
            **kwargs,
        )


@dataclass
class TLSHandshakeMetadata:
    """Metadata for completed TLS handshakes."""
    socket_handle: "SocketHandle"
    cipher: tuple[str, str, int] | None  # (cipher_name, protocol, bits)
    version: str | None  # e.g., "TLSv1.3"
    server_hostname: str | None
    start_time: float
    finish_time: float = field(default_factory=time)


@dataclass
class TaskSendMetadata:
    """Metadata for task send operations."""
    task: "RawTask[Command, Any, Any]"
    send_value: Any


@dataclass
class TaskThrowMetadata:
    """Metadata for task throw operations."""
    task: "RawTask[Command, Any, Any]"
    exception: Exception


class EventLoopInstrument:
    """
    Base class for event loop instrumentation.
    
    This class provides hooks for various event loop operations. Subclasses can
    override these methods to implement custom monitoring or logging.
    """
    _token: Token[Self | None] | None = None

    def on_queue_get(self, queue: "AsyncQueue[T]", item: T, immediate: bool) -> None:
        """
        Called every time a queue completes a get command.

        If the task blocks on an empty queue, this callback fires when an items
        is available and returned.

        Args:
            queue (AsyncQueue[T]): The queue which the item was popped.
            item (T): The item that was popped from the queue.
        """
        pass

    def on_queue_put(self, queue: "AsyncQueue[T]", item: T, immediate: bool) -> None:
        """
        Called every time a queue processes a put command.

        If the task blocks on a full queue, this callback fires when the queue
        accepts the item.

        Args:
            queue (AsyncQueue[T]): The queue which the item was added to.
            item (T): The item that was added to the queue.
        """
        pass

    def on_socket_connect_start(self, metadata: SocketConnectStartMetadata) -> None:
        """
        Called when a socket connection is initiated.
        
        Args:
            metadata: Connection metadata including target address
        """
        pass

    def on_socket_connect_ready(self, metadata: SocketConnectReadyMetadata) -> None:
        """
        Called when a socket connection has been established.
        
        Args:
            metadata: Connection metadata including duration and target address
        """
        pass

    def on_socket_recv_start(self, metadata: InstrumentationMetadata) -> None:
        """
        Called when a task starts waiting on a socket recv.
        
        Args:
            metadata: Socket operation metadata
        """
        pass

    def on_socket_recv_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        """
        Called when the socket is ready for reading.
        
        Args:
            metadata: Socket operation metadata including duration
        """
        pass

    def on_socket_recv_data(self, metadata: SocketRecvDataMetadata) -> None:
        """
        Called immediately after the actual bytes have been read.

        Args:
            metadata: Metadata including the received bytes
        """
        pass

    def on_socket_send_data(self, metadata: "SocketSendDataMetadata") -> None:
        """
        Called immediately after bytes have been sent to the kernel.

        Args:
            metadata: Metadata including the sent bytes and actual bytes_sent count
        """
        pass

    def on_tls_handshake_complete(self, metadata: "TLSHandshakeMetadata") -> None:
        """
        Called after a TLS handshake completes successfully.

        Args:
            metadata: Metadata including cipher info and TLS version
        """
        pass

    def on_socket_send_start(self, metadata: InstrumentationMetadata) -> None:
        """
        Called when a task starts waiting on a socket send.
        
        Args:
            metadata: Socket operation metadata
        """
        pass

    def on_socket_send_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        """
        Called when the socket send operation completes.
        
        Args:
            metadata: Socket operation metadata including duration
        """
        pass

    def on_socket_accept_start(self, metadata: InstrumentationMetadata) -> None:
        """
        Called when a task starts waiting on a socket accept.
        
        Args:
            metadata: Socket operation metadata
        """
        pass

    def on_socket_accept_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        """
        Called when a socket accept operation completes.
        
        Args:
            metadata: Socket operation metadata including duration
        """
        pass
        
    def on_socket_close(self, metadata: InstrumentationMetadata) -> None:
        """
        Called when a socket connection is closed.
        
        Args:
            metadata: Socket operation metadata
        """
        pass

    def on_task_before_send(self, metadata: TaskSendMetadata) -> None:
        """
        Called before a task's send() method is invoked.
        
        Args:
            metadata: Task send metadata including the task and value being sent
        """
        pass

    def on_task_after_send(self, metadata: TaskSendMetadata, command: "Command") -> None:
        """
        Called after a task's send() method completes successfully.
        
        Args:
            metadata: Task send metadata including the task and value that was sent
            command: The command yielded by the task
        """
        pass

    def on_task_before_throw(self, metadata: TaskThrowMetadata) -> None:
        """
        Called before a task's throw() method is invoked.
        
        Args:
            metadata: Task throw metadata including the task and exception being thrown
        """
        pass

    def on_task_after_throw(self, metadata: TaskThrowMetadata, command: "Command") -> None:
        """
        Called after a task's throw() method completes successfully.
        
        Args:
            metadata: Task throw metadata including the task and exception that was thrown
            command: The command yielded by the task
        """
        pass

    def on_task_completed(self, task: "RawTask[Command, Any, Any]", result: Any) -> None:
        """
        Called when a task completes successfully (StopIteration).
        
        Args:
            task: The task that completed
            result: The return value of the task
        """
        pass

    def on_task_error(self, task: "RawTask[Command, Any, Any]", exception: Exception) -> None:
        """
        Called when a task raises an exception.
        
        Args:
            task: The task that raised the exception
            exception: The exception that was raised
        """
        pass

    def on_task_cancelled(self, task: "RawTask[Command, Any, Any]", exception: Exception) -> None:
        """
        Called when a task is cancelled (TaskCancelled exception).
        
        Args:
            task: The task that was cancelled
            exception: The TaskCancelled exception
        """
        pass

    def __enter__(self: Self) -> Self:
        # token to restore old value of instrument
        # TODO: change to a list so I can use multiple instruments at the same time
        self._token = _current_instrument.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        _current_instrument.reset(self._token)
        return False


class PrintInstrument(EventLoopInstrument):
    """
    Event loop instrument that prints information to stdout.
    
    This instrument outputs detailed information about socket operations.
    """
    print = print

    def _get_peer_info(self, sock_handle: SocketHandle) -> tuple[str, int]:
        try:
            return sock_handle.socket.getpeername()
        except (OSError, AttributeError):
            raise

    @override
    def on_socket_connect_start(self, metadata: SocketConnectStartMetadata) -> None:
        peer = metadata.target_address
        self.print(f"[CONNECT] Connecting to {peer}.")

    @override
    def on_socket_connect_ready(self, metadata: SocketConnectReadyMetadata) -> None:
        duration = metadata.finish_time - metadata.start_time
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(
            f"[CONNECT] Connected to {peer} in {duration:.4f}s via {metadata.socket_handle.socket.getsockname()}"
        )

    @override
    def on_socket_send_start(self, metadata: InstrumentationMetadata) -> None:
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(f"[SEND] Starting send to {peer}")

    @override
    def on_socket_send_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        duration = metadata.finish_time - metadata.start_time
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(f"[SEND] Completed send to {peer} in {duration:.4f}s")

    @override
    def on_socket_recv_start(self, metadata: InstrumentationMetadata) -> None:
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(f"[RECV] Waiting for data from {peer}")

    @override
    def on_socket_recv_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        duration = metadata.finish_time - metadata.start_time
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(f"[RECV] Ready to receive data from {peer} in {duration:.4f}s")

    @override
    def on_socket_close(self, metadata: InstrumentationMetadata) -> None:
        peer = self._get_peer_info(metadata.socket_handle)
        self.print(f"[CLOSE] Connection closed to {peer}")

    @override
    def on_socket_recv_data(self, metadata: SocketRecvDataMetadata) -> None:
        chunk_len = len(metadata.data)
        # Maybe show the first 50 bytes if it's textual data:
        chunk_preview = metadata.data[:50].decode("utf-8", errors="replace")
        self.print(f"[RECV-DATA] Got {chunk_len} bytes: {chunk_preview!r}")
        self.print(f"[RECV-DATA] FULL DATA:\n{metadata.data.decode()!r}")

    @override
    def on_socket_send_data(self, metadata: SocketSendDataMetadata) -> None:
        data_len = len(metadata.data)
        bytes_sent = metadata.bytes_sent
        # Show first 50 bytes if textual
        data_preview = metadata.data[:50].decode("utf-8", errors="replace")
        self.print(f"[SEND-DATA] Sent {bytes_sent}/{data_len} bytes: {data_preview!r}")

    @override
    def on_tls_handshake_complete(self, metadata: TLSHandshakeMetadata) -> None:
        duration = metadata.finish_time - metadata.start_time
        cipher_info = metadata.cipher[0] if metadata.cipher else "unknown"
        self.print(
            f"[TLS] Handshake complete in {duration:.4f}s: {metadata.version}, {cipher_info}"
        )


class LogInstrument(PrintInstrument):
    """
    Event loop instrument that logs information using the logging module.
    
    This instrument uses the debug log level for all messages.
    """
    print = logger.debug


EMPTY_INSTRUMENT: Final[EventLoopInstrument] = EventLoopInstrument()


def get_current_instrument() -> EventLoopInstrument:
    """
    Get the current instrumentation context.
    
    Returns:
        The currently active instrument or an empty instrument if none is active.
    """
    instrument = _current_instrument.get()
    if instrument:
        return instrument
    else:
        return EMPTY_INSTRUMENT


__all__ = [
    "EventLoopInstrument",
    "PrintInstrument",
    "LogInstrument",
    "InstrumentationMetadata",
    "ReadySocketInstrumentationMetadata",
    "SocketRecvDataMetadata",
    "SocketSendDataMetadata",
    "SocketConnectStartMetadata",
    "SocketConnectReadyMetadata",
    "TLSHandshakeMetadata",
    "TaskSendMetadata",
    "TaskThrowMetadata",
    "get_current_instrument",
]
