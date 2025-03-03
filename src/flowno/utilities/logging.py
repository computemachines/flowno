"""
Logging utilities for asynchronous code in Flowno.

This module provides tools for debugging asynchronous code execution, particularly
coroutines and async generators. The main utility is the `log_async` decorator, which
wraps async functions to log their execution flow, including function calls, yields,
sends, and returns.

Example:
    >>> from flowno.utilities.logging import log_async
    >>> from flowno.core.event_loop.event_loop import EventLoop
    >>> from flowno.core.event_loop.primitives import sleep
    >>> import logging
    >>>
    >>> # Configure logging to see debug messages
    >>> logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    >>>
    >>> # Decorate an async function to log its execution
    >>> @log_async
    ... async def fetch_data(url: str) -> dict:
    ...     print(f"Fetching data from {url}")
    ...     await sleep(0.1)  # Simulate network delay
    ...     return {"result": "success", "url": url}
    >>>
    >>> # Decorate an async generator to log each yielded value
    >>> @log_async
    ... async def stream_data(count: int):
    ...     for i in range(count):
    ...         await sleep(0.05)
    ...         yield f"data chunk {i}"
    >>>
    >>> async def main():
    ...     # The decorator will log the function call, awaits, and return value
    ...     result = await fetch_data("https://example.com/api")
    ...     print(f"Got result: {result}")
    ...     
    ...     # The decorator will log each yield and the final completion
    ...     async for chunk in stream_data(3):
    ...         print(f"Received: {chunk}")
    >>>
    >>> # Create Flowno event loop and run the main task
    >>> event_loop = EventLoop()
    >>> event_loop.run_until_complete(main(), join=True)
    DEBUG: Calling function: main()
    DEBUG: main() is a coroutine
    DEBUG: Starting coroutine: main() via __await__
    DEBUG: Calling function: fetch_data('https://example.com/api')
    DEBUG: fetch_data('https://example.com/api') is a coroutine
    DEBUG: Starting coroutine: fetch_data('https://example.com/api') via __await__
    Fetching data from https://example.com/api
    DEBUG: Resuming coroutine: fetch_data('https://example.com/api') with send(None)
    DEBUG: Coroutine fetch_data('https://example.com/api') yielded SleepCommand(duration=0.1)
    DEBUG: Resuming coroutine: fetch_data('https://example.com/api') with send(None)
    DEBUG: Finished coroutine: fetch_data('https://example.com/api') with result {'result': 'success', 'url': 'https://example.com/api'}
    DEBUG: Coroutine fetch_data('https://example.com/api') completed via __await__ with result {'result': 'success', 'url': 'https://example.com/api'}
    Got result: {'result': 'success', 'url': 'https://example.com/api'}
    DEBUG: Calling function: stream_data(3)
    DEBUG: stream_data(3) is an async generator
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Coroutine stream_data(3) yielded SleepCommand(duration=0.05)
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Async generator stream_data(3) yielded 'data chunk 0'
    Received: data chunk 0
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Coroutine stream_data(3) yielded SleepCommand(duration=0.05)
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Async generator stream_data(3) yielded 'data chunk 1'
    Received: data chunk 1
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Coroutine stream_data(3) yielded SleepCommand(duration=0.05)
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Async generator stream_data(3) yielded 'data chunk 2'
    Received: data chunk 2
    DEBUG: Resuming coroutine: stream_data(3) with send(None)
    DEBUG: Async generator stream_data(3) completed
    DEBUG: Coroutine main() completed via __await__ with result None
"""

import functools
import inspect
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import ParamSpec, TypeVar, overload

from .asyncgen_wrapper import AsyncGeneratorWrapper
from .coroutine_wrapper import CoroutineWrapper

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_T = TypeVar("_T")
_YieldT = TypeVar("_YieldT")
_RT = TypeVar("_RT")


@overload
def log_async(func: Callable[_P, Coroutine[_YieldT, object, _T]]) -> Callable[_P, Coroutine[_YieldT, object, _T]]: ...


@overload
def log_async(func: Callable[_P, AsyncGenerator[_YieldT, object]]) -> Callable[_P, AsyncGenerator[_YieldT, object]]: ...


@overload
def log_async(func: Callable[_P, _T]) -> Callable[_P, _T]: ...


def log_async(func: Callable[_P, Coroutine[_YieldT, object, _T] | AsyncGenerator[_YieldT, object] | _RT]) -> Callable[
    _P, Coroutine[_YieldT, object, _T] | AsyncGenerator[_YieldT, object] | _RT
]:
    """
    Decorator that enhances async functions or generators with detailed execution logging.
    
    This decorator wraps coroutines and async generators to log important events 
    during their execution:
    
    For coroutines:
    - Initial function call with arguments
    - When the coroutine is awaited
    - When the coroutine yields commands to the event loop
    - When the coroutine is resumed with send() or throw()
    - When the coroutine completes (with return value)
    - If an exception occurs
    
    For async generators:
    - Initial generator creation
    - Each time the generator yields a value
    - Each time the generator is resumed
    - When the generator is exhausted or closed
    - If an exception occurs
    
    Args:
        func: The async function or generator function to wrap
        
    Returns:
        A wrapped version of the function that logs execution details
        
    Note:
        This decorator preserves the original function's signature and docstring.
        It's particularly useful for debugging complex asynchronous workflows in Flowno's
        event loop system.
    """
    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Coroutine[_YieldT, object, _T] | AsyncGenerator[_YieldT, object] | _RT:
        # Exclude 'self' from args if present, for methods
        if args and getattr(func, "__self__", None) is not None:
            args_without_self = args[1:]
            logger.debug(f"Excluding 'self' from arguments: {args[0]}")
        else:
            args_without_self = args

        # Create a string representation of the arguments for debugging
        arg_str = ", ".join(
            [
                *[repr(a) for a in args_without_self],  # Positional arguments excluding 'self'
                *[f"{k}={v!r}" for k, v in kwargs.items()],  # Keyword arguments
            ]
        )

        # Call the original function and get the result
        logger.debug(f"Calling function: {func.__name__}({arg_str})")
        result = func(*args, **kwargs)

        # Check if the result is awaitable (coroutine or generator-based coroutine)
        if inspect.iscoroutine(result):
            logger.debug(f"{func.__name__}({arg_str}) is a coroutine")
            # Wrap the awaitable to add debugging
            return CoroutineWrapper(result, func.__name__, arg_str)
        elif inspect.isasyncgen(result):
            logger.debug(f"{func.__name__}({arg_str}) is an async generator")
            # Wrap the async generator to add debugging
            return AsyncGeneratorWrapper(result, func.__name__, arg_str)
        else:
            # Not a coroutine, async generator, or awaitable; log the call and return the result as is
            logger.debug(f"Function {func.__name__}({arg_str}) returned {result!r}")
            logger.warning(f"Function {func.__name__}({arg_str}) is not a coroutine or async generator")
            return result

    return wrapper


__all__ = ["log_async"]
