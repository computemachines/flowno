"""
Async generator wrapper for Flowno's asynchronous execution logging.

This module provides a wrapper for Python async generators that adds detailed logging
for debugging purposes. The wrapper logs async generator execution events including
creation, resumption, yielding, and completion.

For examples and more detailed information, see the :py:mod:`flowno.utilities.logging` module
and its `log_async` decorator which uses this wrapper.
"""

import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import TypeVar, overload

from typing_extensions import override

Yield = TypeVar("Yield")
Send = TypeVar("Send")

logger = logging.getLogger(__name__)


class AsyncGeneratorWrapper(AsyncGenerator[Yield, Send]):
    """
    Wrapper class for async generators to add detailed debugging logs. It
    implements the AsyncGenerator interface and forwards calls to the
    underlying async generator, adding logging statements to '__anext__' and
    'athrow' methods.
    """

    def __init__(self, agen: AsyncGenerator[Yield, Send], func_name: str, arg_str: str) -> None:
        self._agen = agen
        self._func_name = func_name
        self._arg_str = arg_str

    @override
    async def __anext__(self) -> Yield:
        try:
            value = await self._agen.__anext__()
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) yielded {value!r}")
            return value
        except StopAsyncIteration as e:
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) finished")
            raise e  # Re-raise to propagate correctly
        except BaseException as e:
            logger.debug(f"Exception in async generator: {self._func_name}({self._arg_str}): {e!r}")
            raise e  # Re-raise to propagate correctly

    @override
    def __aiter__(self) -> "AsyncGeneratorWrapper[Yield, Send]":
        return self

    @override
    @overload
    async def athrow(
        self, typ: type[BaseException], val: BaseException | object = None, tb: TracebackType | None = None, /
    ) -> Yield: ...

    @override
    @overload
    async def athrow(self, typ: BaseException, val: None = None, tb: TracebackType | None = None, /) -> Yield: ...

    @override
    async def athrow(
        self,
        typ: BaseException | type[BaseException],
        val: BaseException | object | None = None,
        tb: TracebackType | None = None,
    ) -> Yield:
        try:
            exception_name = getattr(typ, "__name__", str(typ))
            logger.debug(
                f"Resuming async generator: {self._func_name}({self._arg_str}) with athrow({exception_name}, {val}, {tb})"
            )
            if val is None:
                value = await self._agen.athrow(typ)
            else:
                assert isinstance(typ, type), "Expected a type for the exception type"
                value = await self._agen.athrow(typ, val, tb)
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) yielded {value!r}")
            return value
        except StopAsyncIteration as e:
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) finished")
            raise e  # Re-raise to propagate correctly
        except BaseException as e:
            logger.debug(f"Exception in async generator: {self._func_name}({self._arg_str}): {e!r}")
            raise e  # Re-raise to propagate correctly

    @override
    async def aclose(self) -> None:
        try:
            logger.debug(f"Closing async generator {self._func_name}({self._arg_str})")
            await self._agen.aclose()
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) closed")
        except BaseException as e:
            logger.debug(f"Exception in async generator {self._func_name}({self._arg_str}) during aclose: {e!r}")
            raise e

    @override
    async def asend(self, value: Send) -> Yield:
        try:
            logger.debug(f"Resuming async generator {self._func_name}({self._arg_str}) with asend({value!r})")
            result = await self._agen.asend(value)
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) yielded {result!r} after asend")
            return result
        except StopAsyncIteration:
            logger.debug(f"Async generator {self._func_name}({self._arg_str}) finished")
            raise
        except BaseException as e:
            logger.debug(f"Exception in async generator {self._func_name}({self._arg_str}) during asend: {e!r}")
            raise


__all__ = ["AsyncGeneratorWrapper"]
