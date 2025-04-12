"""
Coroutine wrapper for Flowno's asynchronous execution logging.

This module provides a wrapper for Python coroutines that adds detailed logging
for debugging purposes. The wrapper logs coroutine execution events including
creation, resumption, yielding, and completion.

For examples and more detailed information, see the :py:mod:`flowno.utilities.logging` module
and its `log_async` decorator which uses this wrapper.
"""

import logging
from collections.abc import Coroutine, Generator
from types import TracebackType
from typing import overload, TypeVar
from typing_extensions import override

Yield = TypeVar("Yield")
T = TypeVar("T")

logger = logging.getLogger(__name__)


class CoroutineWrapper(Coroutine[Yield, object, T]):
    """
    Wrapper for coroutines to add detailed logging.

    This wrapper intercepts coroutine operations and logs execution events,
    making it easier to debug complex asynchronous workflows in Flowno.
    Used internally by the `log_async` decorator.

    Logs when the coroutine is:
        - Created
        - Started/Resumed (via send or throw)
        - Yielding commands to the event loop
        - Returning awaited values

    Ensures that exceptions are propagated correctly.
    """

    def __init__(self, coro: Coroutine[Yield, object, T], func_name: str, arg_str: str):
        self._coro = coro  # The underlying coroutine
        self._func_name = func_name  # Name of the coroutine function
        self._arg_str = arg_str  # String representation of arguments

    def __repr__(self) -> str:
        return f"CoroutineWrapper({self._func_name}({self._arg_str}))"

    @override
    def send(self, value: object) -> Yield:
        try:
            logger.debug(f"Resuming coroutine: {self._func_name}({self._arg_str}) with send({value!r})")
            result = self._coro.send(value)
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) yielded {result!r}")
            return result
        except StopIteration as e:
            # Coroutine has finished execution
            # the return type of an async function gets wrapped in a StopIteration
            final_result: T = e.value  # pyright: ignore[reportAny]
            logger.debug(f"Finished coroutine: {self._func_name}({self._arg_str}) with result {final_result!r}")
            raise
        except BaseException as e:
            # Log any exception raised
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) raised exception {e!r}")
            raise

    @overload
    def throw(
        self, typ: type[BaseException], val: BaseException | object = None, tb: TracebackType | None = None, /
    ) -> Yield: ...

    @overload
    def throw(self, typ: BaseException, val: None = None, tb: TracebackType | None = None, /) -> Yield: ...

    @override
    def throw(
        self,
        typ: type[BaseException] | BaseException,
        val: BaseException | object = None,
        tb: TracebackType | None = None,
    ) -> Yield:
        try:
            typ_name = getattr(typ, "__name__", str(typ))
            logger.debug(f"Throwing into coroutine: {self._func_name}({self._arg_str}) exception {typ_name}({val})")
            if val is None:
                assert isinstance(typ, BaseException), f"Expected BaseException, got {typ!r}"
                result = self._coro.throw(typ)
            else:
                assert isinstance(typ, type), f"Expected type, got {typ!r}"
                result = self._coro.throw(typ, val, tb)
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) yielded {result!r} after throw")
            return result
        except StopIteration as e:
            final_result: T = e.value  # pyright: ignore[reportAny]
            logger.debug(
                f"Finished coroutine after throw: {self._func_name}({self._arg_str}) with result {final_result!r}"
            )
            raise
        except BaseException as e:
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) raised exception after throw: {e!r}")
            raise

    @override
    def close(self):
        self._coro.close()
        logger.debug(f"Coroutine {self._func_name}({self._arg_str}) closed")

    @override
    def __await__(self) -> Generator[Yield, object, T]:
        # Implement __await__ to return an iterator that drives the coroutine
        return self._wrap_awaitable(self._coro.__await__())

    def _wrap_awaitable(self, awaitable: Generator[Yield, object, T]) -> Generator[Yield, object, T]:
        try:
            # Start the coroutine via __await__
            logger.debug(f"Starting coroutine: {self._func_name}({self._arg_str}) via __await__")
            value = yield from awaitable
            # Coroutine completed
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) completed via __await__ with result {value!r}")
            return value
        except StopIteration as e:
            final_result: T = e.value  # pyright: ignore[reportAny]
            logger.debug(
                f"Finished coroutine via __await__: {self._func_name}({self._arg_str}) with result {final_result!r}"
            )
            raise
        except BaseException as e:
            logger.debug(f"Coroutine {self._func_name}({self._arg_str}) raised exception via __await__: {e!r}")
            raise


__all__ = ["CoroutineWrapper"]
