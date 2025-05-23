"""
Low-level concurrency primitives for the Flowno event loop.

This module provides the core asynchronous primitives that enable cooperative
multitasking in Flowno. These primitives are similar to those provided by 
asyncio but specifically tailored for Flowno's event loop.

Examples:
    Sleep can be used directly with the event loop:
    
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.primitives import sleep
    >>> 
    >>> async def delayed_hello():
    ...     print("Hello")
    ...     duration = await sleep(0.5)  # pause for 0.5 seconds
    ...     print(f"World! (slept for {duration:.1f}s)")
    ...     return "Done"
    >>> 
    >>> loop = EventLoop()
    >>> result = loop.run_until_complete(delayed_hello(), join=True)
    Hello
    World! (slept for 0.5s)
    >>> print(result)
    Done
    
    The azip function combines multiple asynchronous streams:
    
    >>> from flowno import node, FlowHDL, Stream
    >>> from flowno.core.event_loop.primitives import azip
    >>> 
    >>> @node
    ... async def Numbers(count: int):
    ...     for i in range(count):
    ...         yield i
    >>> 
    >>> @node(stream_in=["a", "b"])
    ... async def Pairs(a: Stream[int], b: Stream[str]):
    ...     async for num, letter in azip(a, b):
    ...         yield f"{num}:{letter}"
    >>> 
    >>> @node
    ... async def Letters(chars: str):
    ...     for c in chars:
    ...         yield c
    >>> 
    >>> with FlowHDL() as f:
    ...     f.nums = Numbers(3)
    ...     f.chars = Letters("ABC")
    ...     f.pairs = Pairs(f.nums, f.chars)
    ... 
    >>> f.run_until_complete()
    >>> f.pairs.get_data()
    ('0:A', '1:B', '2:C')
"""

import logging
import socket as _socket
import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from timeit import default_timer as timer
from types import coroutine
from typing import Any, TypeVar, cast, overload

from typing_extensions import Unpack

from .commands import SleepCommand, SpawnCommand, ExitCommand
from .selectors import SocketHandle, TLSSocketHandle
from .tasks import TaskHandle
from .types import DeltaTime, RawTask

logger = logging.getLogger(__name__)

_T_co = TypeVar("_T_co", covariant=True)
_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_T3 = TypeVar("_T3")
_T4 = TypeVar("_T4")

@coroutine
def spawn(
    raw_task: RawTask[
        Any,
        Any,
        _T_co
    ]
) -> Generator[
    SpawnCommand[_T_co],
    Any, # pyright: ignore[reportExplicitAny]
    "TaskHandle[_T_co]",
]:
    """
    Spawn a new task to run concurrently with the current task.
    
    Args:
        raw_task: The coroutine to run as a new task.
        
    Returns:
        A TaskHandle that can be used to wait for the task to complete.
    """
    sending = yield SpawnCommand[_T_co](raw_task=raw_task)
    assert isinstance(sending, TaskHandle), "Expected a TaskHandle"
    return cast("TaskHandle[_T_co]", sending)


@coroutine
def sleep(duration: DeltaTime) -> Generator[SleepCommand, None, DeltaTime]:
    """
    Suspend the current task for the specified duration.
    
    Args:
        duration: The number of seconds to sleep.
        
    Returns:
        The actual time slept (which may be slightly longer than requested).
    """
    start = timer()
    desired_end = start + duration
    yield SleepCommand(desired_end)
    actual_end = timer()
    return actual_end - start


@coroutine
def exit(return_value: Any = None, exception: Exception | None = None) -> Generator[ExitCommand, None, None]:
    """
    Forcibly terminate the event loop.
    
    This is a primitive that allows immediate termination of the event loop,
    regardless of any remaining tasks or operations. It's similar to sys.exit()
    but specific to the Flowno event loop.
    
    Args:
        return_value: Optional value to return from run_until_complete (when join=True).
        exception: Optional exception to raise from run_until_complete.
        
    Returns:
        This function never returns normally as it terminates the event loop.
        
    Examples:
        >>> async def early_exit():
        ...     print("About to exit")
        ...     await exit()  # Terminates the event loop immediately
        ...     print("This will never be executed")
        
        >>> async def exit_with_result():
        ...     await exit("success")  # Will be returned if join=True
        
        >>> async def exit_with_error():
        ...     await exit(exception=ValueError("Something went wrong"))
    """
    yield ExitCommand(return_value, exception)
    # This point is never reached as the event loop will terminate


def socket(
    family: _socket.AddressFamily | int = -1,
    type: _socket.SocketKind | int = -1,
    proto: int = -1,
    fileno: int | None = None,
    use_tls: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    server_hostname: str | None = None,
) -> SocketHandle:
    """
    Create a new socket compatible with Flowno's event loop.
    
    Args:
        family: The address family (default: AF_INET)
        type: The socket type (default: SOCK_STREAM)
        proto: The protocol number (default: 0)
        fileno: If specified, the socket is created from an existing file descriptor
        use_tls: When True, creates a TLS-wrapped socket
        ssl_context: The SSL context to use (if use_tls=True)
        server_hostname: The server hostname for TLS certificate validation
        
    Returns:
        A SocketHandle that can be used with the Flowno event loop.
    """
    if use_tls:
        if ssl_context is None:
            ssl_context = ssl.create_default_context()
        return TLSSocketHandle(_socket.socket(family, type, proto, fileno), ssl_context, server_hostname)
    return SocketHandle(_socket.socket(family, type, proto, fileno))


@overload
async def azip(iterable: AsyncIterator[_T_co], /) -> AsyncGenerator[tuple[_T_co], None]: ...


@overload
async def azip(iterable1: AsyncIterator[_T1], iterable2: AsyncIterator[_T2], /) -> AsyncGenerator[tuple[_T1, _T2], None]: ...


@overload
async def azip(iterable1: AsyncIterator[_T1], iterable2: AsyncIterator[_T2], iterable3: AsyncIterator[_T3], /) -> AsyncGenerator[
    tuple[_T1, _T2, _T3], None
]: ...


@overload
async def azip(
    iterable1: AsyncIterator[_T1],
    iterable2: AsyncIterator[_T2],
    iterable3: AsyncIterator[_T3],
    iterable4: AsyncIterator[_T4],
    /,
) -> AsyncGenerator[tuple[_T1, _T2, _T3, _T4], None]: ...


async def azip(*args: Unpack[tuple[AsyncIterator[object], ...]]) -> AsyncGenerator[tuple[object, ...], None]:
    """
    Combine multiple async iterators, similar to the built-in `zip()` function.
    
    This function takes multiple async iterators and yields tuples containing items
    from each iterator, advancing all iterators in lockstep. It stops when the shortest
    iterator is exhausted.
    
    Args:
        *args: Two or more async iterators to combine
        
    Yields:
        Tuples containing one item from each iterator
        
    Example:
        >>> async def gen1():
        ...     for i in range(3):
        ...         yield i
        >>> 
        >>> async def gen2():
        ...     yield "a"
        ...     yield "b"
        >>> 
        >>> # Will yield (0, "a") and (1, "b")
        >>> async for pair in azip(gen1(), gen2()):
        ...     print(pair)
    """
    iters = [aiter(arg) for arg in args]
    while True:
        ret: list[object] = []
        for it in iters:
            try:
                item = await anext(it)
                ret.append(item)
            except StopAsyncIteration:
                return
        yield tuple(ret)
